"""What the programme's own detail page says about applying.

Every guard here is a claim pknuai renders for a human to read, lifted out
and enforced before an application is sent. An application cannot be taken
back by this tool, so anything unreadable counts against applying.
"""

from __future__ import annotations

import re
from datetime import datetime

from . import config, htmltree

_MOMENT = r"(\d{4})[.\-/](\d{1,2})[.\-/](\d{1,2})(?:\s+(\d{1,2}):(\d{2}))?"
RECRUIT_START_RE = re.compile(r"모집\s*기간\s*[:：]?\s*" + _MOMENT)
RECRUIT_WINDOW_RE = re.compile(r"모집\s*기간\s*[:：]?\s*" + _MOMENT + r"\s*[~～\-]\s*" + _MOMENT)
CSRF_RE = re.compile(r'<meta name="_csrf" content="([^"]+)"')
UPLOAD_APPEND_RE = re.compile(r"uploadFormData\.append\(\s*'([A-Za-z_][A-Za-z0-9_]*)'\s*,\s*'([^']*)'\s*\)")
UPLOAD_RECVNO_RE = re.compile(
    r"if\s*\(\s*'([^']*)'\s*==\s*'P'\s*\)\s*\{\s*uploadFormData\.append\(\s*'recvNo'\s*,\s*'([^']*)'\s*\)"
)


def _moment(year, month, day, hour, minute, end_of_day: bool = False):
    try:
        if hour is None and end_of_day:
            when = datetime(int(year), int(month), int(day), 23, 59, 59, tzinfo=config.KST)
        else:
            when = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0),
                            tzinfo=config.KST)
    except ValueError:
        return None
    return when.timestamp()


def parse_recruit_window(html_text: str) -> tuple:
    """(opens, closes) as epoch seconds; either may be None.

    pknuai publishes the window to the minute. That is the one statement about
    timing a human can check, so it is read here and then held against our own
    clock — the page's 모집중 flag is only the site's opinion of itself.
    """
    text = htmltree.strip_tags(html_text)
    ranged = RECRUIT_WINDOW_RE.search(text)
    if ranged:
        groups = ranged.groups()
        return (_moment(*groups[:5]), _moment(*groups[5:], end_of_day=True))
    found = RECRUIT_START_RE.search(text)
    if not found:
        return (None, None)
    return (_moment(*found.groups()), None)


def seat_taken(enrolled_text) -> str:
    text = str(enrolled_text or "")
    return next((state for state in config.SEAT_TAKEN_STATES if state in text), "")


def external_apply_links(html_text: str) -> list:
    """Sites a programme really takes its applications on.

    Some programmes only *record* attendance on pknuai while the sign-up
    happens on a partner site. Pressing pknuai's apply button for one of those
    produces an application that looks complete while the student never
    registered for the event.
    """
    links = []
    for match in re.findall(r'data-link-addr="(https?://[^"]+)"', html_text or ""):
        host = re.sub(r"^https?://([^/:]+).*$", r"\1", match)
        if host and not host.endswith("pknu.ac.kr") and match not in links:
            links.append(match)
    return links


def parse_apply_gate(html_text: str) -> dict:
    """Read the programme's guard clauses out of its own personalApply()."""
    body_match = re.search(r"function personalApply\(persRecvNo\)\s*\{(.*?)\n\}", html_text or "", re.S)
    if not body_match:
        return {"parsed": False}
    body = body_match.group(1)
    status = re.search(r"if\('([^']*)'\s*!=\s*'OK'\)", body)
    recruiting = re.search(r"else if\('([^']*)'\s*!=\s*'1'\)", body)
    apply_type = re.search(r"else if\('([^']*)'\s*==\s*'N0012002'\)", body)
    enrolled = re.search(r"else if\('([^']*)'\.indexOf\('수강중'\)", body)
    survey = re.search(r"if\('(\d+)'\s*==\s*0\)", html_text or "")
    opens, closes = parse_recruit_window(html_text)
    return {
        "parsed": bool(status and recruiting and apply_type),
        "status": status.group(1) if status else "",
        "recruiting": recruiting.group(1) if recruiting else "",
        "apply_type": apply_type.group(1) if apply_type else "",
        "enrolled_text": enrolled.group(1) if enrolled else "",
        "survey_questions": int(survey.group(1)) if survey else 0,
        "external_links": external_apply_links(html_text),
        "recruit_start": opens,
        "recruit_end": closes,
    }


