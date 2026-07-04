from __future__ import annotations

from datetime import date
import html
import json
from pathlib import Path
from typing import Annotated

import os
import secrets

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Form, HTTPException, Request, status
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
    from .ai_provider import check_ai_connection
    from .curriculum import CURRICULUM, WUHAN_DEFAULTS, get_subject_units
    from .db import dict_rows, dumps, get_conn, init_db, loads, utc_now
    from .importer import import_task_sources
    from .notifier import notify
    from .plan_generator import generate_plan_from_text
    from .planner import generate_daily_tasks, seed_demo_sources
    from .quiz import ensure_quiz_for_task, grade_quiz, regenerate_quiz_for_task
    from .report import build_daily_report, build_weekly_report
    from .rewards import today_rewards
    from .review import create_review_item, review_book
    from .scheduler import start_scheduler
    from .settings import get_settings, save_settings
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
    from ai_provider import check_ai_connection
    from curriculum import CURRICULUM, WUHAN_DEFAULTS, get_subject_units
    from db import dict_rows, dumps, get_conn, init_db, loads, utc_now
    from importer import import_task_sources
    from notifier import notify
    from plan_generator import generate_plan_from_text
    from planner import generate_daily_tasks, seed_demo_sources
    from quiz import ensure_quiz_for_task, grade_quiz, regenerate_quiz_for_task
    from report import build_daily_report, build_weekly_report
    from rewards import today_rewards
    from review import create_review_item, review_book
    from scheduler import start_scheduler
    from settings import get_settings, save_settings


BASE_DIR = Path(__file__).resolve().parents[1]
FRONTEND_DIR = BASE_DIR / "frontend"
load_dotenv(BASE_DIR / ".env")

app = FastAPI(title="11岁孩子暑假自主学习陪跑系统", version="1.0.0")
security = HTTPBasic(auto_error=False)
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
    init_db()
    app.state.scheduler = start_scheduler()


@app.on_event("shutdown")
def shutdown() -> None:
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        scheduler.shutdown(wait=False)


def page(name: str) -> FileResponse:
    return FileResponse(FRONTEND_DIR / name)


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
    return not (
        os.getenv("CHILD_PASSWORD", "")
        or os.getenv("PARENT_PASSWORD", "")
        or os.getenv("ADMIN_PASSWORD", "")
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
        tasks = [dict(row) for row in rows]
    done_count = sum(1 for task in tasks if task.get("status") == "completed")
    total_count = len(tasks)
    fallback_html = _render_child_task_fallback(tasks)
    html_text = html_text.replace(
        '<div id="tasks" class="task-list"><p class="muted">正在加载今日任务...</p></div>',
        f'<div id="tasks" class="task-list">{fallback_html}</div>',
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
async def agent_plan(request: Request, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    data = await request.json()
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
            "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
            (student_id, today),
        ).fetchall()
        if not rows:
            result = agent_daily_tasks(conn, student_id, today)
            rows = result["tasks"]
            if rows:
                notify(conn, student_id, "tasks_generated", "今日学习任务已自动生成", f"今天共有 {len(rows)} 个任务。")
                return [dict(row) for row in rows]
        return dict_rows(rows)


@app.post("/api/daily-tasks/generate")
def generate_tasks(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_admin_auth),
) -> dict[str, object]:
    today = target_date or date.today().isoformat()
    with get_conn() as conn:
        result = agent_daily_tasks(conn, student_id, today, force_all_sources=True)
        tasks = result["tasks"]
        notify(conn, student_id, "tasks_generated", "今日学习任务已生成", f"今天共有 {len(tasks)} 个任务。")
        return {"date": today, "count": len(tasks), "tasks": tasks}


@app.post("/api/agent/daily-tasks")
async def agent_daily_tasks_endpoint(request: Request, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    data = await request.json()
    student_id = int(data.get("student_id", 1))
    target_date = data.get("target_date") or date.today().isoformat()
    with get_conn() as conn:
        result = agent_daily_tasks(conn, student_id, target_date, force_all_sources=True)
        result["date"] = target_date
        return result


@app.post("/api/daily-tasks/{task_id}/event")
async def task_event(task_id: int, request: Request, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    data = await request.json()
    event_type = data.get("event_type", "")
    note = data.get("note", "")
    status_map = {
        "start": "in_progress",
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
            return {"task_id": task_id, **assistance, "status": status_map[event_type]}
        return {"task_id": task_id, "status": status_map[event_type]}


@app.get("/api/daily-tasks/{task_id}/quiz")
def get_quiz(task_id: int, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        result = agent_generate_quiz(conn, task_id)
        return {"task": dict(task), "items": result["items"]}


@app.get("/api/agent/task-guidance/{task_id}")
def agent_task_guidance(task_id: int, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return ensure_task_guidance(conn, task_id)


@app.post("/api/daily-tasks/{task_id}/quiz/regenerate")
def regenerate_quiz(task_id: int, _: str = Depends(require_admin_auth)) -> dict[str, object]:
    with get_conn() as conn:
        return agent_generate_quiz(conn, task_id, force=True)


@app.post("/api/daily-tasks/{task_id}/quiz")
async def submit_quiz(task_id: int, request: Request, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    data = await request.json()
    answers = data.get("answers", {})
    with get_conn() as conn:
        task = conn.execute("SELECT * FROM daily_tasks WHERE id = ?", (task_id,)).fetchone()
        if not task:
            raise HTTPException(status_code=404, detail="任务不存在")
        return grade_submission(conn, task_id, answers)


@app.post("/api/agent/grade/{task_id}")
async def agent_grade(task_id: int, request: Request, _: str = Depends(require_child_or_admin_auth)) -> dict[str, object]:
    data = await request.json()
    with get_conn() as conn:
        return grade_submission(conn, task_id, data.get("answers", {}))


@app.post("/api/day/end")
def end_day(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_any_role_auth),
) -> dict[str, object]:
    with get_conn() as conn:
        return agent_daily_report(conn, student_id, target_date or date.today().isoformat())


@app.post("/api/agent/daily-report")
async def agent_report(request: Request, _: str = Depends(require_parent_or_admin_auth)) -> dict[str, object]:
    data = await request.json()
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


@app.get("/api/parent/dashboard")
def parent_dashboard(
    student_id: int = 1,
    target_date: str | None = None,
    _: str = Depends(require_parent_or_admin_auth),
) -> dict[str, object]:
    today = target_date or date.today().isoformat()
    with get_conn() as conn:
        tasks = dict_rows(
            conn.execute(
                "SELECT * FROM daily_tasks WHERE student_id = ? AND date = ? ORDER BY priority, id",
                (student_id, today),
            ).fetchall()
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
            result["wrong_items"] = loads(result.pop("wrong_items_json"), [])
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
        return {
            "date": today,
            "total": len(tasks),
            "completed": completed,
            "tasks": tasks,
            "stuck_tasks": [task for task in tasks if task["status"] == "stuck"],
            "unfinished_tasks": [task for task in tasks if task["status"] != "completed"],
            "quiz_results": quiz_results,
            "report": dict(report) if report else None,
            "weekly_report": dict(weekly_report) if weekly_report else None,
            "review_items": review_rows,
            "rewards": today_rewards(conn, student_id, today),
            "mastery": agent_overview_data["mastery"],
            "agent_runs": agent_overview_data["runs"][:10],
            "notifications": notifications,
        }
