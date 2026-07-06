from __future__ import annotations

from typing import Any


def rubric_for_item(question_type: str, subject: str = "") -> dict[str, Any]:
    if question_type in {"math_exact", "math_variant"}:
        return {"mode": "exact", "full_credit": "答案数值正确；单位题需包含单位。", "common_errors": ["计算错误", "小数点错误", "单位遗漏"]}
    if question_type in {"math_step_explain", "math_word_problem", "math_error_reason"}:
        return {"mode": "rubric", "criteria": ["列出已知条件", "写出关系式或关键步骤", "说明检查点"], "pass_rule": "至少命中 2 项且无明显概念错误。"}
    if question_type in {"chinese_word_dictation", "chinese_pinyin", "chinese_char_group"}:
        return {"mode": "strict_or_near", "full_credit": "字形/拼音/组词准确。", "common_errors": ["错别字", "漏字", "形近字混淆"]}
    if question_type.startswith("chinese_"):
        return {"mode": "rubric", "criteria": ["回到课文依据", "抓住关键词句", "表达完整"], "pass_rule": "至少 2 项达标，不接受空泛回答。"}
    if question_type in {"english_spelling", "english_word_cn_to_en"}:
        return {"mode": "strict", "full_credit": "英文拼写完全正确，大小写不作核心扣分。", "common_errors": ["漏字母", "字母顺序错误", "中文意思混淆"]}
    if question_type.startswith("english_"):
        return {"mode": "rubric", "criteria": ["目标词/句型使用正确", "基本语序正确", "含义匹配"], "pass_rule": "核心词义正确且句子基本通顺。"}
    return {"mode": "rubric", "criteria": ["答案围绕题目", "包含关键依据", "表达清楚"], "pass_rule": "不能只写无关内容或空泛一句话。"}
