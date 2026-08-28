"""The hand-rolled DevTools WebSocket client, against a loopback server."""

import base64
import hashlib
import json
import socket
import struct
import threading
import unittest

from support import TempHome

from pknuai_apply import cdp

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


class FakeDevTools:
    """A minimal server: HTTP /json/version, then a WebSocket that answers
    one CDP command with a canned cookie list."""

    def __init__(self, cookies):
        self.cookies = cookies
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(5)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self):
        while True:
            try:
                client, _addr = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client):
        request = b""
        while b"\r\n\r\n" not in request:
            chunk = client.recv(4096)
            if not chunk:
                client.close()
                return
            request += chunk
        head = request.split(b"\r\n", 1)[0].decode()
        if "/json/version" in head:
            body = json.dumps({"webSocketDebuggerUrl": f"ws://127.0.0.1:{self.port}/devtools/browser/x"})
            client.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\n\r\n".encode() + body.encode()
            )
            client.close()
            return
        # WebSocket upgrade
        key = ""
        for line in request.decode(errors="replace").split("\r\n"):
            if line.lower().startswith("sec-websocket-key:"):
                key = line.split(":", 1)[1].strip()
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()
        client.sendall(
            b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Accept: " + accept.encode() + b"\r\n\r\n"
        )
        message = self._read_frame(client)
        request_id = json.loads(message).get("id", 1)
        reply = json.dumps({"id": request_id, "result": {"cookies": self.cookies}})
        self._send_frame(client, reply)
        client.close()

    def _read_frame(self, client):
        header = client.recv(2)
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack(">H", client.recv(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", client.recv(8))[0]
        mask = client.recv(4)
        data = b""
        while len(data) < length:
            data += client.recv(length - len(data))
        return bytes(byte ^ mask[i % 4] for i, byte in enumerate(data)).decode()

    def _send_frame(self, client, text):
        payload = text.encode()
        header = bytearray([0x81])
        if len(payload) < 126:
            header.append(len(payload))
        else:
            header.append(126)
            header += struct.pack(">H", len(payload))
        client.sendall(bytes(header) + payload)

    def close(self):
        self.sock.close()


class CdpClient(TempHome):
    def test_it_reads_cookies_over_the_websocket(self):
        server = FakeDevTools([
            {"name": "JSESSIONID", "value": "ABC", "domain": "pknuai.pknu.ac.kr"},
            {"name": "other", "value": "x", "domain": "google.com"},
        ])
        try:
            cookies = cdp.all_cookies(server.port, timeout=5)
        finally:
            server.close()
        names = {c["name"]: c["value"] for c in cookies}
        self.assertEqual(names["JSESSIONID"], "ABC")

    def test_a_large_value_survives_the_extended_length_framing(self):
        # Exercises the 126/16-bit length path in both send and receive.
        big = "Z" * 5000
        server = FakeDevTools([{"name": "JSESSIONID", "value": big, "domain": "pknuai.pknu.ac.kr"}])
        try:
            cookies = cdp.all_cookies(server.port, timeout=5)
        finally:
            server.close()
        self.assertEqual(cookies[0]["value"], big)

    def test_discovery_returns_the_browser_socket_url(self):
        server = FakeDevTools([])
        try:
            url = cdp.browser_websocket_url(server.port, timeout=5)
        finally:
            server.close()
        self.assertTrue(url.startswith("ws://127.0.0.1:"))


if __name__ == "__main__":
    unittest.main()
