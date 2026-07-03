from __future__ import annotations

import os
import platform
import shutil
import subprocess
from sqlite3 import Connection
from typing import Any
from urllib import parse, request

from .db import utc_now


MAX_NOTIFICATION_LENGTH = 240


def _shorten(text: str, limit: int = MAX_NOTIFICATION_LENGTH) -> str:
    normalized = " ".join((text or "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1]}…"


def _pushplus_send(title: str, content: str) -> tuple[str, str]:
    token = os.getenv("PUSHPLUS_TOKEN", "").strip()
    if not token:
        return "skipped", "未配置 PUSHPLUS_TOKEN"

    payload = parse.urlencode(
        {
            "token": token,
            "title": title,
            "content": content,
            "template": "markdown",
        }
    ).encode("utf-8")
    req = request.Request("https://www.pushplus.plus/send", data=payload, method="POST")
    try:
        with request.urlopen(req, timeout=8) as resp:
            return "sent", resp.read().decode("utf-8", errors="ignore")[:500]
    except Exception as exc:
        return "failed", str(exc)


def _macos_local_send(title: str, content: str) -> tuple[str, str]:
    script = (
        f'display notification "{_escape_applescript(_shorten(content))}" '
        f'with title "{_escape_applescript(_shorten(title, 80))}"'
    )
    return _run_command(["osascript", "-e", script], "macOS 本地通知已发送")


def _windows_local_send(title: str, content: str) -> tuple[str, str]:
    script = f"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$notify = New-Object System.Windows.Forms.NotifyIcon
$notify.Icon = [System.Drawing.SystemIcons]::Information
$notify.BalloonTipTitle = @'
{_escape_powershell_here_string(_shorten(title, 80))}
'@
$notify.BalloonTipText = @'
{_escape_powershell_here_string(_shorten(content))}
'@
$notify.Visible = $true
$notify.ShowBalloonTip(5000)
Start-Sleep -Seconds 6
$notify.Dispose()
"""
    return _run_command(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        "Windows 本地通知已发送",
    )


def _linux_local_send(title: str, content: str) -> tuple[str, str]:
    if not shutil.which("notify-send"):
        return "skipped", "未找到 notify-send"
    return _run_command(["notify-send", _shorten(title, 80), _shorten(content)], "Linux 本地通知已发送")


def _local_send(title: str, content: str) -> tuple[str, str]:
    system = platform.system().lower()
    if system == "darwin":
        return _macos_local_send(title, content)
    if system == "windows":
        return _windows_local_send(title, content)
    if system == "linux":
        return _linux_local_send(title, content)
    return "skipped", f"当前系统暂不支持本地通知：{platform.system() or 'unknown'}"


def _console_send(title: str, content: str) -> tuple[str, str]:
    print(f"[learning-companion notification] {title}\n{content}", flush=True)
    return "sent", "已输出到服务控制台"


def _run_command(command: list[str], success_detail: str) -> tuple[str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=10, check=False)
    except FileNotFoundError:
        return "skipped", f"未找到命令：{command[0]}"
    except subprocess.TimeoutExpired:
        return "failed", "本地通知命令超时"
    except Exception as exc:
        return "failed", f"{type(exc).__name__}: {exc}"

    if completed.returncode == 0:
        return "sent", success_detail
    detail = (completed.stderr or completed.stdout or "").strip()
    return "failed", detail[:500] or f"命令退出码：{completed.returncode}"


def _escape_applescript(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _escape_powershell_here_string(text: str) -> str:
    return text.replace("'@", "' + \"@\"")


def _send_channel(channel: str, title: str, message: str) -> tuple[str, str]:
    if channel == "pushplus":
        return _pushplus_send(title, message)
    if channel == "local":
        return _local_send(title, message)
    if channel == "console":
        return _console_send(title, message)
    if channel == "none":
        return "skipped", "已关闭外部提醒，仅记录提醒日志"
    return "skipped", f"暂不支持通知通道：{channel}"


def _configured_channels() -> list[str]:
    raw = os.getenv("NOTIFY_CHANNEL", "local").strip().lower() or "local"
    if raw == "auto":
        return ["local", "pushplus"] if os.getenv("PUSHPLUS_TOKEN", "").strip() else ["local"]
    channels = [item.strip() for item in raw.replace(";", ",").split(",") if item.strip()]
    return channels or ["local"]


def notify(conn: Connection, student_id: int, event_type: str, title: str, message: str) -> dict[str, Any]:
    results = []
    for channel in _configured_channels():
        status, detail = _send_channel(channel, title, message)
        conn.execute(
            """
            INSERT INTO notification_logs (student_id, event_type, channel, message, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (student_id, event_type, channel, f"{title}\n\n{message}\n\n{detail}", status, utc_now()),
        )
        results.append({"channel": channel, "status": status, "detail": detail})

    primary = next((result for result in results if result["status"] == "sent"), results[0])
    return {**primary, "results": results}
