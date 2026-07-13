"""Bounded upload reads shared by evidence and document endpoints."""

from pathlib import Path

from fastapi import UploadFile


EVIDENCE_SUFFIXES = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".txt", ".md", ".csv", ".json", ".xml",
    ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".log",
}


async def read_limited_upload(file: UploadFile, max_bytes: int, allowed_suffixes: set[str] = EVIDENCE_SUFFIXES) -> bytes:
    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if not name or suffix not in allowed_suffixes:
        raise ValueError("不支持的文件类型")

    chunks, total = [], 0
    while chunk := await file.read(1024 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise ValueError(f"文件超过 {max_bytes // (1024 * 1024)}MB")
        chunks.append(chunk)
    if not total:
        raise ValueError("文件为空")
    return b"".join(chunks)
