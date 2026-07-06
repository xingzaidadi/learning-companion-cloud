from __future__ import annotations

import os
import sys
import sqlite3
import tempfile
import threading
from pathlib import Path


def main() -> None:
    temp_dir = Path(tempfile.mkdtemp(prefix="learning-db-concurrency-"))
    os.environ["DATABASE_PATH"] = str(temp_dir / "learning.db")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend.db import get_conn, init_db

    init_db()
    with get_conn() as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        assert timeout >= 5000, timeout
        assert mode.lower() in {"wal", "memory", "delete"}

    errors: list[str] = []

    def worker(index: int) -> None:
        try:
            for item in range(12):
                with get_conn() as conn:
                    conn.execute(
                        """
                        INSERT INTO notification_logs (student_id, event_type, channel, message, status, created_at)
                        VALUES (1, 'concurrency_test', 'local', ?, 'sent', datetime('now'))
                        """,
                        (f"worker-{index}-{item}",),
                    )
        except sqlite3.OperationalError as exc:
            errors.append(str(exc))

    threads = [threading.Thread(target=worker, args=(idx,)) for idx in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    with get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM notification_logs WHERE event_type = 'concurrency_test'").fetchone()[0]
    assert count == 96, count
    print("DB_CONCURRENCY_TEST_OK")


if __name__ == "__main__":
    main()
