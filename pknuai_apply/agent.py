"""Keeping the watcher alive without a terminal window open.

A booking is worth nothing if the machine is not watching at the minute the
programme opens, and a terminal window is closed by the first reboot. macOS
gets a launchd agent, Linux a systemd user unit; anything else gets told how
to run it by hand.
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

from . import config, store

LABEL = "com.pknuai.apply.watch"
SERVICE_NAME = "pknuai-apply.service"


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def python_executable() -> str:
    return sys.executable or "python3"


def is_macos() -> bool:
    return platform.system() == "Darwin"


def is_linux() -> bool:
    return platform.system() == "Linux"


def is_windows() -> bool:
    return platform.system() == "Windows"


TASK_NAME = "pknuai-apply-watch"


def pythonw_executable() -> str:
    """The windowless Python on Windows, so no console flashes at logon."""
    exe = sys.executable or "python"
    if is_windows():
        candidate = Path(exe).with_name("pythonw.exe")
        if candidate.exists():
            return str(candidate)
    return exe


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def unit_path() -> Path:
    return Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME


def _environment() -> dict:
    """What the agent needs that a login shell would have given it."""
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin"),
           "PYTHONUNBUFFERED": "1",
           # -m finds the package through the working directory, but a launch
           # agent that inherits an odd cwd would not; say it outright.
           "PYTHONPATH": str(project_root())}
    for name in ("PKNUAI_APPLY_HOME", "XDG_DATA_HOME"):
        value = os.environ.get(name, "").strip()
        if value:
            env[name] = value
    return env


def _run(command: list) -> tuple:
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30)
        return done.returncode, (done.stdout or "") + (done.stderr or "")
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def _escape(value: str) -> str:
    return (str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def plist_text() -> str:
    log_dir = config.data_dir()
    env_entries = "".join(
        f"\n      <key>{_escape(k)}</key><string>{_escape(v)}</string>" for k, v in _environment().items()
    )
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>{_escape(python_executable())}</string>
    <string>-m</string>
    <string>pknuai_apply</string>
    <string>watch</string>
    <string>--quiet</string>
  </array>
  <key>WorkingDirectory</key><string>{_escape(str(project_root()))}</string>
  <key>EnvironmentVariables</key>
  <dict>{env_entries}
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>ProcessType</key><string>Background</string>
  <key>StandardOutPath</key><string>{_escape(str(log_dir / 'agent.out.log'))}</string>
  <key>StandardErrorPath</key><string>{_escape(str(log_dir / 'agent.err.log'))}</string>
</dict>
</plist>
"""


def unit_text() -> str:
    env_lines = "\n".join(f'Environment="{key}={value}"' for key, value in _environment().items())
    return f"""[Unit]
Description=부경대 비교과 자동 신청 감시자
After=network-online.target

[Service]
Type=simple
WorkingDirectory={project_root()}
{env_lines}
ExecStart={python_executable()} -m pknuai_apply watch --quiet
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
"""


def is_installed() -> bool:
    if is_macos():
        return plist_path().exists()
    if is_linux():
        return unit_path().exists()
    if is_windows():
        code, _output = _run(["schtasks", "/query", "/tn", TASK_NAME])
        return code == 0
    return False


def is_running() -> bool:
    # The watcher stamps a heartbeat every second; a fresh one means it is up,
    # whatever the OS. This is the only reliable signal on Windows, where a
    # Task Scheduler status string is localised.
    if store.heartbeat_age() < 30:
        return True
    if is_macos():
        code, output = _run(["launchctl", "list", LABEL])
        if code != 0:
            return False
        for line in output.splitlines():
            if '"PID"' in line:
                return "= 0" not in line
        return False
    if is_linux():
        code, output = _run(["systemctl", "--user", "is-active", SERVICE_NAME])
        return code == 0 and output.strip().startswith("active")
    # Windows falls through to the heartbeat above.
    return False


