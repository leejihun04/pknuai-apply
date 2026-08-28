"""Reading the programme list."""

import unittest

from support import TempHome, fixture

from pknuai_apply import gate, programs


class ListParsing(TempHome):
    def setUp(self):
        super().setUp()
        self.found = programs.parse_programs(fixture("list_page.html"))

    def test_a_programme_rendered_twice_is_one_programme(self):
        self.assertEqual([p["id"] for p in self.found], ["N202608050", "N202608044"])

    def test_the_visible_heading_wins_over_the_stale_title_attribute(self):
        self.assertTrue(self.found[0]["title"].startswith("현직자 온라인 토크콘서트"))

    def test_every_row_carries_the_four_identifiers_the_apply_flow_needs(self):
        for program in self.found:
            self.assertTrue(gate.program_params(program["url"]), program["id"])

    def test_recruit_dates_are_kept_as_printed(self):
        self.assertEqual(self.found[0]["date"], "2026-08-24")
        self.assertEqual(self.found[0]["recruit_text"], "2026-08-24 ~ 2026-09-09")

    def test_organizer_is_appended_only_when_it_is_not_already_there(self):
        self.assertEqual(self.found[1]["title"], "진로설계 워크숍 (취업지원과)")

    def test_search_needs_every_word(self):
        self.assertEqual([p["id"] for p in programs.search(self.found, "진로 워크숍")], ["N202608044"])
        self.assertEqual(programs.search(self.found, "진로 없는말"), [])
        self.assertEqual(len(programs.search(self.found, "")), 2)

    def test_a_page_without_programmes_yields_nothing(self):
        self.assertEqual(programs.parse_programs("<html><body>없음</body></html>"), [])


if __name__ == "__main__":
    unittest.main()
