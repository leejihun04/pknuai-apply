"""Import a session from the browser, or open one and wait for the login.

Two doors to the same place, because a classmate's browser is in one of two
states: already logged in to pknuai (import it), or not (open it, let them log
in with their phone, then capture the session the moment it appears).

Credentials are never asked for or typed. The PKNU login ends in a phone push
that only the student can answer; the tool's job is to notice when they have.
"""

from __future__ import annotations

import platform
import shutil
import tempfile
import time

from . import browsercookies, browserlaunch, cdp, session

LOGIN_URL = "https://pknuai.pknu.ac.kr/web/nonSbjt/program.do?mId=216"


def import_session(browser: str = "") -> dict:
    """Read a logged-in pknuai session out of the browser and store it.

    Returns the same shape as ``session.check``: {ok, reason, ...}. Tries every
    profile that holds a pknuai cookie, fullest first, and keeps the first one
    the site actually accepts.
    """
    try:
        candidates = browsercookies.gather(browser)
    except browsercookies.BrowserImportError as exc:
        return {"ok": False, "reason": str(exc)}
    if not candidates:
        seen = browsercookies.available_browsers()
        where = f"({', '.join(seen)})" if seen else "(브라우저를 찾지 못했습니다)"
        return {"ok": False, "reason": f"브라우저에 로그인된 pknuai 세션이 없습니다 {where}. "
                                       "먼저 브라우저에서 pknuai에 로그인하거나 `session login` 을 쓰세요.",
                "no_session": True}
    last = {"ok": False, "reason": "세션을 가져오지 못했습니다."}
    for label, header in candidates:
        session.save_cookie(header)
        checked = session.check()
        checked["browser"] = label
        if checked.get("ok"):
            checked["reason"] = f"{label} 에서 세션을 가져왔습니다 — {checked['reason']}"
            return checked
        last = checked
    session.forget()  # do not leave a rejected cookie behind
    last["reason"] = f"브라우저에서 세션을 찾았지만 pknuai가 받아들이지 않았습니다. {last.get('reason', '')}"
    return last


def _header_from_cdp(port: int) -> str:
    """Build a Cookie header from the live browser's pknuai cookies."""
    try:
        cookies = cdp.all_cookies(port)
    except cdp.CDPError:
        return ""
    picked = {}
    for cookie in cookies:
        domain = str(cookie.get("domain") or "")
        if domain.endswith("pknu.ac.kr"):
            picked[str(cookie.get("name"))] = str(cookie.get("value"))
    if not any(name in picked for name in browsercookies.SESSION_COOKIE_NAMES):
        return ""
    return "; ".join(f"{name}={value}" for name, value in picked.items())


def capture_via_cdp(browser: str = "", timeout: int = 300, interval: int = 2,
                    on_wait=None) -> dict:
    """Open a browser window, let the student log in, capture the session.

    This is the path that works when the cookie store cannot be read off disk
    — modern Chrome and Edge on Windows — because it reads the cookies from the
    running browser over DevTools, in plain text, the moment the login lands.
    """
    chosen = browserlaunch.pick(browser)
    if not chosen:
        return {"ok": False, "reason": "열 수 있는 브라우저(Edge/Chrome)를 찾지 못했습니다.",
                "no_browser": True}
    label, path = chosen
    port = browserlaunch.free_port()
    profile = tempfile.mkdtemp(prefix="pknuai-login-")
    process = None
    try:
        process = browserlaunch.launch_for_debugging(path, profile, port, LOGIN_URL)
        # Wait for the DevTools endpoint to come up.
        endpoint_deadline = time.time() + 20
        while time.time() < endpoint_deadline:
            try:
                if cdp.browser_websocket_url(port):
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.3)
        deadline = time.time() + max(interval, timeout)
        while time.time() < deadline:
            if on_wait:
                on_wait(int(deadline - time.time()))
            header = _header_from_cdp(port)
            if header:
                session.save_cookie(header)
                checked = session.check()
                checked["browser"] = f"{label} (로그인 창)"
                if checked.get("ok"):
                    checked["reason"] = f"{label} 창에서 로그인해 세션을 가져왔습니다 — {checked['reason']}"
                    return checked
                session.forget()
            time.sleep(interval)
        return {"ok": False, "timed_out": True,
                "reason": "로그인을 기다리는 시간이 지났습니다. 창에서 로그인을 마친 뒤 다시 시도해 주세요."}
    finally:
        if process is not None:
            try:
                process.terminate()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(profile, ignore_errors=True)


def wait_for_login(browser: str = "", timeout: int = 300, interval: int = 3,
                   on_wait=None) -> dict:
    """Open pknuai, then poll the browser until a working session appears.

    ``on_wait`` is called once per poll with the seconds elapsed, so a CLI can
    show a countdown. Returns a session.check-shaped dict.
    """
    # Already logged in to a browser we can read off disk (mac/Linux, or
    # Firefox anywhere): take it with no login at all.
    already = import_session(browser)
    if already.get("ok"):
        return already
    # Otherwise open a window we control and capture the login when it lands.
    # This is the Windows path, and a fine fallback everywhere else.
    return capture_via_cdp(browser, timeout=timeout, interval=max(2, interval), on_wait=on_wait)
