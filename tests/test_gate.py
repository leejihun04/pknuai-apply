"""The guards that decide whether an application may be sent."""

import time
import unittest

from support import TempHome, fixture

from pknuai_apply import gate


class RecruitWindow(TempHome):
    def test_entities_do_not_hide_the_published_minute(self):
        # pknuai writes the window with &nbsp; between date and time. Matching
        # before decoding once read a 09:00 opening as midnight and never saw
        # the closing date at all.
        opens, closes = gate.parse_recruit_window(fixture("detail_open.html"))
        self.assertEqual(gate.window_label(opens), "2026.08.24 09:00")
        self.assertEqual(gate.window_label(closes), "2026.09.09 23:00")

    def test_date_only_window_closes_at_the_end_of_its_last_day(self):
        opens, closes = gate.parse_recruit_window("<p>모집기간 : 2026.08.24 ~ 2026.09.09</p>")
        self.assertEqual(gate.window_label(opens), "2026.08.24 00:00")
        self.assertEqual(gate.window_label(closes), "2026.09.09 23:59")

    def test_no_window_is_not_an_invented_one(self):
        self.assertEqual(gate.parse_recruit_window("<p>운영기간 2026.09.15</p>"), (None, None))

    def test_impossible_date_is_rejected(self):
        opens, _closes = gate.parse_recruit_window("<p>모집기간 : 2026.02.31 ~ 2026.03.01</p>")
        self.assertIsNone(opens)


class Blockers(TempHome):
    def gate_for(self, name):
        return gate.parse_apply_gate(fixture(name))

    def test_open_programme_has_no_blocker(self):
        parsed = self.gate_for("detail_open.html")
        self.assertEqual(gate.blocker({}, parsed, parsed["recruit_start"] + 60), ("", ""))

    def test_before_the_window_defers_instead_of_applying(self):
        parsed = self.gate_for("detail_open.html")
        kind, _message = gate.blocker({}, parsed, parsed["recruit_start"] - 1)
        self.assertEqual(kind, "not_open")

    def test_after_the_window_is_a_final_verdict(self):
        parsed = self.gate_for("detail_open.html")
        kind, _message = gate.blocker({}, parsed, parsed["recruit_end"] + 1)
        self.assertEqual(kind, "window_closed")

    def test_a_seat_already_held_counts_even_before_the_programme_starts(self):
        # pknuai says 신청 from acceptance and only 수강중 once it has started.
        parsed = self.gate_for("detail_applied.html")
        kind, message = gate.blocker({}, parsed, parsed["recruit_start"] + 60)
        self.assertEqual(kind, "enrolled")
        self.assertIn("이미 신청", message)

    def test_survey_team_and_external_are_left_to_a_human(self):
        for name, expected in (("detail_survey.html", "survey"),
                               ("detail_team.html", "team"),
                               ("detail_external.html", "external")):
            parsed = self.gate_for(name)
            kind, _message = gate.blocker({}, parsed, parsed["recruit_start"] + 60)
            self.assertEqual(kind, expected, name)

    def test_unreadable_page_blocks(self):
        self.assertEqual(gate.blocker({}, gate.parse_apply_gate("<html></html>"), time.time())[0],
                         "unreadable")

    def test_pknu_hosted_links_are_not_external_applications(self):
        html = '<a data-link-addr="https://www.pknu.ac.kr/x">안내</a>'
        self.assertEqual(gate.external_apply_links(html), [])


class ApplyPage(TempHome):
    def test_upload_fields_come_from_the_pages_own_script(self):
        fields = gate.parse_upload_fields(fixture("apply_page.html"))
        self.assertEqual(fields["recvNo"], "778899")
        self.assertEqual(fields["nonsubjcCd"], "N202608050")

    def test_team_branch_never_supplies_a_receipt_number(self):
        self.assertEqual(gate.parse_upload_fields(fixture("apply_page_team.html"))["recvNo"], "")

    def test_button_attribute_is_read_out_of_the_matching_tag(self):
        # The page finds these buttons by id prefix and writes the attributes
        # in no fixed order, so an exact-id regex quietly reads an empty value.
        self.assertEqual(gate.button_attr(fixture("apply_page_required.html"),
                                          "applyApplyBtn", "data-atch"), "1")
        self.assertEqual(gate.button_attr(fixture("apply_page.html"),
                                          "applyApplyBtn", "data-atch"), "0")
        self.assertEqual(gate.button_attr(fixture("apply_page.html"),
                                          "applyApplyBtn", "data-missing"), "")

    def test_program_params_need_all_four_identifiers(self):
        self.assertEqual(gate.program_params("https://x/?yy=2026&shtm=20"), {})
        self.assertEqual(
            gate.program_params("https://x/?yy=2026&shtm=20&nonsubjcCd=N1&nonsubjcCrsCd=001")["nonsubjcCd"],
            "N1",
        )


if __name__ == "__main__":
    unittest.main()