def window_label(moment) -> str:
    """A published minute, written the way the page writes it."""
    try:
        return datetime.fromtimestamp(float(moment), config.KST).strftime("%Y.%m.%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def blocker(program: dict, parsed_gate: dict, now: float) -> tuple:
    """(kind, message) describing why not to apply; ("", "") when it may go."""
    if not parsed_gate.get("parsed"):
        return "unreadable", "신청 조건을 읽지 못했습니다"
    if parsed_gate.get("status") != "OK":
        return "closed", f"신청 가능 상태가 아닙니다({parsed_gate.get('status') or 'unknown'})"
    opens, closes = parsed_gate.get("recruit_start"), parsed_gate.get("recruit_end")
    if opens is not None and now < opens:
        return "not_open", f"아직 모집 기간이 아닙니다(모집 시작 {window_label(opens)})"
    if closes is not None and now > closes:
        return "window_closed", f"모집 기간이 끝났습니다({window_label(closes)} 마감)"
    if parsed_gate.get("recruiting") != "1":
        return "not_open", "아직 모집 기간이 아닙니다"
    if parsed_gate.get("apply_type") == config.TEAM_ONLY_CODE:
        return "team", "팀 신청 프로그램입니다"
    taken = seat_taken(parsed_gate.get("enrolled_text"))
    if taken:
        return "enrolled", "이미 수강 중입니다" if taken == "수강중" else "이미 신청한 프로그램입니다"
    if int(parsed_gate.get("survey_questions") or 0) > 0:
        return "survey", "설문 응답이 필요합니다"
    external = parsed_gate.get("external_links") or []
    if external:
        return "external", f"외부 사이트에서 신청하는 프로그램입니다: {external[0]}"
    return "", ""


def button_attr(html_text: str, id_prefix: str, attr: str) -> str:
    """One data attribute off an apply-page button.

    The page finds these with [id^=...] and does not keep the attributes in a
    fixed order, so match the tag first and read the attribute inside it. An
    exact-id, fixed-order regular expression quietly returns an empty string —
    and an empty recvNo is what once orphaned an uploaded 신청서식.
    """
    for tag in re.findall(r"<button\b[^>]*>", html_text or ""):
        if not re.search(rf'id="{re.escape(id_prefix)}[^"]*"', tag):
            continue
        found = re.search(rf'{re.escape(attr)}="([^"]*)"', tag)
        if found:
            return found.group(1).strip()
    return ""


def parse_upload_fields(html_text: str) -> dict:
    """Recover applyFiles.do's form fields from the page's own upload script.

    applyFiles.do binds an uploaded file to an application by the identifiers
    posted beside it, and answers 200 with {"result":"DONE"} even when they are
    missing — the file is simply stored against nothing. programApply.do
    hardcodes the exact values a browser sends, so lifting those literals keeps
    an automated upload identical to a manual one.
    """
    block = re.search(r"function\s+applyFiles\s*\([^)]*\)\s*\{(.*?)^\}", html_text or "", re.S | re.M)
    if not block:
        return {}
    body = block.group(1)
    fields: dict = {}
    for key, value in UPLOAD_APPEND_RE.findall(body):
        if key != "recvNo" and key not in fields:
            fields[key] = value
    # recvNo sits behind a server-rendered branch: only the 개인(P) arm carries
    # the real number, and the other arm deliberately posts an empty one.
    guard = UPLOAD_RECVNO_RE.search(body)
    if guard:
        fields["recvNo"] = guard.group(2) if guard.group(1) == "P" else ""
    return fields


def csrf_token(html_text: str) -> str:
    found = CSRF_RE.search(html_text or "")
    return found.group(1) if found else ""


def program_params(url: str) -> dict:
    """The four identifiers the apply endpoints need, out of a detail URL."""
    from urllib.parse import parse_qs, urlparse

    try:
        query = parse_qs(urlparse(str(url or "")).query)
    except ValueError:
        return {}
    params = {}
    for key in ("yy", "shtm", "nonsubjcCd", "nonsubjcCrsCd"):
        value = (query.get(key) or [""])[0].strip()
        if value:
            params[key] = value
    return params if len(params) == 4 else {}
