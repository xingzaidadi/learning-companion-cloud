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
    "search_material_chunks": ToolSpec(
        name="search_material_chunks",
        description="检索教材/RAG 切片，用于绑定题目来源和回答依据。",
        parameters={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}, "subject": {"type": "string"}}},
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
        description="为每日任务生成带来源、难度、评分规则的小测题。",
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
}


def list_tool_specs() -> list[dict[str, Any]]:
    return [{**spec.__dict__} for spec in TOOLS.values()]


def get_tool_spec(name: str) -> ToolSpec | None:
    return TOOLS.get(name)
