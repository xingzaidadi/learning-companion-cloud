from __future__ import annotations

import re
from sqlite3 import Connection
from typing import Any

from .agent_tools import (
    agent_runs,
    get_task,
    get_task_source,
    get_task_guidance,
    latest_mastery,
    log_agent_run,
    save_learning_plan,
    save_mastery_record,
    save_submissions,
    save_task_guidance,
)
from .ai_provider import call_ai_json_with_meta
from .db import loads
from .plan_generator import generate_plan_from_text
from .planner import generate_daily_tasks as rule_generate_daily_tasks
from .prompts import (
    COMMON_GUARDRAILS,
    DIAGNOSIS_PROMPT,
    GRADE_PROMPT,
    PLAN_PROMPT,
    QUIZ_PROMPT,
    REPORT_PROMPT,
    STUCK_ASSIST_PROMPT,
)
from .quiz import ensure_quiz_for_task, grade_quiz, regenerate_quiz_for_task
from .report import build_daily_report
from .review import create_review_item
from .settings import get_settings


def generate_study_plan(conn: Connection, raw_goal: str, student_id: int = 1) -> dict[str, Any]:
    settings = get_settings(conn)
    ai_plan, ai_meta = call_ai_json_with_meta(
        settings,
        PLAN_PROMPT.format(guardrails=COMMON_GUARDRAILS, goal=raw_goal),
        {},
    )
    rule_plan = generate_plan_from_text(conn, raw_goal, student_id)
    parsed = ai_plan if isinstance(ai_plan, dict) and ai_plan else {"rule_result": rule_plan}
    plan_id = save_learning_plan(conn, student_id, raw_goal, parsed)
    output = {"plan_id": plan_id, **rule_plan, "agent_parsed": parsed}
    log_agent_run(conn, student_id, "plan", {"goal": raw_goal}, output, ai_meta["model"], ai_meta["status"], ai_meta["error"])
    return output


def generate_daily_tasks(
    conn: Connection,
    student_id: int = 1,
    target_date: str | None = None,
    force_all_sources: bool = False,
) -> dict[str, Any]:
    tasks = rule_generate_daily_tasks(conn, student_id, target_date, force_all_sources=force_all_sources)
    for task in tasks:
        ensure_task_guidance(conn, task["id"])
    output = {"count": len(tasks), "tasks": tasks}
    log_agent_run(conn, student_id, "daily_tasks", {"target_date": target_date, "force_all_sources": force_all_sources}, output)
    return output


def ensure_task_guidance(conn: Connection, task_id: int) -> dict[str, Any]:
    existing = get_task_guidance(conn, task_id)
    if existing:
        return existing
    task = get_task(conn, task_id)
    if not task:
        return {"guidance": []}
    source = get_task_source(conn, task.get("source_id"))
    config = source.get("config", {}) if source else {}
    guidance = config.get("study_steps") or _fallback_guidance(task)
    save_task_guidance(conn, task_id, guidance, task.get("completion_standard", ""), "rule")
    output = {"task_id": task_id, "guidance": guidance, "completion_standard": task.get("completion_standard", "")}
    log_agent_run(conn, int(task["student_id"]), "task_guidance", {"task_id": task_id}, output)
    return output


def generate_quiz(conn: Connection, task_id: int, force: bool = False) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {"task_id": task_id, "items": []}
    items = regenerate_quiz_for_task(conn, task_id) if force else ensure_quiz_for_task(conn, task)
    output = {"task_id": task_id, "items": [_public_quiz_item(item) for item in items]}
    log_agent_run(conn, int(task["student_id"]), "quiz", {"task_id": task_id, "force": force}, output)
    return output


def grade_submission(conn: Connection, task_id: int, answers: dict[str, str]) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found", "wrong_items": []}
    if task.get("status") != "completed":
        save_submissions(conn, task_id, answers)
    rule_result = grade_quiz(conn, task_id, answers)
    diagnosis = diagnose_learning(conn, task_id, rule_result)
    output = {**rule_result, "diagnosis": diagnosis}
    log_agent_run(conn, int(task["student_id"]), "grade", {"task_id": task_id, "answers": answers}, output)
    return output


