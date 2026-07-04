"""
Report Service - VeriSure
Generates PDF compliance reports.
"""

import io
from datetime import datetime
from typing import List
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm, mm
from reportlab.lib.colors import HexColor, white, black
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, Image
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics.charts.piecharts import Pie
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.project import Project
from app.models.scan_task import ScanTask
from app.models.finding import Finding, Severity
from app.models.evidence import Evidence
from app.models.assessment import Assessment, PhaseInstance, TaskInstance


# Register Chinese font
try:
    pdfmetrics.registerFont(TTFont('NotoSansCJK', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', subfontIndex=0))
    CHINESE_FONT = 'NotoSansCJK'
except:
    try:
        pdfmetrics.registerFont(TTFont('NotoSansCJK', '/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc', subfontIndex=0))
        CHINESE_FONT = 'NotoSansCJK'
    except:
        CHINESE_FONT = 'Helvetica'


# Colors
PRIMARY_COLOR = HexColor('#6366f1')
SUCCESS_COLOR = HexColor('#10b981')
WARNING_COLOR = HexColor('#f59e0b')
DANGER_COLOR = HexColor('#ef4444')
CRITICAL_COLOR = HexColor('#dc2626')
DARK_BG = HexColor('#1e293b')
LIGHT_BG = HexColor('#f8fafc')
GRAY_TEXT = HexColor('#64748b')


def get_severity_color(severity: str) -> HexColor:
    """Get color for severity level."""
    colors = {
        'critical': CRITICAL_COLOR,
        'high': DANGER_COLOR,
        'medium': WARNING_COLOR,
        'low': HexColor('#3b82f6'),
        'info': GRAY_TEXT,
    }
    return colors.get(severity, GRAY_TEXT)


def get_severity_label(severity: str) -> str:
    """Get Chinese label for severity."""
    labels = {
        'critical': '严重',
        'high': '高危',
        'medium': '中危',
        'low': '低危',
        'info': '信息',
    }
    return labels.get(severity, severity)


def get_judgment_label(judgment: str) -> str:
    """Get Chinese label for judgment."""
    labels = {
        'pass': '符合',
        'fail': '不符合',
        'partial': '部分符合',
        'not_tested': '未检测',
        'paper_compliant': '纸上合规',
    }
    return labels.get(judgment, judgment)


async def generate_report(db: AsyncSession, project_id: int) -> io.BytesIO:
    """Generate PDF report for a project."""
    
    # Fetch project data
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")
    
    # Fetch assessment data
    result = await db.execute(
        select(Assessment)
        .where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc())
        .limit(1)
    )
    assessment = result.scalar_one_or_none()
    
    # Fetch phases and tasks if assessment exists
    phases = []
    if assessment:
        result = await db.execute(
            select(PhaseInstance)
            .where(PhaseInstance.assessment_id == assessment.id)
            .order_by(PhaseInstance.order)
        )
        phases = result.scalars().all()
    
    # Fetch latest scan
    result = await db.execute(
        select(ScanTask)
        .where(ScanTask.project_id == project_id)
        .order_by(ScanTask.created_at.desc())
        .limit(1)
    )
    scan_task = result.scalar_one_or_none()
    
    # Fetch findings
    findings = []
    if scan_task:
        result = await db.execute(
            select(Finding)
            .where(Finding.scan_task_id == scan_task.id)
            .order_by(Finding.severity)
        )
        findings = result.scalars().all()
    
    # Create PDF
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2*cm,
        leftMargin=2*cm,
        topMargin=2*cm,
        bottomMargin=2*cm,
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Title'],
        fontName=CHINESE_FONT,
        fontSize=28,
        textColor=PRIMARY_COLOR,
        spaceAfter=30,
        alignment=TA_CENTER,
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading1'],
        fontName=CHINESE_FONT,
        fontSize=18,
        textColor=DARK_BG,
        spaceBefore=20,
        spaceAfter=12,
    )
    
    subheading_style = ParagraphStyle(
        'CustomSubHeading',
        parent=styles['Heading2'],
        fontName=CHINESE_FONT,
        fontSize=14,
        textColor=DARK_BG,
        spaceBefore=15,
        spaceAfter=8,
    )
    
    body_style = ParagraphStyle(
        'CustomBody',
        parent=styles['Normal'],
        fontName=CHINESE_FONT,
        fontSize=10,
        textColor=GRAY_TEXT,
        spaceBefore=6,
        spaceAfter=6,
        leading=16,
    )
    
    # Build content
    elements = []
    
    # Cover page
    elements.append(Spacer(1, 4*cm))
    elements.append(Paragraph('VeriSure', title_style))
    elements.append(Spacer(1, 1*cm))
    elements.append(Paragraph('等保合规检测报告', ParagraphStyle(
        'Subtitle',
        parent=styles['Title'],
        fontName=CHINESE_FONT,
        fontSize=20,
        textColor=GRAY_TEXT,
        alignment=TA_CENTER,
    )))
    elements.append(Spacer(1, 3*cm))
    
    # Project info table
    compliance_level = str(project.compliance_level.value) if hasattr(project.compliance_level, 'value') else str(project.compliance_level)
    scan_time = scan_task.completed_at.strftime('%Y-%m-%d %H:%M') if scan_task and scan_task.completed_at else '未检测'
    
    project_info = [
        ['项目名称', project.name],
        ['等保等级', compliance_level],
        ['检测时间', scan_time],
        ['合规分数', f"{project.compliance_score or 0} 分"],
        ['报告生成时间', datetime.utcnow().strftime('%Y-%m-%d %H:%M')],
    ]
    
    info_table = Table(project_info, colWidths=[4*cm, 10*cm])
    info_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TEXTCOLOR', (0, 0), (0, -1), GRAY_TEXT),
        ('TEXTCOLOR', (1, 0), (1, -1), DARK_BG),
        ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
        ('ALIGN', (1, 0), (1, -1), 'LEFT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 12),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 12),
        ('LINEBELOW', (0, 0), (-1, -2), 0.5, HexColor('#e2e8f0')),
    ]))
    elements.append(info_table)
    
    # Assessment progress section
    if assessment and phases:
        elements.append(Spacer(1, 1.5*cm))
        elements.append(Paragraph('测评流程进度', ParagraphStyle(
            'SectionTitle',
            parent=styles['Heading2'],
            fontName=CHINESE_FONT,
            fontSize=14,
            textColor=DARK_BG,
            alignment=TA_CENTER,
            spaceAfter=12,
        )))
        
        # Assessment status
        status_labels = {
            'not_started': '未开始',
            'in_progress': '进行中',
            'paused': '已暂停',
            'completed': '已完成',
            'failed': '失败',
        }
        assessment_status = status_labels.get(assessment.status, assessment.status)
        
        progress_data = [
            ['测评名称', assessment.name or '等保测评'],
            ['当前状态', assessment_status],
            ['总体进度', f"{assessment.progress:.1f}%"],
            ['完成阶段', f"{assessment.completed_phases} / {assessment.total_phases}"],
        ]
        
        progress_table = Table(progress_data, colWidths=[4*cm, 10*cm])
        progress_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), GRAY_TEXT),
            ('TEXTCOLOR', (1, 0), (1, -1), DARK_BG),
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'LEFT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
            ('ROUNDEDCORNERS', [4, 4, 4, 4]),
        ]))
        elements.append(progress_table)
        
        # Phase details
        elements.append(Spacer(1, 0.8*cm))
        
        phase_status_labels = {
            'pending': '待执行',
            'active': '执行中',
            'completed': '已完成',
            'skipped': '已跳过',
            'failed': '失败',
        }
        
        phase_data = [['阶段', '状态', '任务进度', '完成时间']]
        for phase in phases:
            phase_status = phase_status_labels.get(phase.status, phase.status)
            task_progress = f"{phase.completed_tasks}/{phase.total_tasks}"
            completed_time = phase.completed_at.strftime('%m-%d %H:%M') if phase.completed_at else '-'
            phase_data.append([phase.name, phase_status, task_progress, completed_time])
        
        phase_table = Table(phase_data, colWidths=[4.5*cm, 2.5*cm, 2.5*cm, 3*cm])
        phase_table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('TEXTCOLOR', (0, 0), (-1, 0), white),
            ('TEXTCOLOR', (0, 1), (-1, -1), DARK_BG),
            ('BACKGROUND', (0, 0), (-1, 0), PRIMARY_COLOR),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e2e8f0')),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [white, LIGHT_BG]),
        ]))
        elements.append(phase_table)
    
    elements.append(PageBreak())
    
    # Executive Summary
    elements.append(Paragraph('执行摘要', heading_style))
    elements.append(Spacer(1, 0.5*cm))
    
    # Summary stats
    critical_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    
    for f in findings:
        severity = f.severity.value if hasattr(f.severity, 'value') else str(f.severity)
        if severity == 'critical':
            critical_count += 1
        elif severity == 'high':
            high_count += 1
        elif severity == 'medium':
            medium_count += 1
        elif severity == 'low':
            low_count += 1
    
    summary_text = f"""
    本次检测共发现 <b>{len(findings)}</b> 个安全问题，其中：
    <br/>• 严重问题：<b>{critical_count}</b> 个
    <br/>• 高危问题：<b>{high_count}</b> 个
    <br/>• 中危问题：<b>{medium_count}</b> 个
    <br/>• 低危问题：<b>{low_count}</b> 个
    <br/><br/>
    综合合规分数为 <b>{project.compliance_score or 0}</b> 分，
    建议优先处理严重和高危问题，尽快完成整改。
    """
    elements.append(Paragraph(summary_text, body_style))
    elements.append(Spacer(1, 1*cm))
    
    # Score gauge
    score = project.compliance_score or 0
    if score >= 90:
        score_status = '优秀'
        score_color = SUCCESS_COLOR
    elif score >= 75:
        score_status = '良好'
        score_color = PRIMARY_COLOR
    elif score >= 60:
        score_status = '一般'
        score_color = WARNING_COLOR
    else:
        score_status = '危险'
        score_color = DANGER_COLOR
    
    score_text = f"""
    <font size="14" color="{score_color.hexval()}"><b>{score_status}</b></font>
    <br/>
    合规分数：<b>{score}</b> / 100
    """
    elements.append(Paragraph(score_text, ParagraphStyle(
        'ScoreStyle',
        parent=body_style,
        alignment=TA_CENTER,
        fontSize=12,
    )))
    
    elements.append(PageBreak())
    
    # Findings Detail
    elements.append(Paragraph('问题详情', heading_style))
    elements.append(Spacer(1, 0.5*cm))
    
    if not findings:
        elements.append(Paragraph('暂无检测数据', body_style))
    else:
        for i, finding in enumerate(findings, 1):
            severity = finding.severity.value if hasattr(finding.severity, 'value') else str(finding.severity)
            judgment = finding.judgment.value if hasattr(finding.judgment, 'value') else str(finding.judgment)
            
            # Finding header
            elements.append(Paragraph(
                f'{i}. [{get_severity_label(severity)}] {finding.clause_id} {finding.clause_name or ""}',
                subheading_style
            ))
            
            # Finding details table
            finding_data = [
                ['条款编号', finding.clause_id],
                ['严重等级', get_severity_label(severity)],
                ['判定结果', get_judgment_label(judgment)],
                ['问题描述', finding.description or '无'],
                ['整改建议', finding.remediation_suggestion or '无'],
            ]
            
            finding_table = Table(finding_data, colWidths=[3*cm, 11*cm])
            finding_table.setStyle(TableStyle([
                ('FONTNAME', (0, 0), (-1, -1), CHINESE_FONT),
                ('FONTSIZE', (0, 0), (-1, -1), 9),
                ('TEXTCOLOR', (0, 0), (0, -1), GRAY_TEXT),
                ('TEXTCOLOR', (1, 0), (1, -1), DARK_BG),
                ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 8),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
                ('BACKGROUND', (0, 0), (-1, -1), LIGHT_BG),
            ]))
            elements.append(finding_table)
            elements.append(Spacer(1, 0.8*cm))
    
    elements.append(PageBreak())
    
    # Recommendations
    elements.append(Paragraph('整改建议', heading_style))
    elements.append(Spacer(1, 0.5*cm))
    
    recommendations = """
    <b>1. 立即整改（严重/高危问题）</b>
    <br/>• 关闭不必要的公网端口，特别是数据库端口（3306, 5432, 6379 等）
    <br/>• 修改所有弱口令，启用强密码策略（≥12位，含大小写+数字+特殊字符）
    <br/>• 修复已知高危漏洞，升级相关组件到最新版本
    <br/><br/>
    <b>2. 短期整改（中危问题）</b>
    <br/>• 启用 HTTPS，配置有效的 SSL 证书
    <br/>• 禁用不安全的协议版本（TLS 1.0/1.1）
    <br/>• 配置访问控制策略，限制管理后台访问 IP
    <br/><br/>
    <b>3. 长期改进</b>
    <br/>• 建立定期安全扫描机制，建议每月至少一次
    <br/>• 完善安全管理制度，确保人员职责明确
    <br/>• 加强安全培训，提高全员安全意识
    <br/>• 考虑部署 WAF、IDS 等安全防护设备
    """
    elements.append(Paragraph(recommendations, body_style))
    
    # Footer
    elements.append(Spacer(1, 2*cm))
    elements.append(Paragraph(
        '本报告由 VeriSure 智能合规验证平台自动生成',
        ParagraphStyle(
            'Footer',
            parent=body_style,
            fontSize=8,
            textColor=GRAY_TEXT,
            alignment=TA_CENTER,
        )
    ))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    return buffer


