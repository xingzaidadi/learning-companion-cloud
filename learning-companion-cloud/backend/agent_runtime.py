from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from sqlite3 import Connection
from typing import Any, Iterator

from .db import dumps, utc_now


@dataclass
class RuntimeContext:
    conn: Connection
    student_id: int
    run_type: str
    input_data: dict[str, Any]
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    run_id: int | None = None
    step_index: int = 0

    def step(
        self,
        step_type: str,
        tool_name: str = "",
        args: dict[str, Any] | None = None,
        observation: dict[str, Any] | list[Any] | None = None,
        validation: dict[str, Any] | None = None,
        status: str = "ok",
        latency_ms: int = 0,
    ) -> None:
        self.step_index += 1
        self.conn.execute(
            """
            INSERT INTO agent_trace_steps (
                run_id, trace_id, step_index, step_type, tool_name,
                args_json, observation_json, validation_json, latency_ms, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                self.run_id,
                self.trace_id,
                self.step_index,
                step_type,
                tool_name,
                dumps(args or {}),
                dumps(observation or {}),
                dumps(validation or {}),
                latency_ms,
                status,
                utc_now(),
            ),
        )


@contextmanager
def agent_run(
    conn: Connection,
    student_id: int,
    run_type: str,
    input_data: dict[str, Any],
    model: str = "rule",
) -> Iterator[RuntimeContext]:
    trace_id = uuid.uuid4().hex
    started = time.perf_counter()
    cursor = conn.execute(
        """
        INSERT INTO agent_runs (
            student_id, run_type, input_json, output_json, model, status, error,
            confidence, evidence_json, warnings_json, latency_ms, quality_score, trace_id, created_at
        )
        VALUES (?, ?, ?, '{}', ?, 'running', '', 0, '[]', '[]', 0, 0, ?, ?)
        """,
        (student_id, run_type, dumps(input_data), model, trace_id, utc_now()),
    )
    context = RuntimeContext(conn=conn, student_id=student_id, run_type=run_type, input_data=input_data, trace_id=trace_id, run_id=int(cursor.lastrowid))
    try:
        yield context
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        conn.execute(
            """
            UPDATE agent_runs
            SET status = 'error', error = ?, latency_ms = ?
            WHERE id = ?
            """,
            (str(exc), latency_ms, context.run_id),
        )
        raise


def finish_agent_run(
    context: RuntimeContext,
    output_data: dict[str, Any] | list[Any],
    status: str = "ok",
    confidence: float = 0.8,
    evidence: list[Any] | None = None,
    warnings: list[str] | None = None,
    quality_score: float = 0.8,
) -> None:
    context.conn.execute(
        """
        UPDATE agent_runs
        SET output_json = ?, status = ?, confidence = ?, evidence_json = ?,
            warnings_json = ?, quality_score = ?, latency_ms = (
                SELECT COALESCE(SUM(latency_ms), 0) FROM agent_trace_steps WHERE run_id = ?
            )
        WHERE id = ?
        """,
        (
            dumps(output_data),
            status,
            confidence,
            dumps(evidence or []),
            dumps(warnings or []),
            quality_score,
            context.run_id,
            context.run_id,
        ),
    )
