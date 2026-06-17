"""
Mock Scan API - CertiProof
Provides mock scan results for testing without actual nmap/nuclei.
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

router = APIRouter(prefix="/mock", tags=["Mock Scan"])


@router.post("/scan/{project_id}/{asset_id}")
async def mock_scan(
    project_id: int,
    asset_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a mock scan with realistic findings for testing."""
    
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
        status=ScanTaskStatus.COMPLETED,
        triggered_by=TriggeredBy.MANUAL,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
    )
    db.add(scan_task)
    await db.flush()
    
    # Mock findings
    mock_findings = [
        {
            "clause_id": "8.1.3.1",
            "clause_name": "边界访问控制",
            "severity": Severity.HIGH,
            "judgment": Judgment.FAIL,
            "description": "发现公网暴露的高危端口 3306 (MySQL)，存在未授权访问风险。",
            "remediation": "立即关闭 3306 端口的公网访问，使用安全组限制为内网访问。",
            "evidence": {
                "tool": "nmap",
                "target": asset.value,
                "open_ports": [
                    {"port": 22, "service": "ssh", "version": "OpenSSH 8.9", "risk": "high"},
                    {"port": 80, "service": "http", "version": "nginx 1.18", "risk": "info"},
                    {"port": 443, "service": "https", "version": "nginx 1.18", "risk": "info"},
                    {"port": 3306, "service": "mysql", "version": "MySQL 8.0", "risk": "critical"},
                ],
            },
        },
        {
            "clause_id": "8.1.4.1",
            "clause_name": "身份鉴别",
            "severity": Severity.CRITICAL,
            "judgment": Judgment.FAIL,
            "description": "SSH 服务存在弱口令，root 用户密码过于简单，可被暴力破解。",
            "remediation": "立即修改 root 密码，设置强密码策略（≥12位，含大小写+数字+特殊字符），并启用密钥认证。",
            "evidence": {
                "tool": "hydra",
                "target": f"{asset.value}:22",
                "weak_credentials": [
                    {"username": "root", "password": "123456", "method": "brute_force"},
                ],
            },
        },
        {
            "clause_id": "8.1.2.2",
            "clause_name": "通信传输加密",
            "severity": Severity.MEDIUM,
            "judgment": Judgment.PARTIAL,
            "description": "HTTP 服务未启用 HTTPS，存在明文传输风险。",
            "remediation": "配置 SSL 证书，启用 HTTPS，并设置 HTTP 到 HTTPS 的自动重定向。",
            "evidence": {
                "tool": "testssl",
                "target": f"http://{asset.value}",
                "ssl_issues": [
                    {"issue": "HTTP without HTTPS", "severity": "medium"},
                    {"issue": "TLS 1.0 supported", "severity": "high"},
                ],
            },
        },
        {
            "clause_id": "8.1.3.3",
            "clause_name": "入侵防范",
            "severity": Severity.HIGH,
            "judgment": Judgment.FAIL,
            "description": "发现已知漏洞 CVE-2023-12345，nginx 存在远程代码执行漏洞。",
            "remediation": "升级 nginx 到最新版本 1.24.0 以上。",
            "evidence": {
                "tool": "nuclei",
                "target": asset.value,
                "vulnerabilities": [
                    {"cve": "CVE-2023-12345", "severity": "high", "affected": "nginx < 1.24.0"},
                ],
            },
        },
        {
            "clause_id": "8.1.4.3",
            "clause_name": "安全审计",
            "severity": Severity.LOW,
            "judgment": Judgment.PASS,
            "description": "系统审计日志已启用，留存时间超过 180 天。",
            "remediation": None,
            "evidence": {
                "tool": "config_check",
                "target": asset.value,
                "audit_config": {
                    "enabled": True,
                    "retention_days": 365,
                    "log_size": "10GB",
                },
            },
        },
    ]
    
    # Create findings and evidence
    created_findings = []
    for mock in mock_findings:
        finding = Finding(
            project_id=project_id,
            scan_task_id=scan_task.id,
            clause_id=mock["clause_id"],
            clause_name=mock["clause_name"],
            severity=mock["severity"],
            judgment=mock["judgment"],
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
    
    # Update scan task summary
    scan_task.findings_count = len(mock_findings)
    scan_task.high_severity_count = len([f for f in mock_findings if f["severity"] in [Severity.HIGH, Severity.CRITICAL]])
    scan_task.medium_severity_count = len([f for f in mock_findings if f["severity"] == Severity.MEDIUM])
    scan_task.low_severity_count = len([f for f in mock_findings if f["severity"] == Severity.LOW])
    
    # Update project compliance score
    total_score = 0
    for mock in mock_findings:
        if mock["judgment"] == Judgment.PASS:
            total_score += 100
        elif mock["judgment"] == Judgment.PARTIAL:
            total_score += 50
        else:
            total_score += 0
    
    project.compliance_score = int(total_score / len(mock_findings))
    
    # Create remediation tickets for non-passing findings
    tickets_created = 0
    for finding in created_findings:
        severity = finding.severity.value if hasattr(finding.severity, 'value') else str(finding.severity)
        judgment = finding.judgment.value if hasattr(finding.judgment, 'value') else str(finding.judgment)
        
        if judgment != 'pass':
            # Determine priority based on severity
            priority_map = {'critical': 'critical', 'high': 'high', 'medium': 'medium', 'low': 'low'}
            priority = priority_map.get(severity, 'medium')
            
            # Set due date based on priority
            due_days = {'critical': 3, 'high': 7, 'medium': 14, 'low': 30}
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
        "findings_count": len(mock_findings),
        "remediation_tickets_created": tickets_created,
        "compliance_score": project.compliance_score,
        "summary": {
            "critical": len([f for f in mock_findings if f["severity"] == Severity.CRITICAL]),
            "high": len([f for f in mock_findings if f["severity"] == Severity.HIGH]),
            "medium": len([f for f in mock_findings if f["severity"] == Severity.MEDIUM]),
            "low": len([f for f in mock_findings if f["severity"] == Severity.LOW]),
        },
    }
