"""A small web page on this machine, for the parts a form does better.

It listens on the loopback interface only. Two things keep a web page in
another tab from driving it anyway: the Host header must be this server's own
address (so a name that resolves to 127.0.0.1 cannot reach it), and every
state-changing call must carry a header a cross-site form cannot set.

The pknuai session cookie is never sent to the browser — the page only ever
learns whether there is one and whether the site still accepts it.
"""

from __future__ import annotations

import json
import platform
import re
import socket
import threading
import time
from email.parser import BytesParser
from email.policy import default as email_default
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import apply as apply_module
from . import agent, browsercookies, config, login_flow, programs, session, store, watch

ASSETS = Path(__file__).resolve().parent.parent / "assets"
CACHE_SECONDS = 120
MAX_UPLOAD_BYTES = 20 * 1024 * 1024

_cache: dict = {"at": 0.0, "programs": [], "error": ""}
_cache_lock = threading.Lock()


def cached_programs(refresh: bool = False) -> tuple:
    """(programs, error). One shared fetch, so a reload is not three requests."""
    with _cache_lock:
        fresh = (time.time() - _cache["at"]) < CACHE_SECONDS
        if fresh and not refresh and _cache["programs"]:
            return list(_cache["programs"]), _cache["error"]
        try:
            found = programs.list_programs()
            _cache.update({"at": time.time(), "programs": found, "error": ""})
            _start_enrolment_refresh(found)
            return list(found), ""
        except session.LoginRequired as exc:
            _cache.update({"at": time.time(), "programs": [], "error": str(exc)})
            return [], str(exc)
        except Exception as exc:  # noqa: BLE001
            message = f"프로그램 목록을 불러오지 못했습니다: {exc}"
            _cache.update({"at": time.time(), "error": message})
            return list(_cache["programs"]), message


def _start_enrolment_refresh(found: list) -> None:
    """Ask pknuai, a few programmes at a time, which seats this account holds.

    A programme applied for by hand is invisible to the ledger; without this
    the page would keep offering 예약 for a seat the student already has. It
    costs one request per programme, so it runs in the background and reads
    only a handful per refresh.
    """
    def worker():
        try:
            apply_module.refresh_enrolment(found)
        except Exception:  # noqa: BLE001 - a badge is never worth a crash
            pass

    threading.Thread(target=worker, daemon=True).start()


