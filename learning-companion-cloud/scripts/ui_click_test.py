from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]


PLAN_TEXT = """
外研社刘兆义版五年级上册英语暑假预习。教材包含 Unit 1 My school is cool、Unit 2 School activities are fun!、Unit 3 The ice world、
Unit 4 I love the sea!、Unit 5 Work it out!、Unit 6 Big days。每天学习 25-35 分钟，每天一小节，不超过五年级上册范围。
""".strip()


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 30
    while time.time() < deadline:
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=1)
            raise RuntimeError(f"服务启动失败\nSTDOUT:\n{stdout}\nSTDERR:\n{stderr}")
        try:
            with urlopen(f"{base_url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.3)
    raise TimeoutError("等待服务启动超时")


def start_server() -> tuple[subprocess.Popen[str], str, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="learning-companion-ui-test-"))
    temp_db = temp_dir / "learning.db"
    port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_PATH": str(temp_db),
            "ENABLE_SCHEDULER": "false",
            "AI_ENABLED": "false",
            "NOTIFY_CHANNEL": "none",
            "CHILD_PASSWORD": "",
            "PARENT_PASSWORD": "",
            "ADMIN_PASSWORD": "",
        }
    )
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    wait_for_health(base_url, process)
    return process, base_url, temp_dir


def fill_if_present(page, selector: str, value: str) -> None:
    locator = page.locator(selector)
    if locator.count():
        locator.first.fill(value)


def click_first(page, selector: str, timeout: int = 10_000) -> None:
    page.locator(selector).first.click(timeout=timeout)


