from __future__ import annotations

from datetime import date, datetime
import html
import json
from pathlib import Path
import re
import statistics
from typing import Annotated, Any

import os
import secrets

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

try:
    from .agent import (
        assist_stuck as agent_assist_stuck,
        generate_daily_report as agent_daily_report,
        generate_daily_tasks as agent_daily_tasks,
        generate_quiz as agent_generate_quiz,
        generate_study_plan as agent_generate_study_plan,
        get_agent_overview,
        grade_submission,
        ensure_task_guidance,
    )
    from .agent_core import (
        build_target_insights,
        build_material_coverage,
        index_material,
        list_active_memories,
        list_skill_mastery,
        recommend_daily_adjustments,
        search_material_chunks,
        skill_targets,
    )
    from .ai_provider import check_ai_connection
    from .agent_tool_registry import list_tool_specs
    from .curriculum import CURRICULUM, WUHAN_DEFAULTS, get_subject_units
    from .day_timeline import build_day_timeline
    from .db import dict_rows, dumps, get_conn, init_db, loads, utc_now
    from .importer import import_task_sources
    from .knowledge_graph import rebuild_knowledge_points, weakest_knowledge_points
    from .learning_strategy import build_dynamic_strategy
    from .material_importer import create_material_from_import, extract_image_file, extract_local_file, extract_public_url
    from .notifier import notify
    from .plan_adjuster import adjust_today_plan, apply_ket_level, auto_adjust_after_event, ket_difficulty_suggestion
    from .plan_generator import generate_plan_from_text
    from .planner import generate_daily_tasks, seed_demo_sources
    from .quiz import ensure_quiz_for_task, grade_quiz, missing_required_answers, parent_confirm_quiz, regenerate_quiz_for_task
    from .report import build_daily_report, build_weekly_report
    from .rewards import today_rewards
    from .review import create_review_item, review_book
    from .scheduler import start_scheduler
    from .settings import get_settings, save_settings
    from .study_schedule import arrange_daily_schedule
    from .system_constraints import build_system_constraints
except ImportError:
    from agent import (
        assist_stuck as agent_assist_stuck,
        generate_daily_report as agent_daily_report,
        generate_daily_tasks as agent_daily_tasks,
        generate_quiz as agent_generate_quiz,
        generate_study_plan as agent_generate_study_plan,
        get_agent_overview,
        grade_submission,
        ensure_task_guidance,
    )
    from agent_core import (
        build_target_insights,
        build_material_coverage,
        index_material,
        list_active_memories,
        list_skill_mastery,
        recommend_daily_adjustments,
        search_material_chunks,
        skill_targets,
    )
    from ai_provider import check_ai_connection
    from agent_tool_registry import list_tool_specs
    from curriculum import CURRICULUM, WUHAN_DEFAULTS, get_subject_units
    from day_timeline import build_day_timeline
    from db import dict_rows, dumps, get_conn, init_db, loads, utc_now
    from importer import import_task_sources
    from knowledge_graph import rebuild_knowledge_points, weakest_knowledge_points
    from learning_strategy import build_dynamic_strategy
    from material_importer import create_material_from_import, extract_image_file, extract_local_file, extract_public_url
    from notifier import notify
    from plan_adjuster import adjust_today_plan, apply_ket_level, auto_adjust_after_event, ket_difficulty_suggestion
    from plan_generator import generate_plan_from_text
    from planner import generate_daily_tasks, seed_demo_sources
    from quiz import ensure_quiz_for_task, grade_quiz, missing_required_answers, parent_confirm_quiz, regenerate_quiz_for_task
    from report import build_daily_report, build_weekly_report
    from rewards import today_rewards
    from review import create_review_item, review_book
    from scheduler import start_scheduler
    from settings import get_settings, save_settings
    from study_schedule import arrange_daily_schedule
    from system_constraints import build_system_constraints


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="11岁孩子暑假自主学习陪跑系统", version="1.0.0")

SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"(?i)(OPENAI_API_KEY|API_KEY|ADMIN_PASSWORD|PARENT_PASSWORD)\s*[:=]\s*['\"]?[^\s'\"，。；;]+"),
)


def sanitize_material_text(text: str) -> str:
    clean = text or ""
    for pattern in SECRET_PATTERNS:
        clean = pattern.sub("[REDACTED_SECRET]", clean)
    return clean
security = HTTPBasic(auto_error=False)


def _is_movement_task(task: dict[str, Any] | Any) -> bool:
    getter = task.get if isinstance(task, dict) else task.__getitem__
    text = " ".join(str(getter(key) or "") for key in ("title", "description", "completion_standard", "check_method"))
    return any(word in text for word in ("运动", "体育", "跳绳", "拉伸", "慢跑"))


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=FRONTEND_DIR / "static"), name="static")


@app.on_event("startup")
def startup() -> None:
    _assert_deploy_auth_safe()
    init_db()
    app.state.scheduler = start_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)


def page(name: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / name)


def _parse_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _task_time_stats(conn, task_id: int, status: str | None = None) -> dict[str, object]:
    rows = conn.execute(
        """
        SELECT event_type, created_at
        FROM task_progress
        WHERE daily_task_id = ?
        ORDER BY id
        """,
        (task_id,),
    ).fetchall()
    elapsed_seconds = 0
    running_since: datetime | None = None
    last_started_at = ""
    for row in rows:
        event_time = _parse_utc(row["created_at"])
        if not event_time:
            continue
        if row["event_type"] in {"start", "resume"}:
            if running_since is None:
                running_since = event_time
                last_started_at = row["created_at"]
            else:
                running_since = event_time
                last_started_at = row["created_at"]
        elif row["event_type"] in {"pause", "stuck", "complete", "check", "revise"}:
            if running_since is not None:
                elapsed_seconds += max(0, int((event_time - running_since).total_seconds()))
                running_since = None
                last_started_at = ""
    timer_state = "stopped"
    if status == "in_progress" and running_since is not None:
        now = _parse_utc(utc_now()) or datetime.utcnow()
        elapsed_seconds += max(0, int((now - running_since).total_seconds()))
        timer_state = "running"
    return {
        "elapsed_seconds": elapsed_seconds,
        "timer_state": timer_state,
        "last_started_at": last_started_at if timer_state == "running" else "",
    }


def _clean_display_text(value: object, max_len: int = 140) -> str:
    text = str(value or "").strip()
    replacements = (
        (r"联调验证[-_：:]?", ""),
        (r"-\d{4,}(?=\D|$)", ""),
        (r"stuck 标准答案[:：]?\s*", ""),
        (r"^D\d+\s*补漏[:：]\s*", "补漏："),
        (r"\n?错因/来源[:：].*", ""),
        (r"标准答案[:：].*", ""),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    text = re.sub(r"\?{4,}", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _sanitize_visible_value(value: object, max_len: int = 180) -> object:
    if isinstance(value, str):
        return _clean_display_text(value, max_len)
    if isinstance(value, list):
        return [_sanitize_visible_value(item, max_len) for item in value]
    if isinstance(value, dict):
        return {key: _sanitize_visible_value(item, max_len) for key, item in value.items()}
    return value


def _sanitize_task_for_display(task: dict) -> dict:
    sanitized = dict(task)
    sanitized["title"] = _clean_display_text(sanitized.get("title"), 64)
    sanitized["description"] = _clean_display_text(sanitized.get("description"), 180)
    sanitized["completion_standard"] = _clean_display_text(sanitized.get("completion_standard"), 120)
    return sanitized


def _sanitize_report_for_display(report: dict | None) -> dict | None:
    if not report:
        return None
    raw_report = dict(report)
    sanitized = {key: _sanitize_visible_value(value, 160) for key, value in raw_report.items()}
    for key, max_len in (
        ("summary", 120),
        ("problems", 120),
        ("tomorrow_first_step", 80),
        ("ten_minute_action", 120),
    ):
        if key in sanitized:
            sanitized[key] = _clean_display_text(sanitized.get(key), max_len)
    summary = str(sanitized.get("summary") or "")
    if "小测：" in summary and (summary.count("；") >= 1 or summary.count("：") >= 3):
        completed = raw_report.get("completed_count", 0)
        total = raw_report.get("total_count", 0)
        sanitized["summary"] = f"今日完成 {completed}/{total}。小测结果已记录，需订正的内容看下方小测区。"
    return sanitized


def _sanitize_review_item_for_display(item: dict) -> dict:
    sanitized = dict(item)
    for key, max_len in (
        ("title", 64),
        ("question", 120),
        ("answer", 120),
        ("description", 160),
        ("completion_standard", 120),
        ("explanation", 120),
        ("reason", 80),
    ):
        if key in sanitized:
            sanitized[key] = _clean_display_text(sanitized.get(key), max_len)
    return sanitized


def _sanitize_notification_for_display(item: dict) -> dict:
    sanitized = dict(item)
    for key, max_len in (("title", 64), ("message", 180)):
        if key in sanitized:
            sanitized[key] = _clean_display_text(sanitized.get(key), max_len)
    return sanitized


def _annotate_task(conn, task: dict) -> dict:
    annotated = _sanitize_task_for_display(dict(task))
    latest_quiz = conn.execute(
        """
        SELECT status
        FROM quiz_results
        WHERE daily_task_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (int(annotated["id"]),),
    ).fetchone()
    if latest_quiz and latest_quiz["status"] in {"needs_revision", "completed"}:
        annotated["status"] = latest_quiz["status"]
    annotated.update(_task_time_stats(conn, int(annotated["id"]), str(annotated.get("status", ""))))
    return annotated


def _annotate_tasks(conn, tasks: list[dict]) -> list[dict]:
    return [_annotate_task(conn, dict(task)) for task in tasks]


def _start_blocker(conn, task, current_status: str):
    blocker = conn.execute(
        """
        SELECT id, title, status
        FROM daily_tasks
        WHERE student_id = ?
          AND date = ?
          AND id != ?
          AND status IN ('checking', 'needs_revision', 'stuck', 'in_progress', 'paused')
        ORDER BY
          CASE WHEN sort_order = 0 THEN 999999 ELSE sort_order END,
          priority,
          id
        LIMIT 1
        """,
        (task["student_id"], task["date"], task["id"]),
    ).fetchone()
    if blocker:
        return blocker
    if current_status == "not_started":
        first_not_started = conn.execute(
            """
            SELECT id, title, status
            FROM daily_tasks
            WHERE student_id = ?
              AND date = ?
              AND status = 'not_started'
            ORDER BY
              CASE WHEN sort_order = 0 THEN 999999 ELSE sort_order END,
              priority,
              id
            LIMIT 1
            """,
            (task["student_id"], task["date"]),
        ).fetchone()
        if first_not_started and int(first_not_started["id"]) != int(task["id"]):
            return first_not_started
    return None


def _render_child_task_fallback(tasks: list[dict]) -> str:
    if not tasks:
        return '<p class="muted">今天还没有任务，请让家长在管理端生成。</p>'
    cards: list[str] = []
    status_text = {
        "not_started": "未开始",
        "in_progress": "进行中",
        "paused": "已暂停",
        "checking": "检查中",
        "completed": "已完成",
        "needs_revision": "需订正",
        "stuck": "卡住了",
    }
    check_method_text = {
        "quiz": "完成后做小测",
        "review_quiz": "补漏复测",
        "checklist_quiz": "完成后检查",
    }
    for task in tasks:
        task_id = int(task["id"])
        status = str(task.get("status", "not_started"))
        cards.append(
            f"""
            <article class="task-card {'active' if status == 'in_progress' else ''}">
              <div class="task-head">
                <div>
                  <h3 class="task-title">{html.escape(str(task.get("title", "")))}</h3>
                  <p class="muted">{html.escape(str(task.get("description", "")))}</p>
                </div>
                <div class="task-meta">
                  <span class="tag {'p0' if task.get("priority") == "P0" else ''}">{html.escape(str(task.get("priority", "")))}</span>
                  <span class="tag">{html.escape(status_text.get(status, status))}</span>
                </div>
              </div>
              <div class="task-meta">
                <span class="tag">{int(task.get("estimated_minutes", 0) or 0)} 分钟</span>
                <span class="tag">已学 {int(int(task.get("elapsed_seconds", 0) or 0) / 60)} 分钟</span>
                <span class="tag">{html.escape(check_method_text.get(str(task.get("check_method", "")), "完成后检查"))}</span>
              </div>
              <p><strong>完成标准：</strong>{html.escape(str(task.get("completion_standard", "")))}</p>
              <div class="actions">
                <button class="primary" data-action="start" data-id="{task_id}">开始</button>
                <button data-action="pause" data-id="{task_id}">暂停</button>
                <button class="warn" data-action="complete" data-id="{task_id}">我做完了，开始检查</button>
                <button class="danger" data-action="stuck" data-id="{task_id}">我卡住了</button>
              </div>
            </article>
            """
        )
    return "\n".join(cards)


def _check_basic(
    credentials: HTTPBasicCredentials | None,
    expected_user: str,
    expected_password: str,
) -> bool:
    if not expected_password:
        return _local_auth_disabled()
    if credentials is None:
        return False
    return secrets.compare_digest(credentials.username, expected_user) and secrets.compare_digest(
        credentials.password,
        expected_password,
    )


def _local_auth_disabled() -> bool:
    if _public_bind_requires_auth():
        return False
    return not (
        os.getenv("CHILD_PASSWORD", "")
        or os.getenv("PARENT_PASSWORD", "")
        or os.getenv("ADMIN_PASSWORD", "")
    )


def _public_bind_requires_auth() -> bool:
    host = os.getenv("APP_HOST", os.getenv("HOST", "127.0.0.1")).strip()
    public_mode = os.getenv("PUBLIC_DEPLOY", "").strip().lower() in {"1", "true", "yes", "on"}
    return public_mode or host in {"0.0.0.0", "::"}


def _assert_deploy_auth_safe() -> None:
    if not _public_bind_requires_auth():
        return
    missing = [name for name in ("CHILD_PASSWORD", "PARENT_PASSWORD", "ADMIN_PASSWORD") if not os.getenv(name, "")]
    if missing:
        raise RuntimeError(
            "公网/局域网绑定必须配置登录密码，缺少：" + ", ".join(missing) + "。"
            "本机自用请用 APP_HOST=127.0.0.1；需要局域网访问请设置三类密码。"
        )


def _auth_failed(detail: str = "需要认证") -> None:
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Basic"},
    )


def require_parent_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    expected_user = os.getenv("PARENT_USER", "parent")
    expected_password = os.getenv("PARENT_PASSWORD", "")
    if _check_basic(credentials, expected_user, expected_password):
        return "local"
    _auth_failed("认证失败")


def require_child_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    expected_user = os.getenv("CHILD_USER", "child")
    expected_password = os.getenv("CHILD_PASSWORD", "")
    if _check_basic(credentials, expected_user, expected_password):
        return "local"
    _auth_failed("认证失败")


def require_admin_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    expected_user = os.getenv("ADMIN_USER", "admin")
    expected_password = os.getenv("ADMIN_PASSWORD", "")
    if _check_basic(credentials, expected_user, expected_password):
        return "local"
    _auth_failed("认证失败")


def require_child_or_admin_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    if _check_basic(credentials, os.getenv("CHILD_USER", "child"), os.getenv("CHILD_PASSWORD", "")):
        return "child"
    if _check_basic(credentials, os.getenv("ADMIN_USER", "admin"), os.getenv("ADMIN_PASSWORD", "")):
        return "admin"
    _auth_failed("认证失败")


def require_parent_or_admin_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    if _check_basic(credentials, os.getenv("PARENT_USER", "parent"), os.getenv("PARENT_PASSWORD", "")):
        return "parent"
    if _check_basic(credentials, os.getenv("ADMIN_USER", "admin"), os.getenv("ADMIN_PASSWORD", "")):
        return "admin"
    _auth_failed("认证失败")


def require_any_role_auth(credentials: HTTPBasicCredentials | None = Depends(security)) -> str:
    if _check_basic(credentials, os.getenv("CHILD_USER", "child"), os.getenv("CHILD_PASSWORD", "")):
        return "child"
    if _check_basic(credentials, os.getenv("PARENT_USER", "parent"), os.getenv("PARENT_PASSWORD", "")):
        return "parent"
    if _check_basic(credentials, os.getenv("ADMIN_USER", "admin"), os.getenv("ADMIN_PASSWORD", "")):
        return "admin"
    _auth_failed("认证失败")


@app.get("/", response_class=HTMLResponse)
def index() -> RedirectResponse:
    return RedirectResponse("/child")


@app.get("/child", response_class=HTMLResponse)
def child_page(_: str = Depends(require_child_auth)) -> HTMLResponse:
    html_text = (FRONTEND_DIR / "child.html").read_text(encoding="utf-8")
    today = date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
            (1, today),
        ).fetchall()
        if not rows:
            result = agent_daily_tasks(conn, 1, today)
            rows = result["tasks"]
        tasks = _annotate_tasks(conn, [dict(row) for row in rows])
    done_count = sum(1 for task in tasks if task.get("status") == "completed")
    total_count = len(tasks)
    fallback_html = _render_child_task_fallback(tasks)
    current_task_html = _render_child_task_fallback(tasks[:1])
    current_placeholder = """<div id="currentTask" class="current-task-shell">
            <div class="empty-state">
              <strong>正在加载当前任务...</strong>
              <p>系统会自动选出现在最该做的一项。</p>
            </div>
          </div>"""
    html_text = html_text.replace(
        current_placeholder,
        f'<div id="currentTask" class="current-task-shell">{current_task_html}</div>',
    )
    html_text = html_text.replace(
        '<div id="tasks" class="task-list compact-task-list"><p class="muted">正在加载今日任务...</p></div>',
        f'<div id="tasks" class="task-list compact-task-list">{fallback_html}</div>',
    )
    html_text = html_text.replace('<span id="doneCount">0</span>', f'<span id="doneCount">{done_count}</span>')
    html_text = html_text.replace('<span id="totalCount">0</span>', f'<span id="totalCount">{total_count}</span>')
    initial_data = json.dumps(tasks, ensure_ascii=False)
    html_text = html_text.replace(
        "let tasks = [];",
        f"window.__INITIAL_TASKS__ = {initial_data};\n      let tasks = window.__INITIAL_TASKS__ || [];",
    )
    return HTMLResponse(html_text, headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"})


@app.get("/parent", response_class=HTMLResponse)
def parent_page(_: str = Depends(require_parent_auth)) -> FileResponse:
    return page("parent.html")


@app.get("/admin", response_class=HTMLResponse)
def admin_page(_: str = Depends(require_admin_auth)) -> FileResponse:
    return page("admin.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "date": date.today().isoformat()}


@app.get("/api/curriculum")
def curriculum(subject: str | None = None, version: str | None = None, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    if subject:
        return {"defaults": WUHAN_DEFAULTS, "subject": subject, "units": get_subject_units(subject, version)}
    return {"defaults": WUHAN_DEFAULTS, "curriculum": CURRICULUM, "subjects": CURRICULUM}


@app.get("/api/settings")
def read_settings(_: str = Depends(require_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return get_settings(conn)


@app.post("/api/settings")
async def update_settings(request: Request, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    payload = await request.json()
    with get_conn() as conn:
        return save_settings(conn, payload)


@app.get("/api/ai/check")
def ai_check(_: str = Depends(require_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return check_ai_connection(get_settings(conn))


@app.get("/api/task-sources")
def list_task_sources(student_id: int = 1, _: str = Depends(require_admin_auth)) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM task_sources WHERE student_id = ? ORDER BY status, category, id DESC",
            (student_id,),
        ).fetchall()
        result = dict_rows(rows)
        for item in result:
            item["config"] = loads(item.pop("config_json"), {})
            item["coverage"] = loads(item.pop("coverage_json", None), {})
        return result


@app.post("/api/task-sources")
def create_task_source(
    category: Annotated[str, Form()],
    title: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    total_units: Annotated[int, Form()] = 1,
    completed_units: Annotated[int, Form()] = 0,
    deadline: Annotated[str, Form()] = "",
    module: Annotated[str, Form()] = "",
    topic: Annotated[str, Form()] = "",
    lesson_content: Annotated[str, Form()] = "",
    knowledge_points: Annotated[str, Form()] = "",
    vocabulary: Annotated[str, Form()] = "",
    estimated_minutes: Annotated[int, Form()] = 25,
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_admin_auth),
) -> dict[str, int | str]:
    if category not in {"summer_homework", "preview", "ket"}:
        raise HTTPException(status_code=400, detail="category 不合法")
    now = utc_now()
    config = {
        "module": module,
        "topic": topic,
        "lesson_content": lesson_content,
        "knowledge_points": knowledge_points,
        "vocabulary": vocabulary,
        "estimated_minutes": estimated_minutes,
    }
    with get_conn() as conn:
        cursor = conn.execute(
            """
            INSERT INTO task_sources (
                student_id, category, title, subject, total_units, completed_units,
                deadline, config_json, status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
            """,
            (
                student_id,
                category,
                title.strip(),
                subject.strip(),
                max(total_units, 1),
                max(completed_units, 0),
                deadline.strip() or None,
                dumps(config),
                now,
                now,
            ),
        )
        return {"id": cursor.lastrowid, "status": "created"}


@app.get("/api/materials/search")
def search_materials(
    q: str,
    subject: str = "",
    student_id: int = 1,
    _: str = Depends(require_parent_or_admin_auth),
) -> list[dict[str, object]]:
    with get_conn() as conn:
        return search_material_chunks(conn, q, subject, student_id)


@app.get("/api/materials/coverage")
def material_coverage(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return build_material_coverage(conn, student_id)


@app.post("/api/materials/{material_id}/index")
def reindex_material(material_id: int, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        result = index_material(conn, material_id)
        result["knowledge_graph"] = rebuild_knowledge_points(conn, int(result.get("student_id", 1)) if "student_id" in result else 1)
        return result


@app.get("/api/learning-targets")
def learning_targets(_: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    return skill_targets()


@app.post("/api/knowledge/rebuild")
def rebuild_knowledge(student_id: int = 1, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return rebuild_knowledge_points(conn, student_id)


@app.get("/api/knowledge/weak-points")
def knowledge_weak_points(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> list[dict[str, object]]:
    with get_conn() as conn:
        return weakest_knowledge_points(conn, student_id)


@app.get("/api/agent/strategy")
def agent_strategy(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return build_dynamic_strategy(conn, student_id, target_date or date.today().isoformat())


@app.get("/api/agent/tools")
def agent_tools(_: str = Depends(require_parent_or_admin_auth)) -> list[dict[str, object]]:
    return list_tool_specs()


@app.get("/api/agent/traces/{trace_id}")
def agent_trace(trace_id: str, _: str = Depends(require_parent_or_admin_auth)) -> list[dict[str, object]]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM agent_trace_steps
            WHERE trace_id = ?
            ORDER BY step_index, id
            """,
            (trace_id,),
        ).fetchall()
        result = dict_rows(rows)
        for item in result:
            item["args"] = loads(item.pop("args_json"), {})
            item["decision"] = loads(item.pop("decision_json", "{}"), {})
            item["observation"] = loads(item.pop("observation_json"), {})
            item["validation"] = loads(item.pop("validation_json"), {})
        return result


@app.get("/api/student/mastery")
def student_mastery(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> list[dict[str, object]]:
    with get_conn() as conn:
        return list_skill_mastery(conn, student_id)


@app.get("/api/student/memory")
def student_memory(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> list[dict[str, object]]:
    with get_conn() as conn:
        return list_active_memories(conn, student_id)


@app.get("/api/parent/insights")
def parent_insights(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return build_target_insights(conn, student_id)


@app.get("/api/agent/daily-adjustments")
def daily_adjustments(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return recommend_daily_adjustments(conn, student_id, target_date)


@app.get("/api/materials")
def list_materials(student_id: int = 1, _: str = Depends(require_admin_auth)) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT lm.*, ts.title AS source_title
            FROM learning_materials lm
            LEFT JOIN task_sources ts ON ts.id = lm.source_id
            WHERE lm.student_id = ?
            ORDER BY lm.id DESC
            LIMIT 100
            """,
            (student_id,),
        ).fetchall()
        result = dict_rows(rows)
        for item in result:
            item["config"] = loads(item.pop("config_json"), {})
        return result


@app.post("/api/materials")
def create_material(
    title: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    material_type: Annotated[str, Form()] = "notes",
    content_text: Annotated[str, Form()] = "",
    file_path: Annotated[str, Form()] = "",
    source_id: Annotated[int, Form()] = 0,
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    allowed = {"textbook_pdf", "word_list", "dictation", "audio_list", "notes"}
    if material_type not in allowed:
        raise HTTPException(status_code=400, detail="material_type 不合法")
    if not title.strip():
        raise HTTPException(status_code=400, detail="资料标题不能为空")
    now = utc_now()
    with get_conn() as conn:
        if source_id:
            source = conn.execute(
                "SELECT id FROM task_sources WHERE id = ? AND student_id = ?",
                (source_id, student_id),
            ).fetchone()
            if not source:
                raise HTTPException(status_code=400, detail="source_id 不存在")
        cursor = conn.execute(
            """
            INSERT INTO learning_materials (
                student_id, source_id, subject, material_type, title,
                content_text, file_path, config_json, source_type, trust_level, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_id,
                source_id or None,
                subject.strip(),
                material_type,
                title.strip(),
                sanitize_material_text(content_text).strip(),
                file_path.strip(),
                dumps({"source": "admin"}),
                "admin_text",
                "user_provided",
                now,
                now,
            ),
        )
        material_id = int(cursor.lastrowid)
        indexed = index_material(conn, material_id)
        knowledge = rebuild_knowledge_points(conn, student_id)
        return {"id": material_id, "status": "created", "rag_index": indexed, "knowledge_graph": knowledge}


@app.post("/api/materials/import-file")
def import_material_file(
    file_path: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    material_type: Annotated[str, Form()] = "textbook_pdf",
    title: Annotated[str, Form()] = "",
    source_id: Annotated[int, Form()] = 0,
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    allowed = {"textbook_pdf", "word_list", "dictation", "audio_list", "notes"}
    if material_type not in allowed:
        raise HTTPException(status_code=400, detail="material_type 不合法")
    try:
        extracted = extract_local_file(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with get_conn() as conn:
        result = create_material_from_import(
            conn,
            student_id=student_id,
            subject=subject,
            material_type=material_type,
            title=title.strip() or extracted["title"],
            content_text=sanitize_material_text(extracted["content_text"]),
            file_path=extracted["file_path"],
            source_id=source_id,
            source_type="local_file",
            extra_config=extracted["meta"],
        )
        result["knowledge_graph"] = rebuild_knowledge_points(conn, student_id)
        return result


@app.post("/api/materials/import-url")
def import_material_url(
    url: Annotated[str, Form()],
    subject: Annotated[str, Form()] = "",
    material_type: Annotated[str, Form()] = "notes",
    title: Annotated[str, Form()] = "",
    source_id: Annotated[int, Form()] = 0,
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    allowed = {"textbook_pdf", "word_list", "dictation", "audio_list", "notes"}
    if material_type not in allowed:
        raise HTTPException(status_code=400, detail="material_type 不合法")
    try:
        extracted = extract_public_url(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with get_conn() as conn:
        result = create_material_from_import(
            conn,
            student_id=student_id,
            subject=subject,
            material_type=material_type,
            title=title.strip() or extracted["title"],
            content_text=sanitize_material_text(extracted["content_text"]),
            file_path=extracted["file_path"],
            source_id=source_id,
            source_type="public_url",
            extra_config=extracted["meta"],
        )
        result["knowledge_graph"] = rebuild_knowledge_points(conn, student_id)
        return result


@app.post("/api/daily-tasks/{task_id}/stuck-photo")
async def upload_stuck_photo(
    task_id: int,
    file: UploadFile = File(...),
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_child_or_admin_auth),
) -> dict[str, object]:
    suffix = Path(file.filename or "question.jpg").suffix.lower() or ".jpg"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".heic", ".heif"}:
        raise HTTPException(status_code=400, detail="只支持拍照图片：JPG、PNG、WEBP、BMP、HEIC")
    upload_dir = BASE_DIR / "data" / "uploads" / "stuck"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", Path(file.filename or f"task-{task_id}{suffix}").name)
    target = upload_dir / f"task-{task_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{safe_name}"
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="图片为空，请重新拍照上传。")
    if len(raw) > 12 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片太大，请压缩到 12MB 以内。")
    target.write_bytes(raw)
    try:
        extracted = extract_image_file(str(target))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ? AND student_id = ?", (task_id, student_id)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        title = f"题目拍照：{task['title']}"
        result = create_material_from_import(
            conn,
            student_id=student_id,
            subject="",
            material_type="notes",
            title=title,
            content_text=sanitize_material_text(extracted["content_text"]),
            file_path=extracted["file_path"],
            source_id=int(task["source_id"] or 0),
            source_type="uploaded_stuck_photo",
            extra_config={"task_id": task_id, **extracted["meta"]},
        )
        return {
            "task_id": task_id,
            "material_id": result["id"],
            "file_path": str(target),
            "text": extracted["content_text"],
            "chars": len(extracted["content_text"]),
        }


@app.post("/api/task-sources/seed")
def seed_sources(student_id: int = 1, _: str = Depends(require_admin_auth)) -> dict[str, int]:
    with get_conn() as conn:
        student = conn.execute("SELECT id FROM students WHERE id = ?", (student_id,)).fetchone()
        if not student:
            raise HTTPException(status_code=400, detail="student_id 不存在")
        return {"created": seed_demo_sources(conn, student_id)}


@app.post("/api/task-sources/import")
def import_sources(
    raw_text: Annotated[str, Form()],
    default_deadline: Annotated[str, Form()] = "",
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return import_task_sources(conn, raw_text, student_id, default_deadline or None)


@app.post("/api/study-plan/generate")
def generate_study_plan(
    raw_text: Annotated[str, Form()],
    student_id: Annotated[int, Form()] = 1,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return agent_generate_study_plan(conn, raw_text, student_id)


@app.post("/api/agent/plan")
def agent_plan(data: dict[str, Any], _: str = Depends(require_admin_auth)) -> dict[str, object]:
    goal = data.get("goal") or data.get("raw_text") or ""
    student_id = int(data.get("student_id", 1))
    with get_conn() as conn:
        return agent_generate_study_plan(conn, goal, student_id)


@app.get("/api/daily-tasks")
def list_daily_tasks(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_child_or_admin_auth),
) -> list[dict]:
    today = target_date or date.today().isoformat()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT * FROM daily_tasks
            WHERE student_id = ? AND date = ?
            ORDER BY
                CASE WHEN planned_start IS NULL OR planned_start = '' THEN '99:99' ELSE planned_start END,
                CASE WHEN sort_order = 0 THEN 999999 ELSE sort_order END,
                priority,
                id
            """,
            (student_id, today),
        ).fetchall()
        if not rows:
            result = agent_daily_tasks(conn, student_id, today)
            rows = result["tasks"]
            if rows:
                notify(conn, student_id, "tasks_generated", "今日学习任务已自动生成", f"今天共有 {len(rows)} 个任务。")
                return _annotate_tasks(conn, [dict(row) for row in rows])
        elif any(not row["planned_start"] for row in rows):
            arrange_daily_schedule(conn, student_id, today)
            rows = conn.execute(
                """
                SELECT * FROM daily_tasks
                WHERE student_id = ? AND date = ?
                ORDER BY
                    CASE WHEN planned_start IS NULL OR planned_start = '' THEN '99:99' ELSE planned_start END,
                    CASE WHEN sort_order = 0 THEN 999999 ELSE sort_order END,
                    priority,
                    id
                """,
                (student_id, today),
            ).fetchall()
        return _annotate_tasks(conn, dict_rows(rows))


@app.get("/api/day-timeline")
def day_timeline(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_child_or_admin_auth),
) -> dict[str, object]:
    today = target_date or date.today().isoformat()
    tasks = list_daily_tasks(student_id=student_id, target_date=today, _=_)
    return {"date": today, **build_day_timeline(tasks)}


@app.post("/api/daily-tasks/generate")
def generate_tasks(
    student_id: int = 1,
    target_date: str | None = None,
    force_all_sources: bool = False,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    today = target_date or date.today().isoformat()
    with get_conn() as conn:
        result = agent_daily_tasks(conn, student_id, today, force_all_sources=force_all_sources)
        tasks = _annotate_tasks(conn, [dict(task) for task in result["tasks"]])
        notify(conn, student_id, "tasks_generated", "今日学习任务已生成", f"今天共有 {len(tasks)} 个任务。")
        return {"date": today, "count": len(tasks), "tasks": tasks, "timeline": build_day_timeline(tasks)}


@app.post("/api/daily-tasks/schedule")
def schedule_tasks(data: dict[str, Any], _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    student_id = int(data.get("student_id", 1))
    target_date = data.get("target_date") or date.today().isoformat()
    order = data.get("order") or []
    with get_conn() as conn:
        if isinstance(order, list) and order:
            now = utc_now()
            for index, task_id in enumerate(order, start=1):
                conn.execute(
                    """
                    UPDATE daily_tasks
                    SET sort_order = ?, schedule_reason = ?, updated_at = ?
                    WHERE id = ? AND student_id = ? AND date = ?
                    """,
                    (index * 10, "家长手动调整顺序；系统重新分配时间段。", now, int(task_id), student_id, target_date),
                )
        tasks = _annotate_tasks(conn, arrange_daily_schedule(conn, student_id, target_date, respect_existing_order=bool(order)))
        return {"date": target_date, "count": len(tasks), "tasks": tasks, "timeline": build_day_timeline(tasks)}


@app.post("/api/agent/daily-tasks")
def agent_daily_tasks_endpoint(data: dict[str, Any], _: str = Depends(require_admin_auth)) -> dict[str, object]:
    student_id = int(data.get("student_id", 1))
    target_date = data.get("target_date") or date.today().isoformat()
    force_all_sources = bool(data.get("force_all_sources", False))
    with get_conn() as conn:
        result = agent_daily_tasks(conn, student_id, target_date, force_all_sources=force_all_sources)
        result["tasks"] = _annotate_tasks(conn, [dict(task) for task in result["tasks"]])
        result["date"] = target_date
        return result


@app.post("/api/daily-tasks/{task_id}/event")
def task_event(task_id: int, data: dict[str, Any], _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    event_type = data.get("event_type", "")
    note = data.get("note", "")
    status_map = {
        "start": "in_progress",
        "resume": "in_progress",
        "pause": "paused",
        "stuck": "stuck",
        "complete": "checking",
        "revise": "needs_revision",
    }
    if event_type not in status_map:
        raise HTTPException(status_code=400, detail="event_type 不合法")
    now = utc_now()
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        current_status = task["status"]
        latest_quiz = conn.execute(
            """
            SELECT status
            FROM quiz_results
            WHERE daily_task_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (task_id,),
        ).fetchone()
        if latest_quiz and latest_quiz["status"] in {"needs_revision", "completed"}:
            current_status = latest_quiz["status"]
        if event_type in {"start", "resume"} and current_status == "in_progress":
            return {"task_id": task_id, "status": current_status, **_task_time_stats(conn, task_id, current_status), "already_applied": True}
        if event_type in {"start", "resume"} and current_status in {"checking", "completed", "needs_revision"}:
            return {"task_id": task_id, "status": current_status, **_task_time_stats(conn, task_id, current_status), "blocked": True}
        if event_type in {"start", "resume"}:
            blocker = _start_blocker(conn, task, current_status)
            if blocker:
                return {
                    "task_id": task_id,
                    "status": current_status,
                    **_task_time_stats(conn, task_id, current_status),
                    "blocked": True,
                    "blocked_by": _sanitize_task_for_display({"id": blocker["id"], "title": blocker["title"], "status": blocker["status"]}),
                }
        if event_type == "pause" and current_status != "in_progress":
            return {"task_id": task_id, "status": current_status, **_task_time_stats(conn, task_id, current_status), "already_applied": True}
        if event_type == "complete" and current_status == "not_started":
            return {"task_id": task_id, "status": current_status, **_task_time_stats(conn, task_id, current_status), "blocked": True}
        if event_type == "complete" and current_status in {"checking", "completed"}:
            return {"task_id": task_id, "status": current_status, **_task_time_stats(conn, task_id, current_status), "already_applied": True}
        if event_type == "complete" and _is_movement_task(task):
            conn.execute(
                "UPDATE daily_tasks SET status = 'completed', updated_at = ? WHERE id = ?",
                (now, task_id),
            )
            conn.execute(
                "INSERT INTO task_progress (daily_task_id, event_type, note, created_at) VALUES (?, 'complete', ?, ?)",
                (task_id, note or "运动打卡完成", now),
            )
            dynamic_adjustment = auto_adjust_after_event(conn, task_id, "complete")
            return {"task_id": task_id, "status": "completed", "movement_completed": True, "dynamic_adjustment": dynamic_adjustment, **_task_time_stats(conn, task_id, "completed")}
        conn.execute(
            "UPDATE daily_tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status_map[event_type], now, task_id),
        )
        conn.execute(
            "INSERT INTO task_progress (daily_task_id, event_type, note, created_at) VALUES (?, ?, ?, ?)",
            (task_id, event_type, note, now),
        )
        if event_type == "stuck":
            assistance = agent_assist_stuck(conn, task_id, note)
            create_review_item(
                conn,
                int(task["student_id"]),
                task_id,
                task["title"],
                task["completion_standard"],
                note or task["description"],
                "stuck",
                1,
            )
            notify(conn, task["student_id"], "stuck", "孩子卡住了", f"{task['title']}\n\n说明：{note or '未填写'}")
            dynamic_adjustment = auto_adjust_after_event(conn, task_id, event_type)
            return {"task_id": task_id, **assistance, "status": status_map[event_type], "dynamic_adjustment": dynamic_adjustment, **_task_time_stats(conn, task_id, status_map[event_type])}
        dynamic_adjustment = auto_adjust_after_event(conn, task_id, event_type)
        return {"task_id": task_id, "status": status_map[event_type], "dynamic_adjustment": dynamic_adjustment, **_task_time_stats(conn, task_id, status_map[event_type])}


@app.get("/api/daily-tasks/{task_id}/quiz")
def get_quiz(task_id: int, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        result = agent_generate_quiz(conn, task_id)
        return {"task": _sanitize_task_for_display(dict(task)), "items": result["items"], "quality": result.get("quality", {})}


@app.get("/api/agent/task-guidance/{task_id}")
def agent_task_guidance(task_id: int, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return ensure_task_guidance(conn, task_id)


@app.post("/api/daily-tasks/{task_id}/quiz/regenerate")
def regenerate_quiz(task_id: int, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return agent_generate_quiz(conn, task_id, force=True)


@app.post("/api/daily-tasks/{task_id}/quiz")
def submit_quiz(task_id: int, data: dict[str, Any], _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    answers = data.get("answers", {})
    if not isinstance(answers, dict):
        raise HTTPException(status_code=400, detail={"message": "答案格式不正确，请重新填写小测。"})
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        if data.get("parent_confirmed") is True or answers.get("__parent_confirmed__") == "true":
            method = str(data.get("confirmation_method") or answers.get("__confirmation_method__") or "oral")
            return parent_confirm_quiz(conn, task_id, method)
        missing = missing_required_answers(conn, task_id, answers)
        if missing:
            raise HTTPException(
                status_code=400,
                detail={"message": "请先完成所有小测题，再提交。", "missing": missing},
            )
        return grade_submission(conn, task_id, answers)


@app.post("/api/agent/grade/{task_id}")
def agent_grade(task_id: int, data: dict[str, Any], _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    answers = data.get("answers", {})
    if not isinstance(answers, dict):
        raise HTTPException(status_code=400, detail={"message": "答案格式不正确，请重新填写小测。"})
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        missing = missing_required_answers(conn, task_id, answers)
        if missing:
            raise HTTPException(
                status_code=400,
                detail={"message": "请先完成所有小测题，再提交。", "missing": missing},
            )
        return grade_submission(conn, task_id, answers)


@app.post("/api/day/end")
def end_day(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_any_role_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return agent_daily_report(conn, student_id, target_date or date.today().isoformat())


@app.post("/api/day/adjust")
def adjust_day(
    data: dict[str, Any],
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    student_id = int(data.get("student_id", 1))
    target_date = data.get("target_date") or date.today().isoformat()
    mode = str(data.get("mode") or "rebalance")
    with get_conn() as conn:
        result = adjust_today_plan(conn, student_id, target_date, mode)
        notify(conn, student_id, "parent_adjust", "家长调整了今日计划", f"模式：{mode}；结果：{result.get('message', '')}")
        tasks = _annotate_tasks(conn, result.pop("tasks", []))
        return {**result, "tasks": tasks, "timeline": build_day_timeline(tasks)}


@app.get("/api/system-constraints")
def system_constraints(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return build_system_constraints(conn, student_id, target_date or date.today().isoformat())


@app.get("/api/ket/difficulty")
def ket_difficulty(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return ket_difficulty_suggestion(conn, student_id)


@app.post("/api/ket/difficulty")
def update_ket_difficulty(data: dict[str, Any], _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    level = str(data.get("level") or "standard")
    student_id = int(data.get("student_id", 1))
    with get_conn() as conn:
        return apply_ket_level(conn, level, student_id)


@app.post("/api/agent/daily-report")
def agent_report(data: dict[str, Any], _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return agent_daily_report(conn, int(data.get("student_id", 1)), data.get("target_date") or date.today().isoformat())


@app.post("/api/week/report")
def week_report(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return build_weekly_report(conn, student_id, target_date or date.today().isoformat())


@app.get("/api/review-items")
def review_items(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> list[dict]:
    with get_conn() as conn:
        return dict_rows(
            conn.execute(
                """
                SELECT * FROM review_items
                WHERE student_id = ?
                ORDER BY
                    CASE status
                        WHEN 'pending' THEN 1
                        WHEN 'scheduled' THEN 2
                        WHEN 'done' THEN 3
                        ELSE 4
                    END,
                    due_date,
                    id DESC
                LIMIT 100
                """,
                (student_id,),
            ).fetchall()
        )


@app.get("/api/review-book")
def read_review_book(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return review_book(conn, student_id)


@app.get("/api/agent/overview")
def agent_overview(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return get_agent_overview(conn, student_id)


@app.get("/api/agent/metrics")
def agent_metrics(student_id: int = 1, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        runs = dict_rows(
            conn.execute(
                """
                SELECT id, run_type, model, status, error, latency_ms, quality_score, trace_id, created_at
                FROM agent_runs
                WHERE student_id = ?
                ORDER BY id DESC
                LIMIT 500
                """,
                (student_id,),
            ).fetchall()
        )
        latencies = sorted(int(run.get("latency_ms") or 0) for run in runs)
        trace_rows = dict_rows(
            conn.execute(
                """
                SELECT step_type, status, score
                FROM agent_trace_steps
                WHERE trace_id IN (
                    SELECT trace_id FROM agent_runs WHERE student_id = ? ORDER BY id DESC LIMIT 100
                )
                """,
                (student_id,),
            ).fetchall()
        )
    fallback_count = sum(1 for run in runs if run.get("model") == "rule" or run.get("status") in {"rule_fallback", "disabled_or_missing_key"})
    error_count = sum(1 for run in runs if run.get("error") or run.get("status") == "error")
    ai_count = sum(1 for run in runs if run.get("model") not in {"", "rule", None})
    required_steps = {"goal", "plan", "decision", "tool_call", "observation", "evaluate", "supervise", "final"}
    observed_steps = {str(row.get("step_type") or "") for row in trace_rows}
    return {
        "total_runs": len(runs),
        "ai_runs": ai_count,
        "fallback_rate": round(fallback_count / max(len(runs), 1), 3),
        "error_rate": round(error_count / max(len(runs), 1), 3),
        "latency_ms": {
            "p50": _percentile(latencies, 0.5),
            "p95": _percentile(latencies, 0.95),
            "avg": round(statistics.mean(latencies), 1) if latencies else 0,
        },
        "trace": {
            "step_count": len(trace_rows),
            "observed_types": sorted(observed_steps),
            "missing_standard_types": sorted(required_steps - observed_steps),
            "avg_step_score": round(statistics.mean(float(row.get("score") or 0) for row in trace_rows), 3) if trace_rows else 0,
        },
        "recent_status": runs[:20],
    }


def _percentile(values: list[int], ratio: float) -> int:
    if not values:
        return 0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * ratio)))
    return int(values[index])


@app.get("/api/parent/dashboard")
def parent_dashboard(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    today = target_date or date.today().isoformat()
    with get_conn() as conn:
        tasks = _annotate_tasks(
            conn,
            dict_rows(
                conn.execute(
                    "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
                    (student_id, today),
                ).fetchall()
            ),
        )
        quiz_results = dict_rows(
            conn.execute(
                """
                SELECT qr.*, dt.title
                FROM quiz_results qr
                JOIN daily_tasks dt ON dt.id = qr.daily_task_id
                WHERE dt.student_id = ? AND dt.date = ?
                ORDER BY qr.id DESC
                """,
                (student_id, today),
            ).fetchall()
        )
        for result in quiz_results:
            result["title"] = _clean_display_text(result.get("title"), 64)
            result["wrong_items"] = loads(result.pop("wrong_items_json"), [])
            result["score"] = loads(result.pop("score_json", None), {})
            result["error_types"] = loads(result.pop("error_types_json", None), {})
            result["mastery"] = loads(result.pop("mastery_json", None), {})
            result["wrong_items"] = _sanitize_visible_value(result["wrong_items"], 180)
        report = conn.execute(
            "SELECT * FROM daily_reports WHERE student_id = ? AND date = ?",
            (student_id, today),
        ).fetchone()
        notifications = dict_rows(
            conn.execute(
                """
                SELECT * FROM notification_logs
                WHERE student_id = ?
                ORDER BY id DESC LIMIT 20
                """,
                (student_id,),
            ).fetchall()
        )
        completed = sum(1 for task in tasks if task["status"] == "completed")
        review_rows = dict_rows(
            conn.execute(
                """
                SELECT * FROM review_items
                WHERE student_id = ? AND status IN ('pending', 'scheduled')
                ORDER BY due_date, id DESC LIMIT 20
                """,
                (student_id,),
            ).fetchall()
        )
        weekly_report = conn.execute(
            "SELECT * FROM weekly_reports WHERE student_id = ? ORDER BY week_start DESC LIMIT 1",
            (student_id,),
        ).fetchone()
        agent_overview_data = get_agent_overview(conn, student_id)
        target_insights = build_target_insights(conn, student_id)
        adjustment = recommend_daily_adjustments(conn, student_id, today)
        constraints = build_system_constraints(conn, student_id, today)
        return {
            "date": today,
            "total": len(tasks),
            "completed": completed,
            "tasks": tasks,
            "stuck_tasks": [task for task in tasks if task["status"] == "stuck"],
            "unfinished_tasks": [task for task in tasks if task["status"] != "completed"],
            "quiz_results": quiz_results,
            "report": _sanitize_report_for_display(dict(report) if report else None),
            "weekly_report": _sanitize_report_for_display(dict(weekly_report) if weekly_report else None),
            "review_items": [_sanitize_review_item_for_display(item) for item in review_rows],
            "rewards": today_rewards(conn, student_id, today),
            "mastery": agent_overview_data["mastery"],
            "agent_runs": agent_overview_data["runs"][:10],
            "notifications": [_sanitize_notification_for_display(item) for item in notifications],
            "target_95": target_insights,
            "daily_adjustment": adjustment,
            "system_constraints": constraints,
        }
