from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .curriculum import find_curriculum_context
from .db import dumps


CHINESE_WORD_BANK: dict[str, dict[str, Any]] = {
    "白鹭": {
        "words": ["白鹭", "精巧", "适宜", "寻常", "美中不足"],
        "chars": {"鹭": "lù", "宜": "yí", "嫌": "xián", "嵌": "qiàn", "匣": "xiá"},
        "sentence": "为什么说“白鹭是一首精巧的诗”？",
        "understand_answer": "抓住白鹭外形、色素、身段和生活画面的美来理解。",
        "summary_answer": "课文从外形和生活画面写出白鹭的精巧、自然与诗意。",
        "expression": "仿照课文，用一句话写一种动物的外形特点。",
    },
    "落花生": {
        "words": ["播种", "浇水", "吩咐", "爱慕", "体面"],
        "chars": {"亩": "mǔ", "吩": "fēn", "咐": "fù", "慕": "mù", "榨": "zhà"},
        "sentence": "父亲为什么拿花生和桃子、石榴、苹果作比较？",
        "understand_answer": "通过对比说明做人要像花生一样有用，不只讲体面。",
        "summary_answer": "课文借落花生告诉我们做人要做有用的人。",
        "expression": "用一种事物写一句说明做人道理的话。",
    },
    "桂花雨": {
        "words": ["懂得", "糕饼", "茶叶", "沉浸", "缠着"],
        "chars": {"箩": "luó", "杭": "háng", "缠": "chán", "浸": "jìn"},
        "sentence": "为什么母亲说这里的桂花再香，也比不上家乡院子里的桂花？",
        "understand_answer": "因为桂花承载着母亲和作者对家乡的思念。",
        "summary_answer": "课文写摇桂花的快乐，表达对童年和故乡的怀念。",
        "expression": "写一句带有家乡或童年回忆的句子。",
    },
    "珍珠鸟": {
        "words": ["繁茂", "隐约", "蓬松", "陪伴", "信赖"],
        "chars": {"蔓": "màn", "睑": "jiǎn", "眸": "móu", "咂": "zā"},
        "sentence": "“信赖，往往创造出美好的境界”是什么意思？",
        "understand_answer": "人与动物彼此信任，才能形成亲近和谐的关系。",
        "summary_answer": "课文写珍珠鸟逐渐亲近作者，表现信赖带来的美好。",
        "expression": "写一句人与动物友好相处的句子。",
    },
}


CHINESE_WORD_MEANINGS: dict[str, str] = {
    "精巧": "精致巧妙，形容白鹭外形匀称好看。",
    "适宜": "合适、恰当。",
    "寻常": "平常、普通。",
    "美中不足": "很好里面还有一点不够完美。",
    "吩咐": "口头指派或嘱咐别人做事。",
    "爱慕": "喜爱羡慕。",
    "体面": "外表或身份上好看、有面子。",
    "沉浸": "完全处在某种情境或感受里。",
    "缠着": "围着不放，反复要求或依附。",
    "信赖": "相信并依靠。",
}


ENGLISH_WORD_BANK: dict[str, list[tuple[str, str]]] = {
    "school": [("school", "学校"), ("library", "图书馆"), ("classroom", "教室"), ("playground", "操场"), ("cool", "酷的/很棒的")],
    "activities": [("activity", "活动"), ("festival", "节日"), ("fun", "有趣的"), ("game", "游戏"), ("club", "社团")],
    "ice": [("ice", "冰"), ("world", "世界"), ("polar", "极地的"), ("ocean", "海洋"), ("animal", "动物")],
    "sea": [("sea", "海"), ("plastic", "塑料"), ("rubbish", "垃圾"), ("poster", "海报"), ("dirty", "脏的")],
    "work": [("detective", "侦探"), ("problem", "问题"), ("answer", "答案"), ("key", "钥匙/关键"), ("must", "必须")],
    "days": [("mooncake", "月饼"), ("celebrate", "庆祝"), ("lunar", "农历的"), ("festival", "节日"), ("ago", "以前")],
}


def _item(question_type: str, question: str, answer: str, explanation: str, options: list[str] | None = None) -> dict[str, Any]:
    data: dict[str, Any] = {
        "question_type": question_type,
        "question": question,
        "answer": answer,
        "explanation": explanation,
    }
    if options is not None:
        data["options_json"] = dumps(options)
    return data


