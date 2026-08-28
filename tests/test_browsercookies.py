"""Reading a session out of the browser, without a real browser."""

import hashlib
import platform
import sqlite3
import subprocess
import unittest
from pathlib import Path

from support import TempHome

from pknuai_apply import browsercookies as bc


def _make_key(password: bytes) -> bytes:
    iterations = 1003 if platform.system() == "Darwin" else 1
    return hashlib.pbkdf2_hmac("sha1", password, b"saltysalt", iterations, 16)


def _encrypt(value: str, domain: str, key: bytes) -> bytes:
    # Mimics Chrome m127+: v10 + AES-128-CBC of (sha256(domain) + value).
    plain = hashlib.sha256(domain.encode()).digest() + value.encode()
    pad = 16 - (len(plain) % 16)
    plain += bytes([pad]) * pad
    done = subprocess.run(
        ["openssl", "enc", "-aes-128-cbc", "-K", key.hex(), "-iv", (b"\x20" * 16).hex(), "-nopad"],
        input=plain, capture_output=True,
    )
    return b"v10" + done.stdout


def _chrome_db(path: Path, rows, key: bytes):
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE cookies(host_key TEXT, name TEXT, value TEXT, encrypted_value BLOB)")
    for host, name, value in rows:
        con.execute("INSERT INTO cookies VALUES(?,?,?,?)", (host, name, "", _encrypt(value, host, key)))
    con.commit()
    con.close()


@unittest.skipUnless(platform.system() in ("Darwin", "Linux"), "browser import is macOS/Linux")
class ChromiumDecrypt(TempHome):
    def setUp(self):
        super().setUp()
        try:
            self.key = _make_key(bc._safe_storage_password("Chrome"))
        except bc.BrowserImportError as exc:
            self.skipTest(f"no keychain access: {exc}")

    def test_the_pknuai_session_is_decrypted_and_other_sites_are_left_out(self):
        db = Path(self.home) / "Cookies"
        _chrome_db(db, [
            ("pknuai.pknu.ac.kr", "JSESSIONID", "SESSION-ABC"),
            (".pknu.ac.kr", "WMONID", "wmonid-1"),
            ("google.com", "SID", "should-not-appear"),
        ], self.key)
        header = bc.cookie_header_from("Chrome", db)
        self.assertIn("JSESSIONID=SESSION-ABC", header)
        self.assertIn("WMONID=wmonid-1", header)
        self.assertNotIn("should-not-appear", header)

    def test_a_browser_without_the_session_cookie_yields_nothing(self):
        db = Path(self.home) / "Cookies"
        _chrome_db(db, [(".pknu.ac.kr", "_ga", "GA1.2.3")], self.key)
        self.assertEqual(bc.cookie_header_from("Chrome", db), "")

    def test_the_store_can_be_read_while_it_is_locked_open(self):
        db = Path(self.home) / "Cookies"
        _chrome_db(db, [("pknuai.pknu.ac.kr", "JSESSIONID", "LIVE")], self.key)
        held = sqlite3.connect(db)
        held.execute("BEGIN EXCLUSIVE")
        try:
            self.assertIn("JSESSIONID=LIVE", bc.cookie_header_from("Chrome", db))
        finally:
            held.rollback()
            held.close()


class Firefox(TempHome):
    def test_plaintext_cookies_need_no_key(self):
        db = Path(self.home) / "cookies.sqlite"
        con = sqlite3.connect(db)
        con.execute("CREATE TABLE moz_cookies(host TEXT, name TEXT, value TEXT)")
        con.execute("INSERT INTO moz_cookies VALUES(?,?,?)", ("pknuai.pknu.ac.kr", "JSESSIONID", "FF-1"))
        con.execute("INSERT INTO moz_cookies VALUES(?,?,?)", ("example.com", "x", "y"))
        con.commit()
        con.close()
        header = bc.cookie_header_from("Firefox", db)
        self.assertEqual(header, "JSESSIONID=FF-1")


if __name__ == "__main__":
    unittest.main()