def install() -> tuple:
    """(ok, message). Writes the unit and starts it now."""
    if is_macos():
        target = plist_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(plist_text(), encoding="utf-8")
        uid = os.getuid()
        _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        code, output = _run(["launchctl", "bootstrap", f"gui/{uid}", str(target)])
        if code != 0:
            # Older macOS releases only understand the load/unload spelling.
            code, output = _run(["launchctl", "load", "-w", str(target)])
        if code != 0:
            return False, f"launchd 등록에 실패했습니다: {output.strip()[:300]}"
        return True, (f"감시자를 등록했습니다 ({LABEL}).\n"
                      f"  설정 파일: {target}\n"
                      "  로그인할 때마다 자동으로 시작하고, 죽으면 다시 살아납니다.")
    if is_linux():
        target = unit_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(unit_text(), encoding="utf-8")
        _run(["systemctl", "--user", "daemon-reload"])
        code, output = _run(["systemctl", "--user", "enable", "--now", SERVICE_NAME])
        if code != 0:
            return False, f"systemd 등록에 실패했습니다: {output.strip()[:300]}"
        return True, (f"감시자를 등록했습니다 ({SERVICE_NAME}).\n"
                      f"  설정 파일: {target}\n"
                      "  로그아웃해도 돌게 하려면: sudo loginctl enable-linger $USER")
    if is_windows():
        # A logon-triggered scheduled task, run windowless so nothing flashes.
        command = f'"{pythonw_executable()}" -m pknuai_apply watch --quiet'
        code, output = _run(["schtasks", "/create", "/tn", TASK_NAME, "/tr", command,
                             "/sc", "onlogon", "/rl", "limited", "/f"])
        if code != 0:
            return False, f"작업 스케줄러 등록에 실패했습니다: {output.strip()[:300]}"
        # /create does not start it now, so kick it off for this session too.
        _run(["schtasks", "/run", "/tn", TASK_NAME])
        return True, (f"감시자를 등록했습니다 (작업 스케줄러: {TASK_NAME}).\n"
                      "  로그인할 때마다 자동으로 시작합니다. 창은 뜨지 않습니다.")
    return False, ("이 운영체제에는 자동 등록을 지원하지 않습니다. 직접 실행해 주세요:\n"
                   f"  {python_executable()} -m pknuai_apply watch")


def uninstall() -> tuple:
    if is_macos():
        target = plist_path()
        uid = os.getuid()
        _run(["launchctl", "bootout", f"gui/{uid}/{LABEL}"])
        _run(["launchctl", "unload", "-w", str(target)])
        existed = target.exists()
        try:
            target.unlink()
        except OSError:
            pass
        return True, "감시자를 해제했습니다." if existed else "등록된 감시자가 없습니다."
    if is_linux():
        target = unit_path()
        _run(["systemctl", "--user", "disable", "--now", SERVICE_NAME])
        existed = target.exists()
        try:
            target.unlink()
        except OSError:
            pass
        _run(["systemctl", "--user", "daemon-reload"])
        return True, "감시자를 해제했습니다." if existed else "등록된 감시자가 없습니다."
    if is_windows():
        code, _output = _run(["schtasks", "/query", "/tn", TASK_NAME])
        _run(["schtasks", "/end", "/tn", TASK_NAME])
        deleted, _out = _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
        return True, "감시자를 해제했습니다." if code == 0 else "등록된 감시자가 없습니다."
    return False, "이 운영체제에는 등록된 감시자가 없습니다."


def restart() -> tuple:
    if not is_installed():
        return False, "감시자가 등록되어 있지 않습니다."
    if is_macos():
        uid = os.getuid()
        _run(["launchctl", "kickstart", "-k", f"gui/{uid}/{LABEL}"])
        return True, "감시자를 다시 시작했습니다."
    if is_linux():
        _run(["systemctl", "--user", "restart", SERVICE_NAME])
        return True, "감시자를 다시 시작했습니다."
    if is_windows():
        _run(["schtasks", "/end", "/tn", TASK_NAME])
        _run(["schtasks", "/run", "/tn", TASK_NAME])
        return True, "감시자를 다시 시작했습니다."
    return False, "지원하지 않는 운영체제입니다."
