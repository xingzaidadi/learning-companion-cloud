from __future__ import annotations

import re
import unicodedata
from sqlite3 import Connection
from decimal import Decimal, InvalidOperation
from typing import Any

from .db import dumps, loads, utc_now
from .grading_rubrics import rubric_for_item
from .ai_provider import call_ai_json_with_meta, generate_ai_questions
from .curriculum import find_curriculum_context
from .question_engine import build_content_quiz, build_variant_questions
from .review import close_related_review_items, create_review_item
from .rewards import add_reward
from .settings import get_settings


def _infer_quiz_skill(subject: str, question: str) -> str:
    if subject == "语文":
        if "听写" in question or "生字" in question:
            return "生字书写"
        if "日积月累" in question or "背" in question or "默" in question:
            return "日积月累背默"
        if "赏析" in question:
            return "句子赏析"
        return "课文理解"
    if subject == "数学":
        if "计算" in question or "结果" in question or re.search(r"\d", question):
            return "计算准确"
        if "应用" in question or "列式" in question:
            return "应用建模"
        return "概念理解"
    if subject == "英语":
        if "拼写" in question or "英文" in question:
            return "单词拼写"
        if "中文" in question or "意思" in question:
            return "词义匹配"
        if "句" in question:
            return "句型替换"
        return "课文理解"
    return "任务执行"


