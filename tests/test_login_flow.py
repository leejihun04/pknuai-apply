"""Importing and waiting for a session, with the browser mocked out."""

import unittest

from support import TempHome

from pknuai_apply import browsercookies, login_flow, session


class ImportSession(TempHome):
    def setUp(self):
        super().setUp()
        self._gather = browsercookies.gather
        self._check = session.check
        self._available = browsercookies.available_browsers

    def tearDown(self):
        browsercookies.gather = self._gather
        session.check = self._check
        browsercookies.available_browsers = self._available
        super().tearDown()

    def test_a_working_session_is_stored(self):
        browsercookies.gather = lambda browser="": [("Chrome", "JSESSIONID=OK")]
        session.check = lambda: {"ok": True, "reason": "정상", "savedAt": 1.0}
        result = login_flow.import_session()
        self.assertTrue(result["ok"])
        self.assertEqual(result["browser"], "Chrome")
        self.assertEqual(session.load_cookie(), "JSESSIONID=OK")

    def test_a_rejected_cookie_is_not_left_behind(self):
        # A stale cookie the site refuses must not sit in the store pretending
        # to be a session; the next command would trust it.
        browsercookies.gather = lambda browser="": [("Chrome", "JSESSIONID=STALE")]
        session.check = lambda: {"ok": False, "reason": "거부됨", "savedAt": 0}
        result = login_flow.import_session()
        self.assertFalse(result["ok"])
        self.assertEqual(session.load_cookie(), "")

    def test_the_first_accepted_profile_wins(self):
        browsercookies.gather = lambda browser="": [("Chrome", "JSESSIONID=A"), ("Edge", "JSESSIONID=B")]
        calls = []

        def fake_check():
            calls.append(session.load_cookie())
            return {"ok": session.load_cookie() == "JSESSIONID=B", "reason": "", "savedAt": 1.0}

        session.check = fake_check
        result = login_flow.import_session()
        self.assertTrue(result["ok"])
        self.assertEqual(result["browser"], "Edge")

    def test_no_browser_session_is_reported_clearly(self):
        browsercookies.gather = lambda browser="": []
        browsercookies.available_browsers = lambda: ["Chrome"]
        result = login_flow.import_session()
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("no_session"))

    def test_a_keychain_refusal_is_surfaced_not_swallowed(self):
        def refuse(browser=""):
            raise browsercookies.BrowserImportError("키체인 접근이 허용되지 않았습니다.")

        browsercookies.gather = refuse
        result = login_flow.import_session()
        self.assertFalse(result["ok"])
        self.assertIn("키체인", result["reason"])


class WaitForLogin(TempHome):
    def setUp(self):
        super().setUp()
        self._import = login_flow.import_session
        self._open = login_flow._open_browser

    def tearDown(self):
        login_flow.import_session = self._import
        login_flow._open_browser = self._open
        super().tearDown()

    def test_it_returns_at_once_when_already_logged_in(self):
        opened = []
        login_flow._open_browser = lambda *a, **k: opened.append(True)
        login_flow.import_session = lambda browser="": {"ok": True, "reason": "정상"}
        result = login_flow.wait_for_login(timeout=1, interval=1)
        self.assertTrue(result["ok"])
        self.assertEqual(opened, [])  # no need to open a browser

    def test_it_opens_the_browser_then_catches_the_session(self):
        login_flow._open_browser = lambda *a, **k: True
        attempts = {"n": 0}

        def fake_import(browser=""):
            attempts["n"] += 1
            return {"ok": attempts["n"] >= 2, "reason": "정상" if attempts["n"] >= 2 else "아직"}

        login_flow.import_session = fake_import
        result = login_flow.wait_for_login(timeout=5, interval=0)
        self.assertTrue(result["ok"])

    def test_it_gives_up_after_the_timeout(self):
        login_flow._open_browser = lambda *a, **k: True
        login_flow.import_session = lambda browser="": {"ok": False, "reason": "아직"}
        result = login_flow.wait_for_login(timeout=0, interval=0)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("timed_out"))


if __name__ == "__main__":
    unittest.main()
