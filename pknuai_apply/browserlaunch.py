"""Finding a browser to open, and opening it under our control for CDP.

Kept apart from the cookie reader because this is about starting a process,
not about decrypting a file. On Windows this is the whole game: Edge is always
present, so a student always has something to log in with.
"""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
from pathlib import Path


def _exists(path: str):
    return path if path and Path(path).exists() else None


def chromium_executables() -> list:
    """(label, path) for Chromium browsers we can launch, best default first."""
    system = platform.system()
    found = []
    if system == "Windows":
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))
        # Edge first: it ships with Windows, so it is always there.
        candidates = [
            ("Edge", rf"{pf86}\Microsoft\Edge\Application\msedge.exe"),
            ("Edge", rf"{pf}\Microsoft\Edge\Application\msedge.exe"),
            ("Chrome", rf"{pf}\Google\Chrome\Application\chrome.exe"),
            ("Chrome", rf"{pf86}\Google\Chrome\Application\chrome.exe"),
            ("Chrome", rf"{local}\Google\Chrome\Application\chrome.exe"),
            ("Brave", rf"{pf}\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ("Whale", rf"{pf86}\Naver\Naver Whale\Application\whale.exe"),
        ]
    elif system == "Darwin":
        candidates = [
            ("Chrome", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
            ("Edge", "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
            ("Brave", "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"),
            ("Whale", "/Applications/Naver Whale.app/Contents/MacOS/Naver Whale"),
            ("Chromium", "/Applications/Chromium.app/Contents/MacOS/Chromium"),
        ]
    else:
        candidates = []
        for label, names in (("Chrome", ("google-chrome", "google-chrome-stable")),
                             ("Chromium", ("chromium", "chromium-browser")),
                             ("Edge", ("microsoft-edge", "microsoft-edge-stable")),
                             ("Brave", ("brave-browser", "brave"))):
            for name in names:
                path = shutil.which(name)
                if path:
                    candidates.append((label, path))
                    break
        return candidates
    seen = []
    for label, path in candidates:
        real = _exists(path)
        if real and real not in [p for _l, p in seen]:
            seen.append((label, real))
    return seen


def pick(browser: str = ""):
    """(label, path) for the requested browser, or the best default."""
    available = chromium_executables()
    if not available:
        return None
    if browser:
        wanted = browser.strip().lower()
        for label, path in available:
            if label.lower() == wanted:
                return (label, path)
    return available[0]


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def launch_for_debugging(path: str, user_data_dir: str, port: int, url: str):
    """Start a browser we can talk to over CDP, showing a window to log in."""
    args = [
        path,
        f"--user-data-dir={user_data_dir}",
        f"--remote-debugging-port={port}",
        "--remote-allow-origins=*",
        "--no-first-run",
        "--no-default-browser-check",
        "--new-window",
        url,
    ]
    creationflags = 0
    if platform.system() == "Windows":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            creationflags=creationflags)
