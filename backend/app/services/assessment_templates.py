"""
等保测评流程模板定义

参考 GB/T 22239-2019 等保基本要求
"""

# 等保二级测评流程模板
LEVEL_2_TEMPLATE = {
    "name": "等保二级测评流程",
    "compliance_level": 2,
    "phases_config": [
        {
            "id": "phase_1",
            "name": "系统定级",
            "order": 1,
            "required": True,
            "description": "确定信息系统安全保护等级",
            "depends_on": [],
            "default_tasks": [
                {"type": "doc_review", "name": "审查定级报告"},
            ]
        },
        {
            "id": "phase_2",
            "name": "备案",
            "order": 2,
            "required": True,
            "depends_on": ["phase_1"],
            "description": "向公安机关备案",
            "default_tasks": [
                {"type": "doc_review", "name": "审查备案证明"},
            ]
        },
        {
            "id": "phase_3",
            "name": "差距分析",
            "order": 3,
            "required": True,
            "depends_on": ["phase_2"],
            "description": "现状调研与差距分析",
            "default_tasks": [
                {"type": "asset_discovery", "name": "资产发现"},
                {"type": "doc_review", "name": "安全管理制度审查"},
            ]
        },
        {
            "id": "phase_4",
            "name": "现场测评",
            "order": 4,
            "required": True,
            "depends_on": ["phase_3"],
            "description": "现场技术测评",
            "default_tasks": [
                {"type": "config_check", "name": "安全配置核查", "description": "检查身份鉴别、访问控制、安全审计等（SSH 白盒核查）"},
                {"type": "vuln_scan", "name": "漏洞扫描", "description": "扫描系统漏洞、Web 漏洞等"},
                {"type": "password_scan", "name": "弱口令检测", "description": "检测 SSH/数据库等弱口令"},
                {"type": "ssl_check", "name": "SSL/TLS 检测", "description": "检测 SSL/TLS 配置安全性"},
                {"type": "db_check", "name": "数据库安全检测", "description": "检测 Redis/MySQL/MongoDB 等未授权访问"},
            ]
        },
        {
            "id": "phase_5",
            "name": "整改加固",
            "order": 5,
            "required": True,
            "depends_on": ["phase_4"],
            "description": "问题整改与安全加固",
            "default_tasks": [
                {"type": "config_check", "name": "整改验证"},
            ]
        },
        {
            "id": "phase_6",
            "name": "测评报告",
            "order": 6,
            "required": True,
            "depends_on": ["phase_5"],
            "description": "生成测评报告",
            "default_tasks": [
                {"type": "doc_review", "name": "报告编制"},
            ]
        },
    ]
}

