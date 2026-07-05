from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import get_conn, init_db  # noqa: E402
from backend.material_importer import create_material_from_import  # noqa: E402


SEEDS = [
    ("语文", "五年级上册语文 RAG 骨架", ROOT / "data" / "seed_materials" / "五年级上册语文_RAG骨架.txt"),
    ("数学", "五年级上册数学 RAG 骨架", ROOT / "data" / "seed_materials" / "五年级上册数学_RAG骨架.txt"),
]


def main() -> None:
    init_db()
    created = []
    skipped = []
    with get_conn() as conn:
        for subject, title, path in SEEDS:
            existing = conn.execute(
                "SELECT id FROM learning_materials WHERE title = ? LIMIT 1",
                (title,),
            ).fetchone()
            if existing:
                skipped.append({"title": title, "reason": f"exists:{existing['id']}"})
                continue
            text = path.read_text(encoding="utf-8")
            result = create_material_from_import(
                conn,
                student_id=1,
                subject=subject,
                material_type="notes",
                title=title,
                content_text=text,
                file_path=str(path),
                source_type="local_file",
                extra_config={"seed": True, "note": "资料骨架用于覆盖矩阵和规则兜底；请用真实教材资料逐步替换。"},
            )
            created.append(result)
    print({"created": created, "skipped": skipped})


if __name__ == "__main__":
    main()