def _source_context(conn: Connection, task: dict[str, Any]) -> dict[str, Any]:
    source_id = task.get("source_id")
    if not source_id:
        return {"category": "review", "subject": "", "config": {}}
    row = conn.execute("SELECT * FROM task_sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return {"category": "unknown", "subject": "", "config": {}}
    return {
        "category": row["category"],
        "subject": row["subject"],
        "config": loads(row["config_json"], {}),
    }


def _materials_context(conn: Connection, task: dict[str, Any], subject: str) -> str:
    source_id = task.get("source_id") or 0
    rows = conn.execute(
        """
        SELECT material_type, title, content_text, file_path
        FROM learning_materials
        WHERE student_id = ?
          AND (
            source_id = ?
            OR (source_id IS NULL AND (? = '' OR subject = '' OR subject = ?))
          )
        ORDER BY source_id DESC, id DESC
        LIMIT 8
        """,
        (task["student_id"], source_id, subject, subject),
    ).fetchall()
    parts: list[str] = []
    for row in rows:
        text = row["content_text"] or row["file_path"]
        if not text:
            continue
        parts.append(f"【资料:{row['material_type']}】{row['title']}\n{text}")
    return "\n".join(parts)


def _material_chunks_for_task(conn: Connection, task: dict[str, Any], subject: str, limit: int = 8) -> list[dict[str, Any]]:
    source_id = task.get("source_id") or 0
    title = task.get("title", "")
    rows = conn.execute(
        """
        SELECT mc.*
        FROM material_chunks mc
        JOIN learning_materials lm ON lm.id = mc.material_id
        WHERE mc.student_id = ?
          AND (? = '' OR mc.subject = ?)
          AND (
            lm.source_id = ?
            OR lm.source_id IS NULL
            OR instr(mc.chunk_text, ?) > 0
            OR instr(mc.source_ref, ?) > 0
          )
        ORDER BY CASE WHEN lm.source_id = ? THEN 0 ELSE 1 END,
                 CASE mc.exam_weight WHEN 'high' THEN 0 ELSE 1 END,
                 mc.id DESC
        LIMIT ?
        """,
        (task["student_id"], subject, subject, source_id, title[:20], title[:20], source_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _best_source_ref(conn: Connection, task: dict[str, Any], subject: str, question: str) -> tuple[str, str]:
    chunks = _material_chunks_for_task(conn, task, subject, limit=12)
    if not chunks:
        return "规则兜底", ""
    terms = [term for term in re.findall(r"[A-Za-z]+|[\u4e00-\u9fff]{2,}", question) if term not in {"请写出", "选择", "结果", "今天"}]
    best = chunks[0]
    best_score = -1
    for chunk in chunks:
        haystack = f"{chunk['chunk_text']} {chunk['source_ref']} {chunk['knowledge_type']} {chunk['section']}"
        score = sum(2 if term in chunk["chunk_text"] else 1 for term in terms if term in haystack)
        if chunk["exam_weight"] == "high":
            score += 1
        if score > best_score:
            best = chunk
            best_score = score
    return best["source_ref"], best["knowledge_type"]


CONTENT_DEPENDENT_CATEGORIES = {"summer_homework", "exercise_book", "workbook", "reading_book"}


def _has_precise_material(conn: Connection, task: dict[str, Any], subject: str) -> bool:
    source_id = task.get("source_id") or 0
    if source_id:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM learning_materials
            WHERE student_id = ? AND source_id = ?
              AND trim(COALESCE(content_text, '')) != ''
            """,
            (task["student_id"], source_id),
        ).fetchone()
        if row and int(row["count"] or 0) > 0:
            return True
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM learning_materials
        WHERE student_id = ?
          AND (? = '' OR subject = ?)
          AND trim(COALESCE(content_text, '')) != ''
        """,
        (task["student_id"], subject, subject),
    ).fetchone()
    return bool(row and int(row["count"] or 0) > 0)


def _content_dependent_without_material(category: str, task: dict[str, Any], subject: str, has_material: bool) -> bool:
    if has_material:
        return False
    text = f"{task.get('title', '')} {task.get('description', '')}"
    if category in CONTENT_DEPENDENT_CATEGORIES:
        return True
    return any(word in text for word in ("暑假作业", "每日一练", "口算", "一本", "练习册", "作业本", "阅读书目"))


def _evidence_check_quiz(title: str, standard: str) -> list[dict[str, Any]]:
    return [
        _short(
            f"请从「{title}」里挑 1 道你刚做过或最不确定的题，写清题号/页码。",
            "写出题号或页码",
            "系统没有这本作业的原题内容，所以只核验你是否能定位真实题目，不杜撰题干。",
        ),
        _short(
            "请用自己的话写出这道题的解题思路、订正步骤或你卡住的位置。",
            "写出思路或卡点",
            "没有原题时，检查重点是过程证据：题号、思路、错因、订正动作。",
        ),
        _choice(
            "如果系统没有作业本原题，最可靠的检查方式是？",
            ["让系统随便编一道类似题", "上传/录入题目或写清题号和卡点", "直接算通过"],
            "上传/录入题目或写清题号和卡点",
            "真实作业必须基于真实题目检查；没有资料时不能假装知道题目。",
        ),
        _choice(
            "这项任务的完成标准是哪一个？",
            ["写完就行", "完成并自行检查一遍，错题做标记", "只做会做的题"],
            "完成并自行检查一遍，错题做标记",
            standard,
        ),
    ]


def _short(question: str, answer: str, explanation: str = "需包含关键概念、步骤或依据；只写无关内容不得分。") -> dict[str, Any]:
    return {
        "question_type": "short",
        "question": question,
        "answer": answer,
        "explanation": explanation,
    }


def _choice(question: str, options: list[str], answer: str, explanation: str) -> dict[str, Any]:
    return {
        "question_type": "choice",
        "question": question,
        "options_json": dumps(options),
        "answer": answer,
        "explanation": explanation,
    }


def _templates(conn: Connection, task: dict[str, Any]) -> list[dict[str, Any]]:
    if task.get("check_method") == "review_quiz":
        review_link = conn.execute(
            """
            SELECT note
            FROM task_progress
            WHERE daily_task_id = ? AND event_type = 'review_item'
            ORDER BY id DESC LIMIT 1
            """,
            (task["id"],),
        ).fetchone()
        review_item = None
        if review_link and str(review_link["note"]).isdigit():
            review_item = conn.execute("SELECT * FROM review_items WHERE id = ?", (int(review_link["note"]),)).fetchone()
        if review_item:
            variants = build_variant_questions(review_item["question"], review_item["answer"])
            if variants:
                return variants[:4]

    title = task.get("title", "今天任务")
    standard = task.get("completion_standard", "完成任务")
    context = _source_context(conn, task)
    category = context["category"]
    subject = context["subject"]
    config = dict(context["config"])
    materials_context = _materials_context(conn, task, subject)
    has_precise_material = _has_precise_material(conn, task, subject)
    if materials_context:
        config["materials_context"] = materials_context
    settings = get_settings(conn)
    region = settings.get("region", {})
    version = (
        region.get("chinese_version")
        if "语文" in subject
        else region.get("math_version")
        if "数学" in subject
        else region.get("english_version")
    )
    content_text = "\n".join(
        str(value)
        for value in (
            title,
            task.get("description", ""),
            standard,
            config.get("lesson_content", ""),
            config.get("knowledge_points", ""),
            config.get("vocabulary", ""),
            config.get("raw", ""),
            materials_context,
        )
        if value
    )
    curriculum_context = find_curriculum_context(
        "chinese" if "语文" in subject else "math" if "数学" in subject else "english" if "英语" in subject else "",
        content_text,
        version,
    )
    scope = ""
    if curriculum_context:
        scope = f"{curriculum_context.get('unit')}；知识点：{'、'.join(curriculum_context.get('points', []))}；范围限制：{curriculum_context.get('scope_note')}"
    if _content_dependent_without_material(category, task, subject, has_precise_material):
        return _evidence_check_quiz(title, standard)
    ai_items = generate_ai_questions(settings, scope, content_text)
    content_items = build_content_quiz(
        category=category,
        subject=subject,
        title=title,
        description=task.get("description", ""),
        standard=standard,
        config=config,
        version=version,
    )
    if ai_items and content_items:
        seen: set[str] = set()
        merged: list[dict[str, Any]] = []
        for item in [*content_items[:5], *ai_items[:3], *content_items[5:]]:
            key = f"{item.get('question_type')}::{item.get('question')}"
            if key not in seen:
                merged.append(item)
                seen.add(key)
        return merged[:7]
    if ai_items:
        return ai_items
    if content_items:
        return content_items

    if task.get("check_method") == "review_quiz":
        variants = build_variant_questions(title, standard)
        return variants[:4] if variants else [
            _choice("复测时遇到不会，最应该怎么做？", ["空着跳过", "写清卡点并请家长协助", "随便填"], "写清卡点并请家长协助", "补漏复测要留下明确卡点。"),
        ]

    if category == "summer_homework":
        return _evidence_check_quiz(title, standard)

    if category == "preview":
        topic = config.get("topic") or title
        if "小数" in topic or subject == "数学":
            return [
                _choice("3.6 × 10 的结果是？", ["0.36", "36", "360"], "36", "小数乘 10，小数点向右移动一位。"),
                _choice("4.8 ÷ 10 的结果是？", ["48", "0.48", "4.08"], "0.48", "小数除以 10，小数点向左移动一位。"),
                _short(f"请用一句话说明今天预习的知识点「{topic}」。", "说清知识点"),
                _short("写出一道你能独立完成的例题或同类题。", "写出题目和答案"),
            ]
        return [
            _short(f"请概括今天预习的知识点「{topic}」。", "说清知识点"),
            _short("写出一个例题或例句。", "写出例子"),
            _choice("预习后最重要的是？", ["只看不练", "做少量练习确认会用", "马上学下一章"], "做少量练习确认会用", "预习要形成可检查的掌握。"),
        ]

    if category == "ket":
        module = (config.get("module") or subject or title).lower()
        if "听" in module or "listening" in module:
            return [
                _short("请写出今天听力中听到的 2 个关键词。", "写出关键词"),
                _choice("听力没听清时第一反应应该是？", ["停住不做", "抓关键词继续听", "乱选"], "抓关键词继续听", "KET 听力先抓关键词和场景。"),
                _short("请写出 1 个今天需要复习的英文词或短语。", "写出词汇"),
            ]
        if "口" in module or "speaking" in module:
            return [
                _short("请写出今天口语回答的主题。", "写出主题"),
                _short("请写出一句完整英文回答。", "写出英文句子"),
                _choice("KET 口语回答最重要的是？", ["只说一个词", "完整句 + 声音清楚", "完全不回答"], "完整句 + 声音清楚", "口语训练要敢说完整句。"),
            ]
        return [
            _short("请写出今天记住的 3 个 KET 单词。", "写出单词"),
            _short("任选 1 个单词造一个英文短句。", "写出短句"),
            _choice("复习 KET 词汇最适合的方式是？", ["一天背很多不复习", "每天短练并重复", "只看中文"], "每天短练并重复", "KET 更适合高频短练。"),
        ]

    return [
        _short(f"请写出你完成「{title}」后最有把握的一点。", "已完成"),
        _short(f"「{title}」的完成标准是什么？", standard, "对照任务卡上的完成标准检查。"),
        _choice("如果遇到不会的题，正确做法是哪一个？", ["跳过不管", "标记并说明卡在哪里", "直接点完成"], "标记并说明卡在哪里", "不会时要留下线索，方便订正和家长协助。"),
    ]


HIDDEN_ENGLISH_ANSWER_TYPES = {"english_word_cn_to_en", "english_spelling"}


def _english_answer_tokens(answer: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z'-]*", answer or "")
        if len(token) >= 3
    }


def _question_contains_token(question: str, token: str) -> bool:
    return re.search(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", question or "", re.I) is not None


def _safe_english_sentence_fill(question: str, protected_tokens: set[str]) -> str:
    cleaned = question
    for token in protected_tokens:
        cleaned = re.sub(rf"(?<![A-Za-z]){re.escape(token)}(?![A-Za-z])", "desk", cleaned, flags=re.I)
    if any(_question_contains_token(cleaned, token) for token in protected_tokens):
        return "句型填空：There ___ a desk here."
    return cleaned


def _leak_scan_text(item: dict[str, Any]) -> str:
    options = loads(str(item.get("options_json", "[]")), [])
    return "\n".join([str(item.get("question", "")), *(str(option) for option in options)])


def _remove_cross_answer_leaks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    protected_by_index: dict[int, set[str]] = {
        index: _english_answer_tokens(str(item.get("answer", "")))
        for index, item in enumerate(items)
        if item.get("question_type") in HIDDEN_ENGLISH_ANSWER_TYPES
    }
    protected_tokens = {token for tokens in protected_by_index.values() for token in tokens}
    if not protected_tokens:
        return items

    cleaned_items: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        own_tokens = protected_by_index.get(index, set())
        tokens_to_hide = protected_tokens - own_tokens
        question = str(item.get("question", ""))
        scan_text = _leak_scan_text(item)
        leaked_tokens = {token for token in tokens_to_hide if _question_contains_token(scan_text, token)}
        if leaked_tokens and item.get("question_type") == "english_sentence_fill":
            item = {**item, "question": _safe_english_sentence_fill(question, leaked_tokens)}
            scan_text = _leak_scan_text(item)
            leaked_tokens = {token for token in tokens_to_hide if _question_contains_token(scan_text, token)}
        if leaked_tokens:
            continue
        cleaned_items.append(item)
    return cleaned_items if len(cleaned_items) >= 3 else items


def ensure_quiz_for_task(conn: Connection, task: dict[str, Any]) -> list[dict[str, Any]]:
    existing = conn.execute(
        "SELECT * FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task["id"],),
    ).fetchall()
    if existing:
        return [dict(row) for row in existing]

    now = utc_now()
    items = _remove_cross_answer_leaks(_templates(conn, task))
    context = _source_context(conn, task)
    subject = context.get("subject") or ""
    for item in items:
        source_ref, chunk_skill = _best_source_ref(conn, task, subject, item.get("question", ""))
        if source_ref == "规则兜底" and any(mark in item.get("explanation", "") for mark in ("不杜撰题干", "不能假装知道题目")):
            source_ref = "过程核验：未录入原题"
        skill = chunk_skill or _infer_quiz_skill(subject, item.get("question", ""))
        quality_score = 0.92 if source_ref != "规则兜底" else 0.78
        conn.execute(
            """
            INSERT INTO quiz_items (
                daily_task_id, question_type, question, options_json,
                answer, explanation, subject, skill, source_ref, quality_score, grading_rubric_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                item["question_type"],
                item["question"],
                item.get("options_json", "[]"),
                item["answer"],
                item["explanation"],
                subject,
                skill,
                source_ref,
                quality_score,
                dumps(rubric_for_item(item.get("question_type", ""), subject)),
                now,
            ),
        )
    rows = conn.execute(
        "SELECT * FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task["id"],),
    ).fetchall()
    return [dict(row) for row in rows]


def regenerate_quiz_for_task(conn: Connection, task_id: int) -> list[dict[str, Any]]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        return []
    conn.execute("DELETE FROM quiz_items WHERE daily_task_id = ?", (task_id,))
    return ensure_quiz_for_task(conn, dict(task))


def _compact(value: str) -> str:
    return re.sub(r"[\s，。、“”‘’！!？?：:；;,.（）()\[\]{}]+", "", value or "").lower()


def _normalize_pinyin(value: str) -> str:
    text = unicodedata.normalize("NFD", value or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = text.replace("ü", "u").replace("v", "u")
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _numbers(value: str) -> list[Decimal]:
    found: list[Decimal] = []
    for raw in re.findall(r"-?\d+(?:\.\d+)?", value or ""):
        try:
            found.append(Decimal(raw))
        except InvalidOperation:
            continue
    return found


def _numeric_match(user_answer: str, expected: str) -> bool:
    expected_values = _numbers(expected)
    user_values = _numbers(user_answer)
    if not expected_values or not user_values:
        return False
    return any(user_value == expected_value for user_value in user_values for expected_value in expected_values)


def _exact_match(user_answer: str, expected: str, *, numeric_inside_text: bool = False) -> bool:
    normalized_user = _compact(user_answer)
    for value in expected.split("|"):
        normalized_expected = _compact(value)
        if normalized_user == normalized_expected:
            return True
        try:
            if Decimal(normalized_user) == Decimal(normalized_expected):
                return True
        except InvalidOperation:
            pass
    if numeric_inside_text and _numeric_match(user_answer, expected):
        return True
    return False


def _extract_quoted_char(question: str) -> str:
    match = re.search(r"「(.)」", question or "")
    return match.group(1) if match else ""


def _is_open_type(question_type: str) -> bool:
    return question_type in {
        "short",
        "chinese_word_explain",
        "chinese_sentence_understand",
        "chinese_summary",
        "chinese_expression",
        "english_translation",
        "english_reading_check",
        "english_sentence_make",
        "math_step_explain",
    }


def _fallback_open_grade(question_type: str, user_answer: str, expected: str) -> tuple[bool, str]:
    text = (user_answer or "").strip()
    if not text:
        return False, "未作答"
    if question_type == "english_translation":
        expected_words = [word.lower() for word in re.findall(r"[A-Za-z]+", expected)]
        user_words = [word.lower() for word in re.findall(r"[A-Za-z]+", user_answer)]
        hits = sum(1 for word in expected_words if word in user_words)
        return hits >= max(1, min(2, len(expected_words))), "本地检查核心英文词"
    if question_type == "english_sentence_make":
        required = re.search(r"包含\s+([A-Za-z][A-Za-z'-]{2,})", expected or "")
        if required:
            required_word = required.group(1).lower()
            user_words = {word.lower() for word in re.findall(r"[A-Za-z]+", user_answer)}
            return required_word in user_words and len(user_words) >= 3, f"本地检查是否包含 {required_word} 并写成句子"
        return bool(re.search(r"[A-Za-z]+", text)) and len(re.findall(r"[A-Za-z]+", text)) >= 3, "本地检查完整英文短句"
    if question_type == "math_step_explain":
        return len(text) >= 6 and any(key in text for key in ("先", "再", "因为", "公式", "小数", "步骤", "×", "÷")), "本地检查是否说出步骤"
    if question_type.startswith("chinese_"):
        return len(_compact(text)) >= 6, "本地检查是否完整表达"
    return bool(text), "本地检查非空答案"


def _ai_grade_open(
    conn: Connection,
    question_type: str,
    question: str,
    user_answer: str,
    expected: str,
    explanation: str,
) -> tuple[bool, str, str]:
    fallback_correct, fallback_reason = _fallback_open_grade(question_type, user_answer, expected)
    fallback = {
        "correct": fallback_correct,
        "reason": fallback_reason,
        "error_type": "",
    }
    settings = get_settings(conn)
    result, meta = call_ai_json_with_meta(
        settings,
        f"""
你是武汉小学五年级上册语数英陪跑老师。请批改一道开放题，只输出 JSON。
不要超纲，不替孩子扩写答案，只判断是否基本达成本题要求。
字段：
correct: true/false
reason: 20字以内说明
error_type: 从 错字/拼音/词义/理解/表达/拼写/句型/语序/计算/小数点/概念/审题/单位/步骤不清 中选择一个，不确定用 表达

题型：{question_type}
题目：{question}
标准答案/要点：{expected}
讲解：{explanation}
孩子答案：{user_answer}
""".strip(),
        fallback,
    )
    if isinstance(result, dict):
        return bool(result.get("correct")), str(result.get("reason") or fallback_reason), "ai" if meta.get("used_ai") else "rule"
    return fallback_correct, fallback_reason, "rule"


def _error_type(question_type: str, question: str, user_answer: str, expected: str) -> str:
    if question_type == "chinese_word_dictation":
        return "错字"
    if question_type == "chinese_pinyin":
        return "拼音"
    if question_type in ("chinese_word_explain",):
        return "词义"
    if question_type in ("chinese_sentence_understand", "chinese_summary"):
        return "理解"
    if question_type == "chinese_expression":
        return "表达"
    if question_type in ("english_word_cn_to_en", "english_spelling"):
        return "拼写"
    if question_type == "english_word_en_to_cn":
        return "词义"
    if question_type in ("english_sentence_fill", "english_translation", "english_sentence_make"):
        return "句型"
    if question_type in ("math_concept_choice",):
        return "概念"
    if question_type in ("math_word_problem",):
        if expected and not _numeric_match(user_answer, expected):
            return "审题"
        return "单位"
    if question_type in ("math_step_explain",):
        return "步骤不清"
    if question_type in ("math_error_reason",):
        return "概念"
    if question_type.startswith("math_"):
        expected_nums = _numbers(expected)
        user_nums = _numbers(user_answer)
        if expected_nums and user_nums:
            expected_value = expected_nums[0]
            if any(abs(user_value) == abs(expected_value * Decimal(10)) or abs(user_value * Decimal(10)) == abs(expected_value) for user_value in user_nums):
                return "小数点"
        return "计算"
    return "表达"


def _review_reason(question_type: str, error_type: str) -> str:
    if question_type.startswith("chinese_"):
        if error_type == "错字":
            return "wrong_chinese_dictation"
        if error_type == "拼音":
            return "wrong_chinese_pinyin"
        return "wrong_chinese_understanding"
    if question_type.startswith("english_"):
        if error_type == "拼写":
            return "wrong_english_spelling"
        if error_type == "词义":
            return "wrong_english_meaning"
        return "wrong_english_sentence"
    if question_type.startswith("math_"):
        if error_type in ("计算", "小数点"):
            return "wrong_math_calculation"
        if error_type == "审题":
            return "wrong_math_word_problem"
        return "wrong_math_concept"
    return "wrong_quiz"


def _mastery_level(ratio: float) -> str:
    if ratio >= 0.9:
        return "A"
    if ratio >= 0.8:
        return "B"
    if ratio >= 0.6:
        return "C"
    return "D"


def _quiz_pass_ratio(conn: Connection) -> float:
    settings = get_settings(conn)
    raw_value = settings.get("path_rules", {}).get("quiz_pass_score", 0.8)
    try:
        ratio = float(raw_value)
    except (TypeError, ValueError):
        ratio = 0.8
    return min(max(ratio, 0.5), 1.0)


def _latest_quiz_result(conn: Connection, task_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT total, correct, wrong_items_json, score_json,
               error_types_json, mastery_json, status
        FROM quiz_results
        WHERE daily_task_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (task_id,),
    ).fetchone()
    if not row:
        return None
    return {
        "task_id": task_id,
        "total": row["total"],
        "correct": row["correct"],
        "status": row["status"],
        "wrong_items": loads(row["wrong_items_json"], []),
        "score_json": loads(row["score_json"], {}),
        "error_types": loads(row["error_types_json"], {}),
        "mastery": loads(row["mastery_json"], {}),
        "already_checked": True,
    }


def missing_required_answers(conn: Connection, task_id: int, answers: dict[str, Any]) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, question_type, question FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    missing: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        value = answers.get(str(row["id"]), "")
        if value is None or str(value).strip() == "":
            missing.append(
                {
                    "id": row["id"],
                    "index": index,
                    "question_type": row["question_type"],
                    "question": row["question"],
                }
            )
    return missing


def grade_quiz(conn: Connection, task_id: int, answers: dict[str, str]) -> dict[str, Any]:
    task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
    if not task:
        raise ValueError("任务不存在")
    if task["status"] == "completed":
        latest = _latest_quiz_result(conn, task_id)
        if latest:
            return latest
    items = conn.execute(
        "SELECT * FROM quiz_items WHERE daily_task_id = ? ORDER BY id",
        (task_id,),
    ).fetchall()
    wrong_items: list[dict[str, str]] = []
    correct = 0
    error_counts: dict[str, int] = {}
    for item in items:
        user_answer = answers.get(str(item["id"]), "").strip()
        expected = item["answer"].strip()
        question_type = item["question_type"]
        grading_source = "rule"
        if question_type == "choice" or question_type.endswith("_choice") or question_type == "math_error_reason":
            is_correct = _compact(user_answer) == _compact(expected)
        elif question_type == "chinese_word_dictation":
            is_correct = _compact(user_answer) == _compact(expected)
        elif question_type == "chinese_pinyin":
            is_correct = any(_normalize_pinyin(user_answer) == _normalize_pinyin(value) for value in expected.split("|"))
        elif question_type == "chinese_char_group":
            required_char = _extract_quoted_char(item["question"])
            is_correct = bool(required_char and required_char in user_answer)
        elif question_type in ("english_word_cn_to_en", "english_spelling"):
            is_correct = _exact_match(user_answer, expected)
        elif question_type == "english_word_en_to_cn":
            is_correct = _compact(expected) in _compact(user_answer) or _compact(user_answer) in _compact(expected)
        elif question_type in ("exact", "math_exact", "math_word_problem", "math_variant"):
            is_correct = _exact_match(user_answer, expected, numeric_inside_text=True)
        elif question_type == "english_sentence_fill":
            is_correct = _exact_match(user_answer, expected)
        elif _is_open_type(question_type):
            is_correct, _reason, grading_source = _ai_grade_open(conn, question_type, item["question"], user_answer, expected, item["explanation"])
        else:
            is_correct = bool(user_answer)
        if is_correct:
            correct += 1
        else:
            error_type = _error_type(question_type, item["question"], user_answer, expected)
            error_counts[error_type] = error_counts.get(error_type, 0) + 1
            wrong_items.append(
                {
                    "question_type": question_type,
                    "question": item["question"],
                    "your_answer": user_answer,
                    "answer": expected,
                    "explanation": item["explanation"],
                    "error_type": error_type,
                    "mastery_level": "D" if not user_answer else "C",
                    "next_action": f"先订正这题，再做 {error_type} 同类变式。",
                    "grading_source": grading_source,
                }
            )
            if task["check_method"] != "review_quiz":
                for days_later in (1, 3, 7, 14):
                    create_review_item(
                        conn,
                        int(task["student_id"]),
                        task_id,
                        item["question"],
                        expected,
                        item["explanation"],
                        _review_reason(question_type, error_type),
                        days_later,
                        f"D{days_later}",
                    )

    total = len(items)
    ratio = correct / total if total else 0
    pass_ratio = _quiz_pass_ratio(conn)
    status = "completed" if ratio >= pass_ratio else "needs_revision"
    mastery = {
        "mastery_level": _mastery_level(ratio),
        "next_action": "继续新课" if status == "completed" else "先完成错因补漏，再推进新课",
        "parent_note": "小测已通过。" if status == "completed" else "建议家长用 10 分钟陪孩子订正最高频错因。",
    }
    score_json = {
        "score": round(ratio * 100, 1),
        "pass_score": round(pass_ratio * 100, 1),
        "correct_rate": ratio,
    }
    now = utc_now()
    conn.execute(
        """
        INSERT INTO quiz_results (
            daily_task_id, total, correct, wrong_items_json,
            score_json, error_types_json, mastery_json, status, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (task_id, total, correct, dumps(wrong_items), dumps(score_json), dumps(error_counts), dumps(mastery), status, now),
    )
    conn.execute(
        "UPDATE daily_tasks SET status = ?, updated_at = ? WHERE id = ?",
        (status, now, task_id),
    )
    is_new_completion = status == "completed" and task["status"] != "completed"
    if is_new_completion and task["source_id"]:
        conn.execute(
            """
            UPDATE task_sources
            SET completed_units = MIN(total_units, completed_units + 1), updated_at = ?
            WHERE id = ?
            """,
            (now, task["source_id"]),
        )
    if is_new_completion and task["check_method"] == "review_quiz":
        link = conn.execute(
            """
            SELECT note FROM task_progress
            WHERE daily_task_id = ? AND event_type = 'review_item'
            ORDER BY id DESC LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if link and link["note"].isdigit():
            close_related_review_items(conn, int(link["note"]), "passed")
    if is_new_completion:
        add_reward(conn, int(task["student_id"]), 10, "小测通过", f"{task['title']} 小测 {correct}/{total}")
    conn.execute(
        "INSERT INTO task_progress (daily_task_id, event_type, note, created_at) VALUES (?, 'check', ?, ?)",
        (task_id, f"小测 {correct}/{total}", now),
    )
    return {
        "task_id": task_id,
        "total": total,
        "correct": correct,
        "status": status,
        "wrong_items": wrong_items,
        "score_json": score_json,
        "error_types": error_counts,
        "mastery": mastery,
    }
