"""The command line. Everything the web page does, and a couple of things more."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import agent, config, gate, login_flow, programs, session, store, watch, webui
from . import apply as apply_module

STATUS_LABEL = {
    "applied": "✅ 신청 완료",
    "already": "ℹ️ 이미 신청됨",
    "would_apply": "🧪 신청 가능(시험 실행)",
    "skipped": "⏭️ 건너뜀",
    "failed": "⚠️ 실패",
    "login_required": "🔑 로그인 필요",
}


def _print(*parts) -> None:
    print(*parts, flush=True)


def _relative(moment) -> str:
    try:
        seconds = float(moment) - time.time()
    except (TypeError, ValueError):
        return ""
    if seconds <= 0:
        return "지금"
    days, rest = divmod(int(seconds), 86400)
    hours, rest = divmod(rest, 3600)
    minutes = rest // 60
    if days:
        return f"{days}일 {hours}시간 뒤"
    if hours:
        return f"{hours}시간 {minutes}분 뒤"
    return f"{minutes}분 뒤" if minutes else f"{int(seconds)}초 뒤"


def _clipboard() -> str:
    for command in (["pbpaste"], ["wl-paste"], ["xclip", "-selection", "clipboard", "-o"]):
        try:
            done = subprocess.run(command, capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout
    return ""


# ---------- session ----------

def cmd_session(args) -> int:
    if args.action == "check":
        result = session.check()
        _print(("✅ " if result["ok"] else "⚠️ ") + result["reason"])
        if result.get("savedAt"):
            saved = datetime.fromtimestamp(result["savedAt"], config.KST)
            _print(f"   저장 시각: {saved.strftime('%Y-%m-%d %H:%M')}")
        return 0 if result["ok"] else 1
    if args.action == "forget":
        _print("세션을 지웠습니다." if session.forget() else "지울 세션이 없습니다.")
        return 0
    if args.action == "import":
        _print("브라우저에서 로그인된 pknuai 세션을 찾는 중… (키체인 팝업이 뜨면 '허용')")
        result = login_flow.import_session(args.browser)
        _print(("✅ " if result["ok"] else "⚠️ ") + result["reason"])
        if not result["ok"] and result.get("no_session"):
            _print("   → 아직 로그인 전이면 `pknuai-apply session login` 을 쓰세요.")
        return 0 if result["ok"] else 1
    if args.action == "login":
        _print("브라우저를 열어 pknuai 로그인 페이지로 이동합니다. 휴대폰 인증까지 마쳐 주세요.")
        _print("로그인이 끝나면 자동으로 세션을 가져옵니다. (기다리는 중 Ctrl+C 로 취소)")
        last = {"printed": 0}

        def countdown(remaining):
            if remaining // 10 != last["printed"]:
                last["printed"] = remaining // 10
                _print(f"   … 로그인 대기 중 (남은 시간 {remaining}s)")

        result = login_flow.wait_for_login(args.browser, timeout=args.timeout, on_wait=countdown)
        _print(("✅ " if result["ok"] else "⚠️ ") + result["reason"])
        return 0 if result["ok"] else 1

    cookie = ""
    if args.file:
        cookie = Path(args.file).expanduser().read_text(encoding="utf-8")
    elif args.stdin:
        cookie = sys.stdin.read()
    elif args.clipboard:
        cookie = _clipboard()
        if not cookie:
            _print("클립보드에서 아무것도 읽지 못했습니다.")
            return 1
    else:
        _print("pknuai에 로그인한 브라우저에서 개발자도구 → 네트워크 → program.do 요청의")
        _print("Cookie 요청 헤더 전체를 복사해 붙여넣고 Enter 를 누르세요. (화면에 표시되지 않습니다)")
        try:
            import getpass

            cookie = getpass.getpass("Cookie: ")
        except (EOFError, KeyboardInterrupt):
            _print("\n취소했습니다.")
            return 1
    try:
        session.save_cookie(cookie)
    except ValueError as exc:
        _print(f"⚠️ {exc}")
        return 1
    result = session.check()
    _print(("✅ " if result["ok"] else "⚠️ ") + result["reason"])
    return 0 if result["ok"] else 1


# ---------- 목록 ----------

def _load_programs(pages: int = None) -> list:
    try:
        return programs.list_programs(pages)
    except session.LoginRequired as exc:
        _print(f"🔑 {exc}")
        raise SystemExit(1)


def cmd_list(args) -> int:
    found = programs.search(_load_programs(args.pages), args.query)
    if args.json:
        _print(json.dumps(found, ensure_ascii=False, indent=2))
        return 0
    if not found:
        _print("조건에 맞는 프로그램이 없습니다.")
        return 0
    booked, ledger = store.reservations(), store.ledger()
    for program in found:
        marks = []
        if program["id"] in booked:
            marks.append("예약됨")
        record = ledger.get(program["id"])
        if isinstance(record, dict):
            marks.append(STATUS_LABEL.get(record.get("status", ""), record.get("status", "")).split(" ")[-1])
        badge = f"  [{' · '.join(marks)}]" if marks else ""
        _print(f"{program['id']}  {program['title']}{badge}")
        _print(f"{'':11}모집 {program['recruit_text'] or '-'}")
    _print(f"\n{len(found)}건. 예약: pknuai-apply reserve <코드>")
    return 0


def cmd_show(args) -> int:
    program = next((p for p in _load_programs(args.pages) if p["id"] == args.code), None)
    if program is None:
        booking = store.reservations().get(args.code)
        if not isinstance(booking, dict):
            _print(f"{args.code} 를 목록에서 찾지 못했습니다.")
            return 1
        program = {"id": args.code, "title": booking.get("title", ""), "url": booking.get("url", "")}
    try:
        cookie = session.require_cookie()
    except session.LoginRequired as exc:
        _print(f"🔑 {exc}")
        return 1
    detail = apply_module.session_request("GET", program["url"], cookie)
    parsed = gate.parse_apply_gate(detail.text)
    kind, message = gate.blocker(program, parsed, time.time())
    _print(f"{program['id']}  {program['title']}")
    _print(f"  원문      {program['url']}")
    _print(f"  모집기간  {gate.window_label(parsed.get('recruit_start')) or '-'}"
           f" ~ {gate.window_label(parsed.get('recruit_end')) or '-'}")
    _print(f"  상태      {parsed.get('status') or '-'} / 모집중={parsed.get('recruiting') or '-'}"
           f" / 내 상태={parsed.get('enrolled_text') or '없음'}")
    _print(f"  설문      {parsed.get('survey_questions')}문항")
    if parsed.get("external_links"):
        _print(f"  외부신청  {parsed['external_links'][0]}")
    _print(f"  지금 신청 {'가능' if not kind else f'불가 — {message}'}")
    return 0


# ---------- 예약 ----------

def cmd_reserve(args) -> int:
    program = next((p for p in _load_programs(args.pages) if p["id"] == args.code), None)
    if program is None:
        _print(f"{args.code} 를 목록에서 찾지 못했습니다. `pknuai-apply list -q <검색어>` 로 코드를 확인해 주세요.")
        return 1
    if args.attach:
        path = Path(args.attach).expanduser()
        if not path.is_file():
            _print(f"첨부파일을 찾지 못했습니다: {path}")
            return 1
        saved = store.save_attachment(program["id"], path.name, path.read_bytes())
        _print(f"첨부파일을 저장했습니다: {saved.name}")
    store.reserve(program, with_attachment=not args.no_attachment)
    store.clear_deferral(program["id"])
    store.log(f"예약 추가 {program['id']} {program['title'][:40]}", echo=False)
    _print(f"✅ 예약했습니다: {program['title']}")
    if not agent.is_running():
        _print("⚠️ 감시자가 돌고 있지 않습니다. `pknuai-apply install-agent` 로 등록하거나"
               " `pknuai-apply watch` 를 켜 두세요.")
    return 0


def cmd_cancel(args) -> int:
    if store.cancel(args.code):
        store.log(f"예약 취소 {args.code}", echo=False)
        _print(f"예약을 취소했습니다: {args.code}")
        return 0
    _print(f"{args.code} 는 예약되어 있지 않습니다.")
    return 1


def cmd_status(args) -> int:
    result = session.check() if args.check_session else {"ok": bool(session.load_cookie()),
                                                         "reason": "세션 저장됨" if session.load_cookie() else "세션 없음"}
    _print(f"세션    {'✅' if result['ok'] else '⚠️'} {result['reason']}")
    running = agent.is_running()
    _print(f"감시자  {'✅ 실행 중' if running else ('⏸️ 등록됨(정지)' if agent.is_installed() else '⚠️ 미등록')}"
           f"  ({agent.LABEL})")
    _print(f"데이터  {config.data_dir()}")

    rows = watch.snapshot()
    _print(f"\n예약 {len(rows)}건")
    for row in rows:
        when = f"{row['opensLabel']} ({_relative(row['opensAt'])})" if row["opensAt"] else "개시 시각 미확인"
        _print(f"  {row['code']}  {row['title'][:44]}")
        _print(f"{'':13}개시 {when}")
        if row["lastKind"]:
            _print(f"{'':13}최근 {row['lastKind']} — {row['lastDetail'][:60]}")
        if row["attachment"]:
            _print(f"{'':13}첨부 {row['attachment']}"
                   f"{'' if row['withAttachment'] else ' (제출 꺼짐)'}")

    ledger = store.ledger()
    if ledger:
        _print(f"\n처리된 프로그램 {len(ledger)}건")
        for code, entry in sorted(ledger.items(), key=lambda item: item[1].get("at", ""), reverse=True)[:10]:
            label = STATUS_LABEL.get(entry.get("status", ""), entry.get("status", ""))
            _print(f"  {code}  {label}  {str(entry.get('title', ''))[:40]}  {entry.get('at', '')[:16]}")
    return 0


# ---------- 신청 ----------

def cmd_apply(args) -> int:
    outcomes = apply_module.run_reserved(only=args.code or "", dry_run=args.dry_run, respect_sleep=False)
    if not outcomes:
        _print("지금 시도할 예약이 없습니다.")
        return 0
    for outcome in outcomes:
        label = STATUS_LABEL.get(outcome["status"], outcome["status"])
        _print(f"{label}  {outcome['code']}  {outcome['title'][:44]}")
        if outcome.get("reason"):
            _print(f"    {outcome['reason']}")
    return 0 if any(o["status"] in ("applied", "already", "would_apply") for o in outcomes) else 1


def cmd_watch(args) -> int:
    return watch.run(once=args.once, quiet=args.quiet)


def cmd_serve(args) -> int:
    return webui.serve(args.host, args.port, open_browser=not args.no_open)


def cmd_install_agent(args) -> int:
    ok, message = agent.install()
    _print(("✅ " if ok else "⚠️ ") + message)
    return 0 if ok else 1


def cmd_uninstall_agent(args) -> int:
    ok, message = agent.uninstall()
    _print(("✅ " if ok else "⚠️ ") + message)
    return 0 if ok else 1


def cmd_restart_agent(args) -> int:
    ok, message = agent.restart()
    _print(("✅ " if ok else "⚠️ ") + message)
    return 0 if ok else 1


def cmd_logs(args) -> int:
    lines = store.tail(args.lines)
    if not lines:
        _print("아직 기록이 없습니다.")
        return 0
    for line in lines:
        _print(line)
    return 0


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def _session_args(action, parsed):
    return _Args(action=action, browser=getattr(parsed, "browser", ""),
                 timeout=getattr(parsed, "timeout", 300), file=None, stdin=False, clipboard=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pknuai-apply",
        description="부경대 비교과(pknuai) 프로그램을 예약해 두면 모집 시작 순간에 자동으로 신청합니다.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    p = subparsers.add_parser(
        "session",
        help="pknuai 로그인 세션 저장/가져오기/확인",
        description=("import: 이미 로그인된 브라우저에서 자동으로 가져오기(가장 쉬움). "
                     "login: 브라우저를 열어 로그인한 뒤 자동 포착. "
                     "set: Cookie 헤더를 직접 붙여넣기."),
    )
    p.add_argument("action", nargs="?", default="import",
                   choices=["import", "login", "set", "check", "forget"])
    p.add_argument("--browser", default="",
                   help="특정 브라우저만 사용 (chrome, edge, brave, whale, firefox …)")
    p.add_argument("--timeout", type=int, default=300, help="login: 로그인 대기 시간(초)")
    p.add_argument("--file", help="set: 쿠키가 담긴 파일에서 읽기")
    p.add_argument("--stdin", action="store_true", help="set: 표준 입력에서 읽기")
    p.add_argument("--clipboard", action="store_true", help="set: 클립보드에서 읽기")
    p.set_defaults(func=cmd_session)

    sc = subparsers.add_parser("import", help="이미 로그인된 브라우저에서 세션 가져오기 (session import 축약)")
    sc.add_argument("--browser", default="")
    sc.set_defaults(func=lambda a: cmd_session(_session_args("import", a)))
    sc = subparsers.add_parser("login", help="브라우저를 열어 로그인하고 세션 포착 (session login 축약)")
    sc.add_argument("--browser", default="")
    sc.add_argument("--timeout", type=int, default=300)
    sc.set_defaults(func=lambda a: cmd_session(_session_args("login", a)))

    p = subparsers.add_parser("list", help="비교과 프로그램 목록")
    p.add_argument("query", nargs="?", default="", help="제목 검색어")
    p.add_argument("-q", "--query", dest="query", help=argparse.SUPPRESS)
    p.add_argument("--pages", type=int, default=None, help=f"읽어올 목록 페이지 수 (기본 {config.LIST_PAGES})")
    p.add_argument("--json", action="store_true", help="JSON으로 출력")
    p.set_defaults(func=cmd_list)

    p = subparsers.add_parser("show", help="프로그램 하나의 신청 조건 확인")
    p.add_argument("code")
    p.add_argument("--pages", type=int, default=None)
    p.set_defaults(func=cmd_show)

    p = subparsers.add_parser("reserve", help="프로그램 예약 (모집 시작 시 자동 신청)")
    p.add_argument("code")
    p.add_argument("--attach", help="신청서식 파일 경로")
    p.add_argument("--no-attachment", action="store_true", help="저장된 첨부파일을 보내지 않기")
    p.add_argument("--pages", type=int, default=None)
    p.set_defaults(func=cmd_reserve)

    p = subparsers.add_parser("cancel", help="예약 취소")
    p.add_argument("code")
    p.set_defaults(func=cmd_cancel)

    p = subparsers.add_parser("status", help="세션·감시자·예약 상태")
    p.add_argument("--check-session", action="store_true", help="pknuai에 실제로 물어서 세션 확인")
    p.set_defaults(func=cmd_status)

    p = subparsers.add_parser("apply", help="지금 바로 신청 시도")
    p.add_argument("code", nargs="?", default="")
    p.add_argument("--dry-run", action="store_true", help="실제로 신청하지 않고 가능 여부만 확인")
    p.set_defaults(func=cmd_apply)

    p = subparsers.add_parser("watch", help="모집 시작을 기다리는 감시자 실행")
    p.add_argument("--once", action="store_true", help="한 번만 확인하고 종료")
    p.add_argument("--quiet", action="store_true", help="터미널 출력 없이 로그 파일만")
    p.set_defaults(func=cmd_watch)

    p = subparsers.add_parser("serve", help="로컬 웹 화면 열기")
    p.add_argument("--port", type=int, default=None)
    p.add_argument("--host", default=None)
    p.add_argument("--no-open", action="store_true", help="브라우저를 자동으로 열지 않기")
    p.set_defaults(func=cmd_serve)

    subparsers.add_parser("install-agent", help="감시자를 자동 시작으로 등록").set_defaults(func=cmd_install_agent)
    subparsers.add_parser("uninstall-agent", help="자동 시작 등록 해제").set_defaults(func=cmd_uninstall_agent)
    subparsers.add_parser("restart-agent", help="감시자 다시 시작").set_defaults(func=cmd_restart_agent)

    p = subparsers.add_parser("logs", help="감시자 로그")
    p.add_argument("-n", "--lines", type=int, default=40)
    p.set_defaults(func=cmd_logs)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except session.LoginRequired as exc:
        _print(f"🔑 {exc}")
        return 1
    except KeyboardInterrupt:
        return 130
