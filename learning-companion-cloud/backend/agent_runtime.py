from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .agent_tool_registry import get_tool_spec, validate_tool_call
from .ai_provider import call_ai_json_with_meta


ToolExecutor = Callable[[dict[str, Any]], Any]


def run_controlled_tool_loop(
    settings: dict[str, Any],
    *,
    goal: str,
    context: dict[str, Any],
    candidate_tools: list[str],
    executors: dict[str, ToolExecutor],
    fallback_tool: str,
    fallback_arguments: dict[str, Any],
    allow_write: bool = False,
) -> dict[str, Any]:
    """Run a small, controlled tool loop.

    This is intentionally not an unconstrained autonomous Agent loop. The model can
    choose only from whitelisted tools; every choice is schema-validated before
    execution; fallback remains deterministic when AI is disabled or invalid.
    """

    tool_specs = []
    for name in candidate_tools:
        spec = get_tool_spec(name)
        if spec:
            tool_specs.append(
                {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                    "side_effect": spec.side_effect,
                    "idempotent": spec.idempotent,
                }
            )

    fallback_decision = {
        "tool": fallback_tool,
        "arguments": fallback_arguments,
        "reason": "规则兜底选择最安全的工具。",
    }
    prompt = (
        "你是儿童学习陪跑系统的受控 Agent Runtime。\n"
        "只能从给定 tools 中选择一个工具，不允许编造工具，不允许越权写入。\n"
        "请只输出 JSON：{\"tool\":\"工具名\",\"arguments\":{},\"reason\":\"选择理由\"}。\n"
        f"目标：{goal}\n"
        f"上下文：{context}\n"
        f"可用工具：{tool_specs}\n"
    )
    decision, meta = call_ai_json_with_meta(settings, prompt, fallback_decision)
    if not isinstance(decision, dict):
        decision = fallback_decision
    tool_name = str(decision.get("tool") or fallback_tool)
    arguments = decision.get("arguments")
    if not isinstance(arguments, dict):
        arguments = fallback_arguments

    if tool_name not in executors:
        tool_name = fallback_tool
        arguments = fallback_arguments
    validation = validate_tool_call(tool_name, arguments, allow_write=allow_write)
    if not validation.get("ok"):
        tool_name = fallback_tool
        arguments = fallback_arguments
        validation = validate_tool_call(tool_name, arguments, allow_write=allow_write)

    observation: Any = None
    status = "ok"
    error = ""
    try:
        observation = executors[tool_name](arguments)
    except Exception as exc:  # pragma: no cover - defensive safety belt
        status = "error"
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
        observation = []

    return {
        "mode": "controlled_tool_loop",
        "used_ai_decision": bool(meta.get("used_ai")),
        "model": meta.get("model", "rule"),
        "status": status if status != "ok" else meta.get("status", "ok"),
        "error": error or meta.get("error", ""),
        "steps": [
            {
                "step_index": 1,
                "step_type": "select_tool",
                "tool_name": tool_name,
                "arguments": arguments,
                "reason": decision.get("reason", ""),
                "validation": validation,
            },
            {
                "step_index": 2,
                "step_type": "observe",
                "tool_name": tool_name,
                "observation_preview": _preview_observation(observation),
                "status": status,
            },
        ],
        "final_observation": observation,
    }


def _preview_observation(observation: Any) -> Any:
    if isinstance(observation, list):
        return {"count": len(observation), "items": observation[:2]}
    if isinstance(observation, dict):
        return {key: observation[key] for key in list(observation)[:6]}
    return observation
