"""What the tool remembers between runs."""

import time
import unittest

from support import TempHome

from pknuai_apply import config, store

PROGRAM = {"id": "N202608050", "title": "토크콘서트",
           "url": "https://pknuai.pknu.ac.kr/web/nonSbjt/programDetail.do?mId=216&yy=2026"
                  "&shtm=20&nonsubjcCd=N202608050&nonsubjcCrsCd=001"}


class Reservations(TempHome):
    def test_a_booking_keeps_the_url_it_was_made_from(self):
        # The list only shows the newest pages; a programme booked three weeks
        # early has scrolled off by the time it opens, and without the stored
        # URL the watcher would have nothing to knock on.
        store.reserve(PROGRAM)
        self.assertEqual(store.reservations()[PROGRAM["id"]]["url"], PROGRAM["url"])

    def test_cancelling_forgets_the_booking_and_its_deferral(self):
        store.reserve(PROGRAM)
        store.note_deferral(PROGRAM["id"], "not_open", "아직")
        self.assertTrue(store.cancel(PROGRAM["id"]))
        self.assertEqual(store.reservations(), {})
        self.assertEqual(store.deferred(), {})
        self.assertFalse(store.cancel(PROGRAM["id"]))

    def test_the_attachment_switch_defaults_to_on(self):
        store.reserve(PROGRAM)
        self.assertFalse(store.attachment_opted_out(PROGRAM["id"]))
        store.reserve(PROGRAM, with_attachment=False)
        self.assertTrue(store.attachment_opted_out(PROGRAM["id"]))

    def test_a_booking_without_a_code_is_refused(self):
        with self.assertRaises(ValueError):
            store.reserve({"title": "no code"})


class Deferrals(TempHome):
    def test_a_programme_that_opens_later_is_left_alone_for_a_while(self):
        now = time.time()
        store.note_deferral("N1", "not_open", "아직", now + 86400, now)
        self.assertTrue(store.still_sleeping("N1", now + 60))
        self.assertFalse(store.still_sleeping("N1", now + config.DEFERRED_RECHECK_SECONDS + 1))

    def test_the_sleep_never_outlasts_the_opening_minute(self):
        now = time.time()
        opens = now + 60
        store.note_deferral("N1", "not_open", "아직", opens, now)
        self.assertFalse(store.still_sleeping("N1", opens + 1))

    def test_only_a_not_open_verdict_sleeps(self):
        now = time.time()
        store.note_deferral("N1", "unreadable", "읽지 못함", None, now)
        self.assertFalse(store.still_sleeping("N1", now + 1))

    def test_repeating_the_same_reason_is_not_news(self):
        self.assertTrue(store.note_deferral("N1", "not_open", "아직"))
        self.assertFalse(store.note_deferral("N1", "not_open", "아직"))
        self.assertTrue(store.note_deferral("N1", "not_open", "다른 이유"))


class Attachments(TempHome):
    def test_a_file_is_stored_under_the_programme_code(self):
        path = store.save_attachment("N1", "신청서식.hwp", b"hello")
        self.assertEqual(path.name, "N1.hwp")
        self.assertEqual(store.attachment_for("N1").read_bytes(), b"hello")

    def test_an_uploaded_name_cannot_escape_the_directory(self):
        path = store.save_attachment("N1", "../../../etc/passwd", b"x")
        self.assertEqual(path.parent, store.attachment_dir())
        self.assertEqual(path.name, "N1.bin")

    def test_replacing_a_file_leaves_only_the_new_one(self):
        store.save_attachment("N1", "a.hwp", b"1")
        store.save_attachment("N1", "b.pdf", b"2")
        self.assertEqual(sorted(p.name for p in store.attachment_dir().glob("N1.*")), ["N1.pdf"])

    def test_an_empty_file_is_not_offered_as_an_attachment(self):
        store.save_attachment("N1", "a.hwp", b"")
        self.assertIsNone(store.attachment_for("N1"))

    def test_deleting_reports_whether_anything_went(self):
        store.save_attachment("N1", "a.hwp", b"1")
        self.assertTrue(store.delete_attachment("N1"))
        self.assertFalse(store.delete_attachment("N1"))


class Log(TempHome):
    def test_lines_are_kept_and_read_back_newest_last(self):
        store.log("첫 줄", echo=False)
        store.log("둘째 줄", echo=False)
        self.assertEqual(len(store.tail(10)), 2)
        self.assertIn("둘째 줄", store.tail(1)[0])

    def test_a_broken_file_reads_as_empty_rather_than_raising(self):
        store.save_json(config.RESERVATIONS_FILE, {"N1": {"title": "x"}})
        (store.config.data_dir() / config.RESERVATIONS_FILE).write_text("{{{", encoding="utf-8")
        self.assertEqual(store.reservations(), {})


if __name__ == "__main__":
    unittest.main()