def assist_stuck(conn: Connection, task_id: int, note: str = "") -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {"task_id": task_id, "status": "not_found", "assistance": _fallback_stuck_assistance({}, None, note)}

    source = get_task_source(conn, task.get("source_id"))
    guidance = ensure_task_guidance(conn, task_id)
    fallback = _fallback_stuck_assistance(task, source, note)
    settings = get_settings(conn)
    if not note.strip():
        ai_result = fallback
        ai_meta = {"used_ai": False, "model": "rule", "status": "rule_fallback", "error": "blank stuck note"}
    else:
        ai_result, ai_meta = call_ai_json_with_meta(
            settings,
            STUCK_ASSIST_PROMPT.format(
                guardrails=COMMON_GUARDRAILS,
                stuck_context={
                    "task": task,
                    "source": source,
                    "existing_guidance": guidance,
                    "child_note": note,
                },
            ),
            fallback,
        )
    assistance = _normalize_stuck_assistance(ai_result if isinstance(ai_result, dict) else fallback, fallback)
    output = {
        "task_id": task_id,
        "task_title": task.get("title", ""),
        "child_note": note,
        "status": "assisted",
        "assistant_source": "ai" if ai_meta.get("used_ai") else "rule",
        "assistance": assistance,
        "review_action": f"已把“{assistance['review_focus']}”加入后续补漏和复测重点。",
    }
    log_agent_run(
        conn,
        int(task["student_id"]),
        "stuck_assist",
        {"task_id": task_id, "note": note},
        output,
        ai_meta["model"],
        ai_meta["status"],
        ai_meta["error"],
    )
    return output


def diagnose_learning(conn: Connection, task_id: int, quiz_result: dict[str, Any]) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        return {}
    source = get_task_source(conn, task.get("source_id"))
    subject = source.get("subject", "") if source else ""
    knowledge_point = _knowledge_point(source, task)
    score = quiz_result["correct"] / quiz_result["total"] if quiz_result.get("total") else 0
    fallback = _rule_diagnosis(score, quiz_result)
    settings = get_settings(conn)
    ai_result, ai_meta = call_ai_json_with_meta(
        settings,
        DIAGNOSIS_PROMPT.format(
            guardrails=COMMON_GUARDRAILS,
            learning_context={
                "task": task,
                "subject": subject,
                "knowledge_point": knowledge_point,
                "quiz_result": quiz_result,
            },
        ),
        fallback,
    )
    result = ai_result if isinstance(ai_result, dict) and ai_result else fallback
    save_mastery_record(
        conn,
        int(task["student_id"]),
        task_id,
        subject,
        knowledge_point,
        result.get("mastery_level", fallback["mastery_level"]),
        float(score),
        result.get("diagnosis", fallback["diagnosis"]),
        result.get("next_action", fallback["next_action"]),
    )
    if result.get("mastery_level") in ("C", "D"):
        create_review_item(
            conn,
            int(task["student_id"]),
            task_id,
            task["title"],
            task.get("completion_standard", ""),
            result.get("diagnosis", ""),
            "mastery_low",
            1,
        )
    log_agent_run(
        conn,
        int(task["student_id"]),
        "diagnose",
        {"task_id": task_id, "quiz_result": quiz_result},
        result,
        ai_meta["model"],
        ai_meta["status"],
        ai_meta["error"],
    )
    return result


def generate_daily_report(conn: Connection, student_id: int = 1, target_date: str | None = None) -> dict[str, Any]:
    report = build_daily_report(conn, student_id, target_date)
    mastery = latest_mastery(conn, student_id, 10)
    settings = get_settings(conn)
    ai_report, ai_meta = call_ai_json_with_meta(
        settings,
        REPORT_PROMPT.format(guardrails=COMMON_GUARDRAILS, report_context={"report": report, "mastery": mastery}),
        {},
    )
    if isinstance(ai_report, dict) and ai_report:
        report.update({key: ai_report[key] for key in ("summary", "problems", "tomorrow_first_step") if key in ai_report})
    log_agent_run(conn, student_id, "daily_report", {"target_date": target_date}, report, ai_meta["model"], ai_meta["status"], ai_meta["error"])
    return report


def get_agent_overview(conn: Connection, student_id: int = 1) -> dict[str, Any]:
    return {"mastery": latest_mastery(conn, student_id, 20), "runs": agent_runs(conn, student_id, 30)}


def _fallback_guidance(task: dict[str, Any]) -> list[str]:
    title = task.get("title", "")
    if "语文" in title:
        return ["通读课文", "圈出生字词", "概括主要内容", "找关键句说明理由"]
    if "数学" in title:
        return ["看例题", "讲清步骤", "做基础题", "整理易错点"]
    if "英语" in title or "KET" in title:
        return ["听读单词句子", "记 3-5 个关键词", "用句型造句", "标记不会的词"]
    return ["读清要求", "独立完成", "检查一遍", "标记卡点"]


def _public_quiz_item(item: dict[str, Any]) -> dict[str, Any]:
    data = dict(item)
    data["options"] = loads(data.pop("options_json", "[]"), [])
    data.pop("answer", None)
    data.pop("explanation", None)
    return data


