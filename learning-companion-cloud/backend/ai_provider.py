from __future__ import annotations

import json
import os
from typing import Any
from urllib import request
from urllib import error as urlerror


PROMPT_TEMPLATE = """
你是武汉小学五年级上册语数英学习陪跑系统的出题老师。
请严格根据【教材范围】和【当天学习内容】出 3-5 道小测题。
不要超出五年级上册课本范围，不要引入竞赛题或初中知识。
输出 JSON 数组，每项字段：
question_type: choice | exact | short
question: 题干
options_json: 选择题选项数组字符串，非选择题用 []
answer: 标准答案
explanation: 简短讲解

【教材范围】
{scope}

【当天学习内容】
{content}
"""

DEFAULT_API_URL = "https://api.openai.com/v1/chat/completions"
DEFAULT_MODEL = "gpt-4o-mini"


def _env_ai_enabled() -> bool:
    return os.getenv("AI_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def _effective_api_url(ai: dict[str, Any]) -> str:
    return normalize_chat_completions_url(
        os.getenv("OPENAI_BASE_URL") or os.getenv("AI_API_URL") or ai.get("api_url") or DEFAULT_API_URL
    )


def _effective_model(ai: dict[str, Any]) -> str:
    return os.getenv("OPENAI_MODEL") or os.getenv("AI_MODEL") or ai.get("model") or DEFAULT_MODEL


def normalize_chat_completions_url(api_url: str) -> str:
    url = (api_url or DEFAULT_API_URL).strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return f"{url}/chat/completions"
    return url


def ai_enabled(settings: dict[str, Any]) -> bool:
    ai = settings.get("ai", {})
    return bool(
        (ai.get("enabled") or _env_ai_enabled())
        and (ai.get("api_url") or os.getenv("AI_API_URL") or os.getenv("OPENAI_BASE_URL") or DEFAULT_API_URL)
        and (os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY"))
    )


def generate_ai_questions(settings: dict[str, Any], scope: str, content: str) -> list[dict[str, Any]]:
    if not ai_enabled(settings):
        return []
    ai = settings.get("ai", {})
    api_url = _effective_api_url(ai)
    model = _effective_model(ai)
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": PROMPT_TEMPLATE.format(scope=scope, content=content),
            }
        ],
        "temperature": 0.3,
    }
    req = request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
        content_text = data["choices"][0]["message"]["content"]
        parsed = _parse_json_array(content_text)
        return [_normalize_item(item) for item in parsed][:5]
    except Exception:
        return []


def call_ai_json(settings: dict[str, Any], prompt: str, fallback: Any) -> Any:
    if not ai_enabled(settings):
        return fallback
    ai = settings.get("ai", {})
    api_url = _effective_api_url(ai)
    model = _effective_model(ai)
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
    }
    req = request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        content_text = data["choices"][0]["message"]["content"]
        start = min([index for index in [content_text.find("{"), content_text.find("[")] if index >= 0], default=-1)
        if start < 0:
            return fallback
        end = max(content_text.rfind("}"), content_text.rfind("]"))
        return json.loads(content_text[start : end + 1])
    except Exception:
        return fallback


def check_ai_connection(settings: dict[str, Any]) -> dict[str, Any]:
    ai = settings.get("ai", {})
    api_url = _effective_api_url(ai)
    model = _effective_model(ai)
    api_key = os.getenv("AI_API_KEY") or os.getenv("OPENAI_API_KEY", "")
    result: dict[str, Any] = {
        "enabled": bool(ai.get("enabled")),
        "api_url_set": bool(api_url),
        "model": model,
        "key_present": bool(api_key),
        "ok": False,
        "status": "not_checked",
        "error": "",
        "message": "",
    }
    if not result["enabled"] or not api_key:
        result["status"] = "disabled_or_missing_key"
        result["message"] = "AI 未启用或缺少 API Key，系统会使用本地规则兜底。"
        return result

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Return exactly this JSON object: {\"ok\": true}"}],
        "temperature": 0,
    }
    req = request.Request(
        api_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            result["ok"] = 200 <= response.status < 300
            result["status"] = str(response.status)
            result["message"] = "AI 连接可用。" if result["ok"] else "AI 连接未通过。"
            return result
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        result["status"] = str(exc.code)
        result["error"] = body[:500]
        result["message"] = "AI 服务返回错误，系统会使用本地规则兜底。"
        return result
    except Exception as exc:
        result["status"] = "exception"
        result["error"] = f"{type(exc).__name__}: {str(exc)[:300]}"
        result["message"] = "AI 检查异常，系统会使用本地规则兜底。"
        return result


def _parse_json_array(text: str) -> list[dict[str, Any]]:
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < start:
        return []
    data = json.loads(text[start : end + 1])
    return data if isinstance(data, list) else []


def _normalize_item(item: dict[str, Any]) -> dict[str, Any]:
    options = item.get("options_json", [])
    if isinstance(options, list):
        options_json = json.dumps(options, ensure_ascii=False)
    else:
        options_json = str(options or "[]")
    return {
        "question_type": item.get("question_type", "short"),
        "question": str(item.get("question", ""))[:300],
        "options_json": options_json,
        "answer": str(item.get("answer", ""))[:200],
        "explanation": str(item.get("explanation", ""))[:300],
    }
