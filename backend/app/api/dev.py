"""
开发环境数据种子端点
用于快速生成测试数据验证等保测评流程
"""

import logging
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import User
from app.models.project import Project, ComplianceLevel, ProjectStatus
from app.models.asset import Asset, AssetType, VerificationStatus
from app.models.assessment import Assessment, PhaseInstance, TaskInstance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/dev", tags=["dev"])


@router.post("/seed")
async def seed_test_data(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    一键生成完整的等保三级测评测试数据

    创建：
    - 一个三级等保项目
    - 4 个资产（2 个 Linux IP + 1 个域名 + 1 个数据库 IP）
    - 完整的 7 阶段测评流程
    - 每个阶段的任务都有模拟结果
    - 所有阶段标记为已完成
    """
    from app.services.flow_engine import get_flow_engine
    from app.services.assessment_templates import LEVEL_3_TEMPLATE

    # 创建项目
    project = Project(
        user_id=current_user.id,
        name="测试系统 - 等保三级测评",
        system_name="企业信息管理系统 V2.0",
        description="用于验证等保测评流程的测试项目",
        compliance_level=ComplianceLevel.LEVEL_3,
        status=ProjectStatus.ACTIVE,
        compliance_score=78,
    )
    db.add(project)
    await db.flush()

    # 创建资产
    assets_data = [
        {"asset_type": AssetType.IP, "value": "192.168.1.10", "name": "Web应用服务器"},
        {"asset_type": AssetType.IP, "value": "192.168.1.20", "name": "数据库服务器"},
        {"asset_type": AssetType.DOMAIN, "value": "test.example.com", "name": "企业官网"},
        {"asset_type": AssetType.IP, "value": "192.168.1.30", "name": "文件服务器"},
    ]
    assets = []
    for ad in assets_data:
        asset = Asset(
            project_id=project.id,
            asset_type=ad["asset_type"],
            value=ad["value"],
            name=ad["name"],
            verification_status=VerificationStatus.VERIFIED,
            is_active=True,
        )
        db.add(asset)
        assets.append(asset)
    await db.flush()

    # 创建测评
    assessment = Assessment(
        project_id=project.id,
        template_id=1,  # 使用默认模板
        name=LEVEL_3_TEMPLATE["name"],
        target_system=project.system_name or project.name,
        assessment_level=3,
        status="completed",
        progress=100.0,
        total_phases=len(LEVEL_3_TEMPLATE["phases_config"]),
        completed_phases=len(LEVEL_3_TEMPLATE["phases_config"]),
        started_at=datetime.utcnow() - timedelta(days=30),
        completed_at=datetime.utcnow(),
        owner_id=current_user.id,
    )
    db.add(assessment)
    await db.flush()

    # 模拟结果数据
    mock_results = {
        "doc_review": {
            "status": "completed",
            "file_name": "模拟文档.pdf",
            "validation": {"match": True, "message": "文档审查通过"},
        },
        "asset_discovery": {
            "status": "completed",
            "target": "192.168.1.0/24",
            "asset_results": {
                "192.168.1.10": {"status": "completed", "open_ports": [22, 80, 443]},
                "192.168.1.20": {"status": "completed", "open_ports": [3306, 6379]},
                "192.168.1.30": {"status": "completed", "open_ports": [22, 445]},
            },
        },
        "config_check": {
            "status": "completed",
            "target": "192.168.1.10",
            "results": [
                {"capability": "linux_baseline", "status": "completed", "target": "192.168.1.10",
                 "result": {"checks": {"password_policy": {"compliant": True}, "ssh_config": {"compliant": False, "issues": ["PermitRootLogin yes"]}}}},
            ],
            "failed": [],
        },
        "vuln_scan": {
            "status": "completed",
            "target": "192.168.1.10",
            "results": [
                {"capability": "scan_vulnerabilities", "status": "completed", "target": "192.168.1.10",
                 "result": {"findings": [
                     {"id": "CVE-2024-1234", "severity": "high", "name": "OpenSSL 缓冲区溢出"},
                     {"id": "CVE-2024-5678", "severity": "medium", "name": "Nginx 信息泄露"},
                 ]}},
            ],
            "failed": [],
        },
        "password_scan": {
            "status": "completed",
            "target": "192.168.1.10",
            "results": [
                {"capability": "scan_weak_passwords", "status": "completed", "target": "192.168.1.10",
                 "result": {"found": [], "tested_users": 15, "tested_passwords": 100}},
            ],
            "failed": [],
        },
        "ssl_check": {
            "status": "completed",
            "target": "test.example.com",
            "results": [
                {"capability": "scan_ssl", "status": "completed", "target": "test.example.com",
                 "result": {"grade": "B", "issues": ["TLS 1.0 enabled", "Weak cipher suite"]}},
            ],
            "failed": [],
        },
        "db_check": {
            "status": "completed",
            "target": "192.168.1.20",
            "results": [
                {"capability": "redis_check", "status": "completed", "target": "192.168.1.20",
                 "result": {"unauthorized": False}},
                {"capability": "mysql_check", "status": "completed", "target": "192.168.1.20",
                 "result": {"empty_password": False}},
            ],
            "failed": [],
        },
        "network_check": {
            "status": "completed",
            "target": "192.168.1.1",
            "results": [
                {"capability": "snmp_walk", "status": "completed", "target": "192.168.1.1",
                 "result": {"community_strings": ["public"], "vulnerable": True}},
            ],
            "failed": [],
        },
        "pentest": {
            "status": "completed",
            "target": "test.example.com",
            "results": [
                {"capability": "scan_vulnerabilities", "status": "completed", "target": "test.example.com",
                 "result": {"findings": [
                     {"id": "PT-001", "severity": "high", "name": "SQL注入漏洞"},
                 ]}},
            ],
            "failed": [],
        },
        "interview": {
            "status": "completed",
            "interviewee": "系统管理员",
            "summary": "访谈完成，了解了系统安全管理情况",
        },
    }

    # 创建阶段和任务
    now = datetime.utcnow()
    for i, phase_config in enumerate(LEVEL_3_TEMPLATE["phases_config"]):
        phase = PhaseInstance(
            assessment_id=assessment.id,
            phase_id=phase_config["id"],
            name=phase_config["name"],
            description=phase_config.get("description", ""),
            order=phase_config["order"],
            status="completed",
            total_tasks=len(phase_config["default_tasks"]),
            completed_tasks=len(phase_config["default_tasks"]),
            progress=100.0,
            started_at=now - timedelta(days=30 - i * 4),
            completed_at=now - timedelta(days=26 - i * 4),
            depends_on=phase_config.get("depends_on", []),
        )
        db.add(phase)
        await db.flush()

        for task_config in phase_config["default_tasks"]:
            task_type = task_config["type"]
            mock_result = mock_results.get(task_type, {"status": "completed"})

            task = TaskInstance(
                phase_id=phase.id,
                task_type=task_type,
                name=task_config["name"],
                description=task_config.get("description", ""),
                status="completed",
                priority=1,  # 使用整数优先级
                result=mock_result,
                started_at=now - timedelta(days=30 - i * 4),
                completed_at=now - timedelta(days=28 - i * 4),
            )
            db.add(task)

    await db.commit()

    return {
        "status": "success",
        "project_id": project.id,
        "project_name": project.name,
        "assessment_id": assessment.id,
        "assets_count": len(assets),
        "phases_count": len(LEVEL_3_TEMPLATE["phases_config"]),
        "message": "测试数据已生成，所有阶段已完成",
    }
