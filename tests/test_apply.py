"""The submission itself: what it sends, and what stops it."""

import json
import time
import unittest

from support import TempHome, fixture

from pknuai_apply import apply as apply_module
from pknuai_apply import config, gate, http_client, session, store

PROGRAM = {
    "id": "N202608050",
    "title": "현직자 온라인 토크콘서트 (취업지원과)",
    "url": ("https://pknuai.pknu.ac.kr/web/nonSbjt/programDetail.do?mId=216&yy=2026"
            "&shtm=20&nonsubjcCd=N202608050&nonsubjcCrsCd=001"),
}


class FakeSite:
    """Stands in for pknuai, and remembers exactly what was sent to it."""

    def __init__(self, detail="detail_open.html", apply_page="apply_page.html",
                 submit_result="OK", detail_status=200, ready_page=None):
        self.detail = fixture(detail)
        self.apply_page = fixture(apply_page)
        self.ready_page = fixture(ready_page) if ready_page else self.apply_page
        self.submit_result = submit_result
        self.detail_status = detail_status
        self.calls = []

    def __call__(self, method, url, **kwargs):
        self.calls.append({"method": method, "url": url, **kwargs})
        if url.startswith(config.PROGRAM_DETAIL_URL):
            return http_client.Response(self.detail_status, self.detail)
        if url.startswith(config.APPLY_PAGE_URL):
            page = self.apply_page if self.count(config.APPLY_PAGE_URL) == 1 else self.ready_page
            return http_client.Response(200, page)
        if url.startswith(config.APPLY_INIT_URL):
            return http_client.Response(200, json.dumps({"result": "1"}))
        if url.startswith(config.APPLY_SUBMIT_URL):
            return http_client.Response(200, json.dumps({"result": self.submit_result}))
        if url.startswith(config.APPLY_FILES_URL):
            return http_client.Response(200, json.dumps({"result": "DONE"}))
        raise AssertionError(f"unexpected call: {url}")

    def count(self, prefix):
        return len([call for call in self.calls if call["url"].startswith(prefix)])

    def last(self, prefix):
        for call in reversed(self.calls):
            if call["url"].startswith(prefix):
                return call
        return None


class ApplyFlow(TempHome):
    def setUp(self):
        super().setUp()
        self.original = http_client.request

    def tearDown(self):
        http_client.request = self.original
        super().tearDown()

    def use(self, site):
        http_client.request = site
        return site

    def when_open(self, site=None):
        site = site or FakeSite()
        parsed = gate.parse_apply_gate(site.detail)
        return site, parsed["recruit_start"] + 60

    def test_an_open_programme_is_applied_for(self):
        site, now = self.when_open(self.use(FakeSite()))
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual(outcome["status"], "applied")
        self.assertEqual(outcome["recv_no"], "778899")

    def test_the_submission_carries_the_csrf_token_and_the_pages_own_identifiers(self):
        site, now = self.when_open(self.use(FakeSite()))
        apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        submit = site.last(config.APPLY_SUBMIT_URL)
        self.assertEqual(submit["headers"]["X-CSRF-Token"], "c1f0a0e2-token")
        self.assertEqual(submit["headers"]["Ajax"], "true")
        self.assertEqual(submit["data"], {"yy": "2026", "shtm": "20",
                                          "nonsubjcCd": "N202608050", "recvNo": "778899"})

    def test_nothing_is_sent_before_the_window_opens(self):
        site = self.use(FakeSite())
        parsed = gate.parse_apply_gate(site.detail)
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x",
                                                now=parsed["recruit_start"] - 3600)
        self.assertEqual((outcome["status"], outcome["kind"]), ("skipped", "not_open"))
        self.assertEqual(outcome["recruit_start"], parsed["recruit_start"])
        self.assertEqual([call for call in site.calls if call["method"] == "POST"], [])

    def test_nothing_is_sent_after_the_window_closes(self):
        site = self.use(FakeSite())
        parsed = gate.parse_apply_gate(site.detail)
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x",
                                                now=parsed["recruit_end"] + 3600)
        self.assertEqual(outcome["kind"], "window_closed")
        self.assertEqual(site.count(config.APPLY_SUBMIT_URL), 0)

    def test_a_dry_run_stops_before_the_first_write(self):
        site, now = self.when_open(self.use(FakeSite()))
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", dry_run=True, now=now)
        self.assertEqual(outcome["status"], "would_apply")
        self.assertEqual([call for call in site.calls if call["method"] == "POST"], [])

    def test_a_required_file_that_is_missing_defers_instead_of_applying(self):
        site, now = self.when_open(self.use(FakeSite(apply_page="apply_page_required.html")))
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual((outcome["status"], outcome["kind"]), ("skipped", "attachment_missing"))
        self.assertEqual(site.count(config.APPLY_SUBMIT_URL), 0)
        store.save_attachment(PROGRAM["id"], "form.hwp", b"x")
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual((outcome["status"], outcome["attachment"]), ("applied", "N202608050.hwp"))

    def test_the_stored_file_is_bound_to_the_application(self):
        site, now = self.when_open(self.use(FakeSite()))
        store.save_attachment(PROGRAM["id"], "신청서식.hwp", b"hello")
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        upload = site.last(config.APPLY_FILES_URL)
        self.assertEqual(outcome["attachment"], "N202608050.hwp")
        # applyFiles.do stores a file against nothing when the identifiers are
        # missing, and still answers 200 — so they have to be on the wire.
        self.assertIn(b'name="recvNo"', upload["body"])
        self.assertIn(b"778899", upload["body"])
        self.assertIn(b"N202608050", upload["body"])
        # The page does not send this header on the upload, so neither do we.
        self.assertNotIn("Ajax", upload["headers"])

    def test_a_stored_file_is_still_sent_when_the_page_does_not_demand_one(self):
        site, now = self.when_open(self.use(FakeSite()))
        store.save_attachment(PROGRAM["id"], "form.hwp", b"x")
        store.reserve(PROGRAM, with_attachment=False)
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual(outcome["status"], "applied")
        self.assertEqual(site.count(config.APPLY_FILES_URL), 0)

    def test_turning_the_file_off_where_the_page_demands_one_stops_the_application(self):
        site, now = self.when_open(self.use(FakeSite(apply_page="apply_page_required.html")))
        store.save_attachment(PROGRAM["id"], "form.hwp", b"x")
        store.reserve(PROGRAM, with_attachment=False)
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual((outcome["status"], outcome["kind"]), ("skipped", "attachment_missing"))
        self.assertIn("꺼져", outcome["reason"])
        self.assertEqual(site.count(config.APPLY_SUBMIT_URL), 0)

    def test_an_unreadable_receipt_number_stops_the_submission(self):
        site, now = self.when_open(self.use(FakeSite(ready_page="detail_open.html")))
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual((outcome["status"], outcome["kind"]), ("failed", "unreadable"))
        self.assertEqual(site.count(config.APPLY_SUBMIT_URL), 0)

    def test_the_sites_already_applied_answer_is_not_a_failure(self):
        site, now = self.when_open(self.use(FakeSite(submit_result=config.ALREADY_APPLIED_RESULT)))
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual(outcome["status"], "already")

    def test_an_expired_session_is_reported_as_such(self):
        site, now = self.when_open(self.use(FakeSite(detail_status=403)))
        outcome = apply_module.apply_to_program(PROGRAM, "JSESSIONID=x", now=now)
        self.assertEqual((outcome["status"], outcome["kind"]), ("login_required", "session"))


