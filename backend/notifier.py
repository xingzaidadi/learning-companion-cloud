from __future__ import annotations

import os
from sqlite3 import Connection
from typing import Any
from urllib import parse, request

from .db import utc_now


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


def notify(conn: Connection, student_id: int, event_type: str, title: str, message: str) -> dict[str, Any]:
    channel = os.getenv("NOTIFY_CHANNEL", "pushplus").strip() or "pushplus"
    if channel == "pushplus":
        status, detail = _pushplus_send(title, message)
    else:
        status, detail = "skipped", f"暂不支持通道：{channel}"

    conn.execute(
        """
        INSERT INTO notification_logs (student_id, event_type, channel, message, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (student_id, event_type, channel, f"{title}\n\n{message}\n\n{detail}", status, utc_now()),
    )
    return {"channel": channel, "status": status, "detail": detail}
