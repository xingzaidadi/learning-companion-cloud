from __future__ import annotations

import re
from datetime import date, timedelta
from sqlite3 import Connection
from typing import Any

from .curriculum import get_subject_units
from .db import dumps, utc_now
from .settings import get_settings


def _flatten_lessons(units: list[dict[str, Any]]) -> list[str]:
    lessons: list[str] = []
    for unit in units:
        for lesson in unit.get("lessons", []):
            lessons.append(f"{unit['unit']}：{lesson}")
    return lessons


def _deadline(default_days: int = 30) -> str:
    return (date.today() + timedelta(days=default_days)).isoformat()


def _summer_deadline(text: str) -> str:
    if "2026年8月31日" in text or "2026-08-31" in text:
        return "2026-08-31"
    return _deadline(56)


def _detect_total_units(text: str, default: int) -> int:
    matches = re.findall(r"(\d+)\s*(?:节|课|篇|页|小节|单元|天)", text)
    if not matches:
        return default
    numbers = [int(value) for value in matches]
    useful = [value for value in numbers if value >= 6]
    return useful[0] if useful else default


def _detect_completed(text: str, default: int = 0) -> int:
    match = re.search(r"(?:已完成|目前已完成)\s*(\d+)", text)
    return int(match.group(1)) if match else default


def _homework_source(text: str) -> dict[str, Any]:
    subject = ""
    lowered = text.lower()
    for candidate in ("语文", "数学", "英语"):
        if candidate in text:
            subject = candidate
            break
    if not subject:
        if "math" in lowered:
            subject = "数学"
        elif "english" in lowered:
            subject = "英语"
        elif "chinese" in lowered or "reading" in lowered:
            subject = "语文"
    title = "寒假作业本" if "寒假" in text else "暑假作业本" if "暑假" in text else "作业本"
    return {
        "category": "summer_homework",
        "title": title if not subject else f"{subject}{title}",
        "subject": subject,
        "total_units": _detect_total_units(text, 30),
        "completed_units": 0,
        "deadline": _deadline(35),
        "config": {
            "display_label": "寒假作业" if "寒假" in text else "暑假作业" if "暑假" in text else "作业",
            "estimated_minutes": 30,
            "pacing": "每日一小节",
            "unit_label": "小节",
            "lesson_content": "按作业本顺序每日完成一小节，先独立完成，再检查订正。",
            "knowledge_points": "读题；独立完成；检查；订正",
            "study_steps": [
                "先看清今天这一小节的题目要求。",
                "独立完成会做的题，难题先做标记。",
                "完成后用 5 分钟检查计算、错别字或漏题。",
                "把不会的题写入卡点说明。",
            ],
        },
    }


def _book_source(subject: str, text: str, settings: dict[str, Any]) -> dict[str, Any]:
    if subject == "英语" and _looks_like_fltrp_english_plan(text):
        return _fltrp_english_source(text)

    region = settings.get("region", {})
    version = (
        region.get("chinese_version")
        if subject == "语文"
        else region.get("math_version")
        if subject == "数学"
        else region.get("english_version")
    )
    key = "chinese" if subject == "语文" else "math" if subject == "数学" else "english"
    lessons = _flatten_lessons(get_subject_units(key, version))
    unit_label = "篇课文" if subject == "语文" else "节" if subject == "数学" else "课"
    default_total = len(lessons) or 20
    return {
        "category": "preview",
        "title": f"五年级上册{subject}每日学习",
        "subject": subject,
        "total_units": _detect_total_units(text, default_total),
        "completed_units": 0,
        "deadline": _deadline(45),
        "config": {
            "estimated_minutes": 30 if subject != "数学" else 35,
            "pacing": f"每日一{unit_label}",
            "unit_label": unit_label,
            "lesson_sequence": lessons,
            "lesson_content": f"按五年级上册{subject}课本顺序每日学习一{unit_label}。",
            "knowledge_points": "课本核心知识点；当天例题/课文；易错点；复述或讲解",
            "study_steps": _study_steps(subject),
        },
    }


