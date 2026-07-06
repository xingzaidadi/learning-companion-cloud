from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPORT_DIR = ROOT / "reports" / "evals"


def main() -> None:
    report = _load_json(REPORT_DIR / "latest_eval_report.json", {})
    history = []
    history_path = REPORT_DIR / "eval_history.jsonl"
    if history_path.exists():
        history = [json.loads(line) for line in history_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    html = render_dashboard(report, history[-20:])
    (REPORT_DIR / "eval_dashboard.html").write_text(html, encoding="utf-8")
    print(json.dumps({"status": "EVAL_DASHBOARD_OK", "path": str(REPORT_DIR / "eval_dashboard.html"), "history": len(history)}, ensure_ascii=False))


def render_dashboard(report: dict, history: list[dict]) -> str:
    summaries = report.get("summaries", [])
    cards = []
    for summary in summaries:
        cards.append(
            f"""
            <article class="card">
              <h2>{summary.get('agent')}</h2>
              <p class="score">{summary.get('pass_rate')}</p>
              <p>Case: {summary.get('total')}｜Avg: {summary.get('avg_score')}｜Known gaps: {len(summary.get('known_gap_cases', []))}</p>
              <pre>{json.dumps(summary.get('difficulty_scores', {}), ensure_ascii=False, indent=2)}</pre>
            </article>
            """
        )
    points = ",".join(str(item.get("overall_avg_score", 0)) for item in history)
    labels = ",".join(json.dumps(item.get("generated_at", "")[5:16], ensure_ascii=False) for item in history)
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Agent Eval Dashboard</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 0; padding: 28px; background: #f6f7fb; color: #172033; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 16px; }}
    .card {{ background: white; border: 1px solid #e5e7ef; border-radius: 18px; padding: 18px; box-shadow: 0 12px 30px rgba(31, 41, 55, .08); }}
    .score {{ font-size: 44px; font-weight: 800; margin: 8px 0; color: #4f46e5; }}
    pre {{ white-space: pre-wrap; background: #f8fafc; padding: 12px; border-radius: 12px; }}
    canvas {{ width: 100%; height: 220px; background: white; border-radius: 18px; border: 1px solid #e5e7ef; }}
  </style>
</head>
<body>
  <h1>Agent Eval Dashboard</h1>
  <p>生成时间：{report.get('generated_at', '-')}；趋势点：{len(history)}</p>
  <section class="grid">{''.join(cards)}</section>
  <h2>回归趋势</h2>
  <canvas id="trend" width="900" height="240" aria-label="Eval avg score trend"></canvas>
  <script>
    const values = [{points}];
    const labels = [{labels}];
    const canvas = document.getElementById('trend');
    const ctx = canvas.getContext('2d');
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = '#4f46e5'; ctx.lineWidth = 4;
    ctx.beginPath();
    values.forEach((value, index) => {{
      const x = 40 + index * ((canvas.width - 80) / Math.max(values.length - 1, 1));
      const y = canvas.height - 35 - value * (canvas.height - 70);
      if (index === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      ctx.fillText(labels[index] || '', x - 20, canvas.height - 10);
    }});
    ctx.stroke();
  </script>
</body>
</html>
"""


def _load_json(path: Path, default: dict) -> dict:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
