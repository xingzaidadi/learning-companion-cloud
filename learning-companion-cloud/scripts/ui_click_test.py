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
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
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
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.on("console", lambda message: browser_errors.append(message.text) if message.type == "error" else None)
        page.on("dialog", lambda dialog: dialog.accept("不理解 school 这个词怎么读"))

        page.goto(f"{base_url}/admin")
        page.wait_for_selector("#quickPlanForm")
        quick_plan_text = "寒假作业本，每日一小节；语文书，每日一篇课文"
        page.fill("#quickPlanForm textarea[name='raw_text']", quick_plan_text)
        page.click("#quickPlanSubmit")
        page.wait_for_function(
            "() => document.querySelector('#quickPlanResult')?.innerText.includes('已生成 2 条长期计划')",
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
        page.click("#generateToday")
        page.wait_for_selector("button[data-action='regenerateQuiz']")
        click_first(page, "button[data-action='regenerateQuiz']")
        page.wait_for_timeout(500)

        page.goto(f"{base_url}/child")
        page.wait_for_selector("#tasks .task-card")
        page.click("#startNext")
        page.wait_for_timeout(500)
        click_first(page, "#tasks button[data-action='start']")
        page.wait_for_timeout(300)
        click_first(page, "#tasks button[data-action='pause']")
        page.wait_for_timeout(300)
        click_first(page, "#tasks button[data-action='stuck']")
        page.wait_for_selector("#assistBox h3")
        click_first(page, "#tasks button[data-action='complete']")
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
