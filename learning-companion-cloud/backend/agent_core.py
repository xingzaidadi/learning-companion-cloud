from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from sqlite3 import Connection
from typing import Any

from .db import dumps, loads, utc_now
from .rag_engine import embedding_backend_status, embedding_score_for_chunk, upsert_chunk_embedding


EXAM_TARGET = {'goal': '五年级上册语文、数学、英语阶段性考试稳定 95+',
 'pass_score': 0.95,
 'daily_max_minutes': 90,
 'principles': ['不以做完为目标，以能力点达标为目标', '所有任务必须能被小测或微练习验证', '错题和卡点必须进入补漏复习', '新课推进必须服从薄弱点补齐', '内容必须限制在当前小学五年级上册范围内']}


SKILL_MAP = {'语文': [('生字认读', 0.98),
        ('生字书写', 0.98),
        ('词义理解', 0.96),
        ('课文理解', 0.95),
        ('句子赏析', 0.92),
        ('日积月累背默', 0.98),
        ('习作表达', 0.9)],
 '数学': [('概念理解', 0.95), ('计算准确', 0.98), ('步骤表达', 0.92), ('应用建模', 0.9), ('易错辨析', 0.95), ('检查验算', 0.95)],
 '英语': [('听音辨词', 0.95), ('朗读跟读', 0.95), ('单词拼写', 0.95), ('词义匹配', 0.96), ('中译英', 0.9), ('句型替换', 0.9), ('课文理解', 0.9)],
 '综合': [('任务执行', 0.95), ('错题订正', 1.0)]}


COVERAGE_REQUIREMENTS = {'语文': [('课文正文', ['课文', '阅读', '白鹭', '落花生', '桂花雨', '少年中国说']),
        ('生字词', ['生字', '词语', '听写', '会写', '会认']),
        ('课后题', ['课后', '思考', '练习', '默读', '背诵']),
        ('语文园地', ['语文园地', '交流平台', '词句段运用']),
        ('日积月累', ['日积月累', '背默', '古诗', '名言']),
        ('习作', ['习作', '作文', '写作'])],
 '数学': [('单元目录', ['目录', '单元', '小数乘法', '位置', '小数除法', '可能性', '多边形']),
        ('概念例题', ['例', '例题', '想一想', '说一说']),
        ('计算练习', ['算一算', '计算', '竖式', '口算']),
        ('应用题', ['解决问题', '应用', '列式']),
        ('易错验算', ['验算', '检查', '易错', '改错'])],
 '英语': [('Unit目录', ['Unit', 'unit', 'Module', 'Lesson']),
        ('单词表', ['单词', 'word', 'Words', 'vocabulary']),
        ('句型', ['句型', 'sentence', 'There', 'Can', 'What', 'Where']),
        ('课文/对话', ['Story', 'Listen', 'Read', 'Talk', '课文', '对话']),
        ('听写/音频', ['听写', '音频', 'listen', 'dictation', '.mp3'])]}


SUBJECT_KEYWORDS = {'语文': ['语文', '课文', '生字', '词语', '白鹭', '日积月累', '语文园地', '习作', '阅读'],
 '数学': ['数学', '小数', '除法', '乘法', '计算', '应用题', '例题', '列式'],
 '英语': ['英语', 'Unit', 'unit', 'school', 'library', 'classroom', 'teacher', '单词', '默写', '听读']}


def infer_subject(text: str) -> str:
    for subject, keywords in SUBJECT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return subject
    return '综合'


def infer_skill(subject: str, text: str) -> str:
    if subject == '语文':
        if '日积月累' in text:
            return '日积月累背默'
        if '生字' in text or '听写' in text:
            return '生字书写'
        if '词' in text:
            return '词义理解'
        if '仿写' in text or '习作' in text:
            return '习作表达'
        return '课文理解'
    if subject == '数学':
        if '应用' in text or '列式' in text:
            return '应用建模'
        if '步骤' in text or '为什么' in text:
            return '步骤表达'
        if '计算' in text or '小数' in text or '验算' in text:
            return '计算准确'
        return '概念理解'
    if subject == '英语':
        if '拼' in text or '默写' in text or "dictation" in text:
            return '单词拼写'
        if '读' in text or '听' in text or "listen" in text:
            return '朗读跟读'
        if '中文' in text or '意思' in text:
            return '词义匹配'
        if '句' in text or "sentence" in text:
            return '句型替换'
        return '词义匹配'
    return '任务执行'