def _rule_diagnosis(score: float, quiz_result: dict[str, Any]) -> dict[str, Any]:
    if score >= 0.9:
        level = "A"
        next_action = "明天可以继续新课。"
        diagnosis = "掌握较好，能继续推进。"
    elif score >= 0.8:
        level = "B"
        next_action = "明天先短复习 10 分钟，再继续新课。"
        diagnosis = "基本掌握，但还需要巩固表达或步骤。"
    elif score >= 0.6:
        level = "C"
        next_action = "明天先补当前知识点，暂缓新课。"
        diagnosis = "部分掌握，存在明显薄弱点。"
    else:
        level = "D"
        next_action = "需要家长介入，先重讲再练。"
        diagnosis = "当前任务未掌握，需要帮助。"
    if quiz_result.get("wrong_items"):
        diagnosis += f" 错题/问题 {len(quiz_result['wrong_items'])} 个。"
    return {
        "mastery_level": level,
        "diagnosis": diagnosis,
        "next_action": next_action,
        "parent_attention": "help" if level == "D" else "watch" if level == "C" else "none",
        "new_task_allowed": level in ("A", "B"),
    }


def _fallback_stuck_assistance(task: dict[str, Any], source: dict[str, Any] | None, note: str) -> dict[str, str]:
    subject = (source or {}).get("subject") or task.get("subject") or "这项内容"
    title = task.get("title") or "当前任务"
    standard = task.get("completion_standard") or task.get("description") or "完成本任务的核心要求"
    blocker = note.strip()
    if not blocker:
        return _blank_stuck_help(subject, title, standard)
    targeted = _targeted_stuck_help(subject, blocker, title)
    if targeted:
        return targeted
    return {
        "encouragement": "按下面 3 步做，不用再猜。",
        "likely_blocker": f"你说的卡点是：{blocker}。",
        "hint_1": _direct_solution_for_subject(subject, blocker, title, standard),
        "guiding_question": "做完第 1 步后，如果还不会，把卡住的那个词/句/算式原样发出来。",
        "mini_example": _mini_example_for_subject(subject),
        "try_again": "现在只执行第 1 步，完成后再点“我做完了，开始检查”。",
        "if_still_stuck": "不要耗着；把具体卡点补充清楚，系统继续给下一步。",
        "review_focus": _review_focus_for_subject(subject, blocker),
        "parent_note": "孩子已触发卡住辅导；建议先让孩子说题目要求和第一步，不要直接讲完整答案。",
    }


def _blank_stuck_help(subject: str, title: str, standard: str) -> dict[str, str]:
    if "英语" in subject or any(word.lower() in title.lower() for word in ("unit", "school", "english")):
        likely = "你还没有写具体卡点。先判断是：不会读单词、听不懂音频、看不懂句子，还是不知道要交什么。"
        hint = "这项英语任务先只做第一步：听或朗读 1 分钟，圈出 1 个不会读的词，不要一次想做完整个任务。"
        question = "你现在最卡的是哪一个词或哪一句？如果是单词，直接写：不会读 school。"
        example = "例如卡在 library，就先做三件事：读 library，知道它是“图书馆”，再放回句子 There is a library."
        retry = "现在先圈出一个不会读/不会拼的词，写到卡住输入框里；如果没有，就读完第一段再点完成检查。"
        focus = "英语具体卡点：单词读音、词义或句型"
    elif "数学" in subject:
        likely = "你还没有写具体卡点。数学通常卡在：不知道第一步、列式不清、计算出错、小数点或单位。"
        hint = "先只写两行：已知条件是什么？问题要求什么？暂时不要急着算。"
        question = "你卡在列式、计算，还是小数点/单位？可以写：不知道第一步怎么做。"
        example = "例如 2.4×3，先写单价 2.4 元、数量 3 支，再列式 2.4×3。"
        retry = "现在先把题里的数字和问题圈出来，再写一个算式。"
        focus = "数学具体卡点：审题、列式、计算或单位"
    elif "语文" in subject:
        likely = "你还没有写具体卡点。语文通常卡在：不认识字、不懂词、不懂句子、不会概括或不会仿写。"
        hint = "先只做一件事：回到课文或任务要求，圈出你不认识的字词或最不懂的一句话。"
        question = "你具体卡在哪个字、词或句子？可以写：不认识鹭这个字。"
        example = "例如卡在“鹭”，就先查读音 lù，再看它和“白鹭”这个词连在一起。"
        retry = "现在先圈一个具体字词或一句话，再重新点卡住并写清楚。"
        focus = "语文具体卡点：字词、句子理解或概括表达"
    else:
        likely = "你还没有写具体卡点。现在系统只能先帮你拆任务要求，不能准确判断是哪一步不会。"
        hint = f"先对照完成标准：“{standard}”，圈出要交付的结果。"
        question = "你卡在看不懂要求、不会第一步，还是做完不知道对不对？"
        example = "先把任务拆成：看懂要求、完成第一步、检查答案。"
        retry = "现在先写一句：我卡在____。"
        focus = "任务要求和第一步执行"
    return {
        "encouragement": "先别看长说明，只做下面这一步。",
        "likely_blocker": "你还没写具体问题，所以我不能直接判断答案。",
        "hint_1": f"{hint} {question}",
        "guiding_question": question,
        "mini_example": example,
        "try_again": retry,
        "if_still_stuck": "下一次点卡住时，只写一个具体点：不会读哪个词、不会哪一步、哪个字不认识。",
        "review_focus": focus,
        "parent_note": f"孩子在《{title}》点了卡住但未写具体问题，建议先追问卡在哪个字、词、句、步骤或单词。",
    }


