"""Submitting one application, and only when every check says it is safe.

Order matters here, and each step exists because of something that went wrong
against the real site:

* the window the page publishes is checked against our own clock, because the
  page's 모집중 flag has been wrong and an application cannot be withdrawn;
* the 신청 고유번호 is read before the file is sent, because applyFiles.do
  answers 200 for an upload bound to nothing;
* the ledger is written the moment a seat is taken, because a duplicate
  submission is the one mistake with no undo.
"""

from __future__ import annotations

import time

from . import config, gate, http_client, session, store


def session_request(method: str, url: str, cookie: str, *, token: str = "", data=None,
                    body: bytes = None, content_type: str = "", ajax: bool = True):
    headers = {"Referer": f"{config.PKNUAI_ORIGIN}/web/nonSbjt/program.do?mId=216"}
    if token:
        headers["X-CSRF-Token"] = token
        # The upload is the one call the page makes without this header. Send
        # exactly what a browser sends and nothing more.
        if ajax:
            headers["Ajax"] = "true"
    return http_client.request(
        method, url, cookie=cookie, headers=headers, data=data, body=body,
        content_type=content_type, timeout=30,
    )


def _json_result(response) -> str:
    import json

    try:
        payload = json.loads(response.text or "")
    except ValueError:
        return ""
    if isinstance(payload, dict):
        return str(payload.get("result") or "")
    return ""


def upload_attachment(path, cookie: str, token: str, fields: dict) -> bool:
    """Attach the student's file to a finalised application."""
    fields = dict(fields or {})
    if not str(fields.get("recvNo") or "").strip():
        store.log("첨부파일 업로드 생략: 신청 고유번호(recvNo)가 없습니다.")
        return False
    try:
        body, content_type = http_client.multipart(fields, "files", path)
        response = session_request(
            "POST", config.APPLY_FILES_URL, cookie, token=token, ajax=False,
            body=body, content_type=content_type,
        )
        if not response.ok:
            store.log(f"첨부파일 업로드 실패: HTTP {response.status}")
            return False
        return True
    except Exception as exc:  # noqa: BLE001
        store.log(f"첨부파일 업로드 실패: {exc}")
        return False


