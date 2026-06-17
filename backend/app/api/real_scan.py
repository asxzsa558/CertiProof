"""
Real Scan API - CertiProof
Real port scanning using Python native socket.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from datetime import datetime, timedelta
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project
from app.models.asset import Asset
from app.models.scan_task import ScanTask, ScanTaskType, ScanTaskStatus, TriggeredBy
from app.models.finding import Finding, Severity, Judgment, JudgmentEngine, FindingStatus
from app.models.evidence import Evidence, EvidenceType
from app.models.remediation import RemediationTicket, RemediationStatus
from app.services.real_scan_service import scan_host, check_ssl, generate_compliance_findings

router = APIRouter(prefix="/real", tags=["Real Scan"])


@router.post("/scan/{project_id}/{asset_id}")
async def real_scan(
    project_id: int,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Execute real port scan on target asset."""
    
    # Verify project and asset
    result = await db.execute(
        select(Project).where(Project.id == project_id, Project.user_id == current_user.id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id, Asset.project_id == project_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Create scan task
    scan_task = ScanTask(
        project_id=project_id,
        asset_id=asset_id,
        task_type=ScanTaskType.FULL,
        status=ScanTaskStatus.RUNNING,
        triggered_by=TriggeredBy.MANUAL,
        started_at=datetime.utcnow(),
    )
    db.add(scan_task)
    await db.flush()
    
    try:
        # Execute real scan
        scan_result = scan_host(asset.value)
        
        # Check SSL if HTTPS is open
        ssl_result = None
        if any(p["port"] == 443 for p in scan_result["open_ports"]):
            ssl_result = check_ssl(asset.value, 443)
        
        # Generate compliance findings
        mock_findings = generate_compliance_findings(scan_result, asset.value)
        
        # Create findings and evidence
        created_findings = []
        for mock in mock_findings:
            severity_map = {
                "critical": Severity.CRITICAL,
                "high": Severity.HIGH,
                "medium": Severity.MEDIUM,
                "low": Severity.LOW,
                "info": Severity.INFO,
            }
            judgment_map = {
                "pass": Judgment.PASS,
                "fail": Judgment.FAIL,
                "partial": Judgment.PARTIAL,
            }
            
            finding = Finding(
                project_id=project_id,
                scan_task_id=scan_task.id,
                clause_id=mock["clause_id"],
                clause_name=mock["clause_name"],
                severity=severity_map.get(mock["severity"], Severity.INFO),
                judgment=judgment_map.get(mock["judgment"], Judgment.FAIL),
                judgment_engine=JudgmentEngine.RULE,
                description=mock["description"],
                remediation_suggestion=mock["remediation"],
                status=FindingStatus.OPEN,
            )
            db.add(finding)
            await db.flush()
            created_findings.append(finding)
            
            # Create evidence
            evidence = Evidence(
                finding_id=finding.id,
                evidence_type=EvidenceType.TOOL_OUTPUT,
                source=mock["evidence"]["tool"],
                content=mock["evidence"],
            )
            db.add(evidence)
        
        # Add SSL evidence if checked
        if ssl_result:
            ssl_finding = Finding(
                project_id=project_id,
                scan_task_id=scan_task.id,
                clause_id="8.1.2.2",
                clause_name="通信传输加密",
                severity=Severity.MEDIUM if ssl_result["issues"] else Severity.INFO,
                judgment=Judgment.FAIL if ssl_result["issues"] else Judgment.PASS,
                judgment_engine=JudgmentEngine.RULE,
                description=f"SSL/TLS 检查: {'发现问题' if ssl_result['issues'] else '配置正常'}",
                remediation_suggestion="; ".join(ssl_result["issues"]) if ssl_result["issues"] else None,
                status=FindingStatus.OPEN,
            )
            db.add(ssl_finding)
            await db.flush()
            created_findings.append(ssl_finding)
            
            evidence = Evidence(
                finding_id=ssl_finding.id,
                evidence_type=EvidenceType.TOOL_OUTPUT,
                source="ssl_check",
                content=ssl_result,
            )
            db.add(evidence)
        
        # Update scan task summary
        scan_task.status = ScanTaskStatus.COMPLETED
        scan_task.completed_at = datetime.utcnow()
        scan_task.findings_count = len(created_findings)
        scan_task.high_severity_count = len([f for f in created_findings if f.severity in [Severity.HIGH, Severity.CRITICAL]])
        scan_task.medium_severity_count = len([f for f in created_findings if f.severity == Severity.MEDIUM])
        scan_task.low_severity_count = len([f for f in created_findings if f.severity in [Severity.LOW, Severity.INFO]])
        
        # Update project compliance score
        total_score = 0
        for finding in created_findings:
            if finding.judgment == Judgment.PASS:
                total_score += 100
            elif finding.judgment == Judgment.PARTIAL:
                total_score += 50
            else:
                total_score += 0
        
        project.compliance_score = int(total_score / len(created_findings)) if created_findings else 0
        
        # Create remediation tickets for non-passing findings
        tickets_created = 0
        for finding in created_findings:
            severity = finding.severity.value if hasattr(finding.severity, 'value') else str(finding.severity)
            judgment = finding.judgment.value if hasattr(finding.judgment, 'value') else str(finding.judgment)
            
            if judgment != 'pass':
                priority_map = {'critical': 'critical', 'high': 'high', 'medium': 'medium', 'low': 'low', 'info': 'low'}
                priority = priority_map.get(severity, 'medium')
                
                due_days = {'critical': 3, 'high': 7, 'medium': 14, 'low': 30, 'info': 60}
                due_date = datetime.utcnow() + timedelta(days=due_days.get(priority, 14))
                
                ticket = RemediationTicket(
                    finding_id=finding.id,
                    project_id=project_id,
                    title=f"[{severity.upper()}] {finding.clause_name or finding.clause_id}",
                    description=finding.description,
                    remediation_plan=finding.remediation_suggestion,
                    priority=priority,
                    status=RemediationStatus.OPEN,
                    due_date=due_date,
                    assigned_by=current_user.id,
                )
                db.add(ticket)
                tickets_created += 1
        
        await db.commit()
        
        return {
            "scan_task_id": scan_task.id,
            "status": "completed",
            "target": asset.value,
            "scan_result": scan_result,
            "findings_count": len(created_findings),
            "remediation_tickets_created": tickets_created,
            "compliance_score": project.compliance_score,
            "summary": scan_result["summary"],
        }
        
    except Exception as e:
        scan_task.status = ScanTaskStatus.FAILED
        scan_task.completed_at = datetime.utcnow()
        scan_task.error_message = str(e)
        await db.commit()
        raise HTTPException(status_code=500, detail=f"Scan failed: {str(e)}")