def _direct_solution_for_subject(subject: str, blocker: str, title: str, standard: str) -> str:
    lower = blocker.lower()
    if "英语" in subject or any(key in lower for key in ("school", "word", "unit", "读", "拼", "记")):
        if "记" in blocker or "背" in blocker:
            return "1. 把这个词抄 3 遍；2. 盖住英文，看中文写 1 遍；3. 放进句子读 1 遍。"
        if "读" in blocker or "不会读" in blocker:
            return "1. 先把不会读的单词单独圈出来；2. 看音节或跟读 3 遍；3. 放回原句再读 1 遍。"
        return "1. 找出这句里的关键词；2. 先翻译主语和动词；3. 再补地点/形容词。"
    if "数学" in subject:
        if "小数点" in blocker:
            return "1. 先按整数算；2. 数小数因数有几位小数；3. 在积里从右往左点同样位数。"
        if "第一步" in blocker or "列式" in blocker:
            return "1. 圈已知条件；2. 圈问题要求；3. 写出关系式，不急着算。"
        return "1. 重写题目数字；2. 写算式；3. 算完检查小数点和单位。"
    if "语文" in subject:
        if "不认识" in blocker or "怎么读" in blocker:
            return "1. 圈出生字；2. 查/写拼音；3. 用这个字组一个课文里的词。"
        if "概括" in blocker:
            return "1. 找谁/什么；2. 找做了什么；3. 加上表达的情感或道理。"
        return "1. 回到课文找原句；2. 圈关键词；3. 用自己的话说这一句什么意思。"
    return f"1. 对照完成标准：{standard}；2. 只做第一步；3. 做完再检查。"


def _targeted_stuck_help(subject: str, blocker: str, title: str) -> dict[str, str] | None:
    char = _extract_unknown_char(blocker)
    if char:
        return _unknown_char_help(char, title)
    word = _extract_unknown_word(blocker)
    if word:
        return {
            "encouragement": "这个问题问得很好，不认识词先解决读音和意思，再继续做任务。",
            "likely_blocker": f"你卡在“{word}”这个词，不是整项任务都不会。",
            "hint_1": f"1. 圈出“{word}”；2. 查读音和意思；3. 放回原句，用自己的话说这一句。",
            "guiding_question": f"“{word}”前后一句是在写景、写人，还是写要完成的动作？",
            "mini_example": "遇到不会的词，可以按“读音—意思—放回句子”三步处理。",
            "try_again": f"现在先查清“{word}”的读音和意思，再用自己的话说一遍这一句。",
            "if_still_stuck": "如果还是不懂，把包含这个词的完整句子再发出来，系统会按这句话继续拆。",
            "review_focus": f"词语理解：{word}",
            "parent_note": "孩子卡在词语理解，建议先让孩子读出词、说大概意思，再回到原句理解。",
        }
    if "题目" in blocker or "要求" in blocker or "不知道做什么" in blocker:
        return {
            "encouragement": "不是不会做，是题目要求还没拆开。先把要求翻译成自己的话。",
            "likely_blocker": "你卡在任务要求：不知道先做哪一步。",
            "hint_1": f"1. 只看任务名《{title}》；2. 圈动词：读/圈/概括/说明；3. 先完成第一个动词。",
            "guiding_question": "这项任务最后要你交出什么：一句话、几道题、一个解释，还是一段复述？",
            "mini_example": "比如“概括主要内容”不是背全文，而是说清：谁/什么，怎么样，表达了什么。",
            "try_again": "现在只写第一步：我今天要先完成____。",
            "if_still_stuck": "如果还不清楚，把任务卡上的一句要求原样发出来，再继续拆。",
            "review_focus": "任务要求拆解",
            "parent_note": "孩子卡在理解任务要求，先让孩子圈动词，不要直接代做。",
        }
    return None