def apply_to_program(program: dict, cookie: str, *, dry_run: bool = False, now: float = None) -> dict:
    """Submit one personal application. Returns an outcome; never raises."""
    now = time.time() if now is None else now
    code = str(program.get("id") or "")
    base = {"code": code, "title": str(program.get("title") or ""), "url": str(program.get("url") or "")}
    params = gate.program_params(program.get("url"))
    if not params:
        return {**base, "status": "skipped", "kind": "unreadable",
                "reason": "프로그램 식별자를 읽지 못했습니다"}

    try:
        detail = session_request("GET", str(program.get("url")), cookie)
        if detail.status in (401, 403) or session.login_wall(detail.text):
            raise session.LoginRequired(f"pknuai 세션이 만료되었습니다. {session.HINT}")
        token = gate.csrf_token(detail.text)
        if not token:
            return {**base, "status": "skipped", "kind": "unreadable",
                    "reason": "CSRF 토큰을 찾지 못했습니다"}

        parsed = gate.parse_apply_gate(detail.text)
        kind, message = gate.blocker(program, parsed, now)
        if kind:
            skipped = {**base, "status": "skipped", "kind": kind, "reason": message}
            if kind == "not_open":
                # Lets the watcher sleep until the published minute instead of
                # rediscovering the opening on a polling boundary.
                skipped["recruit_start"] = parsed.get("recruit_start")
                skipped["recruit_end"] = parsed.get("recruit_end")
            return skipped

        # Whether a file is required is stated only on the apply page, so look
        # before committing to anything.
        apply_page = session_request(
            "GET",
            http_client.with_query(config.APPLY_PAGE_URL,
                                   {"mId": "216", **params, "recvNo": "", "appType": "P"}),
            cookie,
        )
        needs_attachment = gate.button_attr(apply_page.text, "applyApplyBtn", "data-atch") not in ("", "0")
        stored_attachment = store.attachment_for(code)
        opted_out = store.attachment_opted_out(code)
        attachment = None if opted_out else stored_attachment
        if needs_attachment and not attachment:
            return {
                **base, "status": "skipped", "kind": "attachment_missing",
                "reason": (
                    "첨부파일이 필요한데 예약에서 '신청서식 함께 제출'이 꺼져 있습니다."
                    if opted_out and stored_attachment
                    else "첨부파일이 필요합니다. 파일을 올려두면 자동으로 신청합니다."
                ),
            }

        if dry_run:
            return {**base, "status": "would_apply", "kind": "", "reason": "dry_run",
                    "attachment": str(attachment) if attachment else ""}

        init = session_request(
            "POST", config.APPLY_INIT_URL, cookie, token=token,
            data={**params, "teamCd": "", "teamCdBefore": "", "recvNo": "", "agree": "1"},
        )
        if not init.ok:
            return {**base, "status": "failed", "kind": "http",
                    "reason": f"신청 준비 실패(HTTP {init.status})"}
        if _json_result(init) == "0":
            return {**base, "status": "failed", "kind": "rejected",
                    "reason": "신청 준비 단계에서 거부되었습니다"}

        ready = session_request(
            "GET",
            http_client.with_query(config.APPLY_PAGE_URL,
                                   {"mId": "216", **params, "recvNo": "", "appType": "P"}),
            cookie,
        )
        upload_fields = gate.parse_upload_fields(ready.text)
        recv_no = str(upload_fields.get("recvNo") or "").strip()
        if not recv_no:
            recv_no = gate.button_attr(ready.text, "applyApplyBtn", "data-recv-no")
        if not recv_no:
            # The page itself refuses to submit without one ("수강신청 고유번호가
            # 없습니다"), and submitting anyway is what silently orphaned an
            # uploaded 신청서식 while answering DONE.
            return {**base, "status": "failed", "kind": "unreadable",
                    "reason": "신청 고유번호(recvNo)를 읽지 못했습니다"}

        submit = session_request(
            "POST", config.APPLY_SUBMIT_URL, cookie, token=token,
            data={"yy": params["yy"], "shtm": params["shtm"],
                  "nonsubjcCd": params["nonsubjcCd"], "recvNo": recv_no},
        )
        if not submit.ok:
            return {**base, "status": "failed", "kind": "http",
                    "reason": f"신청 실패(HTTP {submit.status})"}
        result = _json_result(submit)
        if result == config.ALREADY_APPLIED_RESULT:
            return {**base, "status": "already", "kind": "", "reason": "이미 신청된 프로그램입니다",
                    "result": result}
        if not result:
            return {**base, "status": "failed", "kind": "unknown",
                    "reason": "신청 결과를 확인하지 못했습니다"}

        uploaded = ""
        if attachment:
            fields = {key: params.get(key, "") for key in ("yy", "shtm", "nonsubjcCd")}
            fields.update({k: v for k, v in upload_fields.items() if k != "recvNo"})
            fields["recvNo"] = recv_no
            if upload_attachment(attachment, cookie, token, fields):
                uploaded = attachment.name
            else:
                return {**base, "status": "applied", "kind": "", "result": result, "recv_no": recv_no,
                        "reason": "신청은 되었지만 첨부파일 업로드에 실패했습니다. 직접 확인해 주세요."}
        return {**base, "status": "applied", "kind": "", "reason": "", "result": result,
                "recv_no": recv_no, "attachment": uploaded}
    except session.LoginRequired as exc:
        return {**base, "status": "login_required", "kind": "session", "reason": str(exc)}
    except Exception as exc:  # noqa: BLE001 - one programme must not stop the run
        return {**base, "status": "failed", "kind": "error", "reason": str(exc).replace("\n", " ")[:200]}


def reserved_programs(now: float = None) -> list:
    """What is booked and not yet on record, newest booking last.

    Everything needed to knock on a programme is kept in the reservation
    itself, so a booking still works weeks later, long after the programme has
    scrolled off the list.
    """
    book = store.ledger()
    pending = []
    for code, entry in (store.reservations() or {}).items():
        if str(code) in book:
            continue
        if not isinstance(entry, dict) or not gate.program_params(entry.get("url")):
            continue
        pending.append({"id": str(code), "title": entry.get("title", ""), "url": entry.get("url", "")})
    return pending


