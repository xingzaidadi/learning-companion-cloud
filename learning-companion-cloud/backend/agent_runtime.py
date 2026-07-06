from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any

from .agent_tool_registry import get_tool_spec, validate_tool_call
from .ai_provider import call_ai_json_with_meta


ToolExecutor = Callable[[dict[str, Any]], Any]


STANDARD_TRACE_TYPES = ("goal", "plan", "decision", "tool_call", "observation", "evaluate", "supervise", "final")
RUNTIME_ROLES = ("Planner", "Executor", "Evaluator", "Supervisor")


def run_controlled_agent_runtime(
    *,
    goal: str,
    context: dict[str, Any],
    tool_name: str,
    arguments: dict[str, Any],
    executor: ToolExecutor,
    allow_write: bool = True,
    evaluator: Callable[[Any], dict[str, Any]] | None = None,
    supervisor: Callable[[Any, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Execute one bounded Agent loop with auditable trace steps.

    The Runtime is intentionally controlled for a child-learning product: the
    model never receives unconstrained authority, while engineering still gets a
    real Goal -> Plan -> Decision -> Tool -> Observation -> Evaluation ->
    Supervisor -> Final loop for testing and interview demonstration.
    """

    started = perf_counter()
    validation = validate_tool_call(tool_name, arguments, allow_write=allow_write)
    steps: list[dict[str, Any]] = [
        {
            "step_type": "goal",
            "thought": "把用户/孩子目标转成可审计的 Agent 运行目标。",
            "decision": {"goal": goal, "context_keys": sorted(context.keys())},
            "observation": {"context": context},
            "status": "ok",
            "score": 1.0,
        },
        {
            "step_type": "plan",
            "thought": "采用受控单步计划：只调用白名单工具，先规则兜底，再交给页面闭环。",
            "decision": {"tool": tool_name, "arguments": arguments, "allow_write": allow_write},
            "status": "ok",
            "score": 1.0,
        },
        {
            "step_type": "decision",
            "thought": "校验工具 Schema、权限和幂等性，避免越权执行。",
            "tool_name": tool_name,
            "args": arguments,
            "validation": validation,
            "status": "ok" if validation.get("ok") else "blocked",
            "score": 1.0 if validation.get("ok") else 0.0,
        },
    ]
    observation: Any = None
    status = "ok"
    error = ""
    if validation.get("ok"):
        try:
            observation = executor(arguments)
        except Exception as exc:  # pragma: no cover - runtime safety belt
            status = "error"
            error = f"{type(exc).__name__}: {str(exc)[:200]}"
            observation = {"error": error}
    else:
        status = "blocked"
        error = str(validation.get("error") or "validation_failed")
        observation = {"error": error}

    latency_ms = int((perf_counter() - started) * 1000)
    steps.append(
        {
            "step_type": "tool_call",
            "thought": "执行受控工具并记录耗时、参数和错误。",
            "tool_name": tool_name,
            "args": arguments,
            "observation": _preview_observation(observation),
            "validation": validation,
            "latency_ms": latency_ms,
            "status": status,
            "error": error,
            "score": 1.0 if status == "ok" else 0.0,
        }
    )
    evaluation = evaluator(observation) if evaluator else _default_evaluate(observation, status, error)
    steps.append(
        {
            "step_type": "observation",
            "thought": "把工具输出压缩成后续评分可读取的观察。",
            "tool_name": tool_name,
            "observation": _preview_observation(observation),
            "status": status,
            "score": float(evaluation.get("score", 0.8) or 0.8),
        }
    )
    steps.append(
        {
            "step_type": "evaluate",
            "thought": "检查输出是否满足任务完成、证据、无泄题和补救闭环要求。",
            "decision": evaluation,
            "status": "ok" if evaluation.get("passed", True) else "warn",
            "score": float(evaluation.get("score", 0.8) or 0.8),
        }
    )
    supervision = supervisor(observation, evaluation) if supervisor else _default_supervise(evaluation)
    steps.append(
        {
            "step_type": "supervise",
            "thought": "由 Supervisor 决定是否需要补救、重试、降级或家长关注。",
            "decision": supervision,
            "status": str(supervision.get("status") or "ok"),
            "score": float(supervision.get("score", evaluation.get("score", 0.8)) or 0.8),
        }
    )
    steps.append(
        {
            "step_type": "final",
            "thought": "输出最终结果并把运行证据交给 Trace/Eval/日报。",
            "observation": {"status": status, "error": error, "latency_ms": latency_ms},
            "status": status,
            "error": error,
            "score": float(evaluation.get("score", 0.8) or 0.8),
        }
    )
    return {
        "mode": "controlled_runtime_loop",
        "goal": goal,
        "tool_name": tool_name,
        "arguments": arguments,
        "status": status,
        "error": error,
        "latency_ms": latency_ms,
        "validation": validation,
        "observation": observation,
        "evaluation": evaluation,
        "supervision": supervision,
        "trace_steps": steps,
    }


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
                "step_type": "goal",
                "thought": "明确孩子卡住辅导目标，只允许检索资料和给分步提示。",
                "decision": {"goal": goal, "candidate_tools": candidate_tools},
                "status": "ok",
                "score": 1.0,
            },
            {
                "step_index": 2,
                "step_type": "decision",
                "thought": "选择最安全且最相关的只读工具。",
                "tool_name": tool_name,
                "arguments": arguments,
                "decision": {"tool": tool_name, "arguments": arguments},
                "reason": decision.get("reason", ""),
                "validation": validation,
                "status": "ok" if validation.get("ok") else "warn",
                "score": 1.0 if validation.get("ok") else 0.5,
            },
            {
                "step_index": 3,
                "step_type": "tool_call",
                "thought": "执行检索工具并拿到教材依据。",
                "tool_name": tool_name,
                "observation_preview": _preview_observation(observation),
                "status": status,
                "error": error,
                "score": 1.0 if status == "ok" else 0.0,
            },
            {
                "step_index": 4,
                "step_type": "evaluate",
                "thought": "检查是否拿到可用于分步辅导的证据。",
                "decision": {"has_observation": bool(observation), "used_ai_decision": bool(meta.get("used_ai"))},
                "status": status,
                "score": 1.0 if observation else 0.6,
            },
            {
                "step_index": 5,
                "step_type": "final",
                "thought": "将检索观察交给卡住辅导生成器。",
                "observation_preview": _preview_observation(observation),
                "status": status,
                "score": 1.0 if status == "ok" else 0.5,
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


def _default_evaluate(observation: Any, status: str, error: str) -> dict[str, Any]:
    if status != "ok" or error:
        return {"passed": False, "score": 0.4, "reason": error or status}
    if isinstance(observation, dict):
        useful = bool(observation)
        return {"passed": useful, "score": 0.9 if useful else 0.5, "reason": "dict_observation"}
    if isinstance(observation, list):
        return {"passed": bool(observation), "score": 0.9 if observation else 0.5, "reason": "list_observation"}
    return {"passed": observation is not None, "score": 0.8 if observation is not None else 0.5, "reason": "generic_observation"}


def _default_supervise(evaluation: dict[str, Any]) -> dict[str, Any]:
    if evaluation.get("passed", True):
        return {"status": "ok", "action": "continue", "score": evaluation.get("score", 0.8)}
    return {"status": "warn", "action": "fallback_or_remediate", "score": min(float(evaluation.get("score", 0.5) or 0.5), 0.7)}
