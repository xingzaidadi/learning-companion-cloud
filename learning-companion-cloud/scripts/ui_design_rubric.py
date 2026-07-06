from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "ui_audit" / "latest"


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def score(items: list[tuple[str, bool, str]]) -> dict:
    passed = [name for name, ok, _detail in items if ok]
    failed = [{"name": name, "detail": detail} for name, ok, detail in items if not ok]
    return {"score": round(len(passed) / max(len(items), 1) * 10, 2), "passed": passed, "failed": failed}


def main() -> None:
    child = read("frontend/child.html")
    parent = read("frontend/parent.html")
    admin = read("frontend/admin.html")
    css = read("frontend/static/styles.css")
    combined = child + parent + admin + css
    button_count = combined.count("<button")
    aria_button_count = combined.count("aria-label=")
    child_copy_lengths = [len(text) for text in re.findall(r">([^<>]{6,40})<", child) if re.search(r"[\u4e00-\u9fff]", text)]
    avg_child_copy_length = sum(child_copy_lengths) / max(len(child_copy_lengths), 1)

    checks = {
        "child_focus": [
            ("single_current_task", "currentTask" in child and "当前任务" in child, "孩子端必须优先展示当前任务。"),
            ("clear_primary_action", "primaryButton" in child and "secondaryButtons" in child, "主要动作和次要动作必须分层。"),
            ("timer_visible", "elapsed" in child and ("学习时长" in child or "已学" in child), "计时必须对孩子可见。"),
            ("progressive_details", child.count("<details") >= 2, "检查区和队列应渐进展开，不能一次堆满。"),
        ],
        "parent_clarity": [
            ("summary_first", "parentSummary" in parent and "你现在只需要看这里" in parent, "家长端必须先给结论。"),
            ("action_focus", "parentActions" in parent, "家长端必须有明确行动建议。"),
            ("details_collapsed", parent.count("<details") >= 4, "家长端细节默认可折叠。"),
        ],
        "admin_operability": [
            ("natural_input_primary", "quickPlanForm" in admin, "管理端必须以自然语言计划为主入口。"),
            ("advanced_collapsed", "admin-advanced-area" in admin and "<details" in admin, "高级能力不能默认铺满。"),
            ("agent_evidence_visible", "showTrace" in admin, "Agent 决策证据必须可查。"),
        ],
        "visual_language": [
            ("color_tokens", all(token in css for token in ("--primary", "--secondary", "--chinese", "--math", "--english")), "三科和主色必须有明确色彩 token。"),
            ("soft_background", "radial-gradient" in css and "linear-gradient" in css, "页面背景不能是纯白平铺。"),
            ("card_system", ".card" in css and "--radius" in css, "卡片和圆角系统必须统一。"),
            ("responsive", "@media (max-width: 820px)" in css, "必须适配窄屏。"),
        ],
        "accessibility_ux": [
            ("aria_coverage", 'role="main"' in child and 'role="main"' in parent and 'role="main"' in admin and aria_button_count >= 8, "三端主区域和关键按钮必须有无障碍名称。"),
            ("live_regions", 'aria-live="polite"' in child and 'role="status"' in child, "孩子端当前任务、小测和卡点提示需要状态播报。"),
            ("touch_target_size", "min-height: 44px" in css and "min-width: 44px" in css, "按钮触控面积至少 44px。"),
            ("focus_visible", ":focus-visible" in css and "outline" in css, "键盘焦点必须清晰可见。"),
            ("child_copy_length", avg_child_copy_length <= 18, f"孩子端平均文案长度应适龄，当前 {avg_child_copy_length:.1f}。"),
            ("contrast_tokens", all(token in css for token in ("--text", "--muted", "--primary-dark", "--danger")), "颜色 token 应支持可读对比度。"),
        ],
        "maintainability": [
            ("no_visible_entities", not re.search(r"&#\d{4,};", child + parent + admin), "页面可见中文不能依赖数字 HTML 实体。"),
            ("no_dirty_tokens", not any(token in combined for token in ("????", "undefined", "NaN", "\ufffd")), "不能出现脏文本。"),
            ("mostly_chinese_labels", sum(1 for text in ("开始", "暂停", "卡住", "检查", "家长", "管理") if text in combined) >= 5, "核心用户文案必须中文可读。"),
        ],
    }

    report = {"sections": {}, "overall_score": 0.0}
    section_scores = []
    for name, items in checks.items():
        result = score(items)
        report["sections"][name] = result
        section_scores.append(result["score"])
    report["overall_score"] = round(sum(section_scores) / len(section_scores), 2)

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    (REPORT_DIR / "ui_design_rubric.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# UI Design Rubric", "", f"- Overall score: `{report['overall_score']}`", ""]
    for section, result in report["sections"].items():
        lines.append(f"- `{section}`: `{result['score']}` / 10")
        for failure in result["failed"]:
            lines.append(f"  - Failed `{failure['name']}`: {failure['detail']}")
    (REPORT_DIR / "ui_design_rubric.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps(report, ensure_ascii=False))
    if report["overall_score"] < 9.0 or any(result["failed"] for result in report["sections"].values()):
        raise AssertionError(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
