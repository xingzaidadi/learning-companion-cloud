from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    output_schema: dict[str, Any]
    permission: str = "agent"
    side_effect: str = "read"
    idempotent: bool = True
    timeout_seconds: int = 10


TOOLS: dict[str, ToolSpec] = {
    "generate_study_plan": ToolSpec(
        name="generate_study_plan",
        description="把家长自然语言目标拆成长期学习计划和任务源。",
        parameters={"type": "object", "required": ["student_id", "raw_goal"], "properties": {"student_id": {"type": "integer"}, "raw_goal": {"type": "string"}}},
        output_schema={"type": "object"},
        side_effect="write",
    ),
    "search_material_chunks": ToolSpec(
        name="search_material_chunks",
        description="检索教材/RAG 切片，用于绑定题目来源和回答依据。",
        parameters={
            "type": "object",
            "required": ["query"],
            "properties": {
                "query": {"type": "string"},
                "subject": {"type": "string"},
                "student_id": {"type": "integer"},
                "limit": {"type": "integer"},
            },
        },
        output_schema={"type": "array", "items": {"type": "object"}},
    ),
    "generate_daily_tasks": ToolSpec(
        name="generate_daily_tasks",
        description="根据学习计划、掌握度和复习需求生成当天任务。",
        parameters={"type": "object", "properties": {"student_id": {"type": "integer"}, "target_date": {"type": "string"}}},
        output_schema={"type": "object"},
        side_effect="write",
    ),
    "generate_quiz": ToolSpec(
        name="generate_quiz",
        description="为每日任务生成带来源、难度和评分规则的小测题。",
        parameters={"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "integer"}}},
        output_schema={"type": "object"},
        side_effect="write",
    ),
    "grade_quiz": ToolSpec(
        name="grade_quiz",
        description="批改小测，更新错题、掌握度和复习计划。",
        parameters={"type": "object", "required": ["task_id", "answers"], "properties": {"task_id": {"type": "integer"}, "answers": {"type": "object"}}},
        output_schema={"type": "object"},
        side_effect="write",
        idempotent=False,
    ),
    "diagnose_learning": ToolSpec(
        name="diagnose_learning",
        description="根据小测结果诊断掌握度，必要时生成补救复习项。",
        parameters={"type": "object", "required": ["task_id", "quiz_result"], "properties": {"task_id": {"type": "integer"}, "quiz_result": {"type": "object"}}},
        output_schema={"type": "object"},
        side_effect="write",
        idempotent=False,
    ),
    "assist_stuck": ToolSpec(
        name="assist_stuck",
        description="孩子卡住时给出分步提示和微练习，不直接泄露答案。",
        parameters={"type": "object", "required": ["task_id"], "properties": {"task_id": {"type": "integer"}, "note": {"type": "string"}}},
        output_schema={"type": "object"},
        side_effect="write",
    ),
    "write_memory": ToolSpec(
        name="write_memory",
        description="写入长期记忆、错题或卡点。",
        parameters={"type": "object", "properties": {"subject": {"type": "string"}, "skill": {"type": "string"}, "content": {"type": "string"}}},
        output_schema={"type": "object"},
        side_effect="write",
    ),
    "generate_daily_report": ToolSpec(
        name="generate_daily_report",
        description="汇总当天任务、小测、卡点、补救队列和明日建议。",
        parameters={"type": "object", "properties": {"student_id": {"type": "integer"}, "target_date": {"type": "string"}}},
        output_schema={"type": "object"},
        side_effect="write",
    ),
}


def list_tool_specs() -> list[dict[str, Any]]:
    return [{**spec.__dict__} for spec in TOOLS.values()]


def get_tool_spec(name: str) -> ToolSpec | None:
    return TOOLS.get(name)


def validate_tool_call(name: str, arguments: dict[str, Any], *, allow_write: bool = True) -> dict[str, Any]:
    spec = get_tool_spec(name)
    if not spec:
        return {"ok": False, "tool": name, "error": "unknown_tool"}
    if spec.side_effect == "write" and not allow_write:
        return {"ok": False, "tool": name, "error": "write_not_allowed"}
    missing = [key for key in spec.parameters.get("required", []) if key not in arguments]
    if missing:
        return {"ok": False, "tool": name, "error": "missing_required", "missing": missing}
    return {
        "ok": True,
        "tool": name,
        "side_effect": spec.side_effect,
        "idempotent": spec.idempotent,
        "timeout_seconds": spec.timeout_seconds,
    }
