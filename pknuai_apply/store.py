"""Everything this tool remembers, as small JSON files in one directory.

The ledger is the safety rail: a programme written down as applied is never
submitted again, whatever the site or a later bug says. Writes are atomic, so
an interrupted run cannot leave a half-written ledger behind.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import re
import tempfile
import time
from datetime import datetime
from pathlib import Path

from . import config

MAX_LOG_BYTES = 512 * 1024


def _path(name: str) -> Path:
    return config.data_dir() / name


def load_json(name: str, default):
    try:
        payload = json.loads(_path(name).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default
    return payload if isinstance(payload, type(default)) else default


def save_json(name: str, payload) -> None:
    target = _path(name)
    handle, temporary = tempfile.mkstemp(prefix=f".{name}.", dir=str(target.parent))
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


@contextlib.contextmanager
def apply_lock():
    """Held while an application is being submitted.

    The watcher and the web page are separate processes reading the same
    ledger. pknuai would answer the second submission with "already applied",
    but a duplicate application is the one mistake with no undo, so they take
    turns instead of racing.
    """
    path = _path("apply.lock")
    handle = open(path, "a+")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def iso(moment: float = None) -> str:
    return datetime.fromtimestamp(moment if moment else time.time(), config.KST).isoformat(timespec="seconds")


# ---------- 예약 ----------

def reservations() -> dict:
    return load_json(config.RESERVATIONS_FILE, {})


def reserve(program: dict, with_attachment: bool = True) -> dict:
    """Book a programme by name.

    The detail URL is stored with the reservation on purpose: the programme
    list only shows the newest few pages, and a programme reserved three weeks
    before it opens has scrolled off by the time it matters. Without the URL
    the watcher would have nothing to knock on.
    """
    code = str(program.get("id") or "").strip()
    if not code:
        raise ValueError("프로그램 코드가 없습니다.")
    booked = reservations()
    booked[code] = {
        "title": str(program.get("title") or ""),
        "url": str(program.get("url") or ""),
        "withAttachment": bool(with_attachment),
        "reservedAt": iso(),
    }
    save_json(config.RESERVATIONS_FILE, booked)
    return booked[code]


def cancel(code: str) -> bool:
    booked = reservations()
    if str(code) not in booked:
        return False
    booked.pop(str(code), None)
    save_json(config.RESERVATIONS_FILE, booked)
    clear_deferral(code)
    return True


def attachment_opted_out(code: str) -> bool:
    """True when this programme was booked with the file deliberately off."""
    entry = reservations().get(str(code))
    return isinstance(entry, dict) and entry.get("withAttachment", True) is False


# ---------- 신청 원장 ----------

def ledger() -> dict:
    return load_json(config.LEDGER_FILE, {})


def record(code: str, entry: dict) -> None:
    book = ledger()
    book[str(code)] = {**entry, "at": iso()}
    save_json(config.LEDGER_FILE, book)


def forget_record(code: str) -> bool:
    book = ledger()
    if str(code) not in book:
        return False
    book.pop(str(code), None)
    save_json(config.LEDGER_FILE, book)
    return True


# ---------- 보류 상태 ----------

def deferred() -> dict:
    return load_json(config.DEFERRED_FILE, {})


def note_deferral(code: str, kind: str, detail: str, opens_at=None, now: float = None) -> bool:
    """Write down why a programme was passed over. True when it is news."""
    now = time.time() if now is None else now
    state = deferred()
    entry = state.get(str(code)) if isinstance(state.get(str(code)), dict) else {}
    fresh = entry.get("kind") != kind or entry.get("detail") != detail
    state[str(code)] = {
        "kind": kind,
        "detail": detail,
        "opensAt": opens_at if opens_at else entry.get("opensAt"),
        "checkedAt": now,
        "firstSeenAt": entry.get("firstSeenAt", now),
    }
    save_json(config.DEFERRED_FILE, state)
    return fresh


def still_sleeping(code: str, now: float) -> bool:
    """True while a programme the site said opens later is not worth asking about.

    Without this the watcher re-reads every reservation on every pass, which is
    how one forgotten booking turned into tens of thousands of requests a day.
    """
    entry = deferred().get(str(code))
    if not isinstance(entry, dict) or entry.get("kind") != "not_open":
        return False
    opens_at = entry.get("opensAt")
    if opens_at and now >= float(opens_at):
        return False
    try:
        checked_at = float(entry.get("checkedAt") or 0)
    except (TypeError, ValueError):
        return False
    return (now - checked_at) < config.DEFERRED_RECHECK_SECONDS


def clear_deferral(code: str) -> None:
    state = deferred()
    if str(code) in state:
        state.pop(str(code), None)
        save_json(config.DEFERRED_FILE, state)


# ---------- 신청 상태(내가 이미 잡은 자리) ----------

def enrolment() -> dict:
    return load_json(config.ENROLMENT_FILE, {})


def save_enrolment(state: dict) -> None:
    save_json(config.ENROLMENT_FILE, state)


# ---------- 첨부파일 ----------

def attachment_dir() -> Path:
    directory = config.data_dir() / config.ATTACHMENT_DIR
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def attachment_for(code: str):
    """The file pre-uploaded for this programme, if there is one."""
    try:
        candidates = sorted(attachment_dir().glob(f"{code}.*"))
    except OSError:
        return None
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return path
        except OSError:
            continue
    return None


def save_attachment(code: str, filename: str, content: bytes) -> Path:
    """Keep one file per programme, under the programme's own code.

    The uploaded name is only used for its extension: a name from a browser
    upload is untrusted, and the stored path has to stay inside this directory.
    """
    suffix = Path(str(filename or "")).suffix.lower()
    if not re.fullmatch(r"\.[a-z0-9]{1,8}", suffix or ""):
        suffix = ".bin"
    for existing in attachment_dir().glob(f"{code}.*"):
        try:
            existing.unlink()
        except OSError:
            pass
    target = attachment_dir() / f"{re.sub(r'[^A-Za-z0-9_-]', '', str(code))}{suffix}"
    target.write_bytes(content)
    return target


def delete_attachment(code: str) -> bool:
    removed = False
    for existing in attachment_dir().glob(f"{code}.*"):
        try:
            existing.unlink()
            removed = True
        except OSError:
            pass
    return removed


# ---------- 로그 ----------

def heartbeat_path() -> Path:
    return _path("watch.heartbeat")


def touch_heartbeat() -> None:
    """The watcher stamps this each loop; anyone can tell it is alive by its age."""
    try:
        heartbeat_path().write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def heartbeat_age() -> float:
    """Seconds since the watcher last stamped, or a huge number if never."""
    try:
        return time.time() - heartbeat_path().stat().st_mtime
    except OSError:
        return float("inf")


def log_path() -> Path:
    return _path(config.LOG_FILE)


def log(message: str, echo: bool = True) -> None:
    """One line, to the terminal and to the log the watcher leaves behind."""
    line = f"[{iso()}] {message}"
    if echo:
        print(line, flush=True)
    path = log_path()
    try:
        if path.exists() and path.stat().st_size > MAX_LOG_BYTES:
            path.replace(path.with_suffix(path.suffix + ".1"))
    except OSError:
        pass
    try:
        with open(path, "a", encoding="utf-8") as stream:
            stream.write(line + "\n")
    except OSError:
        pass


def tail(lines: int = 40) -> list:
    try:
        content = log_path().read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return content[-max(1, lines):]