def infer_section(subject: str, text: str) -> str:
    for section, keywords in COVERAGE_REQUIREMENTS.get(subject, []):
        if any(keyword in text for keyword in keywords):
            return section
    if '日积月累' in text:
        return '日积月累'
    return '正文/资料'

def skill_targets() -> dict[str, Any]:
    return {
        "exam_target": EXAM_TARGET,
        "subjects": {
            subject: [{"skill": skill, "target": target} for skill, target in skills]
            for subject, skills in SKILL_MAP.items()
        },
    }


def ensure_default_skill_mastery(conn: Connection, student_id: int = 1) -> None:
    now = utc_now()
    for subject, skills in SKILL_MAP.items():
        for skill, _target in skills:
            conn.execute(
                """
                INSERT OR IGNORE INTO skill_mastery (
                    student_id, subject, skill, mastery_score, confidence,
                    evidence_json, updated_at
                )
                VALUES (?, ?, ?, 0.5, 0.5, '[]', ?)
                """,
                (student_id, subject, skill, now),
            )


def list_skill_mastery(conn: Connection, student_id: int = 1) -> list[dict[str, Any]]:
    ensure_default_skill_mastery(conn, student_id)
    rows = conn.execute(
        """
        SELECT * FROM skill_mastery
        WHERE student_id = ?
        ORDER BY subject, mastery_score ASC, skill
        """,
        (student_id,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["evidence"] = loads(item.pop("evidence_json"), [])
        item["target_score"] = dict(SKILL_MAP.get(item["subject"], [])).get(item["skill"], EXAM_TARGET["pass_score"])
        item["gap"] = round(max(0.0, item["target_score"] - float(item["mastery_score"])), 3)
        result.append(item)
    return result


def update_skill_mastery(
    conn: Connection,
    student_id: int,
    subject: str,
    skill: str,
    score: float,
    evidence: str,
    daily_task_id: int | None = None,
    quiz_result_id: int | None = None,
) -> None:
    ensure_default_skill_mastery(conn, student_id)
    now = utc_now()
    row = conn.execute(
        """
        SELECT * FROM skill_mastery
        WHERE student_id = ? AND subject = ? AND skill = ? AND unit = '' AND lesson = ''
        """,
        (student_id, subject, skill),
    ).fetchone()
    previous = float(row["mastery_score"]) if row else 0.5
    decayed_previous, decay_factor = _apply_forgetting_decay(previous, str(row["updated_at"]) if row else now)
    conflict_count = int(row["conflict_count"] if row and "conflict_count" in row.keys() else 0)
    conflict = (decayed_previous >= 0.8 and score < 0.6) or (decayed_previous < 0.6 and score >= 0.85)
    if conflict:
        conflict_count += 1
    confidence = round(max(0.35, min(0.9, 0.78 - conflict_count * 0.08 + score * 0.08)), 3)
    weight = 0.45 if conflict else 0.35
    next_score = round(max(0.0, min(1.0, decayed_previous * (1 - weight) + score * weight)), 3)
    previous_evidence = loads(row["evidence_json"] if row else None, [])
    governance_note = {
        "event": "mastery_update",
        "score": round(score, 3),
        "previous": previous,
        "decayed_previous": decayed_previous,
        "decay_factor": decay_factor,
        "conflict": conflict,
        "conflict_count": conflict_count,
    }
    evidence_items = ([evidence, governance_note] + previous_evidence)[:10]
    stable_weakness = 1 if next_score < 0.75 and conflict_count >= 1 else 0
    conn.execute(
        """
        INSERT INTO skill_mastery (
            student_id, subject, skill, mastery_score, confidence, evidence_json,
            last_task_id, last_quiz_result_id, updated_at, conflict_count, decay_factor, stable_weakness
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(student_id, subject, skill, unit, lesson) DO UPDATE SET
            mastery_score = excluded.mastery_score,
            confidence = excluded.confidence,
            evidence_json = excluded.evidence_json,
            last_task_id = excluded.last_task_id,
            last_quiz_result_id = excluded.last_quiz_result_id,
            conflict_count = excluded.conflict_count,
            decay_factor = excluded.decay_factor,
            stable_weakness = excluded.stable_weakness,
            updated_at = excluded.updated_at
        """,
        (student_id, subject, skill, next_score, confidence, dumps(evidence_items), daily_task_id, quiz_result_id, now, conflict_count, decay_factor, stable_weakness),
    )
    if conflict or stable_weakness:
        write_memory(
            conn,
            student_id,
            "semantic" if stable_weakness else "episodic",
            subject,
            skill,
            f"{skill}出现{'稳定薄弱点' if stable_weakness else '冲突证据'}：本次得分 {score:.2f}，历史衰减后 {decayed_previous:.2f}。",
            "memory_governance",
            quiz_result_id or daily_task_id,
            0.85 if stable_weakness else 0.7,
            governance_event="stable_weakness" if stable_weakness else "conflict_resolution",
        )
    compress_learning_memories(conn, student_id, subject, skill)


def write_memory(
    conn: Connection,
    student_id: int,
    memory_type: str,
    subject: str,
    skill: str,
    content: str,
    source_type: str,
    source_id: int | None = None,
    confidence: float = 0.7,
    status: str = "active",
    governance_event: str = "",
    compressed_from: list[int] | None = None,
) -> int:
    now = utc_now()
    blocked = ["忽略规则", "直接告诉我答案", "以后都给答案", "ignore previous"]
    if any(word in content for word in blocked):
        status = "rejected"
        confidence = 0.0
    cursor = conn.execute(
        """
        INSERT INTO memory_records (
            student_id, memory_type, subject, skill, content, source_type,
            source_id, confidence, status, compressed_from_json, governance_event, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (student_id, memory_type, subject, skill, content[:600], source_type, source_id, confidence, status, dumps(compressed_from or []), governance_event, now, now),
    )
    return int(cursor.lastrowid)


def compress_learning_memories(conn: Connection, student_id: int, subject: str, skill: str, threshold: int = 5) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT * FROM memory_records
        WHERE student_id = ? AND subject = ? AND skill = ? AND memory_type = 'episodic' AND status = 'active'
        ORDER BY id DESC
        LIMIT 20
        """,
        (student_id, subject, skill),
    ).fetchall()
    if len(rows) < threshold:
        return {"compressed": False, "count": len(rows)}
    selected = [dict(row) for row in rows[:threshold]]
    source_ids = [int(row["id"]) for row in selected]
    weakness_count = sum(1 for row in selected if any(word in row["content"] for word in ("错", "薄弱", "不会", "未掌握", "冲突")))
    summary = f"{subject}{skill}近期出现 {len(selected)} 条学习记忆，其中 {weakness_count} 条指向薄弱或错因；后续计划应优先短复盘。"
    memory_id = write_memory(
        conn,
        student_id,
        "semantic",
        subject,
        skill,
        summary,
        "memory_compression",
        None,
        min(0.95, 0.65 + weakness_count * 0.06),
        "active",
        governance_event="memory_compression",
        compressed_from=source_ids,
    )
    conn.execute(
        f"UPDATE memory_records SET status = 'compressed', updated_at = ? WHERE id IN ({','.join('?' for _ in source_ids)})",
        (utc_now(), *source_ids),
    )
    return {"compressed": True, "memory_id": memory_id, "source_ids": source_ids}


def _apply_forgetting_decay(previous: float, updated_at: str) -> tuple[float, float]:
    try:
        parsed = datetime.fromisoformat(updated_at.replace("Z", "+00:00")).date()
    except ValueError:
        parsed = date.today()
    days = max(0, (date.today() - parsed).days)
    decay_factor = round(max(0.72, 0.97 ** days), 3)
    return round(previous * decay_factor + 0.5 * (1 - decay_factor), 3), decay_factor


def list_active_memories(conn: Connection, student_id: int = 1, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM memory_records
        WHERE student_id = ? AND status = 'active'
        ORDER BY confidence DESC, id DESC
        LIMIT ?
        """,
        (student_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _keywords(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]{2,}", text)
    stop = {"完成", "学习", "今天", "任务", "预习", "练习", "小测", "课文"}
    return list(dict.fromkeys([word for word in words if word not in stop]))[:12]


def _retrieval_vector(text: str) -> dict[str, float]:
    tokens = [token.lower() for token in re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]", text or "")]
    features = list(tokens)
    for index in range(len(tokens) - 1):
        if re.fullmatch(r"[\u4e00-\u9fff]", tokens[index]) and re.fullmatch(r"[\u4e00-\u9fff]", tokens[index + 1]):
            features.append(tokens[index] + tokens[index + 1])
    vector: dict[str, float] = {}
    for feature in features:
        vector[feature] = vector.get(feature, 0.0) + 1.0
    return vector


def _cosine_similarity(left: dict[str, float], right: dict[str, float]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(key, 0.0) for key, value in left.items())
    if dot <= 0:
        return 0.0
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)


def _split_material_text(text: str) -> list[str]:
    clean = text.strip()
    if not clean:
        return []
    parts = [part.strip() for part in re.split(r"\n{2,}|(?<=。)|(?<=；)|(?<=;)", clean) if part.strip()]
    chunks: list[str] = []
    current = ""
    for part in parts:
        if len(current) + len(part) <= 450:
            current = f"{current}\n{part}".strip()
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks[:80]


def _infer_unit(text: str) -> str:
    match = re.search(r"(Unit\s*\d+|第[一二三四五六七八九十\d]+单元|第\s*\d+\s*单元)", text, flags=re.I)
    return match.group(1).replace(" ", "") if match else ""


def _infer_lesson(text: str) -> str:
    match = re.search(r"(第[一二三四五六七八九十\d]+课|Lesson\s*\d+|课文[：:]\s*[^\n]{1,30})", text, flags=re.I)
    return match.group(1).strip() if match else ""


def analyze_material_coverage(title: str, content: str, subject: str = "") -> dict[str, Any]:
    resolved_subject = subject or infer_subject(f"{title}\n{content[:1500]}")
    text = f"{title}\n{content}"
    requirements = COVERAGE_REQUIREMENTS.get(resolved_subject, [])
    sections: list[dict[str, Any]] = []
    matched_count = 0
    for section, keywords in requirements:
        hits = [keyword for keyword in keywords if keyword.lower() in text.lower()]
        matched = bool(hits)
        matched_count += int(matched)
        sections.append(
            {
                "section": section,
                "covered": matched,
                "hits": hits[:6],
                "importance": "high" if section in {"生字词", "日积月累", "计算练习", "单词表", "听写/音频"} else "medium",
            }
        )
    ratio = round(matched_count / len(requirements), 2) if requirements else 0
    missing = [item["section"] for item in sections if not item["covered"]]
    warnings: list[str] = []
    if resolved_subject == "语文" and "日积月累" in missing:
        warnings.append("语文资料缺少“日积月累”，背默类考点无法精准覆盖。")
    if resolved_subject == "英语" and "单词表" in missing:
        warnings.append("英语资料缺少单词表，听写/拼写题会退化为规则兜底。")
    if resolved_subject == "数学" and "计算练习" in missing:
        warnings.append("数学资料缺少计算练习，计算准确率训练不够精准。")
    return {
        "subject": resolved_subject,
        "coverage_ratio": ratio,
        "sections": sections,
        "missing": missing,
        "warnings": warnings,
    }


def index_material(conn: Connection, material_id: int) -> dict[str, Any]:
    material = conn.execute("SELECT * FROM learning_materials WHERE id = ?", (material_id,)).fetchone()
    if not material:
        return {"material_id": material_id, "count": 0, "status": "not_found"}
    conn.execute("DELETE FROM material_chunks WHERE material_id = ?", (material_id,))
    content = material["content_text"] or material["title"]
    subject = material["subject"] or infer_subject(content)
    coverage = analyze_material_coverage(material["title"], content, subject)
    conn.execute(
        "UPDATE learning_materials SET coverage_json = ?, updated_at = ? WHERE id = ?",
        (dumps(coverage), utc_now(), material_id),
    )
    chunks = _split_material_text(content)
    now = utc_now()
    for index, chunk in enumerate(chunks, start=1):
        chunk_subject = subject or infer_subject(chunk)
        skill = infer_skill(chunk_subject, chunk)
        section = infer_section(chunk_subject, chunk)
        source_ref = f"{material['title']}#{index}"
        cursor = conn.execute(
            """
            INSERT INTO material_chunks (
                material_id, student_id, subject, unit, lesson, section, knowledge_type, chunk_text,
                keywords_json, source_ref, exam_weight, must_master, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                material_id,
                material["student_id"],
                chunk_subject,
                _infer_unit(chunk),
                _infer_lesson(chunk),
                section,
                skill,
                chunk,
                dumps(_keywords(chunk)),
                source_ref,
                "high" if section in {"日积月累", "生字词", "计算练习", "单词表", "听写/音频"} or skill in {"生字书写", "计算准确", "单词拼写"} else "medium",
                1,
                now,
            ),
        )
        upsert_chunk_embedding(conn, int(cursor.lastrowid), chunk)
    return {"material_id": material_id, "count": len(chunks), "status": "indexed", "coverage": coverage}


def search_material_chunks(conn: Connection, query: str, subject: str = "", student_id: int = 1, limit: int = 8) -> list[dict[str, Any]]:
    terms = _keywords(query)
    negative_terms = _negative_scope_terms(query)
    query_vector = _retrieval_vector(query)
    rows = conn.execute(
        """
        SELECT * FROM material_chunks
        WHERE student_id = ? AND (? = '' OR subject = ?)
        ORDER BY id DESC
        LIMIT 200
        """,
        (student_id, subject, subject),
    ).fetchall()
    scored_raw: list[tuple[float, float, float, dict[str, Any]]] = []
    for row in rows:
        item = dict(row)
        keywords = loads(item["keywords_json"], [])
        haystack = f"{item['chunk_text']} {' '.join(keywords)} {item['source_ref']} {item['section']} {item['knowledge_type']}"
        if negative_terms and any(term in haystack for term in negative_terms):
            continue
        keyword_score = sum(2 if term in item["chunk_text"] else 1 for term in terms if term in haystack)
        vector_score = max(_cosine_similarity(query_vector, _retrieval_vector(haystack)), embedding_score_for_chunk(conn, int(item["id"]), query))
        if subject and item["subject"] == subject:
            keyword_score += 1
        bm25_score = _bm25_like_score(terms, haystack)
        if keyword_score > 0 or bm25_score > 0 or vector_score > 0.12 or not terms:
            item["keywords"] = loads(item.pop("keywords_json"), [])
            item["keyword_score"] = keyword_score
            item["bm25_score"] = round(bm25_score, 3)
            item["vector_score"] = round(vector_score, 3)
            scored_raw.append((float(keyword_score), bm25_score, vector_score, item))
    max_keyword = max((row[0] for row in scored_raw), default=1.0) or 1.0
    max_bm25 = max((row[1] for row in scored_raw), default=1.0) or 1.0
    scored: list[tuple[float, dict[str, Any]]] = []
    for keyword_score, bm25_score, vector_score, item in scored_raw:
        keyword_norm = keyword_score / max_keyword
        bm25_norm = bm25_score / max_bm25
        vector_norm = max(0.0, min(1.0, (vector_score + 1.0) / 2.0))
        fused_score = keyword_norm * 0.35 + bm25_norm * 0.2 + vector_norm * 0.45
        if subject and item["subject"] == subject:
            fused_score += 0.05
        item["match_score"] = round(fused_score, 3)
        item["keyword_norm"] = round(keyword_norm, 3)
        item["bm25_norm"] = round(bm25_norm, 3)
        item["vector_norm"] = round(vector_norm, 3)
        item["retrieval_method"] = "hybrid_bm25_semantic_embedding"
        item["embedding_model"] = embedding_backend_status()["model"]
        scored.append((fused_score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1]["id"]), reverse=True)
    return [item for _score, item in scored[:limit]]


def _bm25_like_score(terms: list[str], text: str) -> float:
    if not terms:
        return 0.1
    length = max(len(text), 1)
    score = 0.0
    for term in terms:
        count = text.count(term)
        if count:
            tf = count / (count + 1.2 + 0.25 * length / 500)
            score += tf * (1.5 if len(term) >= 2 else 1.0)
    return score


def _negative_scope_terms(query: str) -> list[str]:
    if not any(marker in query for marker in ("不要", "别", "不能", "不学", "超纲")):
        return []
    candidates = ["初中", "有理数", "方程组", "六年级", "分数除法", "竞赛", "奥数"]
    return [term for term in candidates if term in query]


def build_material_coverage(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT subject, title, coverage_json, config_json, created_at
        FROM learning_materials
        WHERE student_id = ?
        ORDER BY id DESC
        """,
        (student_id,),
    ).fetchall()
    by_subject: dict[str, dict[str, Any]] = {}
    for subject in COVERAGE_REQUIREMENTS:
        by_subject[subject] = {
            "subject": subject,
            "coverage_ratio": 0,
            "covered_sections": [],
            "missing_sections": [section for section, _ in COVERAGE_REQUIREMENTS[subject]],
            "warnings": [],
            "materials": [],
        }
    for row in rows:
        coverage = loads(row["coverage_json"], {}) or {}
        subject = coverage.get("subject") or row["subject"] or "综合"
        if subject not in by_subject:
            continue
        item = by_subject[subject]
        material_sections = coverage.get("sections", [])
        covered = [section["section"] for section in material_sections if section.get("covered")]
        item["covered_sections"] = sorted(set(item["covered_sections"]) | set(covered))
        required = [section for section, _ in COVERAGE_REQUIREMENTS[subject]]
        item["missing_sections"] = [section for section in required if section not in item["covered_sections"]]
        item["coverage_ratio"] = round(len(item["covered_sections"]) / len(required), 2) if required else 0
        item["warnings"].extend(coverage.get("warnings", []))
        item["materials"].append(
            {
                "title": row["title"],
                "coverage_ratio": coverage.get("coverage_ratio", 0),
                "created_at": row["created_at"],
                "source": (loads(row["config_json"], {}) or {}).get("source", ""),
            }
        )
    for item in by_subject.values():
        item["warnings"] = list(dict.fromkeys(item["warnings"]))
        if item["coverage_ratio"] < 0.7:
            item["warnings"].append("资料覆盖不足 70%，今日计划和小测会有部分规则兜底。")
    overall = round(sum(item["coverage_ratio"] for item in by_subject.values()) / len(by_subject), 2)
    return {"overall_ratio": overall, "subjects": list(by_subject.values())}


def evaluate_quiz_quality(conn: Connection, daily_task_id: int) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (daily_task_id,)).fetchone()
    items = conn.execute("SELECT * FROM quiz_items WHERE daily_task_id = ?", (daily_task_id,)).fetchall()
    issues: list[str] = []
    if not task:
        return {"score": 0, "passed": False, "issues": ["任务不存在"]}
    if len(items) < 3:
        issues.append("题量不足，无法支撑 95+ 目标")
    task_text = f"{task['title']} {task['description']} {task['completion_standard']}"
    subject = infer_subject(task_text)
    answer_by_type = [(str(item["question_type"]), str(item["answer"]).strip().lower()) for item in items]
    if len(answer_by_type) != len(set(answer_by_type)):
        issues.append("同题型存在重复答案，区分度不足")
    for item in items:
        question = str(item["question"])
        answer = str(item["answer"]).strip()
        if answer and answer.lower() in question.lower():
            issues.append(f"题干疑似泄露答案：{question[:24]}")
        generic_learning_question = any(marker in question for marker in ("课文理解", "主要介绍", "完成标准", "学习内容"))
        if subject != "综合" and not generic_learning_question and infer_subject(f"{question} {answer}") not in {subject, "综合"}:
            issues.append(f"题目和任务学科相关性弱：{question[:24]}")
    score = max(0.0, round(1.0 - len(issues) * 0.1, 2))
    passed = score >= 0.8
    now = utc_now()
    conn.execute(
        """
        INSERT INTO quiz_quality_results (daily_task_id, score, passed, issues_json, checked_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (daily_task_id, score, int(passed), dumps(issues), now),
    )
    conn.execute(
        """
        UPDATE quiz_items
        SET subject = CASE WHEN subject = '' THEN ? ELSE subject END,
            skill = CASE WHEN skill = '' THEN ? ELSE skill END,
            difficulty = CASE WHEN difficulty = '' THEN 'basic' ELSE difficulty END,
            quality_score = CASE WHEN quality_score = 0 THEN ? ELSE quality_score END
        WHERE daily_task_id = ?
        """,
        (subject, infer_skill(subject, task_text), score, daily_task_id),
    )
    return {"task_id": daily_task_id, "score": score, "passed": passed, "issues": issues, "target": "95+"}


def update_mastery_from_quiz_result(conn: Connection, daily_task_id: int, quiz_result: dict[str, Any]) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (daily_task_id,)).fetchone()
    if not task:
        return {}
    subject = infer_subject(f"{task['title']} {task['description']}")
    skill = infer_skill(subject, f"{task['title']} {task['description']} {quiz_result.get('wrong_items', '')}")
    total = max(1, int(quiz_result.get("total", 0) or 0))
    correct = int(quiz_result.get("correct", 0) or 0)
    score = correct / total
    evidence = f"{task['title']} 小测 {correct}/{total}，目标 95+"
    row = conn.execute(
        "SELECT id FROM quiz_results WHERE daily_task_id = ? ORDER BY id DESC LIMIT 1",
        (daily_task_id,),
    ).fetchone()
    update_skill_mastery(conn, int(task["student_id"]), subject, skill, score, evidence, daily_task_id, int(row["id"]) if row else None)
    if score < EXAM_TARGET["pass_score"]:
        write_memory(
            conn,
            int(task["student_id"]),
            "episodic",
            subject,
            skill,
            f"{task['title']} 未达到 95+：{correct}/{total}，需要补漏",
            "quiz",
            daily_task_id,
            0.82,
        )
    return {"subject": subject, "skill": skill, "score": round(score, 3), "target": EXAM_TARGET["pass_score"]}


def build_target_insights(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    mastery = list_skill_mastery(conn, student_id)
    weak = [item for item in mastery if item["gap"] > 0]
    weak.sort(key=lambda item: (item["gap"], -item["confidence"]), reverse=True)
    memories = list_active_memories(conn, student_id, 8)
    top_weak = weak[:5]
    headline = "已建立 95+ 目标画像，继续按薄弱点补漏"
    if top_weak:
        first = top_weak[0]
        headline = f"距离 95+ 最近要补：{first['subject']}「{first['skill']}」"
    tomorrow = []
    for item in top_weak[:3]:
        tomorrow.append(
            {
                "subject": item["subject"],
                "skill": item["skill"],
                "action": f"先做 10 分钟{item['subject']}「{item['skill']}」补漏，再做新课",
                "target": item["target_score"],
                "current": item["mastery_score"],
            }
        )
    return {
        "exam_target": EXAM_TARGET,
        "headline": headline,
        "weak_points": top_weak,
        "tomorrow_actions": tomorrow,
        "active_memories": memories,
        "readiness_score": round(sum(item["mastery_score"] for item in mastery) / max(1, len(mastery)), 3),
    }


def recommend_daily_adjustments(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    target_date = target_date or date.today().isoformat()
    insights = build_target_insights(conn, student_id)
    tasks = conn.execute(
        "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
        (student_id, target_date),
    ).fetchall()
    total_minutes = sum(int(task["estimated_minutes"] or 0) for task in tasks)
    recommendations = []
    if total_minutes > EXAM_TARGET["daily_max_minutes"]:
        recommendations.append(f"今日任务预计 {total_minutes} 分钟，超过 95+ 稳定学习建议上限 {EXAM_TARGET['daily_max_minutes']} 分钟，应压缩低优先级任务")
    for action in insights["tomorrow_actions"][:2]:
        recommendations.append(action["action"])
    if not recommendations:
        recommendations.append("今日任务量和掌握度正常，按计划推进，并保持小测 95% 目标")
    return {
        "date": target_date,
        "total_minutes": total_minutes,
        "max_minutes": EXAM_TARGET["daily_max_minutes"],
        "recommendations": recommendations,
        "requires_parent_confirm": total_minutes > EXAM_TARGET["daily_max_minutes"],
    }


def open_or_update_tutor_session(conn: Connection, task: dict[str, Any], note: str, assistance: dict[str, Any]) -> dict[str, Any]:
    subject = infer_subject(f"{task.get('title', '')} {task.get('description', '')} {note}")
    skill = infer_skill(subject, note or f"{task.get('title', '')} {task.get('description', '')}")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO tutor_sessions (
            daily_task_id, student_id, status, stuck_note, subject, skill, resolution, created_at, updated_at
        )
        VALUES (?, ?, 'micro_practice', ?, ?, ?, ?, ?, ?)
        """,
        (
            task["id"],
            task["student_id"],
            note,
            subject,
            skill,
            assistance.get("try_again") or assistance.get("hint_1") or "",
            now,
            now,
        ),
    )
    session_id = int(cursor.lastrowid)
    micro_practice = _micro_practice(subject, skill, note)
    conn.execute(
        """
        INSERT INTO tutor_messages (session_id, role, content, meta_json, created_at)
        VALUES (?, 'assistant', ?, ?, ?)
        """,
        (
            session_id,
            micro_practice["prompt"],
            dumps({"micro_practice": micro_practice, "assistance": assistance}),
            now,
        ),
    )
    write_memory(
        conn,
        int(task["student_id"]),
        "episodic",
        subject,
        skill,
        f"卡住：{task['title']}；孩子描述：{note or '未填写'}",
        "stuck",
        int(task["id"]),
        0.72,
    )
    return {"session_id": session_id, "subject": subject, "skill": skill, "micro_practice": micro_practice}


def _micro_practice(subject: str, skill: str, note: str) -> dict[str, str]:
    if subject == "英语":
        return {
            "prompt": "先不看答案：把你卡住的单词读/拼一遍，或者写出它的中文意思。",
            "success_rule": "能读、能拼或能说出意思，就点“我会了，继续学”；否则继续提示。",
        }
    if subject == "数学":
        return {
            "prompt": "先写出题目里的三个量：已知什么、要求什么、用什么关系式。",
            "success_rule": "能列出关系式，再继续完成原题；列不出就继续提示。",
        }
    if subject == "语文":
        return {
            "prompt": "先用一句话说：这个词/句子表面意思是什么？在课文里写谁或什么？",
            "success_rule": "能说出意思和课文作用，再继续学习；说不出就继续提示。",
        }
    return {
        "prompt": "先把卡住点拆成第一小步，只完成这一小步。",
        "success_rule": "完成第一小步后继续学习。",
    }