def _looks_like_fltrp_english_plan(text: str) -> bool:
    normalized = text.lower()
    return any(
        keyword in normalized
        for keyword in (
            "外研社",
            "刘兆义",
            "unit 1",
            "unit1",
            "my school is cool",
            "school activities are fun",
            "the ice world",
            "i love the sea",
            "work it out",
            "big days",
            "音频",
            "默写",
            "字帖",
        )
    )


def _fltrp_english_source(text: str) -> dict[str, Any]:
    sequence = _fltrp_english_sequence()
    return {
        "category": "preview",
        "title": "外研社刘兆义版五年级上册英语暑假预习",
        "subject": "英语",
        "total_units": len(sequence),
        "completed_units": 0,
        "deadline": _deadline(38),
        "config": {
            "display_label": "英语预习",
            "estimated_minutes": 30,
            "pacing": "每日 25–35 分钟",
            "unit_label": "天",
            "lesson_sequence": sequence,
            "lesson_content": "基于五上英语课本、Unit 1–6 单词字帖、Unit 1–6 中译英默写练习和 Unit 1–3 音频推进。",
            "knowledge_points": "听读课文；理解课文；单词认读；字帖书写；中译英默写；小测检查",
            "resources": {
                "textbook": "2026新五上定稿课本.pdf",
                "copybook": "五上单词英语字帖.pdf",
                "dictation": "单词默写练习-Unit 1 至 Unit 6",
                "audio": "Unit 1–3 已有音频；Unit 4–6 暂无音频，用课本朗读和重点句跟读替代",
            },
            "study_steps": [
                "先听音频或朗读课本 5–8 分钟，圈出不会读的词。",
                "看课本图片和 Story/活动内容，说出今天主要讲什么。",
                "认读并书写 3–6 个重点词，优先处理错词。",
                "用本课重点句型说或写 1–2 个短句。",
                "完成小测或中译英默写，低于 80% 次日先补漏。",
            ],
        },
    }


def _fltrp_english_sequence() -> list[str]:
    units = [
        ("Unit 1 My school is cool", True),
        ("Unit 2 School activities are fun!", True),
        ("Unit 3 The ice world", True),
        ("Unit 4 I love the sea!", False),
        ("Unit 5 Work it out!", False),
        ("Unit 6 Big days", False),
    ]
    sequence: list[str] = []
    for unit, has_audio in units:
        audio_step = "听音频跟读" if has_audio else "课本朗读和重点句跟读"
        sequence.extend(
            [
                f"{unit} 第1天：{audio_step}，整体理解单元主题",
                f"{unit} 第2天：Story/课文精读，理解人物、场景和主要句子",
                f"{unit} 第3天：单词认读与字帖书写，整理不会读/不会拼的词",
                f"{unit} 第4天：中译英默写练习，订正错词并复读重点句",
                f"{unit} 第5天：单元复习和小测，未达 80% 次日补漏",
            ]
        )
    return sequence


def _study_steps(subject: str) -> list[str]:
    if subject == "语文":
        return [
            "通读课文，圈出生字词和不理解的句子。",
            "用 2–3 句话概括主要内容。",
            "找 1 个关键句，说明它好在哪里。",
            "完成一段仿写或口头复述。",
        ]
    if subject == "数学":
        return [
            "先看课本例题，讲清每一步为什么这样做。",
            "独立完成 3 道基础题。",
            "完成 1 道应用题或变式题。",
            "整理一个易错点。",
        ]
    return [
        "听读或朗读本课单词和句子。",
        "抄写并记住 3–5 个关键词。",
        "用本课句型说或写 2 个短句。",
        "标记不会读或不会用的词。",
    ]