async def generate_json_report(db: AsyncSession, project_id: int) -> dict:
    """Generate JSON report for a project."""
    
    # Fetch project data
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise ValueError("Project not found")
    
    # Fetch assessment data
    result = await db.execute(
        select(Assessment)
        .where(Assessment.project_id == project_id)
        .order_by(Assessment.created_at.desc())
        .limit(1)
    )
    assessment = result.scalar_one_or_none()
    
    # Fetch phases and tasks if assessment exists
    phases_data = []
    if assessment:
        result = await db.execute(
            select(PhaseInstance)
            .where(PhaseInstance.assessment_id == assessment.id)
            .order_by(PhaseInstance.order)
        )
        phases = result.scalars().all()
        
        for phase in phases:
            # Fetch tasks for this phase
            result = await db.execute(
                select(TaskInstance)
                .where(TaskInstance.phase_id == phase.id)
            )
            tasks = result.scalars().all()
            
            tasks_data = []
            for task in tasks:
                tasks_data.append({
                    'id': task.id,
                    'task_type': task.task_type,
                    'name': task.name,
                    'status': task.status,
                    'result': task.result,
                    'started_at': task.started_at.isoformat() if task.started_at else None,
                    'completed_at': task.completed_at.isoformat() if task.completed_at else None,
                })
            
            phases_data.append({
                'id': phase.id,
                'phase_id': phase.phase_id,
                'name': phase.name,
                'order': phase.order,
                'status': phase.status,
                'total_tasks': phase.total_tasks,
                'completed_tasks': phase.completed_tasks,
                'progress': phase.progress,
                'started_at': phase.started_at.isoformat() if phase.started_at else None,
                'completed_at': phase.completed_at.isoformat() if phase.completed_at else None,
                'tasks': tasks_data,
            })
    
    # Fetch all scan tasks
    result = await db.execute(
        select(ScanTask)
        .where(ScanTask.project_id == project_id)
        .order_by(ScanTask.created_at.desc())
    )
    scan_tasks = result.scalars().all()
    
    # Fetch all findings
    result = await db.execute(
        select(Finding)
        .where(Finding.project_id == project_id)
        .order_by(Finding.severity)
    )
    findings = result.scalars().all()
    
    # Fetch all evidences
    finding_ids = [f.id for f in findings]
    evidences = []
    if finding_ids:
        result = await db.execute(
            select(Evidence)
            .where(Evidence.finding_id.in_(finding_ids))
        )
        evidences = result.scalars().all()
    
    # Build report
    compliance_level = str(project.compliance_level.value) if hasattr(project.compliance_level, 'value') else str(project.compliance_level)
    
    severity_counts = {'critical': 0, 'high': 0, 'medium': 0, 'low': 0, 'info': 0}
    judgment_counts = {'pass': 0, 'fail': 0, 'partial': 0, 'not_tested': 0}
    
    findings_data = []
    for f in findings:
        severity = f.severity.value if hasattr(f.severity, 'value') else str(f.severity)
        judgment = f.judgment.value if hasattr(f.judgment, 'value') else str(f.judgment)
        
        severity_counts[severity] = severity_counts.get(severity, 0) + 1
        judgment_counts[judgment] = judgment_counts.get(judgment, 0) + 1
        
        # Find related evidences
        finding_evidences = [e for e in evidences if e.finding_id == f.id]
        
        findings_data.append({
            'id': f.id,
            'clause_id': f.clause_id,
            'clause_name': f.clause_name,
            'severity': severity,
            'judgment': judgment,
            'judgment_engine': f.judgment_engine.value if hasattr(f.judgment_engine, 'value') else str(f.judgment_engine),
            'description': f.description,
            'remediation_suggestion': f.remediation_suggestion,
            'status': f.status.value if hasattr(f.status, 'value') else str(f.status),
            'evidence_count': len(finding_evidences),
            'created_at': f.created_at.isoformat() if f.created_at else None,
        })
    
    scan_tasks_data = []
    for st in scan_tasks:
        scan_tasks_data.append({
            'id': st.id,
            'task_type': st.task_type.value if hasattr(st.task_type, 'value') else str(st.task_type),
            'status': st.status.value if hasattr(st.status, 'value') else str(st.status),
            'parameters': st.parameters,
            'findings_count': st.findings_count,
            'created_at': st.created_at.isoformat() if st.created_at else None,
            'completed_at': st.completed_at.isoformat() if st.completed_at else None,
        })
    
    score = project.compliance_score or 0
    if score >= 90:
        score_status = '优秀'
    elif score >= 75:
        score_status = '良好'
    elif score >= 60:
        score_status = '一般'
    else:
        score_status = '危险'
    
    report = {
        'report_version': '1.0',
        'generated_at': datetime.utcnow().isoformat(),
        'project': {
            'id': project.id,
            'name': project.name,
            'description': project.description,
            'compliance_level': compliance_level,
            'compliance_score': score,
            'score_status': score_status,
            'status': project.status.value if hasattr(project.status, 'value') else str(project.status),
            'created_at': project.created_at.isoformat() if project.created_at else None,
        },
        'assessment': {
            'id': assessment.id if assessment else None,
            'name': assessment.name if assessment else None,
            'status': assessment.status if assessment else None,
            'progress': assessment.progress if assessment else 0,
            'total_phases': assessment.total_phases if assessment else 0,
            'completed_phases': assessment.completed_phases if assessment else 0,
            'started_at': assessment.started_at.isoformat() if assessment and assessment.started_at else None,
            'completed_at': assessment.completed_at.isoformat() if assessment and assessment.completed_at else None,
            'phases': phases_data,
        },
        'summary': {
            'total_findings': len(findings),
            'severity_counts': severity_counts,
            'judgment_counts': judgment_counts,
            'total_scan_tasks': len(scan_tasks),
        },
        'scan_tasks': scan_tasks_data,
        'findings': findings_data,
        'recommendations': {
            'immediate': [
                '关闭不必要的公网端口，特别是数据库端口（3306, 5432, 6379 等）',
                '修改所有弱口令，启用强密码策略（≥12位，含大小写+数字+特殊字符）',
                '修复已知高危漏洞，升级相关组件到最新版本',
            ],
            'short_term': [
                '启用 HTTPS，配置有效的 SSL 证书',
                '禁用不安全的协议版本（TLS 1.0/1.1）',
                '配置访问控制策略，限制管理后台访问 IP',
            ],
            'long_term': [
                '建立定期安全扫描机制，建议每月至少一次',
                '完善安全管理制度，确保人员职责明确',
                '加强安全培训，提高全员安全意识',
            ],
        },
    }
    
    return report