def _choice(question: str, options: list[str], answer: str, explanation: str, question_type: str = "choice") -> dict[str, Any]:
    return _item(question_type, question, answer, explanation, options)


def _exact(question: str, answer: str, explanation: str, question_type: str = "exact") -> dict[str, Any]:
    return _item(question_type, question, answer, explanation)


def _short(question: str, answer: str, explanation: str, question_type: str = "short") -> dict[str, Any]:
    return _item(question_type, question, answer, explanation)


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", "", value.lower())


def _format_decimal(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _decimal_mul(a: str, b: str) -> str:
    return _format_decimal(Decimal(a) * Decimal(b))


def _decimal_div(a: str, b: str) -> str:
    return _format_decimal(Decimal(a) / Decimal(b))


def _split_values(text: str) -> list[str]:
    values: list[str] = []
    for raw in re.split(r"[\n,，;；、|/]+", text or ""):
        value = raw.strip(" ：:=\t")
        if value and value not in values:
            values.append(value)
    return values


def _chinese_words_from_content(content: str) -> list[str]:
    candidates: list[str] = []
    for line in (content or "").splitlines():
        if any(key in line for key in ("听写词", "生字词", "词语", "字词")):
            _, _, tail = line.partition("：")
            if not tail:
                _, _, tail = line.partition(":")
            candidates.extend(_split_values(tail or line))
    return [word for word in candidates if re.search(r"[\u4e00-\u9fff]", word) and 1 <= len(word) <= 8]


def _vocab_pairs(config: dict[str, Any], content: str) -> list[tuple[str, str]]:
    vocab_text = "\n".join(str(value) for value in (config.get("vocabulary", ""), config.get("lesson_content", ""), content) if value)
    pairs: list[tuple[str, str]] = []
    for raw in re.split(r"[\n,，;；]+", vocab_text):
        part = raw.strip()
        if not part:
            continue
        left = right = ""
        for sep in ("=", "：", ":"):
            if sep in part:
                left, right = [value.strip() for value in part.split(sep, 1)]
                break
        if left and right and re.search(r"[A-Za-z]", left):
            pairs.append((left, right))
        elif left and right and re.search(r"[A-Za-z]", right):
            pairs.append((right, left))
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for english, chinese in pairs:
        english = english.strip()
        chinese = chinese.strip()
        if len(english) > 30 or len(chinese) > 16 or len(re.findall(r"[A-Za-z]+", english)) > 4:
            continue
        if not re.search(r"[\u4e00-\u9fff]", chinese):
            continue
        key = english.lower()
        if key not in seen:
            unique.append((english, chinese))
            seen.add(key)
    return unique


def _guess_chinese_lesson(topic: str, content: str, version: str | None) -> tuple[str, dict[str, Any]]:
    text = topic + "\n" + content
    for lesson, data in CHINESE_WORD_BANK.items():
        if lesson in text:
            return lesson, data
    context = find_curriculum_context("chinese", text, version)
    lesson = ""
    if context:
        lesson = next((name for name in context.get("lessons", []) if name in text), "") or str(context.get("lessons", ["课文"])[0])
    lesson = lesson or topic or "五年级语文课文"
    return lesson, CHINESE_WORD_BANK.get(lesson, CHINESE_WORD_BANK["白鹭"])


def _build_chinese_quiz(topic: str, content: str, config: dict[str, Any], version: str | None) -> list[dict[str, Any]]:
    lesson, bank = _guess_chinese_lesson(topic, content, version)
    configured_words = _split_values(str(config.get("dictation_words", "") or config.get("vocabulary", ""))) or _chinese_words_from_content(content)
    words = configured_words or list(bank["words"])
    chars: dict[str, str] = dict(bank["chars"])
    if config.get("new_chars") and isinstance(config["new_chars"], dict):
        chars.update({str(key): str(value) for key, value in config["new_chars"].items()})
    first_word = words[0]
    first_char, first_pinyin = next(iter(chars.items()))
    explain_word = words[1] if len(words) > 1 else first_word
    explain_answer = CHINESE_WORD_MEANINGS.get(explain_word, "能结合课文语境说出词语大意")
    return [
        _exact(
            "听写：请家长读第 1 个听写词，孩子输入听到的词语。（题目不显示答案）",
            first_word,
            "听写题重点检查字形，必须写成课本词语。",
            "chinese_word_dictation",
        ),
        _exact(
            f"拼音：生字「{first_char}」的读音是什么？",
            first_pinyin,
            f"「{first_char}」读作 {first_pinyin}，拼音题可以写带声调或数字声调。",
            "chinese_pinyin",
        ),
        _short(
            f"组词：用生字「{first_char}」组一个课内相关词语。",
            first_word if first_char in first_word else first_char,
            "组词要含有指定生字，尽量使用课本词语。",
            "chinese_char_group",
        ),
        _short(
            f"词义：请解释「{explain_word}」的大概意思。",
            explain_answer,
            "答案需说明词语基本意思，并能结合课文语境说出作用。",
            "chinese_word_explain",
        ),
        _short(
            bank["sentence"],
            bank["understand_answer"],
            f"理解题要回到《{lesson}》的关键语句和表达方法。",
            "chinese_sentence_understand",
        ),
        _short(
            f"概括：《{lesson}》主要写了什么？",
            bank["summary_answer"],
            "概括要说清对象、事情和表达的情感或道理。",
            "chinese_summary",
        ),
        _short(
            str(bank["expression"]),
            "能围绕题目要求写出一句内容完整、意思清楚的句子",
            "表达题看是否围绕观察点写完整句子，不要求华丽。",
            "chinese_expression",
        ),
    ]


def _guess_english_pairs(topic: str, content: str, config: dict[str, Any], version: str | None) -> tuple[str, list[tuple[str, str]]]:
    pairs = _vocab_pairs(config, content)
    if pairs:
        return topic or "English words", pairs
    text = (topic + "\n" + content).lower()
    context = find_curriculum_context("english", text, version)
    unit = context["unit"] if context else topic or "Unit 1"
    for key, values in ENGLISH_WORD_BANK.items():
        if key in text or key in unit.lower():
            return unit, values
    if "unit 2" in text:
        return unit, ENGLISH_WORD_BANK["activities"]
    if "unit 3" in text:
        return unit, ENGLISH_WORD_BANK["ice"]
    if "unit 4" in text:
        return unit, ENGLISH_WORD_BANK["sea"]
    if "unit 5" in text:
        return unit, ENGLISH_WORD_BANK["work"]
    if "unit 6" in text:
        return unit, ENGLISH_WORD_BANK["days"]
    return unit, ENGLISH_WORD_BANK["school"]


def _build_english_quiz(topic: str, content: str, config: dict[str, Any], version: str | None) -> list[dict[str, Any]]:
    unit, pairs = _guess_english_pairs(topic, content, config, version)
    while len(pairs) < 5:
        pairs = pairs + ENGLISH_WORD_BANK["school"]
    word1, cn1 = pairs[0]
    word2, cn2 = pairs[1]
    word3, cn3 = pairs[2]
    protected_words = {word1.lower(), word2.lower(), word3.lower()}
    sentence_noun = next(
        (
            candidate
            for candidate in ("desk", "book", "map", "door", "window", "bag")
            if candidate.lower() not in protected_words
        ),
        "desk",
    )
    return [
        _exact(f"中译英：{cn1}", word1, f"{cn1} = {word1}", "english_word_cn_to_en"),
        _exact(f"英译中：{word2}", cn2, f"{word2} = {cn2}", "english_word_en_to_cn"),
        _exact(f"默写：请家长读中文「{cn3}」，孩子写英文单词。", word3, "默写单词忽略大小写，但不能漏字母。", "english_spelling"),
        _short(
            f"句型填空：There ___ a {sentence_noun} here.",
            "is",
            "There is + 单数名词；There are + 复数名词。",
            "english_sentence_fill",
        ),
        _short(
            "翻译：我的学校很棒。",
            "My school is cool.",
            "中译英重点检查核心词和基本句型，标点可宽松。",
            "english_translation",
        ),
        _short(
            "造句：写一个介绍学校的完整英文句子。",
            "My school is cool.",
            "造句要有主语、be 动词和描述词。",
            "english_sentence_make",
        ),
        _short(
            "课文理解：这一节主要介绍什么？",
            "school",
            "答案需包含单元主题或课文关键信息，不能只写一个孤立单词。",
            "english_reading_check",
        ),
    ]


def _build_ket_quiz(topic: str, content: str, config: dict[str, Any]) -> list[dict[str, Any]]:
    normalized = _normalize_text(f"{topic} {content} {config.get('module', '')}")
    if any(key in normalized for key in ("听力", "听", "listening", "跟读")):
        return [
            _short("听力复盘：写出今天材料里的 2 个关键词。", "关键词", "听力不是逐词听懂，先抓场景和关键词。", "english_reading_check"),
            _choice("KET 听力没听清一处时，最合适的做法是？", ["停住想刚才那句", "继续听后面的关键词", "直接放弃"], "继续听后面的关键词", "考试中要跟上录音节奏。", "choice"),
            _short("跟读检查：写出或说出你今天跟读最顺的一句英文。", "完整英文句子", "句子要完整，能读清楚更重要。", "english_sentence_make"),
        ]
    if any(key in normalized for key in ("阅读", "读", "reading")):
        return [
            _short("阅读定位：写出 1 个答案来自原文哪一句或哪几个词。", "原文依据", "KET 阅读要训练定位依据，而不是只凭感觉。", "english_reading_check"),
            _choice("做 KET 阅读题时，先看什么更稳？", ["先看题干关键词", "直接背全文", "只看选项最长的"], "先看题干关键词", "先找关键词，再回原文定位。", "choice"),
            _short("词汇复盘：写出今天阅读里 2 个需要复习的词。", "写出词汇", "词汇要回到语境里复习。", "english_word_en_to_cn"),
        ]
    if any(key in normalized for key in ("写作", "写", "writing")):
        return [
            _short("写作检查：写出今天最满意的一句英文。", "完整英文句子", "检查主语、动词、单复数和标点。", "english_sentence_make"),
            _choice("KET 写作短句最先保证什么？", ["句子完整", "词越难越好", "越长越好"], "句子完整", "小学阶段先保证完整、准确、清楚。", "choice"),
            _short("请用 because 或 also 写一个补充句。", "完整英文句子", "进阶孩子可以练习连接词，让表达更完整。", "english_sentence_make"),
        ]
    if any(key in normalized for key in ("口语", "口头", "speaking", "话题")):
        return [
            _short("口语话题：写出今天你回答的话题。", "写出主题", "先明确话题，再组织句子。", "english_reading_check"),
            _short("写出一句你可以直接说出口的完整英文回答。", "完整英文句子", "口语回答要用完整句，声音清楚。", "english_sentence_make"),
            _choice("KET 口语回答更应该像哪一种？", ["只说一个词", "完整句 + 一个理由", "完全背中文"], "完整句 + 一个理由", "能补充理由，表达会更自然。", "choice"),
        ]
    if any(key in normalized for key in ("模拟", "周测", "mock")):
        return [
            _short("周测复盘：写出今天错得最多的一类题。", "错题类型", "模拟的价值在复盘，不是只看分数。", "english_reading_check"),
            _short("写出 2 个要进入下周复习的错词。", "写出错词", "错词需要滚动复习。", "english_spelling"),
            _choice("小模拟后最重要的一步是？", ["马上做下一套", "整理错因和错词", "只看总分"], "整理错因和错词", "错因会决定次日补救任务。", "choice"),
        ]
    return [
        _short("词汇复盘：写出今天记住的 5 个 KET 单词。", "写出单词", "标准/进阶模式可以从 3 个提高到 5 个。", "english_spelling"),
        _short("任选 1 个词写一个英文短句。", "完整英文句子", "短句要完整、自然。", "english_sentence_make"),
        _choice("KET 备考最稳的方式是？", ["每天短练并复盘", "一次背很多不复习", "只刷题不整理"], "每天短练并复盘", "持续短练 + 错题复盘更适合孩子。", "choice"),
    ]


def _math_decimal_items(content: str, topic: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(content + topic)
    wants_mul = any(key in normalized for key in ("小数乘", "乘法", "乘整数", "小数乘整数"))
    wants_div = any(key in normalized for key in ("小数除", "除法", "除以整数", "小数除以整数"))
    if "乘除" in normalized:
        wants_mul = True
        wants_div = True
    if not wants_mul and not wants_div and "小数" not in normalized:
        return []
    if wants_div and not wants_mul:
        exact_q = ("两步计算：18.9 ÷ 3 + 2.75 = ?", "9.05", "先算 18.9÷3=6.3，再算 6.3+2.75=9.05。")
        word_problem = ("应用题：一根 24.6 米的绳子平均剪成 6 段，每段再剪去 0.35 米，剩下每段多少米？", "3.75", "24.6÷6=4.1 米，4.1-0.35=3.75 米。")
        concept = _choice("小数除法验算时，下面哪一步最稳？", ["商×除数，看是否等于被除数", "只看答案像不像", "把小数点都去掉"], "商×除数，看是否等于被除数", "除法可用乘法验算，小数点也要对应检查。", "math_concept_choice")
    else:
        exact_q = ("两步计算：3.6 × 8 - 4.75 = ?", "24.05", "先算 3.6×8=28.8，再算 28.8-4.75=24.05。")
        word_problem = ("应用题：每本练习册 7.8 元，买 5 本后用 50 元付款，应找回多少元？", "11", "总价 7.8×5=39 元，50-39=11 元。")
        concept = _choice("估算判断：4.9×7 的结果最接近下面哪一个？", ["3.5", "35", "350"], "35", "4.9 接近 5，5×7=35，可先用估算判断数量级。", "math_concept_choice")
    return [
        _exact(exact_q[0], exact_q[1], exact_q[2], "math_exact"),
        concept,
        _short(f"步骤说明：请说清楚今天「{topic or '小数计算'}」怎样先估算、再精算并验算。", "先估算数量级，再按步骤计算，最后用逆运算或估算检查", "进阶题不只要算对，还要能说明检查方法。", "math_step_explain"),
        _exact(word_problem[0], word_problem[1], word_problem[2], "math_word_problem"),
        _choice("错因判断：把 2.4×15 算成 3.60，主要错在哪里？", ["小数点位置错", "单位错", "题目读错"], "小数点位置错", "24×15=360，但 2.4 只有一位小数，所以结果是 36。", "math_error_reason"),
        _exact("同类变式：6.25 × 4 - 3.8 = ?", "21.2", "6.25×4=25，25-3.8=21.2。", "math_variant"),
    ]


def _math_factor_items(content: str, topic: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(content + topic)
    if not any(key in normalized for key in ("因数", "倍数", "质数", "合数")):
        return []
    return [
        _choice("概念选择：一个数既是 6 的倍数，又是 8 的倍数，下面最小的是？", ["24", "36", "48"], "24", "同时是 6 和 8 的倍数，最小公倍数是 24。", "math_concept_choice"),
        _choice("概念选择：下面哪组数都是 36 的因数？", ["4、6、9", "5、6、8", "3、7、12"], "4、6、9", "36÷4、36÷6、36÷9 都能整除。", "math_concept_choice"),
        _exact("精确回答：写出 48 中大于 5 且小于 20 的所有因数。", "6|8|12|16", "48 的因数有 1、2、3、4、6、8、12、16、24、48，符合条件的是 6、8、12、16。", "math_exact"),
        _short(f"步骤说明：请说明怎样系统找全「{topic or '因数与倍数'}」中的因数，避免漏掉。", "从1开始成对找，找到重复或超过平方根时停止", "进阶要求是有顺序地找，而不是凭感觉写几个。", "math_step_explain"),
        _choice("错因判断：把 2、3、5、7、9 都当作质数，错在哪里？", ["9 不是质数", "2 不是质数", "7 不是质数"], "9 不是质数", "9=3×3，有除了 1 和它本身以外的因数。", "math_error_reason"),
        _choice("同类变式：既是 4 的倍数又是 6 的倍数，且小于 30 的数是？", ["12、24", "8、16", "18、28"], "12、24", "4 和 6 的公倍数小于 30 的有 12、24。", "math_variant"),
    ]


def _math_area_items(content: str, topic: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(content + topic)
    if not any(key in normalized for key in ("面积", "平行四边形", "三角形", "梯形")):
        return []
    return [
        _exact("精确计算：一个梯形上底 6 cm、下底 10 cm、高 4.5 cm，面积是多少？", "36", "梯形面积=(上底+下底)×高÷2=(6+10)×4.5÷2=36。", "math_exact"),
        _choice("概念选择：三角形和平行四边形等底等高时，三角形面积是平行四边形的多少？", ["一半", "一样大", "2 倍"], "一半", "三角形面积=底×高÷2。", "math_concept_choice"),
        _short(f"步骤说明：请写出今天「{topic or '多边形面积'}」先选公式、再代入、最后检查单位的过程。", "先判断图形，写公式，代入底和高，结果写平方单位", "面积题容易错在图形公式、对应的高和平方单位。", "math_step_explain"),
        _exact("应用题：一块平行四边形菜地底 12.5 米，高 8 米，每平方米收 3 千克菜，一共收多少千克？", "300", "面积=12.5×8=100 平方米，100×3=300 千克。", "math_word_problem"),
        _choice("错因判断：算梯形面积时忘记除以 2，主要错在哪里？", ["公式概念错", "单位错", "审题错"], "公式概念错", "梯形面积公式是（上底+下底）×高÷2。", "math_error_reason"),
        _exact("同类变式：三角形底 7.2 cm，高 5 cm，面积是多少？", "18", "面积=7.2×5÷2=18 平方厘米。", "math_variant"),
    ]


def _generic_math_items(topic: str, content: str) -> list[dict[str, Any]]:
    context = find_curriculum_context("math", topic + content)
    unit = context["unit"] if context else topic or "五年级数学上册"
    return [
        _exact("精确计算：7.5×4 - 18.6÷3 = ?", "23.8", "先算 7.5×4=30，再算 18.6÷3=6.2，最后 30-6.2=23.8。", "math_exact"),
        _choice("概念选择：遇到两步应用题，最先应该做什么？", ["先圈条件和问题", "直接凑一个算式", "先看答案"], "先圈条件和问题", "进阶题要先分析数量关系，再列式。", "math_concept_choice"),
        _short(
            f"步骤说明：请说出「{unit}」今天学到的方法，并补充一个容易错的地方和检查办法。",
            "说出方法、易错点和检查办法",
            "进阶小测要求孩子能讲清为什么这样做，而不是只写答案。",
            "math_step_explain",
        ),
        _exact("应用题：妈妈买 3 千克苹果，每千克 8.6 元；又买 2 千克梨，每千克 6.5 元。一共花多少钱？", "38.8", "苹果 8.6×3=25.8 元，梨 6.5×2=13 元，共 38.8 元。", "math_word_problem"),
        _choice("错因判断：两步题只算了第一步就写答案，主要属于哪类问题？", ["审题不完整", "单位错", "抄题错"], "审题不完整", "两步题要确认问题问的是中间量还是最终结果。", "math_error_reason"),
        _exact("同类变式：4.2×6 + 15.6÷4 = ?", "29.1", "4.2×6=25.2，15.6÷4=3.9，共 29.1。", "math_variant"),
    ]


def _build_math_quiz(topic: str, content: str, config: dict[str, Any], version: str | None) -> list[dict[str, Any]]:
    for builder in (_math_decimal_items, _math_factor_items, _math_area_items):
        items = builder(content, topic)
        if items:
            return items
    return _generic_math_items(topic, content)


def build_content_quiz(
    *,
    category: str,
    subject: str,
    title: str,
    description: str,
    standard: str,
    config: dict[str, Any],
    version: str | None = None,
) -> list[dict[str, Any]]:
    topic = str(config.get("topic") or config.get("lesson_title") or title)
    content = "\n".join(
        str(value)
        for value in (
            title,
            description,
            standard,
            config.get("lesson_content", ""),
            config.get("knowledge_points", ""),
            config.get("vocabulary", ""),
            config.get("raw", ""),
            config.get("materials_context", ""),
        )
        if value
    )
    subject_text = subject + "\n" + content
    if category == "ket":
        return _build_ket_quiz(topic, content, config)[:5]
    if "语文" in subject_text:
        return _build_chinese_quiz(topic, content, config, version)[:7]
    if "数学" in subject_text:
        return _build_math_quiz(topic, content, config, version)[:6]
    if "英语" in subject_text or re.search(r"\b(unit|school|library|there is)\b", content, re.I):
        return _build_english_quiz(topic, content, config, version)[:7]
    return []


def build_variant_questions(question: str, answer: str = "") -> list[dict[str, Any]]:
    text = question + " " + answer
    answer_text = str(answer or "").strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z'-]{2,}", answer_text):
        first_letter = answer_text[0]
        length_hint = len(answer_text)
        return [
            _exact("补漏默写：请家长读中文或原错词提示，孩子重新写英文单词。", answer_text, "补漏默写重点检查拼写是否完整。", "english_spelling"),
            _exact(f"首字母补全：这个错词以 {first_letter} 开头，共 {length_hint} 个字母，请写完整单词。", answer_text, "根据首字母和长度回忆完整拼写。", "english_spelling"),
            _choice("复查英文错词时，最有效的一步是什么？", ["只看一眼", "遮住答案再默写", "直接跳过"], "遮住答案再默写", "错词要遮住答案独立默写，才能确认掌握。", "choice"),
        ]
    if any(key in text for key in ("听写", "拼音", "生字", "词语")):
        return [
            _exact("变式听写：请家长再读一遍错词，孩子重新输入。", answer or "已订正", "错字需要当天订正，第二天复听写。", "chinese_word_dictation"),
            _short(f"变式组词：用错字相关生字组词。原题：{question[:40]}", "组词", "词语必须包含目标生字，且符合常见语境。", "chinese_char_group"),
        ]
    if any(key in text.lower() for key in ("english", "中译英", "英译中", "默写", "there")):
        return [
            _exact("变式默写：请重新写出这个单词或句型答案。", answer or "已订正", "英语错词按 1/3/7 天复默。", "english_spelling"),
            _short("变式造句：用这个词写一个新的英文短句。", "完整英文句子", "句子需包含目标词，首字母、基本语序和句末标点要正确。", "english_sentence_make"),
        ]
    if any(key in text for key in ("小数乘", "×", "乘整数")):
        return [
            _exact("变式题：3.7 × 4 = ?", _decimal_mul("3.7", "4"), "先算 37×4=148，再点一位小数，得 14.8。", "math_variant"),
            _exact("变式题：0.6 × 9 = ?", _decimal_mul("0.6", "9"), "6×9=54，所以 0.6×9=5.4。", "math_variant"),
        ]
    if any(key in text for key in ("小数除", "÷", "除以整数")):
        return [
            _exact("变式题：7.5 ÷ 3 = ?", _decimal_div("7.5", "3"), "75÷3=25，所以 7.5÷3=2.5。", "math_variant"),
            _exact("变式题：8.4 ÷ 2 = ?", _decimal_div("8.4", "2"), "84÷2=42，所以 8.4÷2=4.2。", "math_variant"),
        ]
    if any(key in text for key in ("因数", "倍数")):
        return [
            _choice("变式题：下面哪一个是 18 的因数？", ["4", "6", "8"], "6", "18÷6=3，能整除。", "math_variant"),
            _choice("变式题：下面哪一个是 4 的倍数？", ["14", "16", "18"], "16", "16÷4=4，能整除。", "math_variant"),
        ]
    if any(key in text for key in ("面积", "平行四边形", "三角形")):
        return [
            _exact("变式题：平行四边形底 9 cm，高 4 cm，面积是多少？", "36", "面积=底×高=9×4=36。", "math_variant"),
            _exact("变式题：三角形底 8 cm，高 5 cm，面积是多少？", "20", "面积=底×高÷2=8×5÷2=20。", "math_variant"),
        ]
    return [
        _short(f"变式复习：请重新说明这道题的关键：{question[:80]}", "说清关键", "需说明错因、正确方法和下一次检查点。"),
        _choice("补漏复盘：遇到同类题，第一步应该做什么？", ["直接猜答案", "先读题并圈出关键信息", "空着不做"], "先读题并圈出关键信息", "补漏题先定位条件和要求，再动手。", "review_strategy"),
        _short("补漏检查：请写出下一次避免同类错误的一个检查点。", "写出检查点", "检查点必须具体，例如小数点、单位、关键词、拼写或原文依据。", "review_check"),
    ]
