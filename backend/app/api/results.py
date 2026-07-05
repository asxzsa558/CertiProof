from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from typing import List

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.scan_task import ScanTask
from app.models.finding import Finding
from app.models.evidence import Evidence
from app.schemas.result import (
    ScanTaskResponse,
    ScanTaskDetail,
    FindingResponse,
    FindingDetail,
    EvidenceResponse,
    ResultSummary,
)

router = APIRouter(prefix="/results", tags=["Results"])


@router.get("/projects/{project_id}/scans", response_model=List[ScanTaskResponse])
async def list_scan_tasks(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取项目的所有扫描任务"""
    # 验证项目存在且用户有权限访问
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, project_id, current_user.id, "scan:read")
    
    # 获取扫描任务列表
    result = await db.execute(
        select(ScanTask)
        .where(ScanTask.project_id == project_id)
        .order_by(ScanTask.created_at.desc())
    )
    scan_tasks = result.scalars().all()
    
    return scan_tasks


@router.get("/scans/{scan_task_id}", response_model=ScanTaskDetail)
async def get_scan_task(
    scan_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取扫描任务详情"""
    result = await db.execute(
        select(ScanTask).where(ScanTask.id == scan_task_id)
    )
    scan_task = result.scalar_one_or_none()
    
    if not scan_task:
        raise HTTPException(status_code=404, detail="Scan task not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:read")
    
    # 获取 findings
    result = await db.execute(
        select(Finding).where(Finding.scan_task_id == scan_task_id)
    )
    findings = result.scalars().all()
    
    # 构建响应
    response = ScanTaskDetail.model_validate(scan_task)
    response.findings = [FindingResponse.model_validate(f) for f in findings]
    
    return response


@router.get("/scans/{scan_task_id}/summary", response_model=ResultSummary)
async def get_scan_summary(
    scan_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取扫描结果摘要"""
    result = await db.execute(
        select(ScanTask).where(ScanTask.id == scan_task_id)
    )
    scan_task = result.scalar_one_or_none()
    
    if not scan_task:
        raise HTTPException(status_code=404, detail="Scan task not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    project = await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:read")
    
    # 获取 findings
    result = await db.execute(
        select(Finding).where(Finding.scan_task_id == scan_task_id)
    )
    findings = result.scalars().all()
    
    # 统计
    passed = sum(1 for f in findings if f.judgment.value == "pass")
    failed = sum(1 for f in findings if f.judgment.value == "fail")
    partial = sum(1 for f in findings if f.judgment.value == "partial")
    
    return ResultSummary(
        scan_task=ScanTaskResponse.model_validate(scan_task),
        findings=[FindingResponse.model_validate(f) for f in findings],
        total_findings=len(findings),
        passed=passed,
        failed=failed,
        partial=partial,
        compliance_score=project.compliance_score,
    )


@router.get("/findings/{finding_id}", response_model=FindingDetail)
async def get_finding(
    finding_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Finding 详情"""
    result = await db.execute(
        select(Finding).where(Finding.id == finding_id)
    )
    finding = result.scalar_one_or_none()
    
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, finding.project_id, current_user.id, "scan:read")
    
    # 获取 evidences
    result = await db.execute(
        select(Evidence).where(Evidence.finding_id == finding_id)
    )
    evidences = result.scalars().all()
    
    # 构建响应
    response = FindingDetail.model_validate(finding)
    response.evidences = [EvidenceResponse.model_validate(e) for e in evidences]
    
    return response


@router.get("/evidences/{evidence_id}", response_model=EvidenceResponse)
async def get_evidence(
    evidence_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """获取 Evidence 详情"""
    result = await db.execute(
        select(Evidence).where(Evidence.id == evidence_id)
    )
    evidence = result.scalar_one_or_none()
    
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found")
    
    # 验证项目属于当前用户
    result = await db.execute(
        select(Finding).where(Finding.id == evidence.finding_id)
    )
    finding = result.scalar_one_or_none()
    
    from app.api.projects import get_project_for_user
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found")
    await get_project_for_user(db, finding.project_id, current_user.id, "scan:read")
    
    return evidence


@router.delete("/scans/{scan_task_id}")
async def delete_scan_task(
    scan_task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """删除扫描任务及其关联数据"""
    # 获取扫描任务
    result = await db.execute(
        select(ScanTask).where(ScanTask.id == scan_task_id)
    )
    scan_task = result.scalar_one_or_none()
    
    if not scan_task:
        raise HTTPException(status_code=404, detail="Scan task not found")
    
    # 验证项目属于当前用户
    from app.api.projects import get_project_for_user
    await get_project_for_user(db, scan_task.project_id, current_user.id, "scan:cancel")
    
    # 删除关联的 evidences（通过 findings）
    result = await db.execute(
        select(Finding).where(Finding.scan_task_id == scan_task_id)
    )
    findings = result.scalars().all()
    
    for finding in findings:
        await db.execute(
            delete(Evidence).where(Evidence.finding_id == finding.id)
        )
    
    # 删除关联的 findings
    await db.execute(
        delete(Finding).where(Finding.scan_task_id == scan_task_id)
    )
    
    # 删除扫描任务
    await db.execute(
        delete(ScanTask).where(ScanTask.id == scan_task_id)
    )
    
    await db.commit()
    
    return {"message": "扫描任务已删除"}
