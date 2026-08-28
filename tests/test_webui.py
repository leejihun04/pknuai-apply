"""The local page, and the two things that keep other pages out of it."""

import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from support import TempHome, fixture

from pknuai_apply import programs, store, webui


def call(url, *, method="GET", data=None, headers=None):
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers or {})


class Server(TempHome):
    def setUp(self):
        super().setUp()
        self.found = programs.parse_programs(fixture("list_page.html"))
        self.original = webui.cached_programs
        webui.cached_programs = lambda refresh=False: (list(self.found), "")
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), webui.Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        webui.cached_programs = self.original
        super().tearDown()

    def post(self, path, payload, headers=None):
        sent = {"Content-Type": "application/json", "X-Pknuai-Apply": "1"}
        sent.update(headers or {})
        return call(self.base + path, method="POST",
                    data=json.dumps(payload).encode("utf-8"), headers=sent)

    # -- pages ---------------------------------------------------------
    def test_the_page_and_its_assets_are_served(self):
        for path, marker in (("/", b"<title>"), ("/assets/app.css", b":root"),
                             ("/assets/app.js", b"X-Pknuai-Apply")):
            status, body, _headers = call(self.base + path)
            self.assertEqual(status, 200, path)
            self.assertIn(marker, body, path)

    def test_state_carries_the_programme_list_and_never_the_cookie(self):
        status, body, _headers = call(self.base + "/api/state")
        payload = json.loads(body)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["programs"]), 2)
        self.assertNotIn("cookie", json.dumps(payload))

    def test_search_narrows_the_list(self):
        _status, body, _headers = call(self.base + "/api/state?q=%EC%9B%8C%ED%81%AC%EC%88%8D")
        self.assertEqual(len(json.loads(body)["programs"]), 1)

    def test_unknown_paths_are_not_found(self):
        self.assertEqual(call(self.base + "/etc/passwd")[0], 404)

    # -- guards --------------------------------------------------------
    def test_a_request_for_another_host_name_is_refused(self):
        # Stops a name that resolves to 127.0.0.1 from driving this server.
        status, _body, _headers = call(self.base + "/api/state", headers={"Host": "evil.example"})
        self.assertEqual(status, 403)

    def test_a_write_without_the_custom_header_is_refused(self):
        status, body, _headers = call(self.base + "/api/reserve", method="POST",
                                      data=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "missing_header")

    def test_a_write_from_another_origin_is_refused(self):
        status, body, _headers = self.post("/api/reserve", {"code": "N202608050"},
                                           headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 403)
        self.assertEqual(json.loads(body)["error"], "bad_origin")

    # -- actions -------------------------------------------------------
    def test_booking_and_cancelling_through_the_page(self):
        status, body, _headers = self.post("/api/reserve", {"code": "N202608050"})
        self.assertEqual((status, json.loads(body)["ok"]), (200, True))
        self.assertIn("N202608050", store.reservations())
        self.post("/api/reserve", {"code": "N202608050", "reserved": False})
        self.assertEqual(store.reservations(), {})

    def test_booking_something_not_on_the_list_is_refused(self):
        status, body, _headers = self.post("/api/reserve", {"code": "N999"})
        self.assertEqual(status, 404)
        self.assertFalse(json.loads(body)["ok"])

    def test_the_attachment_round_trip(self):
        boundary = "----test"
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"신청서식.hwp\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\nhello\r\n"
            f"--{boundary}--\r\n"
        ).encode("utf-8")
        status, response, _headers = call(
            self.base + "/api/attachment/N202608050", method="POST", data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "X-Pknuai-Apply": "1"},
        )
        self.assertEqual((status, json.loads(response)["name"]), (200, "N202608050.hwp"))

        status, content, headers = call(self.base + "/api/attachment/N202608050")
        self.assertEqual((status, content), (200, b"hello"))
        self.assertIn("attachment", headers.get("Content-Disposition", ""))

        status, _content, _headers = call(self.base + "/api/attachment/N202608050",
                                          method="DELETE", headers={"X-Pknuai-Apply": "1"})
        self.assertEqual(status, 200)
        self.assertIsNone(store.attachment_for("N202608050"))

    def test_asking_for_a_missing_attachment_is_not_found(self):
        self.assertEqual(call(self.base + "/api/attachment/N999")[0], 404)

    def test_state_lists_the_browsers_a_session_could_be_imported_from(self):
        from pknuai_apply import browsercookies
        self.original_browsers = browsercookies.available_browsers
        browsercookies.available_browsers = lambda: ["Chrome", "Edge"]
        try:
            _status, body, _headers = call(self.base + "/api/state")
            self.assertEqual(json.loads(body)["browsers"], ["Chrome", "Edge"])
        finally:
            browsercookies.available_browsers = self.original_browsers

    def test_import_runs_the_flow_and_never_returns_the_cookie(self):
        from pknuai_apply import login_flow
        original = login_flow.import_session
        login_flow.import_session = lambda browser="": {"ok": True, "reason": "Chrome 에서 가져왔습니다",
                                                        "browser": "Chrome", "cookie": "secret"}
        try:
            status, body, _headers = self.post("/api/session/import", {})
            payload = json.loads(body)
            self.assertEqual((status, payload["ok"]), (200, True))
            # The endpoint echoes the flow result; the cookie value itself is
            # not something the page needs, and the real flow never puts it here.
            self.assertNotIn("secret", json.dumps(payload))
        finally:
            login_flow.import_session = original

    def test_open_login_needs_the_custom_header(self):
        status, _body, _headers = call(self.base + "/api/session/open-login", method="POST",
                                       data=b"{}", headers={"Content-Type": "application/json"})
        self.assertEqual(status, 403)


if __name__ == "__main__":
    unittest.main()