class Concurrency(TempHome):
    def setUp(self):
        super().setUp()
        session.save_cookie("JSESSIONID=test")
        self.original_request = http_client.request
        self.original_ledger = store.ledger

    def tearDown(self):
        http_client.request = self.original_request
        store.ledger = self.original_ledger
        super().tearDown()

    def test_a_seat_taken_between_the_queue_and_the_lock_is_not_applied_for(self):
        # The watcher and the web page are separate processes. The second one
        # to get the lock must notice that the ledger changed underneath it.
        site = FakeSite()
        http_client.request = site
        store.reserve(PROGRAM)
        calls = {"n": 0}

        def racing_ledger():
            calls["n"] += 1
            # Empty while the queue is built, taken by the time the lock is won.
            return {} if calls["n"] <= 1 else {PROGRAM["id"]: {"status": "applied"}}

        store.ledger = racing_ledger
        outcomes = apply_module.run_reserved(respect_sleep=False)
        self.assertEqual(outcomes, [])
        self.assertEqual(site.count(config.APPLY_SUBMIT_URL), 0)


class Enrolment(TempHome):
    def setUp(self):
        super().setUp()
        session.save_cookie("JSESSIONID=test")
        self.original = http_client.request

    def tearDown(self):
        http_client.request = self.original
        super().tearDown()

    def test_a_seat_taken_by_hand_is_noticed(self):
        http_client.request = FakeSite(detail="detail_applied.html")
        state = apply_module.refresh_enrolment([PROGRAM])
        self.assertEqual(state[PROGRAM["id"]]["state"], "신청")

    def test_an_expired_session_is_not_written_down_as_not_enrolled(self):
        http_client.request = FakeSite(detail_status=403)
        self.assertEqual(apply_module.refresh_enrolment([PROGRAM]), {})


class Settling(TempHome):
    def test_a_taken_seat_is_written_down_and_the_booking_released(self):
        store.reserve(PROGRAM)
        apply_module.settle({**PROGRAM, "code": PROGRAM["id"], "status": "applied",
                             "kind": "", "reason": "", "result": "OK", "recv_no": "1"})
        self.assertIn(PROGRAM["id"], store.ledger())
        self.assertNotIn(PROGRAM["id"], store.reservations())

    def test_a_seat_taken_by_hand_is_recorded_as_taken_not_refused(self):
        store.reserve(PROGRAM)
        apply_module.settle({**PROGRAM, "code": PROGRAM["id"], "status": "skipped",
                             "kind": "enrolled", "reason": "이미 신청한 프로그램입니다"})
        self.assertEqual(store.ledger()[PROGRAM["id"]]["status"], "already")

    def test_a_retryable_skip_keeps_the_booking(self):
        store.reserve(PROGRAM)
        apply_module.settle({**PROGRAM, "code": PROGRAM["id"], "status": "skipped",
                             "kind": "not_open", "reason": "아직", "recruit_start": time.time() + 600})
        self.assertIn(PROGRAM["id"], store.reservations())
        self.assertEqual(store.deferred()[PROGRAM["id"]]["kind"], "not_open")

    def test_a_programme_on_record_is_never_attempted_again(self):
        store.reserve(PROGRAM)
        store.record(PROGRAM["id"], {"title": PROGRAM["title"], "status": "applied"})
        self.assertEqual(apply_module.reserved_programs(time.time()), [])

    def test_a_booking_without_identifiers_is_ignored(self):
        store.reserve({"id": "N1", "title": "x", "url": "https://pknuai.pknu.ac.kr/x"})
        self.assertEqual(apply_module.reserved_programs(time.time()), [])


if __name__ == "__main__":
    unittest.main()
