"""
证据管理服务
负责证据的上传、查询、删除
"""
import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.evidence import Evidence, EvidenceType
from app.models.questionnaire import QuestionnaireRecord
from app.services.file_storage import file_storage

logger = logging.getLogger(__name__)


class EvidenceService:
    """证据管理服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def upload_evidence(
        self,
        project_id: int,
        file_name: str,
        file_content: bytes,
        mime_type: Optional[str] = None,
        evidence_type: EvidenceType = EvidenceType.DOCUMENT,
        clause_id: Optional[str] = None,
        questionnaire_record_id: Optional[int] = None,
        finding_id: Optional[int] = None,
        description: Optional[str] = None,
        uploaded_by: Optional[int] = None,
    ) -> Evidence:
        """
        上传证据文件
        
        Args:
            project_id: 项目ID
            file_name: 文件名
            file_content: 文件内容
            mime_type: MIME 类型
            evidence_type: 证据类型
            clause_id: 关联的等保条款
            questionnaire_record_id: 关联的问卷记录
            finding_id: 关联的漏洞
            description: 证据描述
            uploaded_by: 上传用户ID
        
        Returns:
            创建的 Evidence 对象
        """
        # 保存文件到存储
        file_path, hash_sha256, file_size = await file_storage.save_file(
            project_id=project_id,
            file_name=file_name,
            content=file_content,
        )
        
        # 创建 Evidence 记录
        evidence = Evidence(
            project_id=project_id,
            finding_id=finding_id,
            questionnaire_record_id=questionnaire_record_id,
            clause_id=clause_id,
            evidence_type=evidence_type,
            source="manual",
            file_name=file_name,
            file_path=file_path,
            file_size=file_size,
            mime_type=mime_type,
            description=description,
            hash_sha256=hash_sha256,
            uploaded_by=uploaded_by,
        )
        
        self.db.add(evidence)
        await self.db.commit()
        await self.db.refresh(evidence)
        
        logger.info(f"Uploaded evidence: id={evidence.id}, file={file_name}, size={file_size}")
        
        return evidence
    
    async def get_evidence(self, evidence_id: int) -> Optional[Evidence]:
        """获取证据详情"""
        result = await self.db.execute(
            select(Evidence).where(Evidence.id == evidence_id)
        )
        return result.scalar_one_or_none()
    
    async def list_evidences_by_questionnaire(
        self,
        questionnaire_record_id: int
    ) -> List[Evidence]:
        """列出问卷记录关联的所有证据"""
        result = await self.db.execute(
            select(Evidence)
            .where(Evidence.questionnaire_record_id == questionnaire_record_id)
            .order_by(Evidence.created_at.desc())
        )
        return result.scalars().all()
    
    async def list_evidences_by_project(
        self,
        project_id: int,
        clause_id: Optional[str] = None
    ) -> List[Evidence]:
        """列出项目关联的所有证据"""
        query = select(Evidence).where(Evidence.project_id == project_id)
        
        if clause_id:
            query = query.where(Evidence.clause_id == clause_id)
        
        query = query.order_by(Evidence.created_at.desc())
        
        result = await self.db.execute(query)
        return result.scalars().all()
    
    async def download_evidence(self, evidence_id: int) -> Optional[bytes]:
        """
        下载证据文件
        
        Returns:
            文件内容，如果证据不存在则返回 None
        """
        evidence = await self.get_evidence(evidence_id)
        
        if not evidence or not evidence.file_path:
            return None
        
        return await file_storage.read_file(evidence.file_path)
    
    async def delete_evidence(self, evidence_id: int) -> bool:
        """
        删除证据
        
        Returns:
            是否删除成功
        """
        evidence = await self.get_evidence(evidence_id)
        
        if not evidence:
            return False
        
        # 删除文件
        if evidence.file_path:
            await file_storage.delete_file(evidence.file_path)
        
        # 删除数据库记录
        await self.db.delete(evidence)
        await self.db.commit()
        
        logger.info(f"Deleted evidence: id={evidence_id}")
        
        return True
    
    async def check_questionnaire_documents_complete(
        self,
        questionnaire_record_id: int
    ) -> dict:
        """
        检查问卷记录的文档证据是否完整
        
        Returns:
            {
                "complete": bool,
                "total_required": int,
                "total_uploaded": int,
                "missing_questions": [question_id, ...]
            }
        """
        # 获取问卷记录
        result = await self.db.execute(
            select(QuestionnaireRecord).where(QuestionnaireRecord.id == questionnaire_record_id)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            return {"complete": False, "total_required": 0, "total_uploaded": 0, "missing_questions": []}
        
        # 获取关联的证据
        evidences = await self.list_evidences_by_questionnaire(questionnaire_record_id)
        uploaded_question_ids = set()
        for e in evidences:
            if e.description and e.description.startswith("question:"):
                q_id = e.description.replace("question:", "")
                uploaded_question_ids.add(q_id)

        # 检查每个需要证据的问题
        questions = record.questions or []
        evidence_required = record.evidence_required or {}

        missing_questions = []
        for q in questions:
            q_id = q["id"]
            if q.get("evidence_required"):
                # 检查是否有证据关联到这个问题
                if q_id not in uploaded_question_ids:
                    missing_questions.append(q_id)
        
        total_required = len([q for q in questions if q.get("evidence_required")])
        
        return {
            "complete": len(missing_questions) == 0,
            "total_required": total_required,
            "total_uploaded": total_required - len(missing_questions),
            "missing_questions": missing_questions,
        }