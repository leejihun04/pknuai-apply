"""Read a logged-in pknuai session straight out of the browser.

Copying a Cookie header by hand from DevTools is the one step a classmate is
likely to get wrong, so this lifts it automatically. Chromium-family browsers
encrypt their cookie values, but only with a key the same user can read from
their own keychain, and the decryption needs nothing beyond what macOS and
Linux already ship (``security``/``secret-tool``, ``sqlite3`` via Python,
``openssl``) — no pip, in keeping with the rest of the tool.

Nothing here leaves the machine. It reads the user's own cookie store, decodes
the pknuai cookies, and hands them to the same verifier a pasted cookie goes
through.
"""

from __future__ import annotations

import glob
import hashlib
import os
import platform
import shutil
import sqlite3
import subprocess
import tempfile
from pathlib import Path

PKNUAI_HOSTS = ("pknuai.pknu.ac.kr", ".pknuai.pknu.ac.kr", ".pknu.ac.kr")
# The cookie that actually carries the login. If it is not among what we found,
# the browser is not logged in to pknuai and there is nothing to import.
SESSION_COOKIE_NAMES = ("JSESSIONID", "WMONID")


class BrowserImportError(Exception):
    """No usable pknuai session could be read from the browser."""


# ---------- locating cookie stores ----------

def _mac_supports() -> Path:
    return Path.home() / "Library" / "Application Support"


def _linux_config() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME", "").strip()
    return Path(base).expanduser() if base else Path.home() / ".config"


def chromium_profiles() -> list:
    """(browser label, cookie-db path) for every Chromium profile we can see."""
    system = platform.system()
    roots = {}
    if system == "Windows":
        # Chrome/Edge cookies are app-bound encrypted here; `session login`
        # (CDP) reads them from the live browser instead.
        return []
    if system == "Darwin":
        support = _mac_supports()
        roots = {
            "Chrome": support / "Google/Chrome",
            "Chrome Beta": support / "Google/Chrome Beta",
            "Edge": support / "Microsoft Edge",
            "Brave": support / "BraveSoftware/Brave-Browser",
            "Whale": support / "Naver/Whale",
            "Chromium": support / "Chromium",
            "Arc": support / "Arc/User Data",
            "Vivaldi": support / "Vivaldi",
        }
    elif system == "Linux":
        config = _linux_config()
        roots = {
            "Chrome": config / "google-chrome",
            "Chromium": config / "chromium",
            "Edge": config / "microsoft-edge",
            "Brave": config / "BraveSoftware/Brave-Browser",
            "Whale": config / "naver-whale",
            "Vivaldi": config / "vivaldi",
        }
    found = []
    for label, root in roots.items():
        if not root.exists():
            continue
        for profile in ("Default", *[Path(p).name for p in glob.glob(str(root / "Profile *"))]):
            for candidate in (root / profile / "Network" / "Cookies", root / profile / "Cookies"):
                if candidate.exists():
                    found.append((label, candidate))
                    break
    return found


def firefox_profiles() -> list:
    system = platform.system()
    if system == "Darwin":
        root = _mac_supports() / "Firefox" / "Profiles"
    elif system == "Linux":
        root = Path.home() / ".mozilla" / "firefox"
    elif system == "Windows":
        appdata = os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))
        root = Path(appdata) / "Mozilla" / "Firefox" / "Profiles"
    else:
        return []
    if not root.exists():
        return []
    return [("Firefox", Path(db)) for db in glob.glob(str(root / "*" / "cookies.sqlite"))]


def available_browsers() -> list:
    """Distinct browser labels with a cookie store present, for the UI."""
    seen = []
    for label, _path in chromium_profiles() + firefox_profiles():
        if label not in seen:
            seen.append(label)
    return seen


# ---------- decryption ----------

def _safe_storage_password(label: str) -> bytes:
    """The browser's Safe Storage key, from the OS secret store."""
    system = platform.system()
    account = {"Edge": "Microsoft Edge", "Brave": "Brave", "Chromium": "Chromium",
               "Whale": "Whale", "Vivaldi": "Vivaldi", "Arc": "Arc"}.get(label, "Chrome")
    service = f"{'' if label == 'Arc' else account} Safe Storage".strip()
    service = {"Chrome": "Chrome Safe Storage", "Chrome Beta": "Chrome Safe Storage",
               "Edge": "Microsoft Edge Safe Storage", "Brave": "Brave Safe Storage",
               "Chromium": "Chromium Safe Storage", "Whale": "Whale Safe Storage",
               "Vivaldi": "Vivaldi Safe Storage", "Arc": "Arc Safe Storage"}.get(label, service)
    if system == "Darwin":
        done = subprocess.run(
            ["security", "find-generic-password", "-w", "-s", service, "-a", account],
            capture_output=True, text=True, timeout=20,
        )
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout.strip().encode()
        raise BrowserImportError(
            f"{label} 키체인 접근이 허용되지 않았습니다. 팝업이 뜨면 '허용'을 눌러 주세요."
        )
    if system == "Linux":
        for keyring_service in (f"{account} Keys", f"{account} Safe Storage"):
            done = subprocess.run(
                ["secret-tool", "lookup", "application", account.lower()],
                capture_output=True, timeout=20,
            )
            if done.returncode == 0 and done.stdout:
                return done.stdout.strip()
        # Chromium on a headless Linux box falls back to this fixed password.
        return b"peanuts"
    raise BrowserImportError("이 운영체제에서는 브라우저 자동 가져오기를 지원하지 않습니다.")


def _iterations() -> int:
    return 1003 if platform.system() == "Darwin" else 1


def _decrypt_value(encrypted: bytes, key: bytes) -> str:
    if not encrypted:
        return ""
    version = encrypted[:3]
    if version not in (b"v10", b"v11"):
        # Not OS-encrypted (older browsers stored the value in plaintext).
        try:
            return encrypted.decode("utf-8")
        except UnicodeDecodeError:
            return ""
    body = encrypted[3:]
    iv = b"\x20" * 16
    done = subprocess.run(
        ["openssl", "enc", "-aes-128-cbc", "-d", "-K", key.hex(), "-iv", iv.hex(), "-nopad"],
        input=body, capture_output=True,
    )
    out = done.stdout
    if not out:
        return ""
    padding = out[-1]
    if 1 <= padding <= 16:
        out = out[:-padding]
    # Chrome m127+ prepends a 32-byte SHA256 of the domain before the value;
    # older builds do not. Try the stripped form first, then the whole thing.
    for candidate in ((out[32:], out) if len(out) > 32 else (out,)):
        try:
            return candidate.decode("utf-8")
        except UnicodeDecodeError:
            continue
    return ""


def _read_sqlite(path: Path, query: str, params: tuple = ()) -> list:
    """Read a browser DB even while the browser holds it open.

    A running browser keeps the file locked, so read a copy rather than the
    original; the -wal/-shm side files come along so recent writes are seen.
    """
    handle, temporary = tempfile.mkstemp(prefix=".cookies-", suffix=".db")
    os.close(handle)
    try:
        shutil.copy2(path, temporary)
        for suffix in ("-wal", "-shm"):
            side = Path(str(path) + suffix)
            if side.exists():
                shutil.copy2(side, temporary + suffix)
        connection = sqlite3.connect(f"file:{temporary}?mode=ro", uri=True)
        connection.text_factory = bytes
        try:
            return connection.execute(query, params).fetchall()
        finally:
            connection.close()
    finally:
        for extra in (temporary, temporary + "-wal", temporary + "-shm"):
            try:
                os.unlink(extra)
            except OSError:
                pass


def _host_clause(column: str) -> str:
    return " OR ".join(f"{column}=?" for _ in PKNUAI_HOSTS)


def _chromium_cookies(label: str, path: Path) -> dict:
    rows = _read_sqlite(
        path,
        "SELECT name, value, encrypted_value FROM cookies WHERE " + _host_clause("host_key"),
        PKNUAI_HOSTS,
    )
    if not rows:
        return {}
    cookies: dict = {}
    key = None
    for name, plain, encrypted in rows:
        name = name.decode("utf-8", "replace")
        value = plain.decode("utf-8", "replace") if plain else ""
        if not value and encrypted:
            if key is None:
                key = hashlib.pbkdf2_hmac("sha1", _safe_storage_password(label), b"saltysalt",
                                          _iterations(), 16)
            value = _decrypt_value(encrypted, key)
        if value:
            cookies[name] = value
    return cookies


def _firefox_cookies(path: Path) -> dict:
    # moz_cookies stores plaintext, so no key is needed.
    rows = _read_sqlite(
        path,
        "SELECT name, value FROM moz_cookies WHERE " + _host_clause("host"),
        PKNUAI_HOSTS,
    )
    return {name.decode("utf-8", "replace"): value.decode("utf-8", "replace")
            for name, value in rows}


def cookie_header_from(label: str, path: Path) -> str:
    cookies = _firefox_cookies(path) if label == "Firefox" else _chromium_cookies(label, path)
    if not cookies:
        return ""
    if not any(name in cookies for name in SESSION_COOKIE_NAMES):
        return ""
    return "; ".join(f"{name}={value}" for name, value in cookies.items())


def gather(browser: str = "") -> list:
    """(label, cookie-header) for every profile that holds a pknuai session.

    Longest header first, so the fullest session is tried before a stub.
    """
    stores = chromium_profiles() + firefox_profiles()
    if browser:
        wanted = browser.strip().lower()
        stores = [(label, path) for label, path in stores if label.lower() == wanted]
    results = []
    seen = set()
    for label, path in stores:
        try:
            header = cookie_header_from(label, path)
        except BrowserImportError:
            raise
        except Exception:  # noqa: BLE001 - a locked or odd profile is just skipped
            continue
        if header and header not in seen:
            seen.add(header)
            results.append((label, header))
    results.sort(key=lambda item: len(item[1]), reverse=True)
    return results
