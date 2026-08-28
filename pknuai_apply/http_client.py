"""HTTP against pknuai, using only the standard library.

Redirects are never followed: pknuai answers an expired session with a 302 to
the portal's login form, and following it would turn "you are logged out" into
a page that parses as "there are no programmes".
"""

from __future__ import annotations

import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

from . import config


@dataclass
class Response:
    status: int
    text: str
    headers: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _decode(raw: bytes, headers) -> str:
    charset = ""
    try:
        charset = headers.get_content_charset() or ""
    except Exception:  # noqa: BLE001
        charset = ""
    for candidate in (charset, "utf-8", "euc-kr"):
        if not candidate:
            continue
        try:
            return raw.decode(candidate)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="replace")


def request(method: str, url: str, *, cookie: str = "", headers: dict = None,
            data=None, body: bytes = None, content_type: str = "",
            timeout: int = 25) -> Response:
    """One request. Never raises for an HTTP status; network errors do raise."""
    sent = dict(config.BROWSER_HEADERS)
    if cookie:
        sent["Cookie"] = cookie
    sent.update(headers or {})
    payload = body
    if payload is None and data is not None:
        payload = urllib.parse.urlencode(data, encoding="utf-8").encode("utf-8")
        sent.setdefault("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8")
    if content_type:
        sent["Content-Type"] = content_type
    req = urllib.request.Request(url, data=payload, headers=sent, method=method.upper())
    try:
        with _opener.open(req, timeout=timeout) as resp:
            return Response(resp.status, _decode(resp.read(), resp.headers), dict(resp.headers))
    except urllib.error.HTTPError as exc:  # 3xx/4xx/5xx still carry a body
        raw = b""
        try:
            raw = exc.read()
        except Exception:  # noqa: BLE001
            pass
        return Response(exc.code, _decode(raw, exc.headers), dict(exc.headers or {}))


def get(url: str, **kwargs) -> Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> Response:
    return request("POST", url, **kwargs)


def with_query(url: str, params: dict) -> str:
    joiner = "&" if "?" in url else "?"
    return url + joiner + urllib.parse.urlencode(params, encoding="utf-8")


def multipart(fields: dict, file_field: str, path) -> tuple:
    """(body, content-type) for one file posted beside ordinary fields.

    The file part carries its own content type, the way a browser sends it. An
    untyped part is exactly the kind of thing an upload filter drops without
    saying so.
    """
    boundary = "----pknuaiApply" + os.urandom(12).hex()
    chunks = []
    for name, value in (fields or {}).items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    filename = os.path.basename(str(path))
    guessed = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    with open(path, "rb") as handle:
        content = handle.read()
    chunks.append(
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="{file_field}"; '
            f'filename="{filename}"\r\nContent-Type: {guessed}\r\n\r\n'
        ).encode("utf-8")
    )
    chunks.append(content)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
