from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.db import get_conn, init_db  # noqa: E402
from backend.material_importer import create_material_from_import, extract_local_file  # noqa: E402


DEFAULT_FILES = [
    {
        "path": r"C:\Users\MI\Downloads\2026新五上定稿课本.pdf",
        "subject": "英语",
        "title": "2026新五上英语定稿课本",
        "material_type": "textbook_pdf",
    },
    {
        "path": r"C:\Users\MI\Downloads\26秋人教五上数学电子课本.pdf",
        "subject": "数学",
        "title": "26秋人教五上数学电子课本",
        "material_type": "textbook_pdf",
    },
]


def main() -> None:
    init_db()
    imported = []
    skipped = []
    with get_conn() as conn:
        for item in DEFAULT_FILES:
            path = Path(item["path"])
            if not path.exists():
                skipped.append({"path": str(path), "reason": "not_found"})
                continue
            existing = conn.execute(
                "SELECT id FROM learning_materials WHERE file_path = ? LIMIT 1",
                (str(path),),
            ).fetchone()
            if existing:
                skipped.append({"path": str(path), "reason": f"exists:{existing['id']}"})
                continue
            try:
                extracted = extract_local_file(str(path))
                result = create_material_from_import(
                    conn,
                    student_id=1,
                    subject=item["subject"],
                    material_type=item["material_type"],
                    title=item["title"],
                    content_text=extracted["content_text"],
                    file_path=extracted["file_path"],
                    source_type="local_file",
                    extra_config=extracted["meta"],
                )
                imported.append({"path": str(path), **result})
            except ValueError as exc:
                skipped.append({"path": str(path), "reason": str(exc)})
    print({"imported": imported, "skipped": skipped})


if __name__ == "__main__":
    main()
