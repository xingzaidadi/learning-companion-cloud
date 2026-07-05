from __future__ import annotations

import re
from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from .db import dumps, loads, utc_now


EXAM_TARGET = {
    "goal": "五年级上册语文、数学、英语阶段性考试稳定 95+",
    "pass_score": 0.95,
    "daily_max_minutes": 90,
    "principles": [
        "不以做完为目标，以能力点达标为目标",
        "所有任务必须能被小测或微练习验证",
        "错题和卡点必须进入补漏复习",
        "新课推进必须服从薄弱点补齐",
        "内容必须限制在当前小学五年级上册范围内",
    ],
}


SKILL_MAP = {
    "语文": [
        ("生字认读", 0.98),
        ("生字书写", 0.98),
        ("词义理解", 0.96),
        ("课文理解", 0.95),
        ("句子赏析", 0.92),
        ("日积月累背默", 0.98),
        ("习作表达", 0.9),
    ],
    "数学": [
        ("概念理解", 0.95),
        ("计算准确", 0.98),
        ("步骤表达", 0.92),
        ("应用建模", 0.9),
        ("易错辨析", 0.95),
        ("检查验算", 0.95),
    ],
    "英语": [
        ("听音辨词", 0.95),
        ("朗读跟读", 0.95),
        ("单词拼写", 0.95),
        ("词义匹配", 0.96),
        ("中译英", 0.9),
        ("句型替换", 0.9),
        ("课文理解", 0.9),
    ],
    "综合": [
        ("任务执行", 0.95),
        ("错题订正", 1.0),
    ],
}


SUBJECT_KEYWORDS = {
    "语文": ["语文", "课文", "生字", "词语", "白鹭", "日积月累", "语文园地", "习作", "阅读"],
    "数学": ["数学", "小数", "除法", "乘法", "计算", "应用题", "例题", "列式"],
    "英语": ["英语", "Unit", "unit", "school", "library", "classroom", "teacher", "单词", "默写", "听读"],
}


def infer_subject(text: str) -> str:
    for subject, keywords in SUBJECT_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return subject
    return "综合"


def infer_skill(subject: str, text: str) -> str:
    if subject == "语文":
        if "日积月累" in text:
            return "日积月累背默"
        if "生字" in text or "听写" in text:
            return "生字书写"
        if "词" in text:
            return "词义理解"
        if "仿写" in text or "习作" in text:
            return "习作表达"
        return "课文理解"
    if subject == "数学":
        if "应用" in text or "列式" in text:
            return "应用建模"
        if "步骤" in text or "为什么" in text:
            return "步骤表达"
        if "计算" in text or "小数" in text:
            return "计算准确"
        return "概念理解"
    if subject == "英语":
        if "拼" in text or "默写" in text:
            return "单词拼写"
        if "读" in text or "听" in text:
            return "朗读跟读"
        if "中文" in text or "意思" in text:
            return "词义匹配"
        if "句" in text:
            return "句型替换"
        return "词义匹配"
    return "任务执行"


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
    next_score = round(max(0.0, min(1.0, previous * 0.65 + score * 0.35)), 3)
    previous_evidence = loads(row["evidence_json"] if row else None, [])
    evidence_items = ([evidence] + previous_evidence)[:8]
    conn.execute(
        """
        INSERT INTO skill_mastery (
            student_id, subject, skill, mastery_score, confidence, evidence_json,
            last_task_id, last_quiz_result_id, updated_at
        )
        VALUES (?, ?, ?, ?, 0.75, ?, ?, ?, ?)
        ON CONFLICT(student_id, subject, skill, unit, lesson) DO UPDATE SET
            mastery_score = excluded.mastery_score,
            confidence = excluded.confidence,
            evidence_json = excluded.evidence_json,
            last_task_id = excluded.last_task_id,
            last_quiz_result_id = excluded.last_quiz_result_id,
            updated_at = excluded.updated_at
        """,
        (student_id, subject, skill, next_score, dumps(evidence_items), daily_task_id, quiz_result_id, now),
    )


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
            source_id, confidence, status, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (student_id, memory_type, subject, skill, content[:600], source_type, source_id, confidence, status, now, now),
    )
    return int(cursor.lastrowid)


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


def index_material(conn: Connection, material_id: int) -> dict[str, Any]:
    material = conn.execute("SELECT * FROM learning_materials WHERE id = ?", (material_id,)).fetchone()
    if not material:
        return {"material_id": material_id, "count": 0, "status": "not_found"}
    conn.execute("DELETE FROM material_chunks WHERE material_id = ?", (material_id,))
    content = material["content_text"] or material["title"]
    subject = material["subject"] or infer_subject(content)
    chunks = _split_material_text(content)
    now = utc_now()
    for index, chunk in enumerate(chunks, start=1):
        chunk_subject = subject or infer_subject(chunk)
        skill = infer_skill(chunk_subject, chunk)
        section = "日积月累" if "日积月累" in chunk else "正文/资料"
        source_ref = f"{material['title']}#{index}"
        conn.execute(
            """
            INSERT INTO material_chunks (
                material_id, student_id, subject, section, knowledge_type, chunk_text,
                keywords_json, source_ref, exam_weight, must_master, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                material_id,
                material["student_id"],
                chunk_subject,
                section,
                skill,
                chunk,
                dumps(_keywords(chunk)),
                source_ref,
                "high" if section == "日积月累" or skill in {"生字书写", "计算准确", "单词拼写"} else "medium",
                1,
                now,
            ),
        )
    return {"material_id": material_id, "count": len(chunks), "status": "indexed"}


def search_material_chunks(conn: Connection, query: str, subject: str = "", student_id: int = 1, limit: int = 8) -> list[dict[str, Any]]:
    terms = _keywords(query)
    rows = conn.execute(
        """
        SELECT * FROM material_chunks
        WHERE student_id = ? AND (? = '' OR subject = ?)
        ORDER BY id DESC
        LIMIT 200
        """,
        (student_id, subject, subject),
    ).fetchall()
    scored: list[tuple[int, dict[str, Any]]] = []
    for row in rows:
        item = dict(row)
        haystack = f"{item['chunk_text']} {' '.join(loads(item['keywords_json'], []))} {item['source_ref']}"
        score = sum(2 if term in item["chunk_text"] else 1 for term in terms if term in haystack)
        if subject and item["subject"] == subject:
            score += 1
        if score > 0 or not terms:
            item["keywords"] = loads(item.pop("keywords_json"), [])
            item["match_score"] = score
            scored.append((score, item))
    scored.sort(key=lambda pair: (pair[0], pair[1]["id"]), reverse=True)
    return [item for _score, item in scored[:limit]]


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
