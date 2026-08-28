"""Import a session from the browser, or open one and wait for the login.

Two doors to the same place, because a classmate's browser is in one of two
states: already logged in to pknuai (import it), or not (open it, let them log
in with their phone, then capture the session the moment it appears).

Credentials are never asked for or typed. The PKNU login ends in a phone push
that only the student can answer; the tool's job is to notice when they have.
"""

from __future__ import annotations

import platform
import subprocess
import time

from . import browsercookies, session

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


def _open_browser(url: str, browser: str = "") -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            command = ["open"]
            if browser:
                command += ["-a", {"chrome": "Google Chrome", "edge": "Microsoft Edge",
                                   "brave": "Brave Browser", "whale": "Whale",
                                   "firefox": "Firefox"}.get(browser.lower(), browser)]
            subprocess.run(command + [url], check=False, timeout=15)
            return True
        if system == "Linux":
            subprocess.run(["xdg-open", url], check=False, timeout=15)
            return True
    except (OSError, subprocess.SubprocessError):
        return False
    import webbrowser

    return webbrowser.open(url)


def wait_for_login(browser: str = "", timeout: int = 300, interval: int = 3,
                   on_wait=None) -> dict:
    """Open pknuai, then poll the browser until a working session appears.

    ``on_wait`` is called once per poll with the seconds elapsed, so a CLI can
    show a countdown. Returns a session.check-shaped dict.
    """
    already = import_session(browser)
    if already.get("ok"):
        return already
    _open_browser(LOGIN_URL, browser)
    deadline = time.time() + max(interval, timeout)
    while time.time() < deadline:
        if on_wait:
            on_wait(int(deadline - time.time()))
        time.sleep(interval)
        result = import_session(browser)
        if result.get("ok"):
            return result
    return {"ok": False, "reason": "로그인을 기다리는 시간이 지났습니다. 브라우저에서 로그인을 마친 뒤 다시 시도해 주세요.",
            "timed_out": True}
