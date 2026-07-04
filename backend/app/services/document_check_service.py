"""
Document Check Service - 文档检查服务
用于检查 document 类型等保条款的合规性
"""
import logging
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.models.evidence import Evidence, EvidenceType
from app.services.evidence_service import EvidenceService

logger = logging.getLogger(__name__)


class DocumentCheckService:
    """文档检查服务 - 用于等保测评中 document 类型条款的合规性检查"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.evidence_service = EvidenceService(db)

    async def check_clause(
        self,
        project_id: int,
        clause_id: str,
        user_id: int
    ) -> Dict[str, Any]:
        """
        检查某个 document 条款的合规性

        Returns:
            {
                "clause_id": str,
                "status": "pass" | "fail" | "partial",
                "required_docs": List[Dict],
                "uploaded_docs": List[Dict],
                "missing_docs": List[Dict],
                "validation_results": List[Dict],
                "pass_rate": float
            }
        """
        # 1. 获取条款定义（从条款库加载）
        clause = await self._get_clause_definition(clause_id)
        if not clause:
            return {
                "clause_id": clause_id,
                "status": "fail",
                "error": f"条款 {clause_id} 不存在"
            }

        # 2. 获取该项目已上传的、关联该条款的证据
        evidences = await self.evidence_service.list_evidences_by_project(
            project_id=project_id,
            clause_id=clause_id
        )

        # 3. 验证每个必需文档
        required_docs = clause.get("required_docs", [])
        validation_results = []
        for req_doc in required_docs:
            matched_evidence = self._find_matching_evidence(req_doc, evidences)
            result = await self.validate_file(req_doc, matched_evidence)
            validation_results.append(result)

        # 4. 统计结果
        uploaded_docs = [r for r in validation_results if r["uploaded"]]
        missing_docs = [r for r in validation_results if not r["uploaded"]]

        total = len(required_docs)
        passed = len(uploaded_docs)
        pass_rate = passed / total if total > 0 else 1.0

        if passed == total:
            status = "pass"
        elif passed == 0:
            status = "fail"
        else:
            status = "partial"

        return {
            "clause_id": clause_id,
            "clause_name": clause.get("name", ""),
            "status": status,
            "pass_rate": round(pass_rate, 2),
            "required_docs": required_docs,
            "uploaded_docs": [r for r in validation_results if r["uploaded"]],
            "missing_docs": missing_docs,
            "validation_results": validation_results,
            "total_required": total,
            "total_uploaded": passed
        }

    async def validate_file(
        self,
        required_doc: Dict[str, Any],
        evidence: Optional[Evidence]
    ) -> Dict[str, Any]:
        """
        验证单个文件是否满足要求

        Args:
            required_doc: 必需文档的定义
            evidence: 已上传的证据对象（可能为 None）

        Returns:
            验证结果
        """
        result = {
            "doc_name": required_doc.get("name", ""),
            "doc_type": required_doc.get("type", "policy"),
            "uploaded": evidence is not None,
            "checks": [],
            "passed": True
        }

        if not evidence:
            result["passed"] = False
            result["message"] = f"未上传 {required_doc.get('name', '')}"
            return result

        result["evidence_id"] = evidence.id
        result["file_name"] = evidence.file_name
        result["file_size"] = evidence.file_size

        checks = []

        # 检查 1: 文件大小
        min_size_kb = required_doc.get("min_size_kb", 0)
        if min_size_kb > 0:
            actual_size_kb = (evidence.file_size or 0) / 1024
            size_check = {
                "name": f"文件大小 >= {min_size_kb}KB",
                "passed": actual_size_kb >= min_size_kb,
                "actual": f"{actual_size_kb:.1f}KB"
            }
            checks.append(size_check)
            if not size_check["passed"]:
                result["passed"] = False

        # 检查 2: 必需关键字
        required_keywords = required_doc.get("required_keywords", [])
        if required_keywords and evidence.raw_output:
            content = evidence.raw_output.lower()
            missing_keywords = [k for k in required_keywords if k.lower() not in content]
            keyword_check = {
                "name": f"包含必需关键字",
                "passed": len(missing_keywords) == 0,
                "missing": missing_keywords
            }
            checks.append(keyword_check)
            if not keyword_check["passed"]:
                result["passed"] = False
        elif required_keywords:
            # 有关键字要求但没有 raw_output
            result["passed"] = False
            checks.append({
                "name": "包含必需关键字",
                "passed": False,
                "message": "无法检查关键字（文档未解析）"
            })

        # 检查 3: 文件类型
        allowed_types = required_doc.get("allowed_types", [])
        if allowed_types and evidence.mime_type:
            type_check = {
                "name": f"文件类型在允许列表中",
                "passed": evidence.mime_type in allowed_types,
                "actual": evidence.mime_type
            }
            checks.append(type_check)
            if not type_check["passed"]:
                result["passed"] = False

        result["checks"] = checks

        if result["passed"]:
            result["message"] = f"{required_doc.get('name', '')} 验证通过"
        else:
            failed_checks = [c["name"] for c in checks if not c.get("passed", True)]
            result["message"] = f"验证失败: {', '.join(failed_checks)}"

        return result

    async def upload_document(
        self,
        project_id: int,
        clause_id: str,
        doc_name: str,
        file_name: str,
        file_content: bytes,
        mime_type: Optional[str] = None,
        user_id: int = None,
        description: Optional[str] = None
    ) -> Evidence:
        """
        上传文档证据

        Returns:
            创建的 Evidence 对象
        """
        return await self.evidence_service.upload_evidence(
            project_id=project_id,
            file_name=file_name,
            file_content=file_content,
            mime_type=mime_type,
            evidence_type=EvidenceType.DOCUMENT,
            clause_id=clause_id,
            description=f"{doc_name}|{description or ''}",
            uploaded_by=user_id
        )

    async def generate_report(
        self,
        project_id: int,
        clauses: List[str] = None
    ) -> Dict[str, Any]:
        """
        生成项目的文档检查报告

        Args:
            project_id: 项目ID
            clauses: 要检查的条款列表（None 表示检查所有 document 类型条款）

        Returns:
            报告数据
        """
        if clauses is None:
            clauses = await self._get_all_document_clauses()

        results = []
        for clause_id in clauses:
            result = await self.check_clause(project_id, clause_id, user_id=None)
            results.append(result)

        total = len(results)
        passed = sum(1 for r in results if r.get("status") == "pass")
        partial = sum(1 for r in results if r.get("status") == "partial")
        failed = sum(1 for r in results if r.get("status") == "fail")

        return {
            "project_id": project_id,
            "total_clauses": total,
            "passed": passed,
            "partial": partial,
            "failed": failed,
            "pass_rate": round(passed / total, 2) if total > 0 else 0,
            "results": results,
            "generated_at": datetime.utcnow().isoformat()
        }

    def _find_matching_evidence(
        self,
        required_doc: Dict[str, Any],
        evidences: List[Evidence]
    ) -> Optional[Evidence]:
        """根据文档名称匹配已上传的证据"""
        doc_name = required_doc.get("name", "")
        for evidence in evidences:
            if evidence.description and evidence.description.startswith(doc_name):
                return evidence
            if doc_name in (evidence.file_name or ""):
                return evidence
        return None

    async def _get_clause_definition(self, clause_id: str) -> Optional[Dict[str, Any]]:
        """从条款库加载条款定义"""
        import yaml
        import os
        from pathlib import Path

        compliance_dir = Path("/reference/compliance")
        if not compliance_dir.exists():
            compliance_dir = Path("/Users/shiziao/Documents/CertiProof/reference/compliance")

        for yaml_file in compliance_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                clauses = data.get("clauses", [])
                for clause in clauses:
                    if clause.get("id") == clause_id:
                        if clause.get("check_type") == "document":
                            return clause
            except Exception as e:
                logger.warning(f"Failed to read {yaml_file}: {e}")

        return None

    async def _get_all_document_clauses(self) -> List[str]:
        """获取所有 document 类型条款"""
        import yaml
        from pathlib import Path

        compliance_dir = Path("/reference/compliance")
        if not compliance_dir.exists():
            compliance_dir = Path("/Users/shiziao/Documents/CertiProof/reference/compliance")

        clause_ids = []
        for yaml_file in compliance_dir.glob("*.yaml"):
            try:
                with open(yaml_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                for clause in data.get("clauses", []):
                    if clause.get("check_type") == "document":
                        clause_ids.append(clause.get("id"))
            except Exception:
                continue

        return clause_ids


from datetime import datetime