def build_state(query: str = "", refresh: bool = False) -> dict:
    found, error = cached_programs(refresh)
    if query:
        found = programs.search(found, query)
    booked = store.reservations()
    ledger = store.ledger()
    enrolled = store.enrolment()
    rows = []
    for program in found:
        code = program["id"]
        booking = booked.get(code) if isinstance(booked.get(code), dict) else None
        record = ledger.get(code) if isinstance(ledger.get(code), dict) else None
        seat = enrolled.get(code) if isinstance(enrolled.get(code), dict) else None
        attachment = store.attachment_for(code)
        rows.append({
            **program,
            "reserved": bool(booking),
            "withAttachment": booking.get("withAttachment", True) if booking else True,
            "attachment": attachment.name if attachment else "",
            "record": record,
            "seat": (seat or {}).get("state", ""),
        })
    have_session = bool(session.load_cookie())
    return {
        "os": {"Darwin": "mac", "Windows": "windows", "Linux": "linux"}.get(platform.system(), "other"),
        "browsers": browsercookies.available_browsers(),
        "programs": rows,
        "error": error,
        "session": {"stored": have_session, "savedAt": session.saved_at()},
        "watcher": {
            "installed": agent.is_installed(),
            "running": agent.is_running(),
            "label": agent.LABEL,
        },
        "reservations": watch.snapshot(),
        "log": store.tail(30),
        "fetchedAt": _cache["at"],
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "pknuai-apply"
    protocol_version = "HTTP/1.1"

    # -- plumbing ------------------------------------------------------
    def log_message(self, fmt, *args):  # quieter than the default
        return

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").strip().lower()
        name = host.rsplit(":", 1)[0] if host.count(":") == 1 else re.sub(r"\]:\d+$", "]", host)
        return name in ("127.0.0.1", "localhost", "[::1]", "::1")

    def _origin_ok(self) -> bool:
        origin = (self.headers.get("Origin") or "").strip().lower()
        if not origin:
            return True
        parsed = urlparse(origin)
        return parsed.hostname in ("127.0.0.1", "localhost", "::1")

    def _send(self, status, body: bytes, content_type: str, extra: dict = None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status, payload: dict):
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return b""
        if length <= 0 or length > MAX_UPLOAD_BYTES:
            return b""
        return self.rfile.read(length)

    def _read_json(self) -> dict:
        try:
            payload = json.loads(self._read_body().decode("utf-8") or "{}")
        except (ValueError, UnicodeDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    # -- routes --------------------------------------------------------
    def do_GET(self):  # noqa: N802
        if not self._host_ok():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "bad_host"})
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        if parsed.path in ("/", "/index.html"):
            return self._file("app.html", "text/html; charset=utf-8")
        if parsed.path == "/assets/app.css":
            return self._file("app.css", "text/css; charset=utf-8")
        if parsed.path == "/assets/app.js":
            return self._file("app.js", "application/javascript; charset=utf-8")
        if parsed.path == "/api/state":
            query = (params.get("q") or [""])[0]
            refresh = (params.get("refresh") or ["0"])[0] == "1"
            return self._json(HTTPStatus.OK, build_state(query, refresh))
        if parsed.path.startswith("/api/attachment/"):
            return self._attachment_download(parsed.path.rsplit("/", 1)[-1])
        return self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    do_HEAD = do_GET

    def do_POST(self):  # noqa: N802
        if not self._host_ok() or not self._origin_ok():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "bad_origin"})
        # A cross-site form cannot set this header, and a cross-site fetch that
        # sets it is stopped by the preflight this server never approves.
        if (self.headers.get("X-Pknuai-Apply") or "") != "1":
            return self._json(HTTPStatus.FORBIDDEN, {"error": "missing_header"})
        path = urlparse(self.path).path
        if path == "/api/session":
            return self._set_session()
        if path == "/api/session/import":
            return self._import_session()
        if path == "/api/session/open-login":
            return self._open_login()
        if path == "/api/reserve":
            return self._reserve()
        if path == "/api/apply":
            return self._apply_now()
        if path == "/api/refresh":
            cached_programs(refresh=True)
            return self._json(HTTPStatus.OK, {"ok": True})
        if path.startswith("/api/attachment/"):
            return self._attachment_upload(path.rsplit("/", 1)[-1])
        return self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    def do_DELETE(self):  # noqa: N802
        if not self._host_ok() or not self._origin_ok():
            return self._json(HTTPStatus.FORBIDDEN, {"error": "bad_origin"})
        if (self.headers.get("X-Pknuai-Apply") or "") != "1":
            return self._json(HTTPStatus.FORBIDDEN, {"error": "missing_header"})
        path = urlparse(self.path).path
        if path.startswith("/api/attachment/"):
            code = self._safe_code(path.rsplit("/", 1)[-1])
            return self._json(HTTPStatus.OK, {"ok": store.delete_attachment(code)})
        return self._json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

    # -- handlers ------------------------------------------------------
    @staticmethod
    def _safe_code(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:40]

    def _file(self, name: str, content_type: str):
        try:
            body = (ASSETS / name).read_bytes()
        except OSError:
            return self._json(HTTPStatus.NOT_FOUND, {"error": "missing_asset"})
        return self._send(HTTPStatus.OK, body, content_type)

    def _set_session(self):
        cookie = str(self._read_json().get("cookie") or "").strip()
        if not cookie:
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "reason": "쿠키가 비어 있습니다."})
        try:
            session.save_cookie(cookie)
        except ValueError as exc:
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "reason": str(exc)})
        checked = session.check()
        if checked.get("ok"):
            cached_programs(refresh=True)
        return self._json(HTTPStatus.OK, checked)

    def _import_session(self):
        # Reads the pknuai cookie straight out of the browser and verifies it.
        # The first read on macOS raises a keychain prompt the user must allow.
        browser = str(self._read_json().get("browser") or "").strip()
        result = login_flow.import_session(browser)
        if result.get("ok"):
            cached_programs(refresh=True)
        # Return only what the page needs. The cookie must never travel to the
        # browser, so echo named fields rather than the whole result dict.
        return self._json(HTTPStatus.OK, {
            "ok": result.get("ok", False),
            "reason": result.get("reason", ""),
            "browser": result.get("browser", ""),
            "no_session": result.get("no_session", False),
        })

    def _open_login(self):
        # Opens pknuai in the browser and starts a background poll, so the
        # student can log in with their phone and the page picks the session up
        # on its own. The poll writes the session; /api/state then reflects it.
        browser = str(self._read_json().get("browser") or "").strip()

        def worker():
            # Open a controlled window and capture the login when it lands. On
            # Windows this is the only path that gets past App-Bound Encryption.
            login_flow.capture_via_cdp(browser, timeout=300)
            cached_programs(refresh=True)

        threading.Thread(target=worker, daemon=True).start()
        return self._json(HTTPStatus.OK, {"ok": True,
                                          "reason": "브라우저에서 로그인을 마치면 이 화면이 자동으로 갱신됩니다."})

    def _reserve(self):
        payload = self._read_json()
        code = self._safe_code(payload.get("code"))
        if not code:
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "reason": "코드가 없습니다."})
        if payload.get("reserved") is False:
            return self._json(HTTPStatus.OK, {"ok": store.cancel(code), "reserved": False})
        found, _error = cached_programs()
        program = next((p for p in found if p["id"] == code), None)
        if program is None:
            return self._json(HTTPStatus.NOT_FOUND,
                              {"ok": False, "reason": "목록에서 프로그램을 찾지 못했습니다. 새로고침 후 다시 시도해 주세요."})
        store.reserve(program, bool(payload.get("withAttachment", True)))
        store.clear_deferral(code)
        store.log(f"예약 추가 {code} {program['title'][:40]}", echo=False)
        return self._json(HTTPStatus.OK, {"ok": True, "reserved": True})

    def _apply_now(self):
        payload = self._read_json()
        code = self._safe_code(payload.get("code"))
        dry_run = bool(payload.get("dryRun"))
        outcomes = apply_module.run_reserved(only=code, dry_run=dry_run, respect_sleep=False)
        if not outcomes:
            return self._json(HTTPStatus.OK,
                              {"ok": False, "reason": "예약되어 있지 않거나 이미 처리된 프로그램입니다."})
        return self._json(HTTPStatus.OK, {"ok": True, "outcome": outcomes[0]})

    def _attachment_upload(self, raw_code: str):
        code = self._safe_code(raw_code)
        content_type = self.headers.get("Content-Type") or ""
        if "multipart/form-data" not in content_type:
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "reason": "multipart 요청이 아닙니다."})
        body = self._read_body()
        if not body:
            return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "reason": "파일이 비었거나 너무 큽니다(최대 20MB)."})
        message = BytesParser(policy=email_default).parsebytes(
            b"Content-Type: " + content_type.encode("utf-8") + b"\r\nMIME-Version: 1.0\r\n\r\n" + body
        )
        for part in message.iter_parts():
            filename = part.get_filename()
            if not filename:
                continue
            saved = store.save_attachment(code, filename, part.get_payload(decode=True) or b"")
            store.log(f"첨부 저장 {code} {saved.name}", echo=False)
            return self._json(HTTPStatus.OK, {"ok": True, "name": saved.name})
        return self._json(HTTPStatus.BAD_REQUEST, {"ok": False, "reason": "파일 부분을 찾지 못했습니다."})

    def _attachment_download(self, raw_code: str):
        path = store.attachment_for(self._safe_code(raw_code))
        if path is None:
            return self._json(HTTPStatus.NOT_FOUND, {"error": "no_attachment"})
        import mimetypes

        guessed = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        inline = guessed.startswith("image/") or guessed == "application/pdf"
        return self._send(
            HTTPStatus.OK, path.read_bytes(), guessed,
            {"Content-Disposition": f'{"inline" if inline else "attachment"}; filename="{path.name}"'},
        )


def serve(host: str = None, port: int = None, open_browser: bool = False) -> int:
    host = host or config.WEB_HOST
    wanted = port or config.WEB_PORT
    # A laptop is a crowded place; if the usual port is taken and the user did
    # not name one, move over rather than refusing to start.
    candidates = [wanted] if port else list(range(wanted, wanted + 10))
    server = None
    for candidate in candidates:
        try:
            server = ThreadingHTTPServer((host, candidate), Handler)
            break
        except OSError as exc:
            last = exc
    if server is None:
        print(f"{host}:{wanted} 에서 서버를 열지 못했습니다: {last}")
        return 1
    server.daemon_threads = True
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"비교과 자동 예약 화면: {url}\n중지하려면 Ctrl+C 를 누르세요.")
    if open_browser:
        try:
            import webbrowser

            webbrowser.open(url)
        except Exception:  # noqa: BLE001
            pass
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n종료합니다.")
    finally:
        server.server_close()
    return 0


def port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.3)
        return probe.connect_ex((host, port)) == 0
