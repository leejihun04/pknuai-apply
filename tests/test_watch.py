"""When the watcher looks, and how hard it knocks."""

import unittest

from support import TempHome

from pknuai_apply import apply as apply_module
from pknuai_apply import config, store, watch

NOW = 1_800_000_000.0
PROGRAM = {"id": "N1", "title": "토크콘서트",
           "url": "https://pknuai.pknu.ac.kr/web/nonSbjt/programDetail.do?mId=216&yy=2026"
                  "&shtm=20&nonsubjcCd=N1&nonsubjcCrsCd=001"}


class Cadence(TempHome):
    def test_it_sleeps_until_just_before_a_published_opening(self):
        due = watch.next_due({"kind": "not_open", "recruit_start": NOW + 3600}, NOW)
        self.assertAlmostEqual(due, NOW + 3600 - config.RESERVATION_BURST_SECONDS, places=3)

    def test_it_knocks_every_couple_of_seconds_right_after_the_published_minute(self):
        due = watch.next_due({"kind": "not_open", "recruit_start": NOW - 5}, NOW)
        self.assertAlmostEqual(due, NOW + config.RESERVATION_BURST_SECONDS, places=3)

    def test_the_burst_is_bounded(self):
        # One forgotten booking knocking every two seconds for ever is tens of
        # thousands of requests a day at the university's site.
        stale = NOW - config.RESERVATION_BURST_WINDOW - 1
        due = watch.next_due({"kind": "not_open", "recruit_start": stale}, NOW)
        self.assertAlmostEqual(due, NOW + config.RESERVATION_CHECK_INTERVAL, places=3)

    def test_anything_else_falls_back_to_the_ordinary_beat(self):
        for outcome in ({"kind": "not_open"}, {"kind": "unreadable"}, {"kind": ""}):
            self.assertAlmostEqual(watch.next_due(outcome, NOW),
                                   NOW + config.RESERVATION_CHECK_INTERVAL, places=3)


class Ticking(TempHome):
    def setUp(self):
        super().setUp()
        watch._due.clear()
        self.attempts = []
        self.original = apply_module.run_reserved
        apply_module.run_reserved = self.fake_run

    def tearDown(self):
        apply_module.run_reserved = self.original
        watch._due.clear()
        super().tearDown()

    def fake_run(self, **kwargs):
        self.attempts.append(kwargs)
        return [{"code": "N1", "title": "토크콘서트", "url": PROGRAM["url"],
                 "status": "skipped", "kind": "not_open", "reason": "아직",
                 "recruit_start": NOW + 3600}]

    def test_nothing_to_do_without_a_booking(self):
        self.assertEqual(watch.tick(NOW), [])
        self.assertEqual(self.attempts, [])

    def test_a_booking_is_tried_once_and_then_left_until_it_is_due(self):
        store.reserve(PROGRAM)
        self.assertEqual(len(watch.tick(NOW)), 1)
        self.assertEqual(watch.tick(NOW + 1), [])
        self.assertEqual(len(self.attempts), 1)

    def test_the_watcher_ignores_the_crawl_length_sleep(self):
        store.reserve(PROGRAM)
        store.note_deferral("N1", "not_open", "아직", NOW + 3600, NOW)
        watch.tick(NOW)
        self.assertEqual(self.attempts[0]["respect_sleep"], False)

    def test_a_restart_does_not_re_ask_about_a_programme_that_opens_in_weeks(self):
        store.reserve(PROGRAM)
        store.note_deferral("N1", "not_open", "아직", NOW + 86400, NOW)
        watch._due.clear()
        watch.seed_due(NOW)
        self.assertEqual(watch.tick(NOW + 5), [])

    def test_a_cancelled_booking_stops_being_watched(self):
        store.reserve(PROGRAM)
        watch.tick(NOW)
        store.cancel("N1")
        self.assertEqual(watch.tick(NOW + 10_000), [])


class Snapshot(TempHome):
    def test_it_reports_the_published_opening_and_the_last_verdict(self):
        store.reserve(PROGRAM)
        store.note_deferral("N1", "not_open", "아직 모집 기간이 아닙니다", NOW + 3600, NOW)
        rows = watch.snapshot(NOW)
        self.assertEqual(rows[0]["code"], "N1")
        self.assertEqual(rows[0]["lastKind"], "not_open")
        self.assertTrue(rows[0]["opensLabel"])

    def test_it_shows_a_stored_file_and_whether_it_will_be_sent(self):
        store.reserve(PROGRAM, with_attachment=False)
        store.save_attachment("N1", "form.hwp", b"x")
        row = watch.snapshot(NOW)[0]
        self.assertEqual(row["attachment"], "N1.hwp")
        self.assertFalse(row["withAttachment"])


if __name__ == "__main__":
    unittest.main()
