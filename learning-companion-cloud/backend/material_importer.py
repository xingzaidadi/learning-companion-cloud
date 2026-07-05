from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from sqlite3 import Connection

try:
    from .agent_core import index_material, infer_subject
    from .db import dumps, utc_now
except ImportError:  # pragma: no cover - direct script import fallback
    from agent_core import index_material, infer_subject
    from db import dumps, utc_now


ALLOWED_FILE_SUFFIXES = {".txt", ".md", ".pdf"}
ALLOWED_URL_SCHEMES = {"http", "https"}
MAX_IMPORT_CHARS = 180_000
HTTP_TIMEOUT_SECONDS = 12


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _read_pdf(path: Path) -> tuple[str, dict[str, Any]]:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover - exercised only when dependency missing
        raise ValueError("当前环境缺少 pypdf，无法解析 PDF；请安装 pypdf 后重试。") from exc

    reader = PdfReader(str(path))
    page_texts: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        text = _clean_text(text)
        if text:
            page_texts.append(f"【第{page_number}页】\n{text}")
    extracted = "\n\n".join(page_texts)
    if len(extracted) >= 80:
        return extracted, {"pages": len(reader.pages), "parser": "pypdf"}
    ocr_text, ocr_meta = _read_pdf_by_ocr(path)
    return ocr_text, {"pages": len(reader.pages), "parser": "pypdf+ocr", **ocr_meta}


def _read_pdf_by_ocr(path: Path, max_pages: int = 140) -> tuple[str, dict[str, Any]]:
    try:
        import fitz
        import numpy as np
        from PIL import Image
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:  # pragma: no cover - depends on optional OCR install
        raise ValueError("PDF 是图片扫描版，当前环境缺少 OCR 组件；请安装 PyMuPDF 和 rapidocr_onnxruntime 后重试。") from exc

    document = fitz.open(str(path))
    ocr = RapidOCR()
    page_texts: list[str] = []
    for page_index in range(min(len(document), max_pages)):
        page = document[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
        image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        result, _elapsed = ocr(np.array(image))
        lines = [str(item[1]).strip() for item in (result or []) if len(item) > 1 and str(item[1]).strip()]
        if lines:
            page_texts.append(f"【第{page_index + 1}页】\n" + "\n".join(lines))
    text = _clean_text("\n\n".join(page_texts))
    if len(text) < 80:
        raise ValueError("OCR 后仍未提取到足够文本，可能图片质量过低或需要人工处理。")
    return text, {"ocr_pages": len(page_texts), "ocr_engine": "rapidocr_onnxruntime"}


def extract_local_file(path_value: str) -> dict[str, Any]:
    path = Path(path_value).expanduser()
    if not path.exists() or not path.is_file():
        raise ValueError(f"文件不存在：{path_value}")
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_FILE_SUFFIXES:
        raise ValueError("只支持 TXT、MD、PDF 三类资料导入")
    if suffix == ".pdf":
        text, meta = _read_pdf(path)
    else:
        text = path.read_text(encoding="utf-8", errors="ignore")
        meta = {"parser": "text"}
    text = _clean_text(text)[:MAX_IMPORT_CHARS]
    if len(text) < 20:
        raise ValueError("文件可提取文本太少，可能是扫描版 PDF，需要先 OCR 或换成可复制文本版本。")
    return {
        "title": path.stem,
        "content_text": text,
        "file_path": str(path),
        "source_type": "local_file",
        "meta": {**meta, "suffix": suffix, "chars": len(text)},
    }


def extract_public_url(url: str) -> dict[str, Any]:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise ValueError("URL 必须是公开 http/https 地址")
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "LearningCompanion/1.0 (+legal-public-material-import)",
            "Accept": "text/html,text/plain,application/pdf;q=0.8,*/*;q=0.5",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(2_000_000)
    except urllib.error.URLError as exc:
        raise ValueError(f"公开 URL 无法读取：{exc}") from exc

    if "pdf" in content_type.lower() or parsed.path.lower().endswith(".pdf"):
        raise ValueError("URL PDF 请先下载到本地后用“本地文件导入”，这样可追踪来源并避免超时。")

    html = raw.decode("utf-8", errors="ignore")
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.I | re.S)
    title = _clean_text(re.sub(r"<[^>]+>", "", title_match.group(1))) if title_match else parsed.netloc
    text = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = _clean_text(text)[:MAX_IMPORT_CHARS]
    if len(text) < 80:
        raise ValueError("该 URL 未提取到足够正文，可能是动态页面；请复制正文或下载公开 PDF 后导入。")
    return {
        "title": title[:80],
        "content_text": text,
        "file_path": url,
        "source_type": "public_url",
        "meta": {"content_type": content_type, "host": parsed.netloc, "chars": len(text)},
    }


def create_material_from_import(
    conn: Connection,
    *,
    student_id: int,
    subject: str,
    material_type: str,
    title: str,
    content_text: str,
    file_path: str,
    source_id: int = 0,
    source_type: str,
    extra_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    resolved_subject = subject.strip() or infer_subject(f"{title}\n{content_text[:1000]}")
    cursor = conn.execute(
        """
        INSERT INTO learning_materials (
            student_id, source_id, subject, material_type, title,
            content_text, file_path, config_json, source_url, source_type, trust_level, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            student_id,
            source_id or None,
            resolved_subject,
            material_type,
            title.strip()[:120],
            content_text.strip(),
            file_path.strip(),
            dumps(
                {
                    "source": source_type,
                    "legal_note": "仅导入用户提供或公开可访问资料；不绕过登录、付费墙或版权保护。",
                    **(extra_config or {}),
                }
            ),
            file_path.strip() if source_type == "public_url" else "",
            source_type,
            "public" if source_type == "public_url" else "user_provided",
            now,
            now,
        ),
    )
    material_id = int(cursor.lastrowid)
    indexed = index_material(conn, material_id)
    return {"id": material_id, "status": "created", "rag_index": indexed}
