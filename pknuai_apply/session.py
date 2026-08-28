"""The one thing only a human can do: log in.

The PKNU portal ends its login with an mSABER/FIDO push to the student's
phone, so no crawler passes it alone. The student logs in once in a browser
and hands over the resulting Cookie header; it is stored 0600 in the data
directory and re-read on every request, so refreshing it never needs a
restart.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from . import config, http_client

HINT = "브라우저에서 pknuai에 로그인한 뒤 `pknuai-apply session set` 으로 쿠키를 다시 저장해 주세요."


class LoginRequired(Exception):
    """The stored session is missing, expired, or no longer accepted."""


def _session_path() -> Path:
    return config.data_dir() / config.SESSION_FILE


def load_cookie() -> str:
    try:
        payload = json.loads(_session_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    return " ".join(str(payload.get("cookie") or "").split())


def save_cookie(cookie: str) -> None:
    """Store the cookie so only this user can read it."""
    cleaned = " ".join(str(cookie or "").split())
    if not cleaned:
        raise ValueError("빈 쿠키는 저장할 수 없습니다.")
    target = _session_path()
    directory = target.parent
    old_mask = os.umask(0o077)
    try:
        handle, temporary = tempfile.mkstemp(prefix=".session.", dir=str(directory))
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump({"cookie": cleaned, "savedAt": time.time()}, stream)
        os.replace(temporary, target)
        os.chmod(target, 0o600)
    finally:
        os.umask(old_mask)


def forget() -> bool:
    try:
        _session_path().unlink()
        return True
    except OSError:
        return False


def saved_at() -> float:
    try:
        payload = json.loads(_session_path().read_text(encoding="utf-8"))
        return float(payload.get("savedAt") or 0)
    except (OSError, ValueError, TypeError):
        return 0.0


def login_wall(text: str) -> bool:
    text = text or ""
    return (
        "로그인하셔야" in text
        or "접근권한이 없습니다" in text
        or ("LoginForm" in text and "portal.pknu.ac.kr" in text)
    )


def require_cookie() -> str:
    cookie = load_cookie()
    if not cookie:
        raise LoginRequired(f"pknuai 세션이 저장되어 있지 않습니다. {HINT}")
    return cookie


def guard(response: http_client.Response) -> http_client.Response:
    """Turn "you are logged out" into an exception instead of an empty page."""
    if response.status in (401, 403) or 300 <= response.status < 400:
        raise LoginRequired(f"pknuai 세션이 만료되었습니다(HTTP {response.status}). {HINT}")
    if login_wall(response.text):
        raise LoginRequired(f"pknuai가 로그인 화면을 돌려주었습니다. {HINT}")
    return response


def fetch(url: str, **kwargs) -> http_client.Response:
    """A GET made as the signed-in student, with the login wall enforced."""
    return guard(http_client.get(url, cookie=require_cookie(), **kwargs))


def check() -> dict:
    """Is the stored session still accepted? Never raises."""
    cookie = load_cookie()
    if not cookie:
        return {"ok": False, "reason": "저장된 세션이 없습니다.", "savedAt": 0}
    url = http_client.with_query(
        config.PROGRAM_LIST_URL, {"mId": "216", "order": "3", "all": "1", "pageIndex": "1"}
    )
    try:
        response = http_client.get(url, cookie=cookie, timeout=20)
    except Exception as exc:  # noqa: BLE001 - offline is not "logged out"
        return {"ok": False, "reason": f"pknuai에 접속하지 못했습니다: {exc}", "savedAt": saved_at()}
    if response.status in (401, 403) or 300 <= response.status < 400 or login_wall(response.text):
        return {"ok": False, "reason": f"세션이 거부되었습니다(HTTP {response.status}). {HINT}",
                "savedAt": saved_at()}
    if not response.ok:
        return {"ok": False, "reason": f"pknuai가 HTTP {response.status}를 돌려주었습니다.",
                "savedAt": saved_at()}
    from .programs import parse_programs  # imported late: programs needs session

    programs = parse_programs(response.text)
    return {"ok": True, "reason": f"세션 정상 — 프로그램 {len(programs)}건을 읽었습니다.",
            "savedAt": saved_at(), "programs": len(programs)}