def generate_plan_from_text(conn: Connection, raw_text: str, student_id: int = 1) -> dict[str, Any]:
    settings = get_settings(conn)
    if _is_dirty_question_text(raw_text):
        return {"created": 0, "items": [], "warnings": ["输入内容疑似编码损坏，已拒绝生成问号计划。请重新粘贴中文原文。"]}
    comprehensive_sources = _comprehensive_summer_sources(raw_text, settings)
    if comprehensive_sources:
        return _insert_sources(conn, comprehensive_sources, student_id)
    chunks = [chunk.strip() for chunk in re.split(r"[;\n；。]", raw_text) if chunk.strip()]
    if len(chunks) <= 1 and _looks_like_english_request(raw_text):
        chunks.insert(0, raw_text.strip())

    now = utc_now()
    created: list[dict[str, Any]] = []
    created_keys: set[tuple[str, str]] = set()
    for chunk in chunks:
        source = _source_from_chunk(chunk, settings)
        if not source:
            continue
        key = (source["category"], source["subject"], source["title"])
        if key in created_keys:
            continue
        if _source_already_exists(conn, student_id, source):
            continue
        created_keys.add(key)
        cursor = conn.execute(
            """
            INSERT INTO task_sources (
                student_id, category, title, subject, total_units, completed_units,
                deadline, config_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                student_id,
                source["category"],
                source["title"],
                source["subject"],
                source["total_units"],
                source["completed_units"],
                source["deadline"],
                dumps(source["config"]),
                now,
                now,
            ),
        )
        source["id"] = cursor.lastrowid
        created.append(source)
    return {"created": len(created), "items": created}


def _insert_sources(conn: Connection, sources: list[dict[str, Any]], student_id: int) -> dict[str, Any]:
    now = utc_now()
    created: list[dict[str, Any]] = []
    created_keys: set[tuple[str, str, str]] = set()
    for source in sources:
        if _is_dirty_question_text(source.get("title", "")):
            continue
        key = (source["category"], source.get("subject", ""), source["title"])
        if key in created_keys:
            continue
        if _source_already_exists(conn, student_id, source):
            continue
        created_keys.add(key)
        cursor = conn.execute(
            """
            INSERT INTO task_sources (
                student_id, category, title, subject, total_units, completed_units,
                deadline, config_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                student_id,
                source["category"],
                source["title"],
                source.get("subject", ""),
                max(int(source.get("total_units", 1)), 1),
                max(int(source.get("completed_units", 0)), 0),
                source.get("deadline") or _deadline(45),
                dumps(source.get("config", {})),
                now,
                now,
            ),
        )
        source["id"] = cursor.lastrowid
        created.append(source)
    return {"created": len(created), "items": created}


def _source_already_exists(conn: Connection, student_id: int, source: dict[str, Any]) -> bool:
    row = conn.execute(
        """
        SELECT 1 FROM task_sources
        WHERE student_id = ? AND status = 'active'
          AND category = ? AND subject = ? AND title = ?
        LIMIT 1
        """,
        (student_id, source["category"], source.get("subject", ""), source["title"]),
    ).fetchone()
    return row is not None


def _source_from_chunk(chunk: str, settings: dict[str, Any]) -> dict[str, Any] | None:
    lowered = chunk.lower()
    if "作业" in chunk or "作业本" in chunk or "homework" in lowered or "workbook" in lowered:
        return _homework_source(chunk)
    if _looks_like_subject_request(chunk, "语文", extra_keywords=("课文", "语文书")) or _looks_like_english_alias_request(lowered, ("chinese", "reading"), ("book", "textbook", "daily", "preview", "lesson")):
        return _book_source("语文", chunk, settings)
    if _looks_like_subject_request(chunk, "数学", extra_keywords=("一节", "数学书", "例题")) or _looks_like_english_alias_request(lowered, ("math", "mathematics"), ("book", "textbook", "daily", "preview", "lesson", "decimal")):
        return _book_source("数学", chunk, settings)
    if _looks_like_english_request(chunk):
        return _book_source("英语", chunk, settings)
    return None


