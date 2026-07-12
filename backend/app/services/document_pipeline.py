"""Document extraction and asynchronous compliance analysis."""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.assessment import TaskInstance
from app.models.evidence import Evidence
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.services.document_control_engine import DocumentControlEngine
from app.services.file_storage import file_storage

logger = logging.getLogger(__name__)
DOCUMENT_SOURCE = "document_control_analysis"
SUPPORTED_SUFFIXES = {".docx", ".pdf", ".txt", ".md", ".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
ANALYSIS_MODES = {"standard", "deep"}


class DocumentExtractionError(ValueError):
    pass


def _block(
    evidence: Evidence,
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
        "block_id": f"e{evidence.id}-b{index}",
        "evidence_id": evidence.id,
        "file_name": evidence.file_name,
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


def _docx_native(path: Path, evidence: Evidence) -> tuple[list[dict], list[tuple[str, bytes]], int]:
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
                blocks.append(_block(evidence, len(blocks), text, "table", section=current_section, table=rows))
            continue
        text = item.text.strip()
        if not text:
            continue
        style = (item.style.name or "").lower() if item.style else ""
        block_type = "heading" if "heading" in style or "标题" in style else "text"
        if block_type == "heading":
            current_section = text
        blocks.append(_block(evidence, len(blocks), text, block_type, section=current_section))

    for section in document.sections:
        for block_type, container in (("header", section.header), ("footer", section.footer)):
            text = "\n".join(p.text.strip() for p in container.paragraphs if p.text.strip())
            if text:
                blocks.append(_block(evidence, len(blocks), text, block_type))

    images: list[tuple[str, bytes]] = []
    with zipfile.ZipFile(path) as archive:
        for name in archive.namelist():
            if name.startswith("word/media/") and Path(name).suffix.lower() in IMAGE_SUFFIXES:
                images.append((Path(name).name, archive.read(name)))
    return blocks, images, max(1, len(document.sections))


def _pdf_native(path: Path, evidence: Evidence, analysis_mode: str = "standard") -> tuple[list[dict], list[tuple[str, bytes]], int]:
    import pypdf
    import pypdfium2 as pdfium

    reader = pypdf.PdfReader(str(path))
    blocks: list[dict] = []
    visual_pages: list[tuple[str, bytes]] = []
    pdf = pdfium.PdfDocument(str(path))
    for page_index, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            blocks.append(_block(evidence, len(blocks), text, "text", page=page_index + 1))
        resources = page.get("/Resources") or {}
        has_images = bool(resources.get("/XObject"))
        if analysis_mode == "deep" or len(text) < 80 or has_images:
            bitmap = pdf[page_index].render(scale=1.5)
            buffer = io.BytesIO()
            bitmap.to_pil().save(buffer, format="PNG")
            visual_pages.append((f"page-{page_index + 1}.png", buffer.getvalue()))
    return blocks, visual_pages, len(reader.pages)


def _text_native(path: Path, evidence: Evidence) -> tuple[list[dict], list[tuple[str, bytes]], int]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    blocks = [
        _block(evidence, index, part, "text")
        for index, part in enumerate(re.split(r"\n\s*\n", text))
        if part.strip()
    ]
    return blocks, [], 1


async def _vision_blocks(evidence: Evidence, images: list[tuple[str, bytes]], start: int) -> tuple[list[dict], list[str]]:
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
                        },
                    },
                )
                response.raise_for_status()
                result = response.json()
                if result.get("status") != "success":
                    raise DocumentExtractionError(result.get("error") or "视觉解析服务未返回成功状态。")
                payload = result.get("data", {})
                for item in payload.get("blocks") or []:
                    text = item.get("text") or ""
                    if not text.strip():
                        continue
                    blocks.append(_block(
                        evidence,
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
    seen: set[tuple] = set()
    for block in sorted(blocks, key=lambda item: 0 if item["source"] == "native" else 1):
        text_key = re.sub(r"[\W_]+", "", block.get("text", "")).lower()
        key = (block.get("evidence_id"), block.get("page"), text_key)
        if not text_key or key in seen:
            continue
        seen.add(key)
        result.append(block)
    return result


def normalize_analysis_mode(mode: str | None) -> str:
    return mode if mode in ANALYSIS_MODES else "standard"


async def extract_evidence(evidence: Evidence, analysis_mode: str = "standard") -> dict[str, Any]:
    analysis_mode = normalize_analysis_mode(analysis_mode)
    path = file_storage.base_path / str(evidence.file_path)
    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        if suffix == ".doc":
            raise DocumentExtractionError("暂不支持旧版 DOC，请转换为 DOCX 或 PDF。")
        raise DocumentExtractionError(f"不支持的文件格式：{suffix or '未知'}")
    if not path.exists():
        raise DocumentExtractionError("上传文件不存在或存储不可用。")

    try:
        if suffix == ".docx":
            native, images, pages = _docx_native(path, evidence)
        elif suffix == ".pdf":
            native, images, pages = _pdf_native(path, evidence, analysis_mode)
        elif suffix in IMAGE_SUFFIXES:
            native, images, pages = [], [(evidence.file_name or path.name, path.read_bytes())], 1
        else:
            native, images, pages = _text_native(path, evidence)
    except Exception as exc:
        raise DocumentExtractionError(f"文件解析失败：{exc}") from exc

    vision, warnings = await _vision_blocks(evidence, images, len(native)) if images else ([], [])
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
    }


async def create_document_run(
    db: AsyncSession,
    task: TaskInstance,
    project_id: int,
    user_id: int,
    analysis_mode: str | None = None,
) -> ScanTask:
    mode = normalize_analysis_mode(analysis_mode)
    previous_analysis = (task.result or {}).get("analysis") if isinstance(task.result, dict) else None
    parameters = {
        "source": DOCUMENT_SOURCE,
        "task_id": task.id,
        "user_id": user_id,
        "analysis_mode": mode,
    }
    if previous_analysis and previous_analysis.get("type") == DOCUMENT_SOURCE:
        parameters["previous_analysis"] = previous_analysis
    run = ScanTask(
        project_id=project_id,
        task_type=ScanTaskType.TARGETED,
        status=ScanTaskStatus.PENDING,
        triggered_by=TriggeredBy.MANUAL,
        parameters=parameters,
        orchestrator_task_id=None,
        progress={"stage": "queued", "percent": 0, "message": "等待文档分析"},
    )
    db.add(run)
    task.status = "in_progress"
    task.result = {"type": "doc_review", "status": "queued", "run_id": None, "analysis_mode": mode, "progress": run.progress}
    await db.commit()
    await db.refresh(run)
    task.result = {"type": "doc_review", "status": "queued", "run_id": run.id, "analysis_mode": mode, "progress": run.progress}
    await db.commit()
    return run


async def process_document_run(db: AsyncSession, run: ScanTask) -> None:
    task_id = int((run.parameters or {}).get("task_id"))
    user_id = int((run.parameters or {}).get("user_id") or 0)
    analysis_mode = normalize_analysis_mode((run.parameters or {}).get("analysis_mode"))
    task = await db.get(TaskInstance, task_id)
    if not task:
        raise DocumentExtractionError("关联的文档检查任务不存在。")

    clause_id = f"DOC-TASK-{task.id}"
    evidences = (await db.execute(
        select(Evidence)
        .where(Evidence.project_id == run.project_id, Evidence.clause_id == clause_id)
        .order_by(Evidence.created_at)
    )).scalars().all()
    if not evidences:
        raise DocumentExtractionError("该任务尚未上传文档。")

    previous_analysis = (run.parameters or {}).get("previous_analysis")
    if not previous_analysis:
        previous_analysis = (task.result or {}).get("analysis") if isinstance(task.result, dict) else None

    run.status = ScanTaskStatus.RUNNING
    run.started_at = datetime.utcnow()
    run.progress = {"stage": "extracting", "percent": 5, "message": "正在提取文档内容"}
    task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
    await db.commit()

    all_blocks: list[dict] = []
    total_pages = 0
    manifests = []
    for index, evidence in enumerate(evidences):
        extraction = await extract_evidence(evidence, analysis_mode)
        total_pages += extraction["page_count"]
        if total_pages > settings.DOCUMENT_MAX_TOTAL_PAGES:
            raise DocumentExtractionError(f"文档总页数超过 {settings.DOCUMENT_MAX_TOTAL_PAGES} 页限制。")
        evidence.content = extraction
        all_blocks.extend(extraction["blocks"])
        manifests.append({
            "evidence_id": evidence.id,
            "file_name": evidence.file_name,
            "analysis_mode": extraction["analysis_mode"],
            "page_count": extraction["page_count"],
            "native_blocks": extraction["native_blocks"],
            "ocr_blocks": extraction["ocr_blocks"],
            "vision_blocks": extraction["vision_blocks"],
            "warnings": extraction["warnings"],
        })
        run.progress = {
            "stage": "extracting",
            "percent": 10 + int(45 * (index + 1) / len(evidences)),
            "message": f"已解析 {index + 1}/{len(evidences)} 个文件",
        }
        task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
        await db.commit()

    run.progress = {"stage": "comparing", "percent": 65, "message": "正在与标准库逐项比对"}
    task.result = {"type": "doc_review", "status": "processing", "run_id": run.id, "analysis_mode": analysis_mode, "progress": run.progress}
    await db.commit()
    expected_name = task.name.split("文档检查：", 1)[1].strip() if "文档检查：" in task.name else task.name
    analysis = DocumentControlEngine().analyze_blocks(all_blocks, expected_doc_name=expected_name)
    analysis["files"] = manifests
    analysis["analysis_mode"] = analysis_mode
    analysis["evidence_ids"] = [evidence.id for evidence in evidences]
    analysis["run_id"] = run.id
    analysis = await DocumentControlEngine().review_with_llm(db, user_id, analysis)
    if previous_analysis and previous_analysis.get("type") == DOCUMENT_SOURCE:
        before = previous_analysis.get("coverage") or 0
        after = analysis.get("coverage") or 0
        fixed = sorted(set(previous_analysis.get("gaps", [])) - set(analysis.get("gaps", [])))
        new_gaps = sorted(set(analysis.get("gaps", [])) - set(previous_analysis.get("gaps", [])))
        analysis["retest_comparison"] = {
            "previous_status": previous_analysis.get("status"),
            "current_status": analysis.get("status"),
            "previous_coverage": before,
            "current_coverage": after,
            "delta": round(after - before, 2),
            "status": "improved" if after > before else ("regressed" if after < before else "unchanged"),
            "initial_gaps": previous_analysis.get("gaps", []),
            "current_gaps": analysis.get("gaps", []),
            "fixed_gaps": fixed,
            "new_gaps": new_gaps,
        }

    from app.api.assessments import _sync_document_gap_findings
    sync = await _sync_document_gap_findings(db, run.project_id, task, analysis, user_id)
    analysis["gap_sync"] = sync
    task_result = {"type": "doc_review", "analysis": analysis, "evidence_ids": analysis["evidence_ids"], "run_id": run.id}
    if analysis.get("status") == "unable":
        task.status = "failed"
        task.completed_at = datetime.utcnow()
        task.result = task_result
    else:
        from app.services.flow_engine import get_flow_engine
        await get_flow_engine(db).complete_task(task.id, task_result)
    run.status = ScanTaskStatus.COMPLETED if analysis.get("status") != "unable" else ScanTaskStatus.FAILED
    run.result_summary = analysis
    run.findings_count = (sync or {}).get("created_or_updated", 0)
    run.progress = {"stage": "completed", "percent": 100, "message": "文档合规分析完成"}
    run.completed_at = datetime.utcnow()
    await db.commit()


async def process_pending_document_runs(db: AsyncSession, limit: int | None = None) -> int:
    runs = (await db.execute(
        select(ScanTask)
        .where(
            ScanTask.status == ScanTaskStatus.PENDING,
            ScanTask.parameters["source"].as_string() == DOCUMENT_SOURCE,
        )
        .order_by(ScanTask.created_at)
        .limit(limit or settings.DOCUMENT_WORKER_BATCH_SIZE)
    )).scalars().all()
    for run in runs:
        try:
            await process_document_run(db, run)
        except Exception as exc:
            logger.exception("Document analysis run %s failed", run.id)
            task = await db.get(TaskInstance, int((run.parameters or {}).get("task_id") or 0))
            if task:
                task.status = "failed"
                task.result = {"type": "doc_review", "status": "unable", "error": str(exc), "run_id": run.id}
            run.status = ScanTaskStatus.FAILED
            run.error_message = str(exc)
            run.progress = {"stage": "failed", "percent": 100, "message": str(exc)}
            run.completed_at = datetime.utcnow()
            await db.commit()
    return len(runs)
