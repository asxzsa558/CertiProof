"""
Document Check API - 文档检查 API
用于等保测评中 document 类型条款的合规性检查
"""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict, Any, List, Optional
import logging

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.services.document_check_service import DocumentCheckService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/document-check", tags=["Document Check"])


@router.post("/upload", response_model=Dict[str, Any])
async def upload_document(
    project_id: int = Form(...),
    clause_id: str = Form(...),
    doc_name: str = Form(...),
    file: UploadFile = File(...),
    description: Optional[str] = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    上传文档证据

    Args:
        project_id: 项目ID
        clause_id: 条款ID
        doc_name: 文档名称
        file: 上传的文件
        description: 文档描述（可选）

    Returns:
        上传结果
    """
    try:
        service = DocumentCheckService(db)

        # 读取文件内容
        file_content = await file.read()

        # 上传文档
        evidence = await service.upload_document(
            project_id=project_id,
            clause_id=clause_id,
            doc_name=doc_name,
            file_name=file.filename,
            file_content=file_content,
            mime_type=file.content_type,
            user_id=current_user.id,
            description=description
        )

        return {
            "status": "success",
            "evidence_id": evidence.id,
            "file_name": evidence.file_name,
            "file_size": evidence.file_size,
            "message": f"文档 {doc_name} 上传成功"
        }
    except Exception as e:
        logger.error(f"Failed to upload document: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"上传失败: {str(e)}")


@router.get("/clause/{clause_id}", response_model=Dict[str, Any])
async def check_clause(
    clause_id: str,
    project_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    检查某个 document 条款的合规性

    Args:
        clause_id: 条款ID
        project_id: 项目ID

    Returns:
        检查结果
    """
    try:
        service = DocumentCheckService(db)
        result = await service.check_clause(
            project_id=project_id,
            clause_id=clause_id,
            user_id=current_user.id
        )
        return result
    except Exception as e:
        logger.error(f"Failed to check clause {clause_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"检查失败: {str(e)}")


@router.get("/project/{project_id}/report", response_model=Dict[str, Any])
async def generate_report(
    project_id: int,
    clauses: Optional[List[str]] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    生成项目的文档检查报告

    Args:
        project_id: 项目ID
        clauses: 要检查的条款列表（None 表示检查所有 document 类型条款）

    Returns:
        报告数据
    """
    try:
        service = DocumentCheckService(db)
        report = await service.generate_report(
            project_id=project_id,
            clauses=clauses
        )
        return report
    except Exception as e:
        logger.error(f"Failed to generate report for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"生成报告失败: {str(e)}")


@router.get("/project/{project_id}/clauses", response_model=Dict[str, Any])
async def list_document_clauses(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    获取项目相关的 document 类型条款列表及其状态

    Args:
        project_id: 项目ID

    Returns:
        条款列表及状态
    """
    try:
        service = DocumentCheckService(db)

        # 获取所有 document 类型条款
        all_clauses = await service._get_all_document_clauses()

        # 检查每个条款的状态
        results = []
        for clause_id in all_clauses:
            result = await service.check_clause(
                project_id=project_id,
                clause_id=clause_id,
                user_id=current_user.id
            )
            results.append({
                "clause_id": clause_id,
                "clause_name": result.get("clause_name", ""),
                "status": result.get("status", "fail"),
                "pass_rate": result.get("pass_rate", 0),
                "total_required": result.get("total_required", 0),
                "total_uploaded": result.get("total_uploaded", 0)
            })

        return {
            "project_id": project_id,
            "total_clauses": len(results),
            "clauses": results
        }
    except Exception as e:
        logger.error(f"Failed to list document clauses for project {project_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"获取条款列表失败: {str(e)}")
