from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import get_conn, init_db  # noqa: E402
from backend.knowledge_graph import rebuild_knowledge_points  # noqa: E402
from backend.knowledge_schema import coverage_summary, render_subject_material  # noqa: E402
from backend.material_importer import create_material_from_import  # noqa: E402


SUBJECTS = ("语文", "数学", "英语")


def main() -> None:
    init_db()
    created = []
    skipped = []
    with get_conn() as conn:
        for subject in SUBJECTS:
            title = f"五年级上册{subject}结构化核心知识库"
            existing = conn.execute(
                "SELECT id FROM learning_materials WHERE title = ? AND student_id = 1 LIMIT 1",
                (title,),
            ).fetchone()
            if existing:
                skipped.append({"title": title, "reason": f"exists:{existing['id']}"})
                continue
            result = create_material_from_import(
                conn,
                student_id=1,
                subject=subject,
                material_type="notes",
                title=title,
                content_text=render_subject_material(subject),
                file_path="builtin://core-knowledge",
                source_type="builtin",
                extra_config={
                    "seed": True,
                    "structured_knowledge": True,
                    "note": "五年级上册核心知识库，用于 RAG、任务生成、小测和评测；后续可用真实教材 PDF 增量补强。",
                },
            )
            created.append(result)
        knowledge = rebuild_knowledge_points(conn, 1)
    print(json.dumps({"created": created, "skipped": skipped, "coverage": coverage_summary(), "knowledge_graph": knowledge}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
