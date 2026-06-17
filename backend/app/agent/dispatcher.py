"""
Agent Dispatcher - CertiProof
Orchestrates skills and generates compliance results.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask, ScanTaskStatus
from app.models.finding import Finding, Severity, Judgment, JudgmentEngine, FindingStatus
from app.models.evidence import Evidence, EvidenceType
from app.agent.skills.tech_domain import tech_domain_skill

logger = logging.getLogger(__name__)


# Compliance score weights
CLAUSE_WEIGHTS = {
    "8.1.4.1": 3.0,  # 身份鉴别
    "8.1.3.1": 2.5,  # 边界防护
    "8.1.4.3": 2.0,  # 安全审计
    "8.1.3.3": 2.0,  # 入侵防范
    "8.1.7.1": 1.5,  # 安全管理制度
    "8.1.4.9": 1.5,  # 数据备份恢复
}

DEFAULT_WEIGHT = 1.0


class AgentDispatcher:
    """
    Agent dispatcher that orchestrates skills and manages scan tasks.
    """

    def __init__(self):
        self.tech_skill = tech_domain_skill

    async def run_scan(
        self,
        db: AsyncSession,
        scan_task_id: int,
    ) -> ScanTask:
        """
        Execute a scan task.
        
        Args:
            db: Database session
            scan_task_id: ID of the scan task
            
        Returns:
            Updated ScanTask
        """
        # Get scan task
        result = await db.execute(select(ScanTask).where(ScanTask.id == scan_task_id))
        scan_task = result.scalar_one_or_none()
        
        if not scan_task:
            raise ValueError(f"Scan task {scan_task_id} not found")
        
        # Update status to running
        scan_task.status = ScanTaskStatus.RUNNING
        scan_task.started_at = datetime.utcnow()
        await db.commit()
        
        try:
            # Get project for compliance level
            proj_result = await db.execute(select(Project).where(Project.id == scan_task.project_id))
            project = proj_result.scalar_one()
            
            # Get asset
            asset = None
            if scan_task.asset_id:
                asset_result = await db.execute(select(Asset).where(Asset.id == scan_task.asset_id))
                asset = asset_result.scalar_one_or_none()
            
            if not asset:
                raise ValueError("Asset not found for scan task")
            
            # Execute tech domain skill
            skill_result = await self.tech_skill.execute(
                target=asset.value,
                asset_type=asset.asset_type.value,
                compliance_level=project.compliance_level.value,
            )
            
            # Save findings
            findings = await self._save_findings(
                db=db,
                scan_task=scan_task,
                skill_result=skill_result,
            )
            
            # Update scan task summary
            scan_task.findings_count = len(findings)
            scan_task.high_severity_count = len([f for f in findings if f.severity == Severity.HIGH or f.severity == Severity.CRITICAL])
            scan_task.medium_severity_count = len([f for f in findings if f.severity == Severity.MEDIUM])
            scan_task.low_severity_count = len([f for f in findings if f.severity == Severity.LOW or f.severity == Severity.INFO])
            
            # Update project compliance score
            await self._update_compliance_score(db, project)
            
            # Mark task as completed
            scan_task.status = ScanTaskStatus.COMPLETED
            scan_task.completed_at = datetime.utcnow()
            await db.commit()
            
            return scan_task
            
        except Exception as e:
            logger.error(f"Scan task {scan_task_id} failed: {e}")
            scan_task.status = ScanTaskStatus.FAILED
            scan_task.error_message = str(e)[:1000]
            scan_task.completed_at = datetime.utcnow()
            await db.commit()
            raise

    async def _save_findings(
        self,
        db: AsyncSession,
        scan_task: ScanTask,
        skill_result: Dict[str, Any],
    ) -> List[Finding]:
        """Save findings from skill result to database."""
        findings = []
        
        for raw_finding in skill_result.get("findings", []):
            # Map severity
            severity_map = {
                "critical": Severity.CRITICAL,
                "high": Severity.HIGH,
                "medium": Severity.MEDIUM,
                "low": Severity.LOW,
                "info": Severity.INFO,
            }
            severity = severity_map.get(raw_finding.get("severity", "info"), Severity.INFO)
            
            # Map judgment
            judgment_map = {
                "pass": Judgment.PASS,
                "fail": Judgment.FAIL,
                "partial": Judgment.PARTIAL,
                "not_tested": Judgment.NOT_TESTED,
                "paper_compliant": Judgment.PAPER_COMPLIANT,
            }
            judgment = judgment_map.get(raw_finding.get("judgment", "fail"), Judgment.FAIL)
            
            # Create finding
            finding = Finding(
                project_id=scan_task.project_id,
                scan_task_id=scan_task.id,
                clause_id=raw_finding.get("clause_id", "unknown"),
                clause_name=raw_finding.get("clause_name"),
                severity=severity,
                judgment=judgment,
                judgment_engine=JudgmentEngine.RULE,  # For now, all are rule-based
                description=raw_finding.get("description"),
                remediation_suggestion=raw_finding.get("remediation"),
                status=FindingStatus.OPEN,
            )
            db.add(finding)
            await db.flush()  # Get the ID
            
            # Create evidence
            evidence_data = raw_finding.get("evidence", {})
            if evidence_data:
                evidence = Evidence(
                    finding_id=finding.id,
                    evidence_type=EvidenceType.TOOL_OUTPUT,
                    source=evidence_data.get("tool", "unknown"),
                    content=evidence_data,
                )
                db.add(evidence)
                await db.flush()
                
                # Update finding with evidence IDs
                finding.evidence_ids = [evidence.id]
            
            findings.append(finding)
        
        await db.commit()
        return findings

    async def _update_compliance_score(self, db: AsyncSession, project: Project):
        """Update project compliance score based on findings."""
        # Get all findings for this project
        result = await db.execute(
            select(Finding).where(Finding.project_id == project.id)
        )
        findings = result.scalars().all()
        
        if not findings:
            project.compliance_score = None
            await db.commit()
            return
        
        # Group by clause
        clause_scores = {}
        for finding in findings:
            clause_id = finding.clause_id
            if clause_id not in clause_scores:
                clause_scores[clause_id] = []
            clause_scores[clause_id].append(finding)
        
        # Calculate score per clause
        total_weighted_score = 0.0
        total_weight = 0.0
        
        for clause_id, clause_findings in clause_scores.items():
            weight = CLAUSE_WEIGHTS.get(clause_id, DEFAULT_WEIGHT)
            total_weight += weight
            
            # Get the worst judgment for this clause
            judgments = [f.judgment for f in clause_findings]
            
            if Judgment.FAIL in judgments:
                score = 0.0
            elif Judgment.PARTIAL in judgments:
                score = 0.5
            elif Judgment.PAPER_COMPLIANT in judgments:
                score = -0.5
            elif Judgment.PASS in judgments:
                score = 1.0
            else:
                score = 0.0
            
            total_weighted_score += score * weight
        
        # Calculate final score (0-100)
        if total_weight > 0:
            raw_score = total_weighted_score / total_weight
            # Clamp to 0-1 range, then scale to 0-100
            final_score = max(0, min(100, int(raw_score * 100)))
        else:
            final_score = 0
        
        project.compliance_score = final_score
        await db.commit()


# Singleton instance
agent_dispatcher = AgentDispatcher()
