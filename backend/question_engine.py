from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from .curriculum import find_curriculum_context
from .db import dumps


def _short(question: str, answer: str, explanation: str) -> dict[str, Any]:
    return {
        "question_type": "short",
        "question": question,
        "answer": answer,
        "explanation": explanation,
    }


def _exact(question: str, answer: str, explanation: str) -> dict[str, Any]:
    return {
        "question_type": "exact",
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


def _math_decimal_items(text: str, topic: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(text + topic)
    wants_mul = any(key in normalized for key in ("小数乘", "乘法", "乘整数", "小数乘整数"))
    wants_div = any(key in normalized for key in ("小数除", "除法", "除以整数", "小数除以整数"))
    if "乘除" in normalized:
        wants_mul = True
        wants_div = True

    items: list[dict[str, Any]] = []
    if wants_mul:
        items.extend(
            [
                _exact("计算：2.4 × 3 = ?", _decimal_mul("2.4", "3"), "小数乘整数，可以先按整数乘法算 24×3=72，再看小数位数得到 7.2。"),
                _exact("计算：0.8 × 6 = ?", _decimal_mul("0.8", "6"), "8×6=48，0.8 有 1 位小数，所以结果是 4.8。"),
                _choice("小数乘整数时，积的小数位数主要由什么决定？", ["整数有几位", "小数因数的小数位数", "数字写得长不长"], "小数因数的小数位数", "先按整数乘，再根据小数因数的小数位数点小数点。"),
            ]
        )
    if wants_div:
        items.extend(
            [
                _exact("计算：6.4 ÷ 4 = ?", _decimal_div("6.4", "4"), "64÷4=16，6.4 比 64 少一位小数，结果是 1.6。"),
                _exact("计算：9.6 ÷ 3 = ?", _decimal_div("9.6", "3"), "96÷3=32，所以 9.6÷3=3.2。"),
                _choice("小数除以整数时，如果被除数末尾不够除，通常可以怎么做？", ["直接丢掉余数", "在末尾添 0 继续除", "把小数点去掉不管"], "在末尾添 0 继续除", "小数末尾添 0 大小不变，可以继续除。"),
            ]
        )
    if not items:
        return []

    items.append(
        _short(
            f"用一句话说清楚今天这节「{topic or '数学预习'}」最核心的方法。",
            "说清方法",
            "能说出计算步骤、为什么这样点小数点，才算真正理解。",
        )
    )
    return items[:5]


def _math_factor_items(text: str, topic: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(text + topic)
    if not any(key in normalized for key in ("因数", "倍数", "质数", "合数")):
        return []
    return [
        _choice("下面哪一个数是 24 的因数？", ["5", "6", "7"], "6", "24÷6=4，能整除，所以 6 是 24 的因数。"),
        _choice("下面哪一个数是 6 的倍数？", ["18", "20", "25"], "18", "18÷6=3，能整除，所以 18 是 6 的倍数。"),
        _exact("写出 12 的一个因数。", "1|2|3|4|6|12", "12 的因数有 1、2、3、4、6、12。"),
        _short(f"请解释「{topic or '因数与倍数'}」里因数和倍数的关系。", "说清关系", "能用一个乘法算式说明即可。"),
    ]


def _math_area_items(text: str, topic: str) -> list[dict[str, Any]]:
    normalized = _normalize_text(text + topic)
    if not any(key in normalized for key in ("面积", "平行四边形", "三角形", "梯形")):
        return []
    return [
        _exact("平行四边形底 8 cm，高 5 cm，面积是多少？", "40", "平行四边形面积=底×高=8×5=40。"),
        _exact("三角形底 10 cm，高 6 cm，面积是多少？", "30", "三角形面积=底×高÷2=10×6÷2=30。"),
        _choice("计算平行四边形面积时，需要哪两个量？", ["底和高", "周长和颜色", "任意两条边"], "底和高", "平行四边形面积公式是底×高。"),
        _short(f"请写出今天「{topic or '图形面积'}」学到的一个面积公式。", "写出公式", "能写出正确公式即可。"),
    ]


def _generic_math_items(topic: str, content: str) -> list[dict[str, Any]]:
    if not topic and not content:
        return []
    return [
        _short(f"今天预习的是「{topic or '数学新课'}」。请写出 1 个核心概念。", "写出核心概念", "核心概念是判断是否真正看懂的第一步。"),
        _short("请仿照今天内容写一道例题，并写出答案。", "写出例题和答案", "能自己仿题说明已经初步掌握。"),
        _short("请写出今天最容易错的一点，以及你准备怎么避免。", "写出易错点", "提前识别易错点，有利于明天复习。"),
    ]


def _chinese_items(topic: str, content: str, version: str | None) -> list[dict[str, Any]]:
    context = find_curriculum_context("chinese", topic + content, version)
    unit = context["unit"] if context else topic or "五年级语文上册"
    points = "、".join(context.get("points", [])[:3]) if context else "概括内容、体会表达、联系生活"
    focus = context.get("quiz_focus", []) if context else []
    items = [
        _short(f"今天语文内容属于「{unit}」。请用 1-2 句话概括你学到的主要内容。", "概括主要内容", "能抓住人物、事件、景物或说明对象即可。"),
        _short(f"请写出今天最重要的一个语文能力点，例如：{points}。", "写出能力点", "语文小测重点看是否理解本课表达方法。"),
        _short("请找出或回忆一个让你印象深的词句，并说明原因。", "说明原因", "能说出感受或表达效果即可。"),
    ]
    if any("说明方法" in value for value in focus) or "说明" in unit:
        items.insert(1, _choice("下面哪一项属于常见说明方法？", ["列数字", "倒叙", "夸张"], "列数字", "五年级说明文重点学习列数字、作比较、打比方等方法。"))
    if any("复述" in value or "缩写" in value for value in focus) or "民间故事" in unit:
        items.insert(1, _short("请按“起因—经过—结果”复述今天故事的主要情节。", "复述情节", "民间故事单元重点训练复述和缩写。"))
    return items[:5]


def _english_curriculum_items(config: dict[str, Any], topic: str, content: str, version: str | None) -> list[dict[str, Any]]:
    context = find_curriculum_context("english", topic + content, version)
    unit = context["unit"] if context else topic or "五年级英语上册"
    points = context.get("points", []) if context else ["core words", "key sentence", "short answer"]
    first_point = points[0] if points else "core words"
    items = [
        _short(f"Today's English topic is 「{unit}」. Write two words you learned today.", "write two words", "写出两个本课词汇即可。"),
        _short(f"Make one sentence with today's key point: {first_point}.", "write one sentence", "能写出一个完整短句即可。"),
        _choice("When you are not sure about an English word, what should you do?", ["Skip forever", "Mark it and review it", "Only read Chinese"], "Mark it and review it", "不会的词要进入复习队列。"),
    ]
    return items


def _ket_vocab_items(config: dict[str, Any], text: str) -> list[dict[str, Any]]:
    vocab_text = config.get("vocabulary") or config.get("lesson_content") or text
    pairs: list[tuple[str, str]] = []
    for raw in re.split(r"[\n,，;；]", vocab_text):
        if "=" in raw:
            left, right = raw.split("=", 1)
            pairs.append((left.strip(), right.strip()))
        elif "：" in raw:
            left, right = raw.split("：", 1)
            pairs.append((left.strip(), right.strip()))
        elif ":" in raw:
            left, right = raw.split(":", 1)
            pairs.append((left.strip(), right.strip()))
    if not pairs:
        return []
    items: list[dict[str, Any]] = []
    for english, chinese in pairs[:3]:
        items.append(_exact(f"写出中文意思：{english}", chinese, f"{english} = {chinese}"))
    items.append(_short("任选今天 1 个 KET 单词造一个英文短句。", "写出英文短句", "造句能检查是否会用，而不只是会背。"))
    return items


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
    topic = config.get("topic") or config.get("lesson_title") or title
    content = "\n".join(
        str(value)
        for value in (
            title,
            description,
            standard,
            config.get("lesson_content", ""),
            config.get("knowledge_points", ""),
            config.get("raw", ""),
        )
        if value
    )

    if category == "preview" and ("语文" in subject or "语文" in content):
        return _chinese_items(topic, content, version)

    if category == "preview":
        for builder in (_math_decimal_items, _math_factor_items, _math_area_items):
            items = builder(content, topic)
            if items:
                return items
        if "数学" in subject or "数学" in content:
            return _generic_math_items(topic, content)

    if category == "preview" and ("英语" in subject or "英语" in content):
        items = _ket_vocab_items(config, content)
        if items:
            return items
        return _english_curriculum_items(config, topic, content, version)

    if category == "ket":
        items = _ket_vocab_items(config, content)
        if items:
            return items

    return []


def build_variant_questions(question: str, answer: str = "") -> list[dict[str, Any]]:
    text = question + " " + answer
    if any(key in text for key in ("小数乘", "×", "乘整数")):
        return [
            _exact("变式题：3.7 × 4 = ?", _decimal_mul("3.7", "4"), "先算 37×4=148，再点一位小数，得 14.8。"),
            _exact("变式题：0.6 × 9 = ?", _decimal_mul("0.6", "9"), "6×9=54，所以 0.6×9=5.4。"),
        ]
    if any(key in text for key in ("小数除", "÷", "除以整数")):
        return [
            _exact("变式题：7.5 ÷ 3 = ?", _decimal_div("7.5", "3"), "75÷3=25，所以 7.5÷3=2.5。"),
            _exact("变式题：8.4 ÷ 2 = ?", _decimal_div("8.4", "2"), "84÷2=42，所以 8.4÷2=4.2。"),
        ]
    if any(key in text for key in ("因数", "倍数")):
        return [
            _choice("变式题：下面哪一个是 18 的因数？", ["4", "6", "8"], "6", "18÷6=3，能整除。"),
            _choice("变式题：下面哪一个是 4 的倍数？", ["14", "16", "18"], "16", "16÷4=4，能整除。"),
        ]
    if any(key in text for key in ("面积", "平行四边形", "三角形")):
        return [
            _exact("变式题：平行四边形底 9 cm，高 4 cm，面积是多少？", "36", "面积=底×高=9×4=36。"),
            _exact("变式题：三角形底 8 cm，高 5 cm，面积是多少？", "20", "面积=底×高÷2=8×5÷2=20。"),
        ]
    return [
        _short(f"变式复习：请重新说明这道题的关键：{question[:80]}", "说清关键", "能说清为什么错、正确方法是什么即可。")
    ]
