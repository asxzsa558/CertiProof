"""Document extraction and asynchronous compliance analysis."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import shutil
import subprocess
import tempfile
import zipfile
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.assessment import Assessment, PhaseInstance, TaskInstance
from app.models.document_knowledge import (
    DocumentAnalysisRun,
    DocumentBlock,
    DocumentControlResult,
    DocumentEvidenceLink,
    DocumentFile,
    DocumentRunFile,
)
from app.services.document_control_engine import DocumentControlEngine
from app.services.file_storage import file_storage
from app.services.knowledge_graph import knowledge_graph

logger = logging.getLogger(__name__)
DOCUMENT_SOURCE = "document_control_analysis"
BATCH_DOCUMENT_SOURCE = "document_batch_classification"
SUPPORTED_SUFFIXES = {".docx", ".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ARCHIVE_SUFFIXES = {".zip", ".rar", ".7z"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ANALYSIS_MODES = {"standard", "deep"}
MAX_BATCH_FILES = 100
MAX_BATCH_UNCOMPRESSED = 300 * 1024 * 1024


class DocumentExtractionError(ValueError):
    pass


def build_retest_comparison(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    before = float(previous.get("coverage") or 0)
    after = float(current.get("coverage") or 0)
    previous_gaps = {item["uid"]: item for item in previous.get("gap_items", [])}
    current_gaps = {item["uid"]: item for item in current.get("gap_items", [])}
    previous_reliable = previous.get("status") != "unable"
    current_reliable = current.get("status") != "unable"

    if previous_reliable and current_reliable:
        fixed_ids = sorted(previous_gaps.keys() - current_gaps.keys())
        new_ids = sorted(current_gaps.keys() - previous_gaps.keys())
        remaining_ids = sorted(previous_gaps.keys() & current_gaps.keys())
        status = "improved" if after > before else ("regressed" if after < before else "unchanged")
        delta = round(after - before, 2)
    else:
        fixed_ids = []
        new_ids = []
        remaining_ids = sorted(previous_gaps) if previous_reliable else []
        status = "unable" if not current_reliable else "baseline_unavailable"
        delta = 0

    return {
        "previous_status": previous.get("status"),
        "current_status": current.get("status"),
        "previous_coverage": before,
        "current_coverage": after,
        "delta": delta,
        "status": status,
        "initial_gaps": [item["reason"] for item in previous_gaps.values()],
        "current_gaps": [item["reason"] for item in current_gaps.values()],
        "fixed_gaps": [previous_gaps[uid]["reason"] for uid in fixed_ids],
        "remaining_gaps": [previous_gaps[uid]["reason"] for uid in remaining_ids],
        "new_gaps": [current_gaps[uid]["reason"] for uid in new_ids],
        "fixed_gap_ids": fixed_ids,
        "remaining_gap_ids": remaining_ids,
        "new_gap_ids": new_ids,
        "comparison_reliable": previous_reliable and current_reliable,
    }


def expand_document_upload(file_name: str, content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    """Return upload documents, safely expanding ZIP, RAR or 7z archives."""
    suffix = Path(file_name).suffix.lower()
    if suffix not in ARCHIVE_SUFFIXES:
        return [(safe_document_name(file_name), content)], []
    if suffix != ".zip":
        return _expand_libarchive(file_name, content)
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise DocumentExtractionError("ZIP 压缩包已损坏或格式无效。") from exc

    documents: list[tuple[str, bytes]] = []
    skipped: list[str] = []
    total_size = 0
    with archive:
        for item in archive.infolist():
            path = Path(item.filename)
            if item.is_dir() or "__MACOSX" in path.parts or path.name.startswith("."):
                continue
            if path.is_absolute() or ".." in path.parts:
                raise DocumentExtractionError("ZIP 包含不安全的文件路径，已拒绝处理。")
            if item.flag_bits & 0x1:
                raise DocumentExtractionError("ZIP 包含加密文件，暂不支持处理。")
            suffix = path.suffix.lower()
            if suffix in ARCHIVE_SUFFIXES:
                raise DocumentExtractionError("暂不支持嵌套压缩包，请先解压后重新打包。")
            if suffix not in SUPPORTED_SUFFIXES:
                skipped.append(item.filename)
                continue
            total_size += item.file_size
            if item.file_size > 100 * 1024 * 1024 or total_size > MAX_BATCH_UNCOMPRESSED:
                raise DocumentExtractionError("ZIP 解压后超过单文件 100MB 或总计 300MB 限制。")
            documents.append((path.as_posix(), archive.read(item)))
            if len(documents) > MAX_BATCH_FILES:
                raise DocumentExtractionError(f"单次最多处理 {MAX_BATCH_FILES} 个文档。")
    if not documents:
        raise DocumentExtractionError("ZIP 中未发现支持的文档。")
    return documents, skipped


def _expand_libarchive(file_name: str, content: bytes) -> tuple[list[tuple[str, bytes]], list[str]]:
    binary = shutil.which("bsdtar")
    if not binary:
        raise DocumentExtractionError("RAR/7z 解压组件不可用，请检查后端镜像中的 libarchive-tools。")
    archive_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=Path(file_name).suffix, delete=False) as archive_file:
            archive_file.write(content)
            archive_path = Path(archive_file.name)
        listing = subprocess.run(
            [binary, "-tf", str(archive_path)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if listing.returncode:
            raise DocumentExtractionError("压缩包已损坏、已加密或格式不受支持。")
        documents: list[tuple[str, bytes]] = []
        skipped: list[str] = []
        total_size = 0
        for member in listing.stdout.splitlines():
            path = Path(member)
            if not member or member.endswith("/") or "__MACOSX" in path.parts or path.name.startswith("."):
                continue
            if path.is_absolute() or ".." in path.parts:
                raise DocumentExtractionError("压缩包包含不安全的文件路径，已拒绝处理。")
            if path.suffix.lower() in ARCHIVE_SUFFIXES:
                raise DocumentExtractionError("暂不支持嵌套压缩包，请先解压后重新打包。")
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                skipped.append(member)
                continue
            process = subprocess.Popen(
                [binary, "-xOf", str(archive_path), "--", member],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            chunks: list[bytes] = []
            member_size = 0
            assert process.stdout is not None
            while chunk := process.stdout.read(1024 * 1024):
                member_size += len(chunk)
                total_size += len(chunk)
                if member_size > 100 * 1024 * 1024 or total_size > MAX_BATCH_UNCOMPRESSED:
                    process.kill()
                    process.wait()
                    raise DocumentExtractionError("压缩包解压后超过单文件 100MB 或总计 300MB 限制。")
                chunks.append(chunk)
            if process.wait(timeout=30):
                raise DocumentExtractionError(f"无法解压 {path.name}，压缩包可能已加密或损坏。")
            documents.append((path.as_posix(), b"".join(chunks)))
            if len(documents) > MAX_BATCH_FILES:
                raise DocumentExtractionError(f"单次最多处理 {MAX_BATCH_FILES} 个文档。")
        if not documents:
            raise DocumentExtractionError("压缩包中未发现支持的文档。")
        return documents, skipped
    except subprocess.TimeoutExpired as exc:
        raise DocumentExtractionError("压缩包解析超时。") from exc
    finally:
        if archive_path:
            archive_path.unlink(missing_ok=True)


def safe_document_name(value: str) -> str:
    path = Path((value or "document").replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise DocumentExtractionError("文件路径不安全，已拒绝处理。")
    parts = [part for part in path.parts if part not in {"", "."}]
    return "/".join(parts) or "document"


def _block(
    document_file: DocumentFile,
    index: int,
    text: str,
    block_type: str = "text",
    page: int | None = None,
    section: str | None = None,
    source: str = "native",
    confidence: float = 1.0,
    table: list[list[str]] | None = None,
    bbox: list[float] | None = None,
) -> dict[str, Any]:
    normalized = re.sub(r"\s+", " ", text or "").strip()
    return {
        "block_id": f"f{document_file.id}-b{index}",
        "document_file_id": document_file.id,
        "file_name": document_file.original_name,
        "page": page,
        "section": section,
        "type": block_type,
        "bbox": bbox,
        "text": normalized,
        "table": table,
        "source": source,
        "confidence": confidence,
        "content_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
    }


def _docx_native(path: Path, document_file: DocumentFile) -> tuple[list[dict], list[tuple[str, bytes]], int]:
    import docx
    from docx.table import Table

    with zipfile.ZipFile(path) as archive:
        if sum(item.file_size for item in archive.infolist()) > 300 * 1024 * 1024:
            raise DocumentExtractionError("DOCX 解压后内容超过 300MB，已拒绝处理。")

    document = docx.Document(str(path))
    blocks: list[dict] = []
    current_section = None

    for item in document.iter_inner_content():
        if isinstance(item, Table):
            rows = [[cell.text.strip() for cell in row.cells] for row in item.rows]
            text = "\n".join(" | ".join(row) for row in rows if any(row))
            if text.strip():
                blocks.append(_block(document_file, len(blocks), text, "table", section=current_section, table=rows))
            continue
        text = item.text.strip()
        if not text:
            continue
        style = (item.style.name or "").lower() if item.style else ""
        block_type = "heading" if "heading" in style or "标题" in style else "text"
        if block_type == "heading":
            current_section = text
        blocks.append(_block(document_file, len(blocks), text, block_type, section=current_section))

    for section in document.sections:
        for block_type, container in (("header", section.header), ("footer", section.footer)):
            text = "\n".join(p.text.strip() for p in container.paragraphs if p.text.strip())
            if text:
                blocks.append(_block(document_file, len(blocks), text, block_type))

    images: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("word/media/") and Path(name).suffix.lower() in IMAGE_SUFFIXES:
                images.append((Path(name).name, archive.read(name)))
    return blocks, images, max(1, len(document.sections))


def _pdf_native(path: Path, document_file: DocumentFile, analysis_mode: str = "standard") -> tuple[list[dict], list[tuple[str, bytes]], int]:
    import pypdf
    import pypdfium2 as pdfium

    reader = pypdf.PdfReader(str(path))
    blocks: list[dict] = []
    visual_pages: list[tuple[str, bytes]] = []
    pdf = pdfium.PdfDocument(str(path))
    for page_index, page in enumerate(reader.pages):
        fragments: list[tuple[float, float, float, str]] = []

        def visitor(text, cm, tm, _font, font_size):
            value = re.sub(r"\s+", " ", text or "").strip()
            if value:
                fragments.append((float(tm[4] + cm[4]), float(tm[5] + cm[5]), float(font_size or 10), value))

        text = (page.extract_text(visitor_text=visitor) or "").strip()
        if fragments:
            lines: dict[int, list[tuple[float, float, str]]] = {}
            for x, y, size, value in fragments:
                lines.setdefault(round(y / 4), []).append((x, size, value))
            for line_key in sorted(lines, reverse=True):
                line = sorted(lines[line_key], key=lambda item: item[0])
                line_text = " ".join(item[2] for item in line).strip()
                if not line_text:
                    continue
                min_x = line[0][0]
                max_size = max(item[1] for item in line)
                max_x = max(item[0] + len(item[2]) * item[1] * 0.55 for item in line)
                y = line_key * 4
                blocks.append(_block(
                    document_file,
                    len(blocks),
                    line_text,
                    "text",
                    page=page_index + 1,
                    bbox=[min_x, y, max_x, y + max_size],
                ))
        elif text:
            blocks.append(_block(document_file, len(blocks), text, "text", page=page_index + 1))
        resources = page.get("/Resources") or {}
        has_images = bool(resources.get("/XObject"))
        if analysis_mode == "deep" or len(text) < 80 or has_images:
            bitmap = pdf[page_index].render(scale=1.5)
            buffer = io.BytesIO()
            bitmap.to_pil().save(buffer, format="PNG")
            visual_pages.append((f"page-{page_index + 1}.png", buffer.getvalue()))
    return blocks, visual_pages, len(reader.pages)


def _text_native(path: Path, document_file: DocumentFile) -> tuple[list[dict], list[tuple[str, bytes]], int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = [
        _block(document_file, index, part, "text")
        for index, part in enumerate(re.split(r"\n\s*\n", text))
        if part.strip()
    ]
    return blocks, [], 1


async def _vision_blocks(
    document_file: DocumentFile,
    images: list[tuple[str, bytes]],
    start: int,
    analysis_mode: str,
    native_available: bool,
) -> tuple[list[dict], list[str]]:
    blocks: list[dict] = []
    warnings: list[str] = []
    async with httpx.AsyncClient(timeout=180) as client:
        for image_name, image_bytes in images:
            try:
                page_match = re.search(r"page-(\d+)", image_name)
                default_page = int(page_match.group(1)) if page_match else None
                response = await client.post(
                    f"{settings.OCR_SERVER_URL}/execute",
                    json={
                        "tool": "document_page_parse",
                        "params": {
                            "image_base64": base64.b64encode(image_bytes).decode(),
                            "file_name": image_name,
                            "use_chart_recognition": True,
                            "analysis_mode": analysis_mode,
                            "cross_validate": analysis_mode == "deep",
                            "prefer_vision": analysis_mode == "deep" or not native_available,
                        },
                    },
                )
                response.raise_for_status()
                result = response.json()
                if result.get("status") != "success":
                    raise DocumentExtractionError(result.get("error") or "视觉解析服务未返回成功状态。")
                payload = result.get("data", {})
                warnings.extend(
                    f"{image_name}: {warning}"
                    for warning in payload.get("warnings") or []
                )
                for item in payload.get("blocks") or []:
                    text = item.get("text") or ""
                    if not text.strip():
                        continue
                    blocks.append(_block(
                        document_file,
                        start + len(blocks),
                        text,
                        block_type=item.get("type") or "image_text",
                        page=item.get("page") or default_page,
                        source=item.get("source") or "vision",
                        confidence=float(item.get("confidence") or 0.7),
                        table=item.get("table"),
                        bbox=item.get("bbox"),
                    ))
            except Exception as exc:
                warnings.append(f"{image_name}: {exc}")
    return blocks, warnings


def _deduplicate(blocks: list[dict]) -> list[dict]:
    result: list[dict] = []
    for block in sorted(blocks, key=lambda item: 0 if item["source"] == "native" else 1):
        block = dict(block)
        text_key = re.sub(r"[\W_]+", "", block.get("text", "")).lower()
        if not text_key:
            continue
        duplicate = next((item for item in result if (
            item.get("document_file_id") == block.get("document_file_id")
            and item.get("page") == block.get("page")
            and SequenceMatcher(
                None,
                re.sub(r"[\W_]+", "", item.get("text", "")).lower(),
                text_key,
            ).ratio() >= 0.94
        )), None)
        if duplicate:
            metadata = duplicate.setdefault("metadata", {})
            metadata.setdefault("corroborated_by", []).append({
                "source": block.get("source"),
                "confidence": block.get("confidence"),
                "bbox": block.get("bbox"),
            })
            duplicate["confidence"] = max(float(duplicate.get("confidence") or 0), float(block.get("confidence") or 0))
            continue
        result.append(block)
    for index, block in enumerate(result):
        block["block_id"] = f"f{block.get('document_file_id')}-b{index}"
    return result


def normalize_analysis_mode(mode: str | None) -> str:
    return mode if mode in ANALYSIS_MODES else "standard"


async def extract_document(document_file: DocumentFile, analysis_mode: str = "standard") -> dict[str, Any]:
    analysis_mode = normalize_analysis_mode(analysis_mode)
    path = file_storage.base_path / str(document_file.storage_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        if suffix == ".doc":
            raise DocumentExtractionError("暂不支持旧版 DOC，请转换为 DOCX 或 PDF。")
        raise DocumentExtractionError(f"不支持的文件格式：{suffix or '未知'}")
    if not path.exists():
        raise DocumentExtractionError("上传文件不存在或存储不可用。")

    try:
        if suffix == ".docx":
            native, images, pages = _docx_native(path, document_file)
        elif suffix == ".pdf":
            native, images, pages = _pdf_native(path, document_file, analysis_mode)
        elif suffix in IMAGE_SUFFIXES:
            native, images, pages = [], [(document_file.original_name or path.name, path.read_bytes())], 1
        else:
            native, images, pages = _text_native(path, document_file)
    except Exception as exc:
        raise DocumentExtractionError(f"文件解析失败：{exc}") from exc

    vision, warnings = await _vision_blocks(
        document_file,
        images,
        len(native),
        analysis_mode,
        bool(native),
    ) if images else ([], [])
    blocks = _deduplicate([*native, *vision])
    if not blocks:
        detail = f"；视觉解析失败：{'；'.join(warnings)}" if warnings else ""
        raise DocumentExtractionError(f"未提取到可分析的文档内容{detail}")
    return {
        "blocks": blocks,
        "analysis_mode": analysis_mode,
        "page_count": pages,
        "native_blocks": len(native),
        "ocr_blocks": sum(1 for block in vision if block.get("source") == "ocr"),
        "vision_blocks": len(vision),
        "warnings": warnings,
        "visual_incomplete": bool(warnings) and (analysis_mode == "deep" or not native),
    }


async def create_document_run(
    db: AsyncSession,
    task: TaskInstance,
    project_id: int,
    user_id: int,
    analysis_mode: str | None = None,
) -> DocumentAnalysisRun:
    mode = normalize_analysis_mode(analysis_mode)
    phase = await db.get(PhaseInstance, task.phase_id)
    assessment = await db.get(Assessment, phase.assessment_id) if phase else None
    if not phase or not assessment or assessment.project_id != project_id:
        raise DocumentExtractionError("文档任务不属于有效的测评流程。")
    files = (await db.execute(
        select(DocumentFile).where(
            DocumentFile.assessment_id == assessment.id,
            DocumentFile.task_id == task.id,
            DocumentFile.is_active.is_(True),
        ).order_by(DocumentFile.created_at)
    )).scalars().all()
    if not files:
        raise DocumentExtractionError("该任务尚未上传或归类文档。")
    previous_run_id = (await db.execute(
        select(DocumentAnalysisRun.id).where(
            DocumentAnalysisRun.task_id == task.id,
            DocumentAnalysisRun.status == "completed",
        ).order_by(DocumentAnalysisRun.created_at.desc()).limit(1)
    )).scalar_one_or_none()
    run = DocumentAnalysisRun(
        project_id=project_id,
        assessment_id=assessment.id,
        phase_id=phase.id,
        task_id=task.id,
        requested_by=user_id,
        run_kind="retest" if previous_run_id else "initial",
        analysis_mode=mode,
        parameters={"previous_run_id": previous_run_id},
        status="queued",
        progress={"stage": "queued", "percent": 0, "message": "等待文档分析"},
    )
    db.add(run)
    await db.flush()
    db.add_all(DocumentRunFile(analysis_run_id=run.id, document_file_id=file.id) for file in files)
    task.status = "in_progress"
    task.result = {"type": "doc_review", "status": "queued", "run_id": run.id, "analysis_mode": mode, "progress": run.progress}
    await db.commit()
    return run


async def create_document_batch_run(
    db: AsyncSession,
    phase_id: int,
    project_id: int,
    document_file_ids: list[int],
    user_id: int,
    analysis_mode: str | None = None,
    skipped_files: list[str] | None = None,
    duplicate_files: list[dict] | None = None,
) -> DocumentAnalysisRun:
    mode = normalize_analysis_mode(analysis_mode)
    phase = await db.get(PhaseInstance, phase_id)
    assessment = await db.get(Assessment, phase.assessment_id) if phase else None
    if not phase or not assessment or assessment.project_id != project_id:
        raise DocumentExtractionError("批量文档不属于有效的测评流程。")
    run = DocumentAnalysisRun(
        project_id=project_id,
        assessment_id=assessment.id,
        phase_id=phase.id,
        task_id=None,
        requested_by=user_id,
        run_kind="batch",
        analysis_mode=mode,
        status="queued",
        parameters={
            "skipped_files": skipped_files or [],
            "duplicate_files": duplicate_files or [],
        },
        progress={"stage": "queued", "percent": 0, "message": "等待批量文档归类"},
    )
    db.add(run)
    await db.flush()
    db.add_all(DocumentRunFile(analysis_run_id=run.id, document_file_id=file_id) for file_id in document_file_ids)
    await db.execute(update(DocumentFile).where(
        DocumentFile.id.in_(document_file_ids),
        DocumentFile.uploaded_in_run_id.is_(None),
    ).values(uploaded_in_run_id=run.id))
    await db.commit()
    return run


async def _files_for_run(db: AsyncSession, run_id: int) -> list[DocumentFile]:
    return list((await db.execute(
        select(DocumentFile)
        .join(DocumentRunFile, DocumentRunFile.document_file_id == DocumentFile.id)
        .where(DocumentRunFile.analysis_run_id == run_id, DocumentFile.is_active.is_(True))
        .order_by(DocumentFile.created_at)
    )).scalars().all())


async def _persist_blocks(
    db: AsyncSession,
    run: DocumentAnalysisRun,
    document_file: DocumentFile,
    extraction: dict[str, Any],
) -> list[dict[str, Any]]:
    await db.execute(delete(DocumentBlock).where(
        DocumentBlock.analysis_run_id == run.id,
        DocumentBlock.document_file_id == document_file.id,
    ))
    await db.execute(update(DocumentBlock).where(
        DocumentBlock.document_file_id == document_file.id,
        DocumentBlock.analysis_run_id != run.id,
        DocumentBlock.is_active.is_(True),
    ).values(is_active=False, embedding=None))
    vectors = [block.get("embedding") for block in extraction["blocks"]]
    embedding_model = next((block.get("embedding_model") for block in extraction["blocks"] if block.get("embedding_model")), None)
    embedding_error = None
    if not vectors or any(vector is None for vector in vectors):
        try:
            from app.services.llm_service import llm_service

            vectors = []
            models = []
            for start in range(0, len(extraction["blocks"]), 32):
                batch = extraction["blocks"][start:start + 32]
                result = await llm_service.embed_with_fallback(
                    db,
                    [str(block.get("text") or "")[:4000] for block in batch],
                    settings.DOCUMENT_EMBEDDING_DIMENSION,
                    input_type="passage",
                )
                vectors.extend(result["embeddings"])
                models.append(result["model"])
            embedding_model = models[0] if models and len(set(models)) == 1 else ",".join(dict.fromkeys(models))
        except SQLAlchemyError:
            raise
        except Exception as exc:
            vectors = [None] * len(extraction["blocks"])
            embedding_error = str(exc)

    rows = []
    for ordinal, block in enumerate(extraction["blocks"]):
        row = DocumentBlock(
            project_id=run.project_id,
            assessment_id=run.assessment_id,
            analysis_run_id=run.id,
            document_file_id=document_file.id,
            ordinal=ordinal,
            page_number=block.get("page"),
            section_path=[block["section"]] if block.get("section") else [],
            block_type=block.get("type") or "text",
            source=block.get("source") or "native",
            source_confidence=float(block.get("confidence") or 0),
            bbox=block.get("bbox"),
            text=block.get("text") or "",
            table_data=block.get("table"),
            content_sha256=block["content_hash"],
            metadata_json=block.get("metadata") or {},
            embedding_model=embedding_model if vectors[ordinal] is not None else None,
            embedding=vectors[ordinal],
            is_active=True,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    document_file.page_count = extraction["page_count"]
    document_file.parse_status = "parsed"
    document_file.extraction_summary = {
        key: extraction[key]
        for key in ("analysis_mode", "page_count", "native_blocks", "ocr_blocks", "vision_blocks", "warnings", "visual_incomplete")
    }
    document_file.extraction_summary.update({
        "embedding_status": "ready" if embedding_model and not embedding_error else "unavailable",
        "embedding_model": embedding_model,
        "embedding_error": embedding_error,
    })
    await knowledge_graph.sync_document_structure(
        db,
        project_id=run.project_id,
        assessment_id=run.assessment_id,
        phase_id=run.phase_id,
        task_id=run.task_id,
        run_id=run.id,
        file_id=document_file.id,
        blocks=[{
            "id": row.id,
            "ordinal": row.ordinal,
            "page_number": row.page_number,
            "section_path": row.section_path,
            "block_type": row.block_type,
            "content_sha256": row.content_sha256,
        } for row in rows],
    )
    return [{
        "block_id": row.id,
        "document_file_id": document_file.id,
        "file_name": document_file.original_name,
        "page": row.page_number,
        "section": row.section_path[-1] if row.section_path else None,
        "type": row.block_type,
        "bbox": row.bbox,
        "text": row.text,
        "table": row.table_data,
        "source": row.source,
        "confidence": row.source_confidence,
        "content_hash": row.content_sha256,
        "metadata": row.metadata_json,
        "embedding_model": row.embedding_model,
        "embedding": list(row.embedding) if row.embedding is not None else None,
    } for row in rows]


async def _extract_and_store(
    db: AsyncSession,
    run: DocumentAnalysisRun,
    document_file: DocumentFile,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cached_run_id = (await db.execute(
        select(DocumentBlock.analysis_run_id)
        .join(DocumentAnalysisRun, DocumentAnalysisRun.id == DocumentBlock.analysis_run_id)
        .where(
            DocumentBlock.document_file_id == document_file.id,
            DocumentBlock.analysis_run_id != run.id,
            DocumentAnalysisRun.analysis_mode == run.analysis_mode,
            DocumentAnalysisRun.status.in_(["running", "completed"]),
        )
        .order_by(DocumentAnalysisRun.created_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    if cached_run_id and document_file.extraction_summary:
        cached = (await db.execute(
            select(DocumentBlock).where(
                DocumentBlock.analysis_run_id == cached_run_id,
                DocumentBlock.document_file_id == document_file.id,
            ).order_by(DocumentBlock.ordinal)
        )).scalars().all()
        if cached:
            extraction = {
                **document_file.extraction_summary,
                "blocks": [{
                    "page": row.page_number,
                    "section": row.section_path[-1] if row.section_path else None,
                    "type": row.block_type,
                    "bbox": row.bbox,
                    "text": row.text,
                    "table": row.table_data,
                    "source": row.source,
                    "confidence": row.source_confidence,
                    "content_hash": row.content_sha256,
                    "metadata": row.metadata_json,
                    "embedding_model": row.embedding_model,
                    "embedding": list(row.embedding) if row.embedding is not None else None,
                } for row in cached],
                "cache_hit": True,
            }
            blocks = await _persist_blocks(db, run, document_file, extraction)
            summary = dict(document_file.extraction_summary or {})
            summary["cache_hit"] = True
            return blocks, summary
    extraction = await extract_document(document_file, run.analysis_mode)
    blocks = await _persist_blocks(db, run, document_file, extraction)
    summary = dict(document_file.extraction_summary or {})
    summary["cache_hit"] = False
    return blocks, summary


async def _persist_control_results(
    db: AsyncSession,
    run: DocumentAnalysisRun,
    analysis: dict[str, Any],
) -> None:
    await db.execute(delete(DocumentControlResult).where(DocumentControlResult.analysis_run_id == run.id))
    for control in analysis.get("controls") or []:
        failed = [point for point in control.get("points") or [] if point.get("status") in {"fail", "partial", "unable"}]
        reason = "；".join(
            point.get("llm_reason") or point.get("missing_judgement") or point.get("text") or "证据不足"
            for point in failed
        ) or "所有必需证据均已定位且未发现矛盾。"
        result = DocumentControlResult(
            project_id=run.project_id,
            assessment_id=run.assessment_id,
            task_id=run.task_id,
            analysis_run_id=run.id,
            control_uid=control.get("uid") or control.get("id"),
            verdict=control.get("status") or "unable",
            confidence=float(analysis.get("confidence") or 0),
            reason=reason,
            missing_requirements=[point.get("uid") for point in failed if point.get("status") == "fail"],
            contradictory_requirements=[point.get("uid") for point in failed if point.get("contradiction")],
            rule_snapshot={
                "control_id": control.get("id"),
                "title": control.get("title"),
                "points": [{key: point.get(key) for key in ("uid", "id", "text", "status", "severity", "missing_judgement")} for point in control.get("points") or []],
            },
            model_snapshot={
                "engine": analysis.get("evidence_engine"),
                "error": analysis.get("llm_review_error"),
                "points": [{
                    "uid": point.get("uid"),
                    "decision": point.get("status"),
                    "confidence": point.get("decision_confidence"),
                    "reason": point.get("llm_reason"),
                    "contradiction": bool(point.get("contradiction")),
                } for point in control.get("points") or []],
            },
        )
        db.add(result)
        await db.flush()
        for point in control.get("points") or []:
            requirement_uid = point.get("uid")
            if not requirement_uid:
                continue
            evidence = point.get("evidence") or []
            if not evidence and point.get("status") == "fail":
                await knowledge_graph.sync_missing_requirement(
                    db,
                    project_id=run.project_id,
                    assessment_id=run.assessment_id,
                    phase_id=run.phase_id,
                    task_id=run.task_id,
                    run_id=run.id,
                    result_id=result.id,
                    control_uid=result.control_uid,
                    requirement_uid=requirement_uid,
                )
            for rank, item in enumerate(evidence, start=1):
                stance = "contradict" if point.get("contradiction") else ("support" if point.get("status") == "pass" else "partial")
                link = DocumentEvidenceLink(
                    control_result_id=result.id,
                    document_block_id=int(item["block_id"]),
                    requirement_uid=requirement_uid,
                    stance=stance,
                    confidence=float(point.get("decision_confidence") or item.get("confidence") or analysis.get("confidence") or 0),
                    rationale=point.get("llm_reason") or f"命中：{', '.join(item.get('matched_keywords') or [])}",
                    rank=rank,
                )
                db.add(link)
                await knowledge_graph.sync_evidence_link(
                    db,
                    project_id=run.project_id,
                    assessment_id=run.assessment_id,
                    phase_id=run.phase_id,
                    task_id=run.task_id,
                    run_id=run.id,
                    result_id=result.id,
                    control_uid=result.control_uid,
                    requirement_uid=requirement_uid,
                    block_id=int(item["block_id"]),
                    stance=stance,
                    confidence=link.confidence,
                )


async def process_document_run(db: AsyncSession, run: DocumentAnalysisRun) -> None:
    task = await db.get(TaskInstance, run.task_id) if run.task_id else None
    if not task:
        raise DocumentExtractionError("关联的文档检查任务不存在。")
    files = await _files_for_run(db, run.id)
    if not files:
        raise DocumentExtractionError("该任务尚未上传文档。")
    previous_run_id = (run.parameters or {}).get("previous_run_id")
    previous_run = await db.get(DocumentAnalysisRun, previous_run_id) if previous_run_id else None
    previous_analysis = previous_run.result_summary if previous_run else None
    analysis_mode = run.analysis_mode
    user_id = run.requested_by or 0

    run.progress = {"stage": "native_extraction", "percent": 5, "message": "正在执行原生内容提取"}
    task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
    await db.commit()

    all_blocks: list[dict] = []
    total_pages = 0
    manifests = []
    extraction_failures = []
    visual_incomplete = False
    for index, document_file in enumerate(files):
        try:
            blocks, extraction_summary = await _extract_and_store(db, run, document_file)
            total_pages += extraction_summary["page_count"]
            if total_pages > settings.DOCUMENT_MAX_TOTAL_PAGES:
                raise DocumentExtractionError(f"文档总页数超过 {settings.DOCUMENT_MAX_TOTAL_PAGES} 页限制。")
            all_blocks.extend(blocks)
            visual_incomplete = visual_incomplete or bool(extraction_summary.get("visual_incomplete"))
            manifests.append({
                "document_file_id": document_file.id,
                "file_name": document_file.original_name,
                "status": "parsed",
                **extraction_summary,
            })
        except SQLAlchemyError:
            raise
        except Exception as exc:
            document_file.parse_status = "failed"
            document_file.extraction_summary = {"analysis_mode": analysis_mode, "error": str(exc)}
            failure = {
                "document_file_id": document_file.id,
                "file_name": document_file.original_name,
                "status": "failed",
                "error": str(exc),
            }
            extraction_failures.append(failure)
            manifests.append(failure)
        run.progress = {
            "stage": "fusion",
            "percent": 10 + int(45 * (index + 1) / len(files)),
            "message": f"已提取并融合 {index + 1}/{len(files)} 个文件",
        }
        task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
        await db.commit()

    if not all_blocks:
        detail = "；".join(item["error"] for item in extraction_failures) or "没有可分析内容"
        raise DocumentExtractionError(f"全部文档均无法提取：{detail}")

    run.progress = {"stage": "retrieval", "percent": 65, "message": "正在从标准图谱召回检查项和候选证据"}
    task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
    await db.commit()
    expected_name = task.name.split("文档检查：", 1)[1].strip() if "文档检查：" in task.name else task.name
    control_engine = await DocumentControlEngine.from_graph(db)
    analysis = await control_engine.analyze_retrieved(db, run.id, expected_doc_name=expected_name)
    analysis["files"] = manifests
    analysis["analysis_mode"] = analysis_mode
    analysis["document_file_ids"] = [document_file.id for document_file in files]
    analysis["run_id"] = run.id
    analysis["extraction_failures"] = extraction_failures
    run.progress = {"stage": "judging", "percent": 82, "message": "正在执行结构化证据判定"}
    task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
    await db.commit()
    analysis = await control_engine.review_with_llm(db, user_id, analysis)
    if extraction_failures or visual_incomplete:
        reasons = []
        if extraction_failures:
            reasons.append(f"{len(extraction_failures)} 个文件提取失败")
        if visual_incomplete:
            reasons.append("必要的视觉解析未完整完成")
        analysis["status"] = "unable"
        analysis["confidence"] = 0
        analysis["message"] = "；".join(reasons) + "，本次不能生成完整合规结论。"
    if previous_analysis and previous_analysis.get("type") == DOCUMENT_SOURCE:
        analysis["retest_comparison"] = build_retest_comparison(previous_analysis, analysis)

    run.progress = {"stage": "generating_results", "percent": 94, "message": "正在生成差距、整改和复测结果"}
    task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
    await db.commit()
    await _persist_control_results(db, run, analysis)
    from app.api.assessments import _sync_document_gap_findings
    sync = await _sync_document_gap_findings(db, run.project_id, task, analysis, user_id)
    analysis["gap_sync"] = sync
    task_result = {"type": "doc_review", "analysis": analysis, "document_file_ids": analysis["document_file_ids"], "run_id": run.id}
    from app.services.flow_engine import get_flow_engine
    await get_flow_engine(db).complete_task(task.id, task_result)
    run.status = "completed"
    run.result_summary = analysis
    if analysis.get("status") == "unable":
        run.error_code = None
        run.error_message = None
        run.progress = {
            "stage": "completed",
            "percent": 100,
            "message": analysis.get("message") or "分析完成，存在无法判断的检查项",
        }
    else:
        run.progress = {"stage": "completed", "percent": 100, "message": "文档合规分析完成"}
    run.completed_at = datetime.utcnow()
    await db.commit()


async def process_document_batch_run(db: AsyncSession, run: DocumentAnalysisRun) -> None:
    parameters = run.parameters or {}
    tasks = (await db.execute(
        select(TaskInstance).where(TaskInstance.phase_id == run.phase_id, TaskInstance.task_type == "doc_review")
    )).scalars().all()
    task_by_name = {
        task.name.split("文档检查：", 1)[1].strip(): task
        for task in tasks
        if "文档检查：" in task.name
    }
    if not task_by_name:
        raise DocumentExtractionError("当前阶段没有可用的文档检查任务。")
    files = await _files_for_run(db, run.id)
    if not files:
        raise DocumentExtractionError("批量上传任务没有可分析的文档。")
    run.progress = {"stage": "native_extraction", "percent": 5, "message": "正在提取并识别文档"}
    await db.commit()

    engine = await DocumentControlEngine.from_graph(db)
    classified: list[dict] = []
    unclassified: list[dict] = []
    affected_task_ids: set[int] = set()
    total_pages = 0
    for index, document_file in enumerate(files):
        run.progress = {
            "stage": "native_extraction",
            "percent": 5 + int(5 * index / len(files)),
            "message": f"正在处理 {index + 1}/{len(files)}：{document_file.original_name}",
        }
        await db.commit()
        try:
            blocks, extraction_summary = await _extract_and_store(db, run, document_file)
            total_pages += extraction_summary.get("page_count") or 0
            if total_pages > settings.DOCUMENT_MAX_TOTAL_PAGES:
                raise DocumentExtractionError(f"文档总页数超过 {settings.DOCUMENT_MAX_TOTAL_PAGES} 页限制。")
            rule_classification = engine.classify_blocks(document_file.original_name, blocks)
            classification = await engine.classify_with_llm(
                db,
                run.requested_by or 0,
                document_file.original_name,
                blocks,
                rule_classification,
            )
            document_file.classification = classification
            matched_task = task_by_name.get(classification.get("document_name"))
            if classification["status"] == "classified" and matched_task:
                document_file.task_id = matched_task.id
                affected_task_ids.add(matched_task.id)
                classified.append({
                    "document_file_id": document_file.id,
                    "file_name": document_file.original_name,
                    "task_id": matched_task.id,
                    **classification,
                })
            else:
                unclassified.append({"document_file_id": document_file.id, "file_name": document_file.original_name, **classification})
        except SQLAlchemyError:
            raise
        except Exception as exc:
            document_file.parse_status = "failed"
            document_file.extraction_summary = {"analysis_mode": run.analysis_mode, "error": str(exc)}
            unclassified.append({
                "document_file_id": document_file.id,
                "file_name": document_file.original_name,
                "status": "unclassified",
                "naming_status": "unable",
                "reason": str(exc),
                "confidence": 0,
            })
        run.progress = {
            "stage": "classification",
            "percent": 10 + int(60 * (index + 1) / len(files)),
            "message": f"已识别 {index + 1}/{len(files)} 个文档",
        }
        await db.commit()

    missing = []
    for document_name, task in task_by_name.items():
        has_document = (await db.execute(
            select(DocumentFile.id).where(
                DocumentFile.assessment_id == run.assessment_id,
                DocumentFile.task_id == task.id,
                DocumentFile.is_active.is_(True),
            ).limit(1)
        )).scalar_one_or_none()
        if not has_document:
            missing.append({"task_id": task.id, "document_name": document_name})

    run.result_summary = {
        "type": BATCH_DOCUMENT_SOURCE,
        "analysis_mode": run.analysis_mode,
        "total_files": len(files),
        "classified": classified,
        "unclassified": unclassified,
        "missing": missing,
        "skipped_files": parameters.get("skipped_files") or [],
        "duplicate_files": parameters.get("duplicate_files") or [],
        "coverage": round((len(task_by_name) - len(missing)) / len(task_by_name), 2),
    }
    run.progress = {"stage": "analyzing", "percent": 85, "message": "归类完成，正在逐项执行合规分析"}
    await db.commit()

    for task_id in sorted(affected_task_ids):
        task = await db.get(TaskInstance, task_id)
        if task:
            await create_document_run(db, task, run.project_id, run.requested_by or 0, run.analysis_mode)

    run.progress = {"stage": "completed", "percent": 100, "message": "文档已归类，合规分析任务已提交"}
    run.status = "completed"
    run.completed_at = datetime.utcnow()
    await db.commit()


async def recover_incomplete_document_runs(db: AsyncSession) -> int:
    recovered = list((await db.execute(
        update(DocumentAnalysisRun)
        .where(DocumentAnalysisRun.status == "running")
        .values(
            status="queued",
            started_at=None,
            progress={"stage": "queued", "percent": 0, "message": "Worker 重启，等待恢复文档分析"},
        )
        .returning(DocumentAnalysisRun.id)
    )).scalars().all())
    if recovered:
        await db.commit()
    return len(recovered)


async def process_pending_document_runs(db: AsyncSession, limit: int | None = None) -> int:
    runs = (await db.execute(
        select(DocumentAnalysisRun)
        .where(DocumentAnalysisRun.status == "queued")
        .order_by(DocumentAnalysisRun.created_at)
        .limit(limit or settings.DOCUMENT_WORKER_BATCH_SIZE)
    )).scalars().all()
    processed = 0
    for run in runs:
        run_id = run.id
        claimed = (await db.execute(
            update(DocumentAnalysisRun)
            .where(DocumentAnalysisRun.id == run.id, DocumentAnalysisRun.status == "queued")
            .values(status="running", started_at=datetime.utcnow())
            .returning(DocumentAnalysisRun.id)
        )).scalar_one_or_none()
        await db.commit()
        if not claimed:
            continue
        processed += 1
        try:
            if run.run_kind == "batch":
                await process_document_batch_run(db, run)
            else:
                await process_document_run(db, run)
        except Exception as exc:
            await db.rollback()
            logger.exception("Document analysis run %s failed", run_id)
            run = await db.get(DocumentAnalysisRun, run_id)
            if not run:
                continue
            task = await db.get(TaskInstance, run.task_id) if run.task_id else None
            if task:
                task.status = "failed"
                task.result = {"type": "doc_review", "status": "unable", "error": str(exc), "run_id": run.id}
            run.status = "failed"
            run.error_code = "document_extraction_failed" if isinstance(exc, DocumentExtractionError) else "document_analysis_failed"
            run.error_message = str(exc)
            run.progress = {"stage": "failed", "percent": 100, "message": str(exc)}
            run.completed_at = datetime.utcnow()
            await db.commit()
    return processed
