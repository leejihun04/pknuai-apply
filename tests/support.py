"""Shared helpers: a temporary data directory and fixture loading."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TempHome(unittest.TestCase):
    """Each test gets its own data directory, so nothing touches real state."""

    def setUp(self):
        self.home = tempfile.mkdtemp(prefix="pknuai-test-")
        self._previous = os.environ.get("PKNUAI_APPLY_HOME")
        os.environ["PKNUAI_APPLY_HOME"] = self.home

    def tearDown(self):
        if self._previous is None:
            os.environ.pop("PKNUAI_APPLY_HOME", None)
        else:
            os.environ["PKNUAI_APPLY_HOME"] = self._previous
        shutil.rmtree(self.home, ignore_errors=True)
