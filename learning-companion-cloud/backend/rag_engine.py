from __future__ import annotations

import hashlib
import json
import math
import os
import re
from sqlite3 import Connection
from typing import Any
from urllib import request

from .db import dumps, loads, utc_now


EMBEDDING_DIM = 64
SEMANTIC_DIM = 128
HASH_MODEL = "local-hash-v1"
SEMANTIC_MODEL = "local-semantic-zh-v1"

SEMANTIC_ALIASES: dict[str, list[str]] = {
    "白鹭": ["精巧", "适宜", "色素", "身段", "一首诗", "美", "散文"],
    "白露": ["白鹭", "精巧", "一首诗"],
    "精巧": ["美", "漂亮", "适宜", "白鹭"],
    "美": ["精巧", "适宜", "白鹭", "诗"],
    "桂花雨": ["家乡", "母亲的话", "桂花", "思乡", "课后题"],
    "母亲的话": ["桂花雨", "家乡", "比不上", "院子里的桂花"],
    "落花生": ["借物喻人", "父亲的话", "花生", "有用的人", "课后习题"],
    "借物喻人": ["落花生", "父亲的话", "做人道理"],
    "日积月累": ["背诵", "默写", "语文园地", "积累"],
    "小数点": ["小数", "积的小数位数", "商的小数点", "验算"],
    "小数乘法": ["积", "竖式", "小数点", "验算"],
    "乘發": ["乘法", "小数乘法", "验算"],
    "多边形面积": ["平行四边形", "三角形", "梯形", "画图", "单位"],
    "质数": ["合数", "因数", "找质数", "练一练"],
    "合数": ["质数", "因数", "找质数", "练一练"],
    "library": ["图书馆", "school", "classroom", "where"],
    "libary": ["library", "图书馆", "spelling", "拼写"],
    "图书馆": ["library", "学校", "教室", "where"],
    "ice": ["ice world", "polar", "cold", "听力原文"],
    "ice world": ["Unit 3", "ice", "polar bear", "听力原文"],
    "听写": ["单词", "拼写", "默写", "dictation"],
}


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


def semantic_embedding(text: str, dim: int = SEMANTIC_DIM) -> list[float]:
    vector = [0.0] * dim
    tokens = _semantic_tokens(text)
    for token, weight in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = int.from_bytes(digest[:2], "big") % dim
        vector[index] += weight
    norm = math.sqrt(sum(value * value for value in vector))
    if not norm:
        return vector
    return [round(value / norm, 6) for value in vector]


def cosine(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return sum(a * b for a, b in zip(left, right))


def effective_embedding_model() -> str:
    mode = os.getenv("EMBEDDING_MODE", "").strip().lower()
    if mode in {"api", "openai"} and (os.getenv("OPENAI_API_KEY") or os.getenv("AI_API_KEY")):
        return os.getenv("OPENAI_EMBEDDING_MODEL") or os.getenv("EMBEDDING_MODEL") or "text-embedding-3-small"
    if mode in {"hash", "local-hash"}:
        return HASH_MODEL
    return os.getenv("EMBEDDING_MODEL") or SEMANTIC_MODEL


def embed_texts(texts: list[str], model: str | None = None) -> tuple[str, list[list[float]]]:
    selected_model = model or effective_embedding_model()
    if selected_model not in {SEMANTIC_MODEL, HASH_MODEL}:
        api_vectors = _api_embed_texts(texts, selected_model)
        if api_vectors:
            return selected_model, api_vectors
    if selected_model == HASH_MODEL:
        return HASH_MODEL, [local_embedding(text) for text in texts]
    return SEMANTIC_MODEL, [semantic_embedding(text) for text in texts]


def upsert_chunk_embedding(conn: Connection, chunk_id: int, text: str, model: str | None = None) -> None:
    selected_model, vectors = embed_texts([text], model)
    vector = vectors[0] if vectors else semantic_embedding(text)
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
        (chunk_id, selected_model, len(vector), dumps(vector), now, now),
    )
    if selected_model != HASH_MODEL:
        hash_vector = local_embedding(text)
        conn.execute(
            """
            INSERT INTO material_embeddings (chunk_id, model, dim, vector_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(chunk_id, model) DO UPDATE SET
                dim = excluded.dim,
                vector_json = excluded.vector_json,
                updated_at = excluded.updated_at
            """,
            (chunk_id, HASH_MODEL, len(hash_vector), dumps(hash_vector), now, now),
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
    return {"student_id": student_id, "model": effective_embedding_model(), "embedded_chunks": len(rows), "dim": SEMANTIC_DIM}


def embedding_score_for_chunk(conn: Connection, chunk_id: int, query: str) -> float:
    rows = conn.execute(
        """
        SELECT model, vector_json
        FROM material_embeddings
        WHERE chunk_id = ?
        ORDER BY CASE
            WHEN model = ? THEN 0
            WHEN model = ? THEN 1
            WHEN model = ? THEN 2
            ELSE 3
        END
        """,
        (chunk_id, effective_embedding_model(), SEMANTIC_MODEL, HASH_MODEL),
    ).fetchall()
    best = 0.0
    for row in rows:
        model = str(row["model"])
        if model == HASH_MODEL:
            query_vector = local_embedding(query)
        elif model == SEMANTIC_MODEL:
            query_vector = semantic_embedding(query)
        else:
            selected, vectors = embed_texts([query], model)
            query_vector = vectors[0] if selected == model and vectors else semantic_embedding(query)
        best = max(best, cosine(query_vector, loads(row["vector_json"], [])))
    return best


def embedding_backend_status() -> dict[str, Any]:
    model = effective_embedding_model()
    return {
        "model": model,
        "mode": "api" if model not in {SEMANTIC_MODEL, HASH_MODEL} else "local",
        "fallbacks": [SEMANTIC_MODEL, HASH_MODEL],
    }


def _semantic_tokens(text: str) -> list[tuple[str, float]]:
    lowered = text.lower()
    raw_tokens = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]{1,4}", lowered)
    tokens: list[tuple[str, float]] = []
    for token in raw_tokens:
        tokens.append((token, 1.0))
        for alias in SEMANTIC_ALIASES.get(token, []):
            tokens.append((alias.lower(), 0.7))
    for key, aliases in SEMANTIC_ALIASES.items():
        if key.lower() in lowered:
            tokens.append((key.lower(), 1.2))
            tokens.extend((alias.lower(), 0.8) for alias in aliases)
    return tokens


def _api_embed_texts(texts: list[str], model: str) -> list[list[float]]:
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    if not api_key:
        return []
    base_url = (os.getenv("OPENAI_BASE_URL") or os.getenv("AI_API_URL") or "https://api.openai.com/v1").rstrip("/")
    if base_url.endswith("/chat/completions"):
        base_url = base_url[: -len("/chat/completions")]
    if not base_url.endswith("/v1"):
        base_url = f"{base_url}/v1" if "://" in base_url else base_url
    payload = {"model": model, "input": texts}
    req = request.Request(
        f"{base_url}/embeddings",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        vectors = [item.get("embedding", []) for item in data.get("data", [])]
        if len(vectors) == len(texts) and all(isinstance(vector, list) and vector for vector in vectors):
            return [[float(value) for value in vector] for vector in vectors]
    except Exception:
        return []
    return []