def settle(outcome: dict, now: float = None) -> None:
    """Write down what happened, and stop chasing what cannot change."""
    now = time.time() if now is None else now
    code, status, kind = outcome["code"], outcome["status"], outcome.get("kind", "")
    if status in {"applied", "already"}:
        store.record(code, {
            "title": outcome["title"], "status": status, "url": outcome["url"],
            "result": outcome.get("result", ""), "attachment": outcome.get("attachment", ""),
            "recvNo": outcome.get("recv_no", ""), "reason": outcome.get("reason", ""),
        })
        store.clear_deferral(code)
        store.cancel(code)
    elif status == "skipped" and kind not in config.RETRYABLE_SKIPS:
        # A verdict that will not change. "Already taken" is not a refusal
        # though — a seat held by hand is still a seat.
        store.record(code, {
            "title": outcome["title"], "status": "already" if kind == "enrolled" else "skipped",
            "kind": kind, "reason": outcome["reason"], "url": outcome["url"],
        })
        store.clear_deferral(code)
        store.cancel(code)
    elif status == "skipped":
        store.note_deferral(code, kind, outcome["reason"], outcome.get("recruit_start"), now)
    elif status in {"failed", "login_required"}:
        store.note_deferral(code, kind, outcome["reason"], None, now)


def run_reserved(only: str = "", dry_run: bool = False, now: float = None,
                 respect_sleep: bool = True) -> list:
    """Try every booking that is due. Returns one outcome per attempt."""
    now = time.time() if now is None else now
    pending = reserved_programs(now)
    if only:
        pending = [program for program in pending if program["id"] == str(only)]
    if not pending:
        return []
    try:
        cookie = session.require_cookie()
    except session.LoginRequired as exc:
        store.log(str(exc))
        return [{"code": program["id"], "title": program["title"], "url": program["url"],
                 "status": "login_required", "kind": "session", "reason": str(exc)}
                for program in pending]

    outcomes = []
    for program in pending:
        if respect_sleep and store.still_sleeping(program["id"], now):
            continue
        with store.apply_lock():
            # Re-read inside the lock: the other process may have taken this
            # very seat while this one was waiting for its turn.
            if program["id"] in store.ledger():
                continue
            outcome = apply_to_program(program, cookie, dry_run=dry_run, now=now)
            if not dry_run:
                settle(outcome, now)
        outcomes.append(outcome)
        store.log(
            f"{outcome['status']}/{outcome.get('kind') or '-'} {outcome['code']} "
            f"{outcome['title'][:40]} {outcome.get('reason', '')}".strip()
        )
    return outcomes


def refresh_enrolment(programs: list, now: float = None) -> dict:
    """Record which listed programmes this account already holds a seat on.

    The ledger only knows about applications this tool made; a programme
    applied for by hand would otherwise look untouched.
    """
    now = time.time() if now is None else now
    listed = [p for p in programs if str(p.get("id") or "")]
    if not listed:
        return store.enrolment()
    try:
        cookie = session.require_cookie()
    except session.LoginRequired:
        return store.enrolment()

    state = store.enrolment()
    stale = []
    for program in listed:
        seen = state.get(str(program["id"])) if isinstance(state.get(str(program["id"])), dict) else {}
        try:
            checked = float(seen.get("checkedAt") or 0)
        except (TypeError, ValueError):
            checked = 0.0
        if now - checked >= config.ENROLMENT_REFRESH_SECONDS:
            stale.append((checked, program))
    # Never-checked programmes first: an unknown is worse than a stale yes.
    stale.sort(key=lambda item: item[0])

    for _checked, program in stale[:config.ENROLMENT_MAX_PER_RUN]:
        code = str(program["id"])
        try:
            detail = session_request("GET", str(program.get("url")), cookie)
            if detail.status in (401, 403) or session.login_wall(detail.text):
                # A dead session must not be written down as "not enrolled".
                break
            parsed = gate.parse_apply_gate(detail.text)
            if not parsed.get("parsed"):
                continue
            taken = gate.seat_taken(parsed.get("enrolled_text"))
            state[code] = {"enrolled": bool(taken), "state": taken,
                           "title": str(program.get("title") or ""), "checkedAt": now}
        except Exception as exc:  # noqa: BLE001
            store.log(f"신청 상태 확인 실패({code}): {exc}", echo=False)

    listed_codes = {str(p["id"]) for p in listed}
    book = store.ledger()
    state = {k: v for k, v in state.items() if k in listed_codes or k in book}
    store.save_enrolment(state)
    return state
