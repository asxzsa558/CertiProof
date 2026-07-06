"""
问卷引擎服务
负责问卷的加载、渲染、评估
"""
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.questionnaire import QuestionnaireRecord
from app.orchestrator.skill_loader import SkillLoader

logger = logging.getLogger(__name__)


class QuestionnaireEngine:
    """问卷引擎"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self.skill_loader = SkillLoader()

    @staticmethod
    def _as_float(value: Any) -> Optional[float]:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _as_list(value: Any) -> List[Any]:
        if value is None:
            return []
        if isinstance(value, list):
            return value
        if isinstance(value, tuple):
            return list(value)
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return [value]

    def _evaluate_number_answer(self, question: Dict, answer: Any) -> bool:
        value = self._as_float(answer)
        if value is None:
            return False

        minimum = self._as_float(
            question.get("min", question.get("minimum", question.get("min_value")))
        )
        maximum = self._as_float(
            question.get("max", question.get("maximum", question.get("max_value")))
        )
        expected = self._as_float(question.get("expected", question.get("equals")))

        if expected is not None:
            return value == expected
        if minimum is None and maximum is None:
            return True
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
        return True

    def _evaluate_multi_select_answer(self, question: Dict, answer: Any) -> bool:
        selected = {str(item) for item in self._as_list(answer)}
        required = question.get("required_options") or question.get("required_values")
        if required is None:
            required = question.get("expected")
        if required is None:
            required = [
                option.get("value", option.get("id", option.get("label")))
                for option in question.get("options", [])
                if isinstance(option, dict) and option.get("required")
            ]
        required_set = {str(item) for item in self._as_list(required)}
        if not required_set:
            return bool(selected)
        return required_set.issubset(selected)
    
    async def get_questionnaire_for_clause(
        self,
        clause_id: str,
        level: int = 3
    ) -> Optional[Dict]:
        """
        获取指定条款的问卷定义
        
        Args:
            clause_id: 条款编号，如 "8.1.1.1.2"
            level: 等保等级（2或3）
        
        Returns:
            问卷定义字典，包含 questions 和 evidence_required
        """
        # 加载条款库
        config = self.skill_loader.load_with_extensions("dengbao_base", level)
        
        # 查找条款
        clause = None
        for c in config.get("clauses", []):
            if c["id"] == clause_id:
                clause = c
                break
        
        if not clause:
            logger.warning(f"Clause not found: {clause_id}")
            return None
        
        # 检查是否为问卷类型
        if clause.get("check_type") != "questionnaire":
            logger.warning(f"Clause {clause_id} is not a questionnaire type")
            return None
        
        # 提取问卷信息
        questionnaire_def = clause.get("questionnaire", {})
        questions = questionnaire_def.get("questions", [])
        
        # 构建证据需求
        evidence_required = {}
        for q in questions:
            if q.get("evidence_required"):
                evidence_required[q["id"]] = "file"  # 默认需要文件证据
        evidence_required["_pass_threshold"] = clause.get("pass_threshold", 1.0)
        
        return {
            "clause_id": clause_id,
            "clause_name": clause.get("name", ""),
            "description": clause.get("description", ""),
            "questions": questions,
            "evidence_required": evidence_required,
            "weight": clause.get("weight", 1.0),
            "pass_threshold": clause.get("pass_threshold", 1.0),
        }
    
    async def create_questionnaire_record(
        self,
        project_id: int,
        clause_id: str,
        level: int = 3,
        user_id: Optional[int] = None
    ) -> Optional[QuestionnaireRecord]:
        """
        创建问卷记录
        
        Args:
            project_id: 项目ID
            clause_id: 条款编号
            level: 等保等级
            user_id: 创建用户ID
        
        Returns:
            创建的问卷记录
        """
        # 获取问卷定义
        questionnaire_def = await self.get_questionnaire_for_clause(clause_id, level)
        
        if not questionnaire_def:
            return None
        
        # 创建记录
        record = QuestionnaireRecord(
            project_id=project_id,
            clause_id=clause_id,
            clause_name=questionnaire_def["clause_name"],
            questions=questionnaire_def["questions"],
            evidence_required=questionnaire_def["evidence_required"],
            status="pending",
            created_by=user_id,
        )
        
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        
        logger.info(f"Created questionnaire record: {record.id} for clause {clause_id}")
        
        return record
    
    async def submit_answers(
        self,
        record_id: int,
        answers: List[Dict]
    ) -> Optional[QuestionnaireRecord]:
        """
        提交问卷答案
        
        Args:
            record_id: 问卷记录ID
            answers: 答案列表 [{"question_id": "q1", "answer": "yes", "evidence": [...]}]
        
        Returns:
            更新后的问卷记录
        """
        # 获取记录
        result = await self.db.execute(
            select(QuestionnaireRecord).where(QuestionnaireRecord.id == record_id)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            logger.error(f"Questionnaire record not found: {record_id}")
            return None
        
        # 保存答案
        record.answers = answers
        record.status = "completed"
        record.completed_at = datetime.utcnow()
        
        await self.db.commit()
        await self.db.refresh(record)
        
        logger.info(f"Submitted answers for questionnaire {record_id}")
        
        return record
    
    async def evaluate_answers(
        self,
        record_id: int
    ) -> Optional[Dict]:
        """
        评估问卷答案
        
        Args:
            record_id: 问卷记录ID
        
        Returns:
            评估结果 {"pass": bool, "score": float, "details": {...}}
        """
        # 获取记录
        result = await self.db.execute(
            select(QuestionnaireRecord).where(QuestionnaireRecord.id == record_id)
        )
        record = result.scalar_one_or_none()
        
        if not record:
            logger.error(f"Questionnaire record not found: {record_id}")
            return None
        
        if not record.answers:
            logger.error(f"No answers submitted for questionnaire {record_id}")
            return None
        
        # 计算得分
        questions = record.questions
        answers = record.answers
        
        # 构建答案映射
        answer_map = {a["question_id"]: a for a in answers}
        
        correct_count = 0
        total_count = len(questions)
        details = []
        
        for q in questions:
            q_id = q["id"]
            q_text = q["text"]
            q_type = q.get("type", "yes_no")
            
            answer = answer_map.get(q_id, {})
            user_answer = answer.get("answer")
            evidence = answer.get("evidence", [])
            
            # 判断是否正确
            is_correct = False
            
            if q_type == "yes_no":
                # yes/no 类型，期望回答 "yes"
                is_correct = (user_answer == "yes")
            elif q_type == "number":
                is_correct = self._evaluate_number_answer(q, user_answer)
            elif q_type == "multi_select":
                is_correct = self._evaluate_multi_select_answer(q, user_answer)
            
            if is_correct:
                correct_count += 1
            
            details.append({
                "question_id": q_id,
                "question_text": q_text,
                "user_answer": user_answer,
                "evidence_count": len(evidence),
                "is_correct": is_correct,
            })
        
        # 计算总分
        score = correct_count / total_count if total_count > 0 else 0.0
        
        pass_threshold = self._as_float((record.evidence_required or {}).get("_pass_threshold")) or 1.0
        passed = (score >= pass_threshold)
        
        evaluation = {
            "pass": passed,
            "score": score,
            "correct_count": correct_count,
            "total_count": total_count,
            "details": details,
        }
        
        # 保存评估结果
        record.evaluation = evaluation
        record.status = "evaluated"
        
        await self.db.commit()
        await self.db.refresh(record)
        
        logger.info(f"Evaluated questionnaire {record_id}: score={score:.2f}, passed={passed}")
        
        return evaluation
    
    async def get_questionnaire_record(
        self,
        record_id: int
    ) -> Optional[QuestionnaireRecord]:
        """获取问卷记录"""
        result = await self.db.execute(
            select(QuestionnaireRecord).where(QuestionnaireRecord.id == record_id)
        )
        return result.scalar_one_or_none()
    
    async def list_questionnaire_records(
        self,
        project_id: int
    ) -> List[QuestionnaireRecord]:
        """列出项目的所有问卷记录"""
        result = await self.db.execute(
            select(QuestionnaireRecord)
            .where(QuestionnaireRecord.project_id == project_id)
            .order_by(QuestionnaireRecord.created_at.desc())
        )
        return result.scalars().all()
    
    async def get_project_questionnaire_summary(
        self,
        project_id: int
    ) -> Dict:
        """
        获取项目问卷汇总
        
        Returns:
            {
                "total": 10,
                "pending": 3,
                "completed": 5,
                "evaluated": 2,
                "passed": 1,
                "failed": 1,
                "average_score": 0.85,
            }
        """
        records = await self.list_questionnaire_records(project_id)
        
        summary = {
            "total": len(records),
            "pending": 0,
            "completed": 0,
            "evaluated": 0,
            "passed": 0,
            "failed": 0,
            "average_score": 0.0,
        }
        
        scores = []
        
        for record in records:
            if record.status == "pending":
                summary["pending"] += 1
            elif record.status == "completed":
                summary["completed"] += 1
            elif record.status == "evaluated":
                summary["evaluated"] += 1
                if record.evaluation:
                    if record.evaluation.get("pass"):
                        summary["passed"] += 1
                    else:
                        summary["failed"] += 1
                    scores.append(record.evaluation.get("score", 0.0))
        
        if scores:
            summary["average_score"] = sum(scores) / len(scores)
        
        return summary
