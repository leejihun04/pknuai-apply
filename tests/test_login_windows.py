"""The Windows-shaped paths, exercised with the OS-specific bits mocked."""

import unittest

from support import TempHome

from pknuai_apply import browsercookies, browserlaunch, login_flow, session


class CdpCapture(TempHome):
    def setUp(self):
        super().setUp()
        self._pick = browserlaunch.pick
        self._launch = browserlaunch.launch_for_debugging
        self._url = login_flow.cdp.browser_websocket_url
        self._cookies = login_flow.cdp.all_cookies
        self._check = session.check

    def tearDown(self):
        browserlaunch.pick = self._pick
        browserlaunch.launch_for_debugging = self._launch
        login_flow.cdp.browser_websocket_url = self._url
        login_flow.cdp.all_cookies = self._cookies
        session.check = self._check
        super().tearDown()

    class _Proc:
        def __init__(self):
            self.terminated = False

        def terminate(self):
            self.terminated = True

    def test_it_opens_a_browser_and_captures_the_cookie_the_login_sets(self):
        proc = self._Proc()
        browserlaunch.pick = lambda browser="": ("Edge", r"C:\msedge.exe")
        browserlaunch.launch_for_debugging = lambda *a, **k: proc
        login_flow.cdp.browser_websocket_url = lambda port, timeout=2.0: "ws://127.0.0.1:1/x"
        state = {"n": 0}

        def cookies(port, timeout=5.0):
            state["n"] += 1
            # The window is empty until the student finishes the login.
            if state["n"] < 2:
                return []
            return [{"name": "JSESSIONID", "value": "LIVE", "domain": "pknuai.pknu.ac.kr"}]

        login_flow.cdp.all_cookies = cookies
        session.check = lambda: {"ok": True, "reason": "정상", "savedAt": 1.0}
        result = login_flow.capture_via_cdp(timeout=5, interval=0)
        self.assertTrue(result["ok"])
        self.assertIn("Edge", result["browser"])
        self.assertEqual(session.load_cookie(), "JSESSIONID=LIVE")
        self.assertTrue(proc.terminated)  # the throwaway window is closed after

    def test_no_browser_present_is_reported(self):
        browserlaunch.pick = lambda browser="": None
        result = login_flow.capture_via_cdp(timeout=1, interval=0)
        self.assertFalse(result["ok"])
        self.assertTrue(result.get("no_browser"))

    def test_a_captured_cookie_the_site_rejects_is_not_kept(self):
        browserlaunch.pick = lambda browser="": ("Chrome", r"C:\chrome.exe")
        browserlaunch.launch_for_debugging = lambda *a, **k: self._Proc()
        login_flow.cdp.browser_websocket_url = lambda port, timeout=2.0: "ws://x"
        login_flow.cdp.all_cookies = lambda port, timeout=5.0: [
            {"name": "JSESSIONID", "value": "STALE", "domain": "pknuai.pknu.ac.kr"}]
        session.check = lambda: {"ok": False, "reason": "거부", "savedAt": 0}
        result = login_flow.capture_via_cdp(timeout=0, interval=0)
        self.assertFalse(result["ok"])
        self.assertEqual(session.load_cookie(), "")


class WindowsImportRouting(TempHome):
    def setUp(self):
        super().setUp()
        self._system = browsercookies.platform.system

    def tearDown(self):
        browsercookies.platform.system = self._system
        super().tearDown()

    def test_chromium_is_not_read_off_disk_on_windows(self):
        # App-Bound Encryption makes that pointless; those users take the CDP
        # path instead, so import must not claim Chrome/Edge here.
        browsercookies.platform.system = lambda: "Windows"
        self.assertEqual(browsercookies.chromium_profiles(), [])

    def test_a_cdp_header_needs_a_real_session_cookie(self):
        # A window that only carries analytics cookies is not a login yet.
        original = login_flow.cdp.all_cookies
        login_flow.cdp.all_cookies = lambda port, timeout=5.0: [
            {"name": "_ga", "value": "GA1", "domain": ".pknu.ac.kr"}]
        try:
            self.assertEqual(login_flow._header_from_cdp(1), "")
            login_flow.cdp.all_cookies = lambda port, timeout=5.0: [
                {"name": "JSESSIONID", "value": "S", "domain": "pknuai.pknu.ac.kr"},
                {"name": "_ga", "value": "GA1", "domain": ".pknu.ac.kr"}]
            header = login_flow._header_from_cdp(1)
            self.assertIn("JSESSIONID=S", header)
            self.assertIn("_ga=GA1", header)
        finally:
            login_flow.cdp.all_cookies = original


if __name__ == "__main__":
    unittest.main()
