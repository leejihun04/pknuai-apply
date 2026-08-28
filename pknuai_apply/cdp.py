"""A tiny Chrome DevTools Protocol client, standard library only.

Windows is the reason this exists. Modern Chrome and Edge encrypt their cookie
store with a key bound to the browser itself (App-Bound Encryption), and they
refuse remote debugging against the normal profile — both changes made
specifically to stop one program reading another's cookies off disk. So on
Windows the reliable way to get a pknuai session is not to decrypt a file but
to open a browser window we control, let the student log in, and read the
cookies the live browser hands us over DevTools — in plain text, no key needed.

This speaks just enough of the protocol: the HTTP discovery endpoint, a
single-frame WebSocket, and two commands (Storage.getCookies, with
Network.getAllCookies as a fallback).
"""

from __future__ import annotations

import base64
import json
import os
import socket
import struct
import urllib.request
from urllib.parse import urlparse


class CDPError(Exception):
    pass


def http_json(port: int, path: str, timeout: float = 2.0):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def browser_websocket_url(port: int, timeout: float = 2.0) -> str:
    return http_json(port, "/json/version", timeout).get("webSocketDebuggerUrl", "")


class WebSocket:
    """Barely a WebSocket: connect, send one text frame, read text frames.

    Enough for a request/response CDP call and nothing more. Client frames are
    masked as the spec requires; server frames are not.
    """

    def __init__(self, url: str, timeout: float = 5.0):
        parsed = urlparse(url)
        self.host = parsed.hostname or "127.0.0.1"
        self.port = parsed.port or 80
        path = parsed.path or "/"
        self.sock = socket.create_connection((self.host, self.port), timeout=timeout)
        self.sock.settimeout(timeout)
        key = base64.b64encode(os.urandom(16)).decode()
        handshake = (
            f"GET {path} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode())
        buffer = b""
        while b"\r\n\r\n" not in buffer:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise CDPError("WebSocket 핸드셰이크가 끊겼습니다.")
            buffer += chunk
        if b" 101 " not in buffer.split(b"\r\n", 1)[0]:
            raise CDPError("WebSocket 업그레이드가 거부되었습니다.")
        self._rest = buffer.split(b"\r\n\r\n", 1)[1]

    def send(self, text: str) -> None:
        payload = text.encode("utf-8")
        header = bytearray([0x81])  # FIN + text
        mask = os.urandom(4)
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", length)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", length)
        header += mask
        masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
        self.sock.sendall(bytes(header) + masked)

    def _recv(self, count: int) -> bytes:
        while len(self._rest) < count:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise CDPError("WebSocket 연결이 끊겼습니다.")
            self._rest += chunk
        head, self._rest = self._rest[:count], self._rest[count:]
        return head

    def recv(self) -> str:
        while True:
            first, second = self._recv(2)
            opcode = first & 0x0F
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._recv(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._recv(8))[0]
            data = self._recv(length) if length else b""
            if opcode == 0x8:  # close
                raise CDPError("서버가 연결을 닫았습니다.")
            if opcode in (0x9, 0xA):  # ping/pong
                continue
            return data.decode("utf-8", "replace")

    def close(self) -> None:
        try:
            self.sock.close()
        except OSError:
            pass


def call(port: int, method: str, params: dict = None, timeout: float = 5.0) -> dict:
    """One browser-level CDP command, returning its result dict."""
    url = browser_websocket_url(port, timeout)
    if not url:
        raise CDPError("DevTools 엔드포인트를 찾지 못했습니다.")
    ws = WebSocket(url, timeout)
    try:
        ws.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
        deadline_frames = 40
        for _ in range(deadline_frames):
            message = json.loads(ws.recv())
            if message.get("id") == 1:
                if "error" in message:
                    raise CDPError(str(message["error"].get("message") or message["error"]))
                return message.get("result", {})
        raise CDPError("CDP 응답을 받지 못했습니다.")
    finally:
        ws.close()


def all_cookies(port: int, timeout: float = 5.0) -> list:
    """Every cookie the browser holds, as [{name, value, domain, ...}]."""
    for method in ("Storage.getCookies", "Network.getAllCookies"):
        try:
            result = call(port, method, {}, timeout)
        except CDPError:
            continue
        cookies = result.get("cookies")
        if cookies is not None:
            return cookies
    return []
