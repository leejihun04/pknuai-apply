"""The watcher: asleep until the minute a programme opens, then insistent.

선착순 programmes can fill in under a minute, so a five-minute poll is not a
plan. pknuai publishes the opening minute on the programme's own page, so the
watcher sleeps until then and only starts knocking hard when the moment has
actually arrived — and stops knocking hard a few minutes later, because a
programme that has not opened by then is full or over, and an unbounded burst
would be a request every two seconds at the university's site for as long as
the booking stands.
"""

from __future__ import annotations

import time

from . import apply as apply_module
from . import config, gate, store

# When each booking is next worth a look. Seeded from what is on disk at start
# so a restart does not re-ask about programmes the site said open in weeks.
_due: dict = {}


def next_due(outcome: dict, now: float) -> float:
    if outcome.get("kind") != "not_open":
        return now + config.RESERVATION_CHECK_INTERVAL
    opens = outcome.get("recruit_start")
    if not opens:
        return now + config.RESERVATION_CHECK_INTERVAL
    if opens > now:
        return max(now + config.RESERVATION_BURST_SECONDS, opens - config.RESERVATION_BURST_SECONDS)
    # Published as open while the gate still says otherwise: worth knocking
    # every couple of seconds right after the published minute, when the site
    # is merely slower than its own clock, and not for ever afterwards.
    if now - opens <= config.RESERVATION_BURST_WINDOW:
        return now + config.RESERVATION_BURST_SECONDS
    return now + config.RESERVATION_CHECK_INTERVAL


def seed_due(now: float = None) -> None:
    """Carry what is already known across a restart."""
    now = time.time() if now is None else now
    for code, entry in (store.deferred() or {}).items():
        if not isinstance(entry, dict) or entry.get("kind") != "not_open":
            continue
        try:
            checked_at = float(entry.get("checkedAt") or 0)
        except (TypeError, ValueError):
            continue
        due = checked_at + config.DEFERRED_RECHECK_SECONDS
        opens_at = entry.get("opensAt")
        if opens_at:
            try:
                due = min(due, float(opens_at) - config.RESERVATION_BURST_SECONDS)
            except (TypeError, ValueError):
                pass
        if due > now:
            _due[str(code)] = due


def tick(now: float = None) -> list:
    """One pass. Returns the outcomes of whatever was actually attempted."""
    now = time.time() if now is None else now
    pending = [program["id"] for program in apply_module.reserved_programs(now)]
    if not pending:
        _due.clear()
        return []
    for stale in [code for code in list(_due) if code not in pending]:
        _due.pop(stale, None)
    if all(now < _due.get(code, 0.0) for code in pending):
        return []

    outcomes = apply_module.run_reserved(now=now, respect_sleep=False)
    seen = set()
    for outcome in outcomes:
        code = str(outcome.get("code") or "")
        seen.add(code)
        if outcome.get("status") in {"applied", "already"}:
            _due.pop(code, None)
        else:
            _due[code] = next_due(outcome, now)
    for code in pending:
        if code not in seen:
            _due[code] = now + config.RESERVATION_CHECK_INTERVAL
    return outcomes


def snapshot(now: float = None) -> list:
    """What the watcher is waiting on, for the status screen."""
    now = time.time() if now is None else now
    state = store.deferred()
    rows = []
    for program in apply_module.reserved_programs(now):
        code = program["id"]
        entry = state.get(code) if isinstance(state.get(code), dict) else {}
        opens_at = entry.get("opensAt")
        rows.append({
            "code": code,
            "title": program["title"],
            "url": program["url"],
            "opensAt": float(opens_at) if opens_at else None,
            "opensLabel": gate.window_label(opens_at) if opens_at else "",
            "lastKind": entry.get("kind", ""),
            "lastDetail": entry.get("detail", ""),
            "checkedAt": entry.get("checkedAt"),
            "nextDueAt": _due.get(code),
            "withAttachment": (store.reservations().get(code) or {}).get("withAttachment", True),
            "attachment": (store.attachment_for(code).name if store.attachment_for(code) else ""),
        })
    rows.sort(key=lambda row: (row["opensAt"] or float("inf")))
    return rows


def run(once: bool = False, quiet: bool = False) -> int:
    """The daemon loop. One second of granularity, which is what the burst needs."""
    seed_due()
    store.touch_heartbeat()
    store.log("감시 시작" + ("" if not once else " (1회)"), echo=not quiet)
    idle_reported = False
    try:
        while True:
            now = time.time()
            pending = apply_module.reserved_programs(now)
            if not pending and not idle_reported:
                store.log("예약이 없습니다. 예약이 추가되면 자동으로 감시합니다.", echo=not quiet)
                idle_reported = True
            elif pending:
                idle_reported = False
            store.touch_heartbeat()
            tick(now)
            if once:
                return 0
            time.sleep(1)
    except KeyboardInterrupt:
        store.log("감시 종료", echo=not quiet)
        return 0