def _comprehensive_summer_sources(text: str, settings: dict[str, Any]) -> list[dict[str, Any]]:
    if not all(keyword in text for keyword in ("KET", "暑假作业", "五年级上册")):
        return []
    deadline = _summer_deadline(text)
    sources: list[dict[str, Any]] = []
    sources.extend(
        [
            _fixed_homework("数学暑假作业本", "数学", 22, 3, 1, 25, "小节", deadline, "每天 1 小节，和口算/每日一练错开难度。"),
            _fixed_homework("数学口算", "数学", 29, 0, 1, 12, "页", deadline, "每天 1 页，限时但不抢速度，重点检查小数点。"),
            _fixed_homework("数学每日一练", "数学", 48, 0, 1, 18, "页", deadline, "每天 1 页，遇到应用题先画图再列式。"),
            _fixed_homework("英语暑假作业本", "英语", 14, 3, 1, 20, "Day", deadline, "每天 1 Day，完成后读 5 分钟重点句。"),
            _fixed_homework("诵读一夏", "语文", 12, 3, 1, 12, "个", deadline, "每天 1 个，先读准，再背关键句。"),
            _fixed_homework("妙笔一下", "语文", 37, 3, 4, 25, "个", deadline, "每天 4 个小练笔，重在完整表达，不追求长。"),
            _fixed_homework("一本", "语文", 7, 0, 1, 40, "组", deadline, "每天 1 组=2 篇阅读理解，先限时完成，再核对答案并圈出依据句。"),
        ]
    )
    sources.append(_reading_source(deadline))
    sources.append(_movie_source(deadline))
    sources.append(_sport_source(deadline))
    sources.append(_ket_source(deadline))
    chinese = _book_source("语文", "语文书每日一篇课文，前3课已学完", settings)
    chinese["completed_units"] = 3
    chinese["deadline"] = deadline
    chinese["config"].update(
        {
            "display_label": "语文预习",
            "estimated_minutes": 30,
            "daily_units": 1,
            "completed_note": "前 3 课已完成，暑假先复习前 3 课，再继续后续课文。",
            "study_steps": ["读课文", "圈生字词", "说主要内容", "背诵/积累", "做小练笔"],
        }
    )
    sources.append(chinese)
    math = _math_2026_preview_source(deadline)
    sources.append(math)
    english = _fltrp_english_source("英语五年级上册 Unit 1-6 暑假预习")
    english["deadline"] = deadline
    sources.append(english)
    return sources


def _fixed_homework(title: str, subject: str, total: int, completed: int, daily_units: int, minutes: int, unit_label: str, deadline: str, note: str) -> dict[str, Any]:
    return {
        "category": "summer_homework",
        "title": title,
        "subject": subject,
        "total_units": total,
        "completed_units": completed,
        "deadline": deadline,
        "config": {
            "display_label": "暑假作业",
            "estimated_minutes": minutes,
            "daily_units": daily_units,
            "pacing": f"每日 {daily_units} {unit_label}",
            "unit_label": unit_label,
            "lesson_content": note,
            "knowledge_points": "独立完成；检查订正；标记卡点",
            "study_steps": ["读清要求", "独立完成", "检查一遍", "标记不会的题"],
        },
    }


def _reading_source(deadline: str) -> dict[str, Any]:
    books = ["一千零一夜", "中国民间故事", "欧洲民间故事", "列那狐的故事", "非洲民间故事", "万物生灵：冯骥才给孩子的散文", "外婆"]
    return {
        "category": "summer_homework",
        "title": "语文阅读书目",
        "subject": "语文",
        "total_units": len(books),
        "completed_units": 0,
        "deadline": deadline,
        "config": {
            "display_label": "阅读",
            "estimated_minutes": 30,
            "daily_units": 1,
            "unit_label": "本",
            "lesson_sequence": books,
            "pacing": "按 7 本书分阶段推进，每天 20–30 分钟。",
            "lesson_content": "每天阅读并用 2 句话复述，读完一本做人物/情节卡。",
            "knowledge_points": "持续阅读；复述；人物情节；好词好句",
            "study_steps": ["安静阅读", "摘 1 句好句", "说 2 句内容", "记录一个问题"],
        },
    }


def _movie_source(deadline: str) -> dict[str, Any]:
    return {
        "category": "summer_homework",
        "title": "娱乐一下：《寻梦环游记》",
        "subject": "综合",
        "total_units": 1,
        "completed_units": 0,
        "deadline": deadline,
        "config": {
            "display_label": "放松",
            "estimated_minutes": 120,
            "daily_units": 1,
            "unit_label": "次",
            "pacing": "安排在周末或阶段任务完成后。",
            "lesson_content": "观看电影《寻梦环游记》，看完口头说最喜欢的人物和原因。",
            "knowledge_points": "放松；表达；亲子交流",
            "study_steps": ["完成当天核心任务", "观看电影", "说喜欢的角色", "家长简单交流"],
        },
    }