def run_browser_clicks(base_url: str) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("缺少 Playwright：请先安装 playwright 后再跑真实浏览器点击测试") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_default_timeout(15_000)
        browser_errors: list[str] = []
        api_responses: list[tuple[int, str]] = []
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.on("console", lambda message: browser_errors.append(message.text) if message.type == "error" else None)
        page.on("response", lambda response: api_responses.append((response.status, response.url)) if "/api/" in response.url else None)
        stuck_notes = ["不认识鹭这个字", "不理解 school 这个词怎么读"]
        page.on("dialog", lambda dialog: dialog.accept(stuck_notes.pop(0) if stuck_notes else "卡在第一步"))

        page.goto(f"{base_url}/admin")
        page.wait_for_selector("#quickPlanForm")
        quick_plan_text = "寒假作业本，每日一小节；语文书，每日一篇课文"
        page.fill("#quickPlanForm textarea[name='raw_text']", quick_plan_text)
        page.click("#quickPlanSubmit")
        page.wait_for_function(
            "() => document.querySelector('#quickPlanResult')?.innerText.includes('已生成 2 条长期计划')",
            timeout=20_000,
        )
        page.wait_for_function(
            "() => document.querySelector('#todayTasks')?.innerText.includes('寒假作业本')",
            timeout=20_000,
        )
        quick_result = page.locator("#quickPlanResult").inner_text()
        today_tasks = page.locator("#todayTasks").inner_text()
        assert "寒假作业本" in quick_result and "五年级上册语文每日学习" in quick_result
        assert "寒假作业本" in today_tasks and ("白鹭" in today_tasks or "语文" in today_tasks)
        page.goto(f"{base_url}/child")
        page.wait_for_selector("#tasks .task-card")
        child_body = page.locator("body").inner_text()
        assert "寒假作业本" in child_body and ("白鹭" in child_body or "语文" in child_body)
        page.click("#startNext")
        page.wait_for_selector("#tasks .task-card.active")
        page.locator("#tasks .task-card.active").locator("button[data-action='stuck']").click()
        page.wait_for_function(
            "() => document.querySelector('#assistBox')?.innerText.includes('当前卡住')"
            " && document.querySelector('#assistBox')?.innerText.includes('你现在要做')",
            timeout=20_000,
        )
        assist_text = page.locator("#assistBox").inner_text()
        assert "你现在要做" in assist_text
        assert "1." in assist_text or "1．" in assist_text
        assert "可能卡在" not in assist_text and "想一想" not in assist_text and "同类小例子" not in assist_text
        api_tasks = page.evaluate("async () => await (await fetch('/api/daily-tasks')).json()")
        assert sum(1 for task in api_tasks if task["status"] == "stuck") == 1
        page.goto(f"{base_url}/parent")
        page.wait_for_selector("#tasks .task-card")
        parent_body = page.locator("body").inner_text()
        assert "寒假作业本" in parent_body and ("白鹭" in parent_body or "语文" in parent_body)

        page.goto(f"{base_url}/admin")
        page.wait_for_selector("#quickPlanForm")
        page.click("summary")
        page.click("#seedDemo")
        page.wait_for_timeout(500)
        page.fill("#quickPlanForm textarea[name='raw_text']", PLAN_TEXT)
        page.click("#quickPlanSubmit")
        page.wait_for_selector("#quickPlanResult .task-card", timeout=20_000)
        page.click("#generateToday")
        page.wait_for_selector("#todayTasks .task-card", timeout=20_000)
        page.wait_for_timeout(500)
        page.click("#refresh")
        page.wait_for_timeout(500)

        fill_if_present(page, "#settingsForm input[name='city']", "武汉")
        fill_if_present(page, "#settingsForm input[name='max_total_minutes']", "110")
        fill_if_present(page, "#settingsForm input[name='quiz_pass_score']", "0.8")
        fill_if_present(page, "#settingsForm input[name='api_url']", "")
        fill_if_present(page, "#settingsForm input[name='model']", "")
        page.select_option("#settingsForm select[name='ai_enabled']", "false")
        page.click("#settingsForm button.primary")
        page.wait_for_timeout(500)
        page.click("#checkAi")
        page.wait_for_selector("#aiStatus")

        page.select_option("#sourceForm select[name='category']", "preview")
        fill_if_present(page, "#sourceForm input[name='title']", "语文五年级上册第一课预习")
        fill_if_present(page, "#sourceForm input[name='subject']", "语文")
        fill_if_present(page, "#sourceForm input[name='total_units']", "3")
        fill_if_present(page, "#sourceForm input[name='completed_units']", "0")
        fill_if_present(page, "#sourceForm input[name='deadline']", "2026-08-31")
        fill_if_present(page, "#sourceForm input[name='topic']", "第一课")
        fill_if_present(page, "#sourceForm textarea[name='lesson_content']", "读课文、圈生字、说主要内容")
        fill_if_present(page, "#sourceForm textarea[name='knowledge_points']", "生字词、课文理解")
        fill_if_present(page, "#sourceForm input[name='estimated_minutes']", "25")
        page.click("#sourceForm button.primary")
        page.wait_for_timeout(500)

        page.fill("#importForm textarea[name='raw_text']", "preview,数学五年级上册小数除法,数学,2,0,2026-08-31,小数除法")
        fill_if_present(page, "#importForm input[name='default_deadline']", "2026-08-31")
        page.click("#importForm button.primary")
        page.wait_for_timeout(500)
        fill_if_present(page, "#materialForm input[name='subject']", "英语")
        page.select_option("#materialForm select[name='material_type']", "word_list")
        fill_if_present(page, "#materialForm input[name='title']", "Unit 1 单词表")
        fill_if_present(page, "#materialForm textarea[name='content_text']", "teacher=老师\nlibrary=图书馆\nclassroom=教室")
        page.click("#materialForm button.primary")
        page.wait_for_timeout(500)
        page.wait_for_selector("#materials .task-card")
        page.click("#generateToday")
        page.wait_for_selector("button[data-action='regenerateQuiz']")
        click_first(page, "button[data-action='regenerateQuiz']")
        page.wait_for_timeout(500)

        page.goto(f"{base_url}/child")
        page.wait_for_selector("#tasks .task-card")
        first_card = page.locator("#tasks .task-card").first
        if "先处理卡住任务" in page.locator("#startNext").inner_text():
            assert "我学会了，继续学" in page.locator("#tasks").inner_text(), "有卡住任务时应先处理卡住任务"
            page.locator("button[data-action='start']").filter(has_text="我学会了，继续学").first.click(force=True)
            page.wait_for_timeout(500)
        else:
            assert "先点开始" in first_card.inner_text(), "未开始任务不应直接显示可检查"
            assert first_card.locator("button.warn").first.is_disabled(), "未开始任务的检查按钮应禁用"
        page.evaluate(
            """
            () => {
              window.__taskListChildMutations = 0;
              const target = document.querySelector("#tasks");
              window.__taskListObserver = new MutationObserver((mutations) => {
                window.__taskListChildMutations += mutations.filter((mutation) => mutation.type === "childList").length;
              });
              window.__taskListObserver.observe(target, { childList: true });
            }
            """
        )
        if "继续当前任务" in page.locator("#startNext").inner_text():
            page.locator("#tasks .task-card.active").first.scroll_into_view_if_needed()
        else:
            page.click("#startNext")
        page.wait_for_timeout(500)
        assert page.evaluate("() => window.__taskListChildMutations") == 0, "点击开始不应重绘整个任务列表"
        workflow_card = page.locator("#tasks .task-card.active").first
        page.wait_for_function(
            "() => Array.from(document.querySelectorAll('#tasks .task-card.active .timer-tag')).some((node) => !node.innerText.includes('0:00'))",
            timeout=5_000,
        )
        workflow_card = page.locator("#tasks .task-card.active").first
        workflow_task_id = workflow_card.locator("button[data-action='pause']").get_attribute("data-id")
        assert workflow_task_id
        assert "进行中" in workflow_card.inner_text()
        assert "已学 0:00" not in workflow_card.inner_text()
        stuck_notes.insert(0, "刚才不会读 school，现在会了")
        workflow_card.locator("button[data-action='stuck']").click(force=True)
        page.wait_for_timeout(500)
        workflow_card = page.locator(f"button[data-action='start'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]")
        assert "我学会了，继续学" in workflow_card.inner_text(), "卡住后应有明确的继续学习按钮"
        assert "学完了，开始检查" in workflow_card.inner_text(), "卡住后应保留学完检查入口"
        assert "学会以后" in page.locator("#assistBox").inner_text(), "卡住提示区应说明学会后怎么继续"
        workflow_card.locator("button[data-action='start']").click(force=True)
        page.wait_for_timeout(500)
        workflow_card = page.locator(f"button[data-action='pause'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]")
        assert "进行中" in workflow_card.inner_text(), "点击我学会了继续学后应回到进行中"
        page.locator(f"button[data-action='pause'][data-id='{workflow_task_id}']").click(force=True)
        page.wait_for_timeout(500)
        api_tasks = page.evaluate("async () => await (await fetch('/api/daily-tasks')).json()")
        workflow_task = next(task for task in api_tasks if task["id"] == int(workflow_task_id))
        assert workflow_task["status"] == "paused", workflow_task
        workflow_card = page.locator(f"button[data-action='complete'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]")
        assert "已学" in workflow_card.inner_text()
        paused_time = workflow_card.locator(".timer-tag").inner_text()
        page.wait_for_timeout(1_500)
        paused_time_after_wait = page.locator(f"button[data-action='complete'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]").locator(".timer-tag").inner_text()
        assert paused_time_after_wait == paused_time, f"暂停后计时不应继续增长：{paused_time} -> {paused_time_after_wait}"
        workflow_card = page.locator(f"button[data-action='complete'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]")
        workflow_card.locator("button[data-action='complete']").click(force=True)
        try:
            page.wait_for_selector("#quizBox form", timeout=5_000)
        except Exception:
            workflow_card = page.locator(f"button[data-action='showQuiz'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]")
            workflow_card.locator("button[data-action='showQuiz']").click(force=True)
            try:
                page.wait_for_selector("#quizBox form")
            except Exception as exc:
                raise AssertionError(
                    "点击“我做完了，开始检查”后没有出现小测表单。\n"
                    f"quizBox={page.locator('#quizBox').inner_text()}\n"
                    f"tasks={page.locator('#tasks').inner_text()}\n"
                    f"errors={browser_errors}\n"
                    f"api_responses={api_responses[-20:]}"
                ) from exc
        workflow_card = page.locator(f"button[data-action='showQuiz'][data-id='{workflow_task_id}']").locator("xpath=ancestor::article[1]")
        assert "继续检查" in workflow_card.inner_text(), "进入检查后应显示继续检查，而不是重复完成"
        assert "继续当前检查" in page.locator("#startNext").inner_text(), "检查中顶部按钮应提示继续当前检查"
        page.click("#startNext")
        page.wait_for_selector("#quizBox form")
        api_tasks = page.evaluate("async () => await (await fetch('/api/daily-tasks')).json()")
        workflow_task = next(task for task in api_tasks if task["id"] == int(workflow_task_id))
        assert workflow_task["status"] == "checking", f"检查中点击顶部按钮不应重新开始任务：{workflow_task}"
        workflow_card.locator("button[data-action='showQuiz']").click(force=True)
        page.wait_for_selector("#quizBox form")
        for index in range(page.locator("#quizBox textarea").count()):
            page.locator("#quizBox textarea").nth(index).fill("测试答案")
        radio_names = page.locator("#quizBox input[type='radio']").evaluate_all(
            "(nodes) => Array.from(new Set(nodes.map((node) => node.name)))"
        )
        for name in radio_names:
            page.locator(f"#quizBox input[type='radio'][name='{name}']").first.check()
        page.click("#quizBox form button.primary")
        page.wait_for_timeout(500)
        page.wait_for_function("() => document.querySelector('#startNext')?.innerText.includes('先订正当前小测')")
        page.click("#startNext")
        page.wait_for_selector("#quizBox form")
        api_tasks = page.evaluate("async () => await (await fetch('/api/daily-tasks')).json()")
        workflow_task = next(task for task in api_tasks if task["id"] == int(workflow_task_id))
        assert workflow_task["status"] == "needs_revision", f"需订正点击顶部按钮不应重新开始任务：{workflow_task}"

        page.goto(f"{base_url}/parent")
        page.wait_for_selector("#endDay")
        page.click("#endDay")
        page.wait_for_timeout(500)
        page.click("#weekReport")
        page.wait_for_timeout(500)

        if browser_errors:
            raise AssertionError("浏览器控制台/页面错误：\n" + "\n".join(browser_errors[:10]))
        browser.close()


def main() -> None:
    process: subprocess.Popen[str] | None = None
    temp_dir: Path | None = None
    try:
        process, base_url, temp_dir = start_server()
        run_browser_clicks(base_url)
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        if temp_dir and temp_dir.exists():
            for child in temp_dir.iterdir():
                child.unlink()
            temp_dir.rmdir()
    print("UI_CLICK_TEST_OK")


if __name__ == "__main__":
    main()
