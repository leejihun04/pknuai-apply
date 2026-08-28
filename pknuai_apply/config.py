"""Where things live, and the few knobs worth turning.

Everything this tool remembers sits in one directory under the user's home,
so removing the tool is removing that directory plus the launch agent. The
defaults are the ones the original bot settled on after a season of running
against pknuai; they are deliberately polite to the university's site.
"""

from __future__ import annotations

import os
from pathlib import Path

try:  # Python 3.9+
    from zoneinfo import ZoneInfo

    KST = ZoneInfo("Asia/Seoul")
except Exception:  # pragma: no cover - a system without tz data
    from datetime import timedelta, timezone

    KST = timezone(timedelta(hours=9), "KST")

APP_NAME = "pknuai-apply"

PKNUAI_ORIGIN = "https://pknuai.pknu.ac.kr"
PROGRAM_LIST_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/program.do"
PROGRAM_DETAIL_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/programDetail.do"
APPLY_INIT_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/getApplyInit.do?mId=216"
APPLY_PAGE_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/programApply.do"
APPLY_SUBMIT_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/addApplyData.do?mId=216"
APPLY_FILES_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/applyFiles.do?mId=216"
CANCEL_URL = f"{PKNUAI_ORIGIN}/web/nonSbjt/updateCancelProgram.do?mId=216"

# Sent on every request. pknuai serves a different page to something that does
# not look like a browser, so this is not decoration.
BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "ko-KR,ko;q=0.9",
    "Referer": f"{PKNUAI_ORIGIN}/",
}

# Team programmes take a team, not a person; the page marks them with this code.
TEAM_ONLY_CODE = "N0012002"
# What the programme page calls the viewer's own state. pknuai says 신청 from
# the moment an application is accepted and only says 수강중 once the programme
# itself has started, so both mean the seat is already held.
SEAT_TAKEN_STATES = ("수강중", "신청")
# addApplyData.do's answer when the seat was already taken by this account.
ALREADY_APPLIED_RESULT = "AROM"

# Skips worth trying again later; everything else is a verdict that will not
# change, and re-asking the site about it is just noise.
RETRYABLE_SKIPS = {"not_open", "attachment_missing", "unreadable"}


def _int_env(name: str, default: int, minimum: int = 0) -> int:
    try:
        return max(minimum, int(os.environ.get(name, "").strip() or default))
    except ValueError:
        return default


def data_dir() -> Path:
    """The one directory this tool writes to."""
    override = os.environ.get("PKNUAI_APPLY_HOME", "").strip()
    if override:
        root = Path(override).expanduser()
    else:
        base = os.environ.get("XDG_DATA_HOME", "").strip()
        root = (Path(base).expanduser() if base else Path.home() / ".local" / "share") / APP_NAME
    root.mkdir(parents=True, exist_ok=True)
    return root


SESSION_FILE = "session.json"
RESERVATIONS_FILE = "reservations.json"
LEDGER_FILE = "applications.json"
DEFERRED_FILE = "deferred.json"
ENROLMENT_FILE = "enrolment.json"
ATTACHMENT_DIR = "attachments"
LOG_FILE = "watch.log"

# How often a reserved programme with no published opening minute is looked at.
RESERVATION_CHECK_INTERVAL = _int_env("PKNUAI_RESERVATION_CHECK_INTERVAL", 30, 2)
# How hard to knock once the published minute arrives. 선착순 programmes can
# fill in under a minute, so this is the whole point of the watcher.
RESERVATION_BURST_SECONDS = _int_env("PKNUAI_RESERVATION_BURST_SECONDS", 2, 1)
# ...and for how long. Without a ceiling, one reservation whose seats are gone
# knocks every two seconds for as long as it stands — tens of thousands of
# requests a day at the university's site.
RESERVATION_BURST_WINDOW = max(
    RESERVATION_BURST_SECONDS, _int_env("PKNUAI_RESERVATION_BURST_WINDOW", 180, 1)
)
# A programme the site said opens in three weeks is not asked again for half an
# hour, in case the opening date is brought forward.
DEFERRED_RECHECK_SECONDS = _int_env("PKNUAI_DEFERRED_RECHECK_SECONDS", 1800, 60)
# Reading "am I already on this?" costs one request per programme, so re-read a
# programme rarely and only a few of them per pass.
ENROLMENT_REFRESH_SECONDS = _int_env("PKNUAI_ENROLMENT_REFRESH_SECONDS", 1800, 300)
ENROLMENT_MAX_PER_RUN = _int_env("PKNUAI_ENROLMENT_MAX_PER_RUN", 6, 1)
# Pages of the programme list to read. One page is 10 programmes.
LIST_PAGES = _int_env("PKNUAI_LIST_PAGES", 3, 1)

WEB_HOST = os.environ.get("PKNUAI_WEB_HOST", "127.0.0.1").strip() or "127.0.0.1"
WEB_PORT = _int_env("PKNUAI_WEB_PORT", 8765, 1)
