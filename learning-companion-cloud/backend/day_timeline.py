from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DAY_START = "08:30"
DAY_END = "21:00"
FIXED_BLOCKS = [
    {"start": "11:30", "end": "14:00", "kind": "meal", "title": "午餐 + 午休", "description": "吃饭、午休、护眼，下午再进入练习。"},
    {"start": "18:00", "end": "19:00", "kind": "meal", "title": "晚餐 + 放松", "description": "吃饭、聊天、整理桌面，不安排硬学习。"},
]


@dataclass(frozen=True)
class TimeBlock:
    start: int
    end: int
    kind: str
    title: str
    description: str = ""
    task: dict[str, Any] | None = None


def _to_minutes(value: str | None) -> int | None:
    if not value or ":" not in value:
        return None
    try:
        hour, minute = value.split(":", 1)
        return int(hour) * 60 + int(minute)
    except ValueError:
        return None


def _format_minutes(value: int) -> str:
    return f"{value // 60:02d}:{value % 60:02d}"


def _block_subject(task: dict[str, Any]) -> str:
    text = f"{task.get('title', '')} {task.get('description', '')}"
    if any(word in text for word in ("运动", "体育", "跳绳", "拉伸", "慢跑")):
        return "体育"
    if any(word in text for word in ("KET", "英语", "Unit", "单词")):
        return "英语"
    if any(word in text for word in ("数学", "小数", "口算", "计算", "面积")):
        return "数学"
    if any(word in text for word in ("语文", "诵读", "妙笔", "阅读", "一本", "课文")):
        return "语文"
    return "综合"


def _task_kind(task: dict[str, Any]) -> str:
    subject = _block_subject(task)
    title = str(task.get("title", ""))
    if subject == "体育":
        return "movement"
    if "阅读" in title:
        return "reading"
    if "KET" in title:
        return "ket"
    return "task"


def _idle_block(start: int, end: int) -> TimeBlock | None:
    minutes = end - start
    if minutes <= 0:
        return None
    if minutes <= 15:
        return TimeBlock(start, end, "break", "护眼休息", "喝水、离开座位、看远处。")
    if minutes <= 35:
        return TimeBlock(start, end, "break", "换脑休息", "上厕所、喝水、整理下一项材料。")
    if minutes <= 75:
        return TimeBlock(start, end, "buffer", "自由活动", "放松一下，保留体力，不额外加题。")
    return TimeBlock(start, end, "buffer", "大段休息", "吃点水果、午休或自由活动，避免连续学习过久。")


def _fixed_blocks_between(start: int, end: int) -> list[TimeBlock]:
    blocks: list[TimeBlock] = []
    for item in FIXED_BLOCKS:
        block_start = _to_minutes(item["start"])
        block_end = _to_minutes(item["end"])
        if block_start is None or block_end is None:
            continue
        clipped_start = max(start, block_start)
        clipped_end = min(end, block_end)
        if clipped_start < clipped_end:
            blocks.append(
                TimeBlock(
                    clipped_start,
                    clipped_end,
                    str(item["kind"]),
                    str(item["title"]),
                    str(item["description"]),
                )
            )
    return blocks


def _fill_gap(start: int, end: int) -> list[TimeBlock]:
    if start >= end:
        return []
    fixed = _fixed_blocks_between(start, end)
    if not fixed:
        idle = _idle_block(start, end)
        return [idle] if idle else []
    blocks: list[TimeBlock] = []
    cursor = start
    for block in sorted(fixed, key=lambda item: item.start):
        if cursor < block.start:
            idle = _idle_block(cursor, block.start)
            if idle:
                blocks.append(idle)
        blocks.append(block)
        cursor = block.end
    if cursor < end:
        idle = _idle_block(cursor, end)
        if idle:
            blocks.append(idle)
    return blocks


def build_day_timeline(tasks: list[dict[str, Any]], day_start: str = DAY_START, day_end: str = DAY_END) -> dict[str, Any]:
    start_minutes = _to_minutes(day_start) or _to_minutes(DAY_START) or 510
    end_minutes = _to_minutes(day_end) or _to_minutes(DAY_END) or 1260
    task_blocks: list[TimeBlock] = []
    for task in tasks:
        planned_start = _to_minutes(str(task.get("planned_start") or ""))
        planned_end = _to_minutes(str(task.get("planned_end") or ""))
        if planned_start is None or planned_end is None or planned_end <= planned_start:
            continue
        task_blocks.append(
            TimeBlock(
                planned_start,
                planned_end,
                _task_kind(task),
                str(task.get("title") or "学习任务"),
                str(task.get("description") or ""),
                dict(task),
            )
        )
    task_blocks.sort(key=lambda item: (item.start, item.end, int(item.task.get("id", 0)) if item.task else 0))

    blocks: list[TimeBlock] = []
    cursor = start_minutes
    for task_block in task_blocks:
        if cursor < task_block.start:
            blocks.extend(_fill_gap(cursor, task_block.start))
        blocks.append(task_block)
        cursor = max(cursor, task_block.end)
    if cursor < end_minutes:
        blocks.extend(_fill_gap(cursor, end_minutes))

    payload_blocks: list[dict[str, Any]] = []
    for index, block in enumerate(blocks, start=1):
        item = {
            "index": index,
            "start": _format_minutes(block.start),
            "end": _format_minutes(block.end),
            "minutes": block.end - block.start,
            "kind": block.kind,
            "title": block.title,
            "description": block.description,
            "is_task": block.task is not None,
        }
        if block.task:
            item["task_id"] = block.task.get("id")
            item["task_status"] = block.task.get("status")
            item["subject"] = _block_subject(block.task)
            item["schedule_block"] = block.task.get("schedule_block", "")
        else:
            item["subject"] = "生活"
        payload_blocks.append(item)

    total_task_minutes = sum(int(block["minutes"]) for block in payload_blocks if block["is_task"])
    total_rest_minutes = sum(int(block["minutes"]) for block in payload_blocks if not block["is_task"])
    return {
        "day_start": _format_minutes(start_minutes),
        "day_end": _format_minutes(end_minutes),
        "blocks": payload_blocks,
        "summary": {
            "task_minutes": total_task_minutes,
            "rest_minutes": total_rest_minutes,
            "total_minutes": max(0, end_minutes - start_minutes),
            "task_count": len(task_blocks),
        },
    }
