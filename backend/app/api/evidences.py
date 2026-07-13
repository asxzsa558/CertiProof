"""
证据管理 API
负责文件上传、下载、删除
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Optional
from pydantic import BaseModel
import io

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.evidence import Evidence, EvidenceType
from app.models.finding import Finding
from app.models.questionnaire import QuestionnaireRecord
from app.services.evidence_service import EvidenceService
from app.services.upload_validation import read_limited_upload

router = APIRouter(prefix="/evidences", tags=["Evidences"])
logger = logging.getLogger(__name__)
MAX_EVIDENCE_UPLOAD_SIZE = 100 * 1024 * 1024


# ========== Response Models ==========

class EvidenceResponse(BaseModel):
    id: int
    project_id: int
    questionnaire_record_id: Optional[int] = None
    finding_id: Optional[int] = None
    clause_id: Optional[str] = None
    evidence_type: str
    file_name: Optional[str] = None
    file_size: Optional[int] = None
    mime_type: Optional[str] = None
    description: Optional[str] = None
    hash_sha256: Optional[str] = None
    created_at: str
    
    class Config:
        from_attributes = True


# ========== API Endpoints ==========

@router.post("/upload", response_model=EvidenceResponse)
async def upload_evidence(
    project_id: int = Form(...),
    file: UploadFile = File(...),
    evidence_type: str = Form("document"),
    clause_id: Optional[str] = Form(None),
    questionnaire_record_id: Optional[int] = Form(None),
    finding_id: Optional[int] = Form(None),
    question_id: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    上传证据文件
    
    支持的 evidence_type:
    - document: 通用文档
    - policy: 制度文档
    - record: 记录文档
    - screenshot: 截图
    - log: 日志文件
    """
    service = EvidenceService(db)
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "evidence:manage")

    if finding_id:
        finding = await db.get(Finding, finding_id)
        if not finding or finding.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Finding does not belong to this project",
            )

    if questionnaire_record_id:
        record = await db.get(QuestionnaireRecord, questionnaire_record_id)
        if not record or record.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Questionnaire record does not belong to this project",
            )
    
    try:
        content = await read_limited_upload(file, MAX_EVIDENCE_UPLOAD_SIZE)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE if "超过" in str(exc) else status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    
    # 验证 evidence_type
    try:
        ev_type = EvidenceType(evidence_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid evidence_type: {evidence_type}"
        )
    
    # 如果关联到问卷，自动使用 question_id 作为描述
    if questionnaire_record_id and question_id:
        description = f"question:{question_id}"
    
    # 上传证据
    evidence = await service.upload_evidence(
        project_id=project_id,
        file_name=file.filename,
        file_content=content,
        mime_type=file.content_type,
        evidence_type=ev_type,
        clause_id=clause_id,
        questionnaire_record_id=questionnaire_record_id,
        finding_id=finding_id,
        description=description,
        uploaded_by=current_user.id,
    )
    
    return EvidenceResponse(
        id=evidence.id,
        project_id=evidence.project_id,
        questionnaire_record_id=evidence.questionnaire_record_id,
        finding_id=evidence.finding_id,
        clause_id=evidence.clause_id,
        evidence_type=evidence.evidence_type.value if hasattr(evidence.evidence_type, 'value') else str(evidence.evidence_type),
        file_name=evidence.file_name,
        file_size=evidence.file_size,
        mime_type=evidence.mime_type,
        description=evidence.description,
        hash_sha256=evidence.hash_sha256,
        created_at=evidence.created_at.isoformat(),
    )


@router.get("/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取证据详情"""
    service = EvidenceService(db)
    evidence = await service.get_evidence(evidence_id)
    
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found"
        )
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, evidence.project_id, current_user.id, "assessment:read")
    
    return EvidenceResponse(
        id=evidence.id,
        project_id=evidence.project_id,
        questionnaire_record_id=evidence.questionnaire_record_id,
        finding_id=evidence.finding_id,
        clause_id=evidence.clause_id,
        evidence_type=evidence.evidence_type.value if hasattr(evidence.evidence_type, 'value') else str(evidence.evidence_type),
        file_name=evidence.file_name,
        file_size=evidence.file_size,
        mime_type=evidence.mime_type,
        description=evidence.description,
        hash_sha256=evidence.hash_sha256,
        created_at=evidence.created_at.isoformat(),
    )


@router.get("/{evidence_id}/download")
async def download_evidence(
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """下载证据文件"""
    service = EvidenceService(db)
    evidence = await service.get_evidence(evidence_id)
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found"
        )
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, evidence.project_id, current_user.id, "assessment:read")

    content = await service.download_evidence(evidence_id)
    if not content:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file missing"
        )
    
    return StreamingResponse(
        io.BytesIO(content),
        media_type=evidence.mime_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'attachment; filename="{evidence.file_name or "evidence"}"'
        }
    )


@router.delete("/{evidence_id}")
async def delete_evidence(
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除证据"""
    service = EvidenceService(db)
    evidence = await service.get_evidence(evidence_id)
    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found"
        )
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, evidence.project_id, current_user.id, "evidence:manage")

    success = await service.delete_evidence(evidence_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found"
        )
    
    return {"message": "Evidence deleted", "id": evidence_id}


@router.get("/questionnaire/{questionnaire_record_id}/list", response_model=list[EvidenceResponse])
async def list_questionnaire_evidences(
    questionnaire_record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出问卷关联的所有证据"""
    service = EvidenceService(db)
    record = await db.get(QuestionnaireRecord, questionnaire_record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Questionnaire record not found")
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, record.project_id, current_user.id, "assessment:read")

    evidences = await service.list_evidences_by_questionnaire(questionnaire_record_id)
    
    return [
        EvidenceResponse(
            id=e.id,
            project_id=e.project_id,
            questionnaire_record_id=e.questionnaire_record_id,
            finding_id=e.finding_id,
            clause_id=e.clause_id,
            evidence_type=e.evidence_type.value if hasattr(e.evidence_type, 'value') else str(e.evidence_type),
            file_name=e.file_name,
            file_size=e.file_size,
            mime_type=e.mime_type,
            description=e.description,
            hash_sha256=e.hash_sha256,
            created_at=e.created_at.isoformat(),
        )
        for e in evidences
    ]


@router.get("/questionnaire/{questionnaire_record_id}/completeness")
async def check_completeness(
    questionnaire_record_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """检查问卷证据完整性"""
    service = EvidenceService(db)
    record = await db.get(QuestionnaireRecord, questionnaire_record_id)
    if not record:
        raise HTTPException(status_code=404, detail="Questionnaire record not found")
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, record.project_id, current_user.id, "assessment:read")

    result = await service.check_questionnaire_documents_complete(questionnaire_record_id)
    
    return result


@router.get("/project/{project_id}/list", response_model=list[EvidenceResponse])
async def list_project_evidences(
    project_id: int,
    clause_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """列出项目关联的所有证据"""
    service = EvidenceService(db)
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "assessment:read")

    evidences = await service.list_evidences_by_project(project_id, clause_id)
    
    return [
        EvidenceResponse(
            id=e.id,
            project_id=e.project_id,
            questionnaire_record_id=e.questionnaire_record_id,
            finding_id=e.finding_id,
            clause_id=e.clause_id,
            evidence_type=e.evidence_type.value if hasattr(e.evidence_type, 'value') else str(e.evidence_type),
            file_name=e.file_name,
            file_size=e.file_size,
            mime_type=e.mime_type,
            description=e.description,
            hash_sha256=e.hash_sha256,
            created_at=e.created_at.isoformat(),
        )
        for e in evidences
    ]