def _extract_unknown_char(blocker: str) -> str:
    patterns = (
        r"不认识\s*([\u4e00-\u9fff])\s*(?:这个)?(?:字|生字)?",
        r"([\u4e00-\u9fff])\s*(?:这个)?字\s*(?:不认识|不会读|怎么读)",
        r"([\u4e00-\u9fff])\s*怎么读",
    )
    for pattern in patterns:
        match = re.search(pattern, blocker)
        if match:
            return match.group(1)
    return ""


def _extract_unknown_word(blocker: str) -> str:
    match = re.search(r"不懂\s*“?([\u4e00-\u9fff]{2,6})”?|不认识\s*“?([\u4e00-\u9fff]{2,6})”?", blocker)
    if not match:
        return ""
    return next((group for group in match.groups() if group), "")


def _unknown_char_help(char: str, title: str) -> dict[str, str]:
    known_chars = {
        "鹭": {
            "pinyin": "lù",
            "meaning": "一种水鸟，常见词是“白鹭”。",
            "memory": "左边“路”提示读音，右边“鸟”提示它和鸟有关。",
            "words": "白鹭、鹭鸶",
        }
    }
    info = known_chars.get(
        char,
        {
            "pinyin": "先查字典或课本注音",
            "meaning": "先看它在课文句子里表示人、物、动作还是样子。",
            "memory": "可以拆偏旁，先看形旁，再看声旁。",
            "words": f"{char}所在的课文词语",
        },
    )
    return {
        "encouragement": "直接按下面步骤做。",
        "likely_blocker": f"你卡在生字“{char}”：读音是 {info['pinyin']}；意思：{info['meaning']}",
        "hint_1": f"1. 在课文里圈出“{char}”；2. 旁边写拼音 {info['pinyin']}；3. 读“{info['words'].split('、')[0]}”三遍。",
        "guiding_question": f"“{char}”在课文里和哪个词连在一起？它是在写一种事物，还是写动作/样子？",
        "mini_example": f"同类例子：{info['words']}。先会读，再放回原句理解。",
        "try_again": f"现在读三遍：{char}，再用“{info['words'].split('、')[0]}”说一句话。",
        "if_still_stuck": "如果还是不会，把这个字所在的完整句子发出来，再按句子继续拆。",
        "review_focus": f"生字认读：{char}",
        "parent_note": f"孩子卡在生字“{char}”，先帮他确认读音和词义，再回到课文原句。",
    }


def _normalize_stuck_assistance(result: dict[str, Any], fallback: dict[str, str]) -> dict[str, str]:
    keys = (
        "encouragement",
        "likely_blocker",
        "hint_1",
        "guiding_question",
        "mini_example",
        "try_again",
        "if_still_stuck",
        "review_focus",
        "parent_note",
    )
    normalized: dict[str, str] = {}
    for key in keys:
        value = result.get(key) if isinstance(result, dict) else ""
        normalized[key] = str(value).strip() if value else fallback[key]
    return normalized


def _mini_example_for_subject(subject: str) -> str:
    if "数学" in subject:
        return "数学可以先用更小的数试一遍：先写已知条件，再写要求什么，最后列式。"
    if "英语" in subject:
        return "英语可以先找关键词：谁做了什么、时间在哪里、题目要选意思还是拼写。"
    if "语文" in subject:
        return "语文可以先读题干，圈出关键词，再回到课文里找对应句子。"
    return "先把任务拆成“看懂要求、完成第一步、检查答案”三个小步骤。"


def _review_focus_for_subject(subject: str, blocker: str) -> str:
    if "数学" in subject:
        return "数学审题、数量关系和第一步列式"
    if "英语" in subject:
        return "英语关键词、句意理解和基础表达"
    if "语文" in subject:
        return "语文题干理解、课文定位和表达完整性"
    return blocker if blocker and blocker != "还没有说清楚卡在哪一步" else "任务理解和第一步执行"


def _knowledge_point(source: dict[str, Any] | None, task: dict[str, Any]) -> str:
    if source:
        config = source.get("config", {})
        return config.get("topic") or config.get("knowledge_points") or source.get("title", "")
    return task.get("title", "")


def _model_name(settings: dict[str, Any]) -> str:
    ai = settings.get("ai", {})
    return ai.get("model") or "rule"
