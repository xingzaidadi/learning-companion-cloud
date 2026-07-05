from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "ui_audit"
LATEST_DIR = REPORT_DIR / "latest"

PLAN_TEXT = "Summer homework workbook, one small section daily; Chinese textbook, one lesson daily; Math textbook, one section daily; English Unit 1 preview."


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(base_url: str, process: subprocess.Popen[str]) -> None:
    deadline = time.time() + 35
    while time.time() < deadline:
        if process.poll() is not None:
            raise RuntimeError("service exited before health check")
        try:
            with urlopen(f"{base_url}/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.25)
    raise TimeoutError("service health check timeout")


def start_server() -> tuple[subprocess.Popen[str], str, Path]:
    temp_dir = Path(tempfile.mkdtemp(prefix="learning-companion-ui-audit-"))
    env = os.environ.copy()
    env.update(
        {
            "DATABASE_PATH": str(temp_dir / "learning.db"),
            "ENABLE_SCHEDULER": "false",
            "AI_ENABLED": "false",
            "NOTIFY_CHANNEL": "none",
            "CHILD_PASSWORD": "",
            "PARENT_PASSWORD": "",
            "ADMIN_PASSWORD": "",
        }
    )
    port = free_port()
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


def ensure_report_dir() -> None:
    LATEST_DIR.mkdir(parents=True, exist_ok=True)
    for item in LATEST_DIR.glob("*"):
        if item.is_file():
            item.unlink()


def record(results: list[dict], page: str, action: str, ok: bool, detail: str = "") -> None:
    results.append({"page": page, "action": action, "ok": ok, "detail": detail})


def click_and_record(page, results: list[dict], page_name: str, selector: str, label: str, wait_ms: int = 600) -> None:
    try:
        locator = page.locator(selector).first
        locator.wait_for(state="visible", timeout=8000)
        locator.click(timeout=8000, force=True)
        page.wait_for_timeout(wait_ms)
        record(results, page_name, label, True)
    except Exception as exc:
        record(results, page_name, label, False, str(exc)[:300])


def fill_if_present(page, selector: str, value: str) -> None:
    locator = page.locator(selector)
    if locator.count():
        locator.first.fill(value)


def screenshot_segments(page, name: str, screenshots: list[str]) -> None:
    page.wait_for_timeout(500)
    height = int(page.evaluate("() => Math.max(document.body.scrollHeight, document.documentElement.scrollHeight)"))
    viewport = page.viewport_size or {"width": 1440, "height": 900}
    segment_height = int(viewport["height"])
    index = 1
    for y in range(0, max(height, 1), segment_height):
        page.evaluate("scrollY => window.scrollTo(0, scrollY)", y)
        page.wait_for_timeout(120)
        path = LATEST_DIR / f"{name}_{index:02d}.png"
        page.screenshot(path=str(path), full_page=False)
        screenshots.append(str(path.relative_to(ROOT)))
        index += 1
    page.evaluate("() => window.scrollTo(0, 0)")


def visual_checks(page, results: list[dict], page_name: str) -> None:
    checks = page.evaluate(
        """
        () => {
          const bodyText = document.body.innerText || '';
          const doc = document.documentElement;
          const isVisible = (el) => {
            const style = window.getComputedStyle(el);
            const rect = el.getBoundingClientRect();
            return style.visibility !== 'hidden' && style.display !== 'none' && rect.width > 0 && rect.height > 0;
          };
          const buttons = [...document.querySelectorAll('button')].filter(isVisible);
          const tinyButtons = buttons.filter(b => {
            const r = b.getBoundingClientRect();
            return r.height > 0 && r.height < 30;
          }).map(b => b.innerText.trim()).slice(0, 8);
          const overflow = doc.scrollWidth - doc.clientWidth;
          const unresolvedSnippets = [...bodyText.matchAll(/.{0,20}(\\$\\{[^}]+\\}|undefined|NaN).{0,20}/g)].map(m => m[0]).slice(0, 6);
          const unresolved = unresolvedSnippets.length > 0;
          const dirtyTokens = ['????', '\u8054\u8c03\u9a8c\u8bc1', '135442', '\u951b', '\u93c8', '\u6d60', '\u9225', '\ufffd'];
          const badText = dirtyTokens.filter(x => bodyText.includes(x));
          const emptyCardDetails = [...document.querySelectorAll('.task-card')]
            .filter(c => isVisible(c) && (c.textContent || '').trim().length === 0)
            .map(c => c.className).slice(0, 8);
          const emptyCards = emptyCardDetails.length;
          return {overflow, unresolved, unresolvedSnippets, badText, emptyCards, emptyCardDetails, buttonCount: buttons.length, tinyButtons};
        }
        """
    )
    record(results, page_name, "no horizontal overflow", checks["overflow"] <= 2, f"overflow={checks['overflow']}")
    record(results, page_name, "no unresolved template text", not checks["unresolved"], json.dumps(checks.get("unresolvedSnippets", checks), ensure_ascii=False))
    record(results, page_name, "no visible dirty text", not checks["badText"], json.dumps(checks["badText"], ensure_ascii=False))
    record(results, page_name, "no empty cards", checks["emptyCards"] == 0, json.dumps(checks.get("emptyCardDetails", []), ensure_ascii=False))
    record(results, page_name, "button touch height", not checks["tinyButtons"], json.dumps(checks["tinyButtons"], ensure_ascii=False))


def run_audit(base_url: str) -> dict:
    from playwright.sync_api import sync_playwright

    ensure_report_dir()
    results: list[dict] = []
    screenshots: list[str] = []
    console_errors: list[dict] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        page = context.new_page()
        page.on("console", lambda msg: console_errors.append({"type": msg.type, "text": msg.text}) if msg.type in {"error", "warning"} else None)
        page.on("pageerror", lambda exc: console_errors.append({"type": "pageerror", "text": str(exc)}))

        page.goto(f"{base_url}/admin", wait_until="networkidle")
        visual_checks(page, results, "admin")
        screenshot_segments(page, "admin_initial", screenshots)
        fill_if_present(page, "#quickPlanForm textarea[name='raw_text']", PLAN_TEXT)
        click_and_record(page, results, "admin", "#quickPlanSubmit", "quick plan submit", 1800)
        click_and_record(page, results, "admin", "#generateToday", "generate today", 1200)
        click_and_record(page, results, "admin", "#refresh", "refresh", 700)
        page.locator("details").first.evaluate("node => node.open = true")
        click_and_record(page, results, "admin", "#settingsForm button.primary", "save settings", 800)
        click_and_record(page, results, "admin", "#checkAi", "check ai", 800)
        fill_if_present(page, "#sourceForm input[name='title']", "UI audit Chinese preview")
        fill_if_present(page, "#sourceForm input[name='subject']", "Chinese")
        fill_if_present(page, "#sourceForm input[name='knowledge_point']", "reading")
        fill_if_present(page, "#sourceForm textarea[name='content']", "Preview one lesson and retell key points.")
        click_and_record(page, results, "admin", "#sourceForm button.primary", "save task source", 1000)
        fill_if_present(page, "#importForm textarea[name='raw_text']", "Chinese preview | reading | one lesson daily")
        click_and_record(page, results, "admin", "#importForm button.primary", "batch import", 1000)
        fill_if_present(page, "#materialForm input[name='subject']", "English")
        fill_if_present(page, "#materialForm input[name='title']", "Unit 1 word list")
        fill_if_present(page, "#materialForm textarea[name='content']", "library=library; classroom=classroom; teacher=teacher")
        click_and_record(page, results, "admin", "#materialForm button.primary", "save material", 1000)
        if page.locator("button[data-action='regenerateQuiz']").count():
            click_and_record(page, results, "admin", "button[data-action='regenerateQuiz']", "regenerate quiz", 1200)
        if page.locator("button[data-action='showTrace']").count():
            click_and_record(page, results, "admin", "button[data-action='showTrace']", "show trace", 700)
        visual_checks(page, results, "admin_after_clicks")
        screenshot_segments(page, "admin_after", screenshots)

        page.goto(f"{base_url}/child", wait_until="networkidle")
        visual_checks(page, results, "child")
        screenshot_segments(page, "child_initial", screenshots)
        click_and_record(page, results, "child", "#startNext", "primary next/start", 1000)
        if page.locator("#currentTask button[data-action='pause']").count():
            click_and_record(page, results, "child", "#currentTask button[data-action='pause']", "pause current", 800)
        if page.locator("#currentTask button[data-action='resume']").count():
            click_and_record(page, results, "child", "#currentTask button[data-action='resume']", "resume current", 800)
        if page.locator("#currentTask button[data-action='stuck']").count():
            click_and_record(page, results, "child", "#currentTask button[data-action='stuck']", "stuck current", 1300)
        if page.locator("#currentTask button[data-action='resume']").count():
            click_and_record(page, results, "child", "#currentTask button[data-action='resume']", "resume after stuck", 800)
        if page.locator("#currentTask button[data-action='complete']").count():
            click_and_record(page, results, "child", "#currentTask button[data-action='complete']", "complete/check current", 1300)
        if page.locator("#currentTask button[data-action='showQuiz']").count():
            click_and_record(page, results, "child", "#currentTask button[data-action='showQuiz']", "show quiz", 1000)
        visual_checks(page, results, "child_after_clicks")
        screenshot_segments(page, "child_after", screenshots)

        page.goto(f"{base_url}/parent", wait_until="networkidle")
        visual_checks(page, results, "parent")
        screenshot_segments(page, "parent_initial", screenshots)
        click_and_record(page, results, "parent", "#endDay", "generate daily report", 1200)
        click_and_record(page, results, "parent", "#weekReport", "generate weekly report", 1200)
        if page.locator("#scheduleDay").count():
            click_and_record(page, results, "parent", "#scheduleDay", "schedule day", 1000)
        page.locator("details").evaluate_all("nodes => nodes.forEach(n => n.open = true)")
        visual_checks(page, results, "parent_after_clicks")
        screenshot_segments(page, "parent_after", screenshots)

        browser.close()

    failures = [item for item in results if not item["ok"]]
    severe_console = [item for item in console_errors if item["type"] == "error" or item["type"] == "pageerror"]
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "results": results,
        "failures": failures,
        "console_errors": console_errors,
        "screenshots": screenshots,
        "summary": {
            "checks": len(results),
            "passed": len(results) - len(failures),
            "failed": len(failures),
            "console_error_count": len(severe_console),
            "screenshot_count": len(screenshots),
        },
    }
    (LATEST_DIR / "ui_audit_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Full UI Audit", "", f"- Created: `{report['created_at']}`", f"- Checks: `{report['summary']['checks']}`", f"- Passed: `{report['summary']['passed']}`", f"- Failed: `{report['summary']['failed']}`", f"- Console errors: `{report['summary']['console_error_count']}`", f"- Screenshots: `{report['summary']['screenshot_count']}`", "", "## Failures"]
    if failures:
        for item in failures:
            lines.append(f"- `{item['page']}` / `{item['action']}`: {item['detail']}")
    else:
        lines.append("- None")
    lines.extend(["", "## Screenshots"])
    for shot in screenshots:
        lines.append(f"- `{shot}`")
    (LATEST_DIR / "ui_audit_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    process, base_url, _temp_dir = start_server()
    try:
        report = run_audit(base_url)
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
    print(json.dumps(report["summary"], ensure_ascii=False))
    if report["failures"]:
        raise AssertionError(json.dumps(report["failures"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