# 等保三级测评流程模板
LEVEL_3_TEMPLATE = {
    "name": "等保三级测评流程",
    "compliance_level": 3,
    "phases_config": [
        {
            "id": "phase_1",
            "name": "系统定级",
            "order": 1,
            "required": True,
            "description": "确定信息系统安全保护等级，编制定级报告，组织专家评审",
            "depends_on": [],
            "default_tasks": [
                {"type": "doc_review", "name": "审查定级报告", "description": "审查系统定级报告的完整性和准确性"},
                {"type": "doc_review", "name": "审查专家评审意见", "description": "审查专家评审会议纪要和意见"},
                {"type": "interview", "name": "访谈系统负责人", "description": "访谈系统负责人了解系统定级过程"},
            ]
        },
        {
            "id": "phase_2",
            "name": "备案",
            "order": 2,
            "required": True,
            "depends_on": ["phase_1"],
            "description": "向公安机关提交备案材料，获取备案证明",
            "default_tasks": [
                {"type": "doc_review", "name": "审查备案证明", "description": "审查公安机关出具的备案证明"},
                {"type": "doc_review", "name": "审查备案材料", "description": "审查备案表格、定级报告等材料"},
            ]
        },
        {
            "id": "phase_3",
            "name": "差距分析",
            "order": 3,
            "required": True,
            "depends_on": ["phase_2"],
            "description": "通过问卷调查、文档审查和初步扫描，了解系统现状与等保目标级别之间的差距",
            "default_tasks": [
                {"type": "asset_discovery", "name": "资产发现", "description": "发现并记录所有信息资产"},
                {"type": "doc_review", "name": "安全管理制度审查", "description": "审查安全管理制度文档的完整性"},
                {"type": "doc_review", "name": "安全组织机构审查", "description": "审查安全管理机构和人员配置"},
                {"type": "interview", "name": "人员访谈", "description": "访谈安全负责人、系统管理员、审计管理员"},
                {"type": "doc_review", "name": "安全建设管理审查", "description": "审查安全方案设计、产品采购、工程实施等文档"},
                {"type": "doc_review", "name": "安全运维管理审查", "description": "审查环境管理、资产管理、介质管理等制度"},
            ]
        },
        {
            "id": "phase_4",
            "name": "现场测评",
            "order": 4,
            "required": True,
            "depends_on": ["phase_3"],
            "description": "现场技术测评，包括安全物理环境、安全通信网络、安全区域边界、安全计算环境、安全管理中心",
            "default_tasks": [
                {"type": "config_check", "name": "安全计算环境检查", "description": "检查身份鉴别、访问控制、安全审计等（SSH白盒核查）"},
                {"type": "vuln_scan", "name": "漏洞扫描", "description": "扫描系统漏洞、Web漏洞等"},
                {"type": "password_scan", "name": "弱口令检测", "description": "检测SSH/数据库等弱口令"},
                {"type": "ssl_check", "name": "SSL/TLS检测", "description": "检测SSL/TLS配置安全性"},
                {"type": "db_check", "name": "数据库安全检测", "description": "检测Redis/MySQL/MongoDB等未授权访问"},
                {"type": "network_check", "name": "网络设备检测", "description": "SNMP团体字检测、网络设备配置读取"},
                {"type": "doc_review", "name": "渗透测试报告审查", "description": "审查渗透测试方案、报告、漏洞修复记录（等保8.1.4.27）"},
            ]
        },
        {
            "id": "phase_5",
            "name": "整改加固",
            "order": 5,
            "required": True,
            "depends_on": ["phase_4"],
            "description": "根据测评结果进行问题整改与安全加固",
            "default_tasks": [
                {"type": "doc_review", "name": "整改方案审查", "description": "审查整改方案的完整性和可行性"},
                {"type": "config_check", "name": "整改验证", "description": "验证整改措施是否落实到位"},
                {"type": "doc_review", "name": "整改报告审查", "description": "审查整改报告和相关证据"},
            ]
        },
        {
            "id": "phase_6",
            "name": "复测验证",
            "order": 6,
            "required": True,
            "depends_on": ["phase_5"],
            "description": "对整改项进行复测验证，确认所有不符合项已整改",
            "default_tasks": [
                {"type": "config_check", "name": "复测验证", "description": "对所有不符合项进行复测"},
                {"type": "doc_review", "name": "复测报告审查", "description": "审查复测报告和证据"},
            ]
        },
        {
            "id": "phase_7",
            "name": "测评报告",
            "order": 7,
            "required": True,
            "depends_on": ["phase_6"],
            "description": "编制等保测评报告，包括测评结论、不符合项清单、整改建议等",
            "default_tasks": [
                {"type": "doc_review", "name": "报告编制", "description": "编制等保测评报告"},
                {"type": "doc_review", "name": "报告审核", "description": "内部审核测评报告"},
                {"type": "doc_review", "name": "报告交付", "description": "向客户交付测评报告"},
            ]
        },
    ]
}

# 任务类型定义
TASK_TYPES = {
    "asset_discovery": {
        "name": "资产发现",
        "description": "发现并记录信息资产",
        "icon": "radar",
    },
    "config_check": {
        "name": "配置核查",
        "description": "检查安全配置是否符合要求（SSH白盒核查）",
        "icon": "setting",
    },
    "vuln_scan": {
        "name": "漏洞扫描",
        "description": "扫描系统漏洞、Web漏洞",
        "icon": "bug",
    },
    "web_scan": {
        "name": "Web安全扫描",
        "description": "Web漏洞/SQL注入/目录爆破",
        "icon": "global",
    },
    "pentest": {
        "name": "渗透测试",
        "description": "进行渗透测试验证安全防线",
        "icon": "thunderbolt",
    },
    "ssl_check": {
        "name": "SSL/TLS检测",
        "description": "检测SSL/TLS配置安全性",
        "icon": "lock",
    },
    "password_scan": {
        "name": "弱口令检测",
        "description": "检测SSH/数据库等弱口令",
        "icon": "key",
    },
    "db_check": {
        "name": "数据库安全检测",
        "description": "检测数据库未授权访问/空口令",
        "icon": "database",
    },
    "network_check": {
        "name": "网络设备检测",
        "description": "SNMP团体字检测/网络设备配置",
        "icon": "cluster",
    },
    "windows_check": {
        "name": "Windows/AD/SMB组合检测",
        "description": "Windows/AD/SMB 用户/SID/共享检测",
        "icon": "windows",
    },
    "full_compliance_scan": {
        "name": "全量合规扫描",
        "description": "端口+SSL+漏洞+弱口令全量扫描",
        "icon": "safety-certificate",
    },
    "doc_review": {
        "name": "文档审查",
        "description": "审查安全管理制度文档",
        "icon": "file-text",
    },
    "interview": {
        "name": "人员访谈",
        "description": "访谈相关人员了解情况",
        "icon": "team",
    },
}
