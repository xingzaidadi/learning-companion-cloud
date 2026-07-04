from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASE_FILE = ROOT / 'tests' / 'agent_core_full_cases.yaml'


def main() -> None:
    text = CASE_FILE.read_text(encoding='utf-8')
    ids = re.findall(r'^  - id: (AC-(?:[A-Z0-9]+-)+\d+)$', text, flags=re.MULTILINE)
    if len(ids) < 45:
        raise AssertionError(f'完整用例数量不足，当前 {len(ids)} 条')
    duplicates = sorted({case_id for case_id in ids if ids.count(case_id) > 1})
    if duplicates:
        raise AssertionError(f'存在重复用例 ID: {duplicates}')
    required_sections = [
        'traceability_sources:',
        'coverage_map:',
        'quality_gates:',
        'open_questions:',
        'execution_summary:',
    ]
    missing = [section for section in required_sections if section not in text]
    if missing:
        raise AssertionError(f'缺少必要章节: {missing}')
    blocks = re.findall(r'  - id: (AC-[\s\S]*?)(?=\n  - id: |\nquality_gates:)', text)
    p0_without_automation = []
    for block in blocks:
        header = block.splitlines()[0].strip()
        if 'priority: P0' in block and 'automation_candidate: true' not in block and 'automation_candidate: partial' not in block:
            p0_without_automation.append(header)
    if p0_without_automation:
        raise AssertionError(f'P0 用例缺少自动化候选标记: {p0_without_automation}')
    print(f'AGENT_CORE_CASES_OK cases={len(ids)}')


if __name__ == '__main__':
    main()
