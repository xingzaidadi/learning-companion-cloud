from __future__ import annotations

from sqlite3 import Connection
from typing import Any

from .curriculum import WUHAN_DEFAULTS
from .db import dumps, loads, utc_now


DEFAULT_SETTINGS: dict[str, Any] = {
    "region": WUHAN_DEFAULTS,
    "study_windows": {
        "morning": "09:00-11:00",
        "afternoon": "15:00-17:00",
        "evening_review": "19:30-20:30",
    },
    "daily_limits": {
        "max_total_minutes": 360,
        "chinese_minutes": 25,
        "math_minutes": 35,
        "english_minutes": 25,
        "ket_minutes": 50,
    },
    "ket_plan": {
        "level": "standard",
        "book_mode": "pending",
        "weekday_minutes": 50,
        "mock_minutes": 70,
        "low_score_remedial_minutes": 35,
    },
    "path_rules": {
        "quiz_pass_score": 0.8,
        "low_score_blocks_new_preview": True,
        "max_daily_tasks": 10,
        "weekend_light_mode": False,
    },
    "ai": {
        "enabled": False,
        "provider": "openai_compatible",
        "model": "gpt-4o-mini",
        "api_url": "https://api.openai.com/v1/chat/completions",
    },
}


def get_settings(conn: Connection) -> dict[str, Any]:
    row = conn.execute("SELECT value_json FROM app_settings WHERE key = 'global'").fetchone()
    if not row:
        return DEFAULT_SETTINGS.copy()
    saved = loads(row["value_json"], {})
    return _deep_merge(DEFAULT_SETTINGS.copy(), saved)


def save_settings(conn: Connection, settings: dict[str, Any]) -> dict[str, Any]:
    merged = _deep_merge(DEFAULT_SETTINGS.copy(), settings)
    conn.execute(
        """
        INSERT INTO app_settings (key, value_json, updated_at)
        VALUES ('global', ?, ?)
        ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at
        """,
        (dumps(merged), utc_now()),
    )
    return merged


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            base[key] = _deep_merge(base[key], value)
        else:
            base[key] = value
    return base
