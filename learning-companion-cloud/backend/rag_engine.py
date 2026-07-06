from __future__ import annotations

import hashlib
import math
import re
from sqlite3 import Connection
from typing import Any

from .db import dumps, loads, utc_now


EMBEDDING_DIM = 64


def local_embedding(text: str, dim: int = EMBEDDING_DIM) -> list[float]:
    """Deterministic local embedding for offline RAG quality gates.

    It is not a replacement for production embedding models, but it gives the
    system a persistent vector signal and stable eval behavior when no AI key is
    available.
    """

    vector = [0.0] * dim
    tokens = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]{1,2}", text.lower())
    for token in tokens:
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dim
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def upsert_chunk_embedding(conn: Connection, chunk_id: int, text: str, model: str = "local-hash-v1") -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO material_embeddings (chunk_id, model, dim, vector_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(chunk_id, model) DO UPDATE SET
            dim = excluded.dim,
            vector_json = excluded.vector_json,
            updated_at = excluded.updated_at
        """,
        (chunk_id, model, EMBEDDING_DIM, dumps(local_embedding(text)), now, now),
    )


def rebuild_material_embeddings(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT id, chunk_text
        FROM material_chunks
        WHERE student_id = ?
        ORDER BY id
        """,
        (student_id,),
    ).fetchall()
    for row in rows:
        upsert_chunk_embedding(conn, int(row["id"]), row["chunk_text"])
    return {"student_id": student_id, "model": "local-hash-v1", "embedded_chunks": len(rows), "dim": EMBEDDING_DIM}


def embedding_score_for_chunk(conn: Connection, chunk_id: int, query: str) -> float:
    row = conn.execute(
        "SELECT vector_json FROM material_embeddings WHERE chunk_id = ? AND model = 'local-hash-v1'",
        (chunk_id,),
    ).fetchone()
    if not row:
        return 0.0
    return cosine(local_embedding(query), loads(row["vector_json"], []))