def _sport_source(deadline: str) -> dict[str, Any]:
    return {
        "category": "summer_homework",
        "title": "每日运动 1 小时",
        "subject": "体育",
        "total_units": 59,
        "completed_units": 0,
        "deadline": deadline,
        "config": {
            "display_label": "运动",
            "estimated_minutes": 60,
            "daily_units": 1,
            "unit_label": "天",
            "pacing": "每天 1 小时：跳绳 1 分钟 + 自选项目 + 拉伸。",
            "lesson_content": "适合小学四升五：跳绳、慢跑、球类、体能小游戏轮换。",
            "knowledge_points": "体能；协调；坚持",
            "study_steps": ["热身 5 分钟", "跳绳 1 分钟", "自选运动 45 分钟", "拉伸 10 分钟"],
        },
    }


def _ket_source(deadline: str) -> dict[str, Any]:
    return {
        "category": "ket",
        "title": "KET 暑假备考",
        "subject": "英语",
        "total_units": 48,
        "completed_units": 0,
        "deadline": deadline,
        "config": {
            "display_label": "KET",
            "module": "听说读写均衡训练",
            "estimated_minutes": 35,
            "daily_units": 1,
            "unit_label": "组",
            "pacing": "每天 30–40 分钟，不过量；每周一次小模拟。",
            "lesson_content": "听力保持优势；词汇 1500 基础上滚动复习；阅读稳步提升；写作重点补短板；口语每周 2–3 次短练。",
            "knowledge_points": "听力；阅读；写作；口语；词汇复习；模拟测试",
            "study_steps": ["复习 10 个词", "完成一项听/读训练", "写 3–5 句", "口头说 1 个话题"],
            "exam_time_note": "考试时间以官方报名通知为准；若 8–9 月考试，每周加一次模拟；若秋季后考试，暑假以基础巩固为主。",
        },
    }


def _math_2026_preview_source(deadline: str) -> dict[str, Any]:
    sequence = [
        "观察简单组合体：看图说位置，能画出从不同方向看到的形状",
        "小数乘法：理解算理，掌握竖式和积的小数位数",
        "小数除法：理解商的小数点位置，会验算",
        "图形的运动：平移、旋转和轴对称的观察与描述",
        "用字母表示数和数量关系：会用字母表示简单关系",
        "多边形的面积：平行四边形、三角形、梯形面积公式和应用",
        "有趣的密铺：观察图形拼铺规律，发展空间想象",
    ]
    return {
        "category": "preview",
        "title": "新版人教版五年级上册数学预习",
        "subject": "数学",
        "total_units": len(sequence),
        "completed_units": 0,
        "deadline": deadline,
        "config": {
            "display_label": "数学预习",
            "estimated_minutes": 35,
            "daily_units": 1,
            "unit_label": "节",
            "lesson_sequence": sequence,
            "lesson_content": "按新版人教版目录预习，重点是小数乘除法和多边形面积。",
            "knowledge_points": "观察组合体；小数乘法；小数除法；图形运动；字母表示数；多边形面积；密铺",
            "study_steps": ["看例题", "讲清算理", "做基础题", "做 1 道变式", "整理易错点"],
        },
    }


def _is_dirty_question_text(text: str) -> bool:
    stripped = (text or "").strip()
    if not stripped:
        return False
    question_count = stripped.count("?")
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    return question_count >= 6 and question_count >= max(6, len(stripped) * 0.45) and chinese_count == 0


def _looks_like_english_alias_request(lowered: str, subjects: tuple[str, ...], intent_words: tuple[str, ...]) -> bool:
    return any(subject in lowered for subject in subjects) and any(word in lowered for word in intent_words)


def _looks_like_subject_request(text: str, subject: str, extra_keywords: tuple[str, ...]) -> bool:
    if subject not in text:
        return False
    pacing_words = ("每日", "每天", "预习", "学习", "暑假", "寒假", "一篇", "一节", "一课")
    return any(word in text for word in pacing_words + extra_keywords)


def _looks_like_english_request(text: str) -> bool:
    if not any(keyword in text for keyword in ("英语", "English", "Unit", "外研社", "刘兆义")):
        return False
    return any(
        keyword in text
        for keyword in (
            "每日",
            "每天",
            "预习",
            "学习",
            "暑假",
            "一课",
            "课本",
            "音频",
            "默写",
            "字帖",
            "Unit",
        )
    )
