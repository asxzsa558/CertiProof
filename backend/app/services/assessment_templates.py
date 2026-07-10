"""
等保自查 5 阶段流程模板。

定位：被测企业自查合规性，回答“是否合规、哪里不合规、如何整改、整改后是否改善”。
"""

CORE_DOCUMENTS = [
    "信息安全管理制度",
    "信息安全管理机构设置文件",
    "人员安全管理制度",
    "安全建设管理制度",
    "安全运维管理制度",
    "信息安全事件应急预案",
    "安全事件管理制度",
    "安全审计管理制度",
    "系统安全方案",
    "信息安全策略文件",
]


def _five_stage_template(level: int) -> dict:
    extra_field_checks = [] if level == 2 else [
        {"type": "network_device_assessment", "name": "网络设备检测", "description": "SNMP 团体字、设备暴露和配置读取风险检测"},
        {"type": "windows_ad_smb_assessment", "name": "Windows/AD/SMB 检测", "description": "Windows、AD、SMB 账户、共享和域环境风险检测"},
    ]
    document_tasks = [
        {"type": "doc_review", "name": f"文档检查：{name}", "description": "条款召回 + LLM 判定文档是否满足等保管理要求"}
        for name in CORE_DOCUMENTS
    ]
    return {
        "name": f"等保{level}级自查流程",
        "compliance_level": level,
        "phases_config": [
            {
                "id": "gap_analysis",
                "name": "差距分析",
                "order": 1,
                "required": True,
                "description": "10 个核心文档检查和基础技术检测，生成初始问题清单",
                "depends_on": [],
                "default_tasks": [
                    *document_tasks,
                    {"type": "high_risk_port_scan", "name": "基础技术检测：高危端口扫描", "description": "只扫描等保和安全检查常关注的高危端口，形成初始暴露面"},
                    {"type": "basic_vulnerability_scan", "name": "基础技术检测：漏洞扫描", "description": "使用 nuclei 做初步漏洞发现，生成初始 Finding"},
                    {"type": "basic_baseline_check", "name": "基础技术检测：配置/基线核查", "description": "自动判别主机可用核查项，需 SSH 凭据时明确提示"},
                    {"type": "basic_weak_password_scan", "name": "基础技术检测：弱口令检测", "description": "检测 SSH 等常见服务弱口令风险"},
                    {"type": "basic_ssl_tls_scan", "name": "基础技术检测：SSL/TLS 检测", "description": "检查证书、协议版本和加密套件风险"},
                ],
            },
            {
                "id": "field_assessment",
                "name": "现场测评",
                "order": 2,
                "required": True,
                "description": "全资产自动化深度检测，覆盖 Web、数据库、网络设备和主机安全",
                "depends_on": ["gap_analysis"],
                "default_tasks": [
                    {"type": "full_asset_assessment", "name": "全资产组合扫描", "description": "对全部资产执行端口、SSL、漏洞、弱口令组合检测"},
                    {"type": "web_vulnerability_assessment", "name": "Web 漏洞扫描", "description": "使用 Nikto 等工具检查常见 Web 服务漏洞"},
                    {"type": "directory_discovery_assessment", "name": "目录爆破/路径发现", "description": "使用 gobuster/ffuf 发现敏感路径、目录和端点"},
                    {"type": "web_fuzz_assessment", "name": "Web 模糊测试", "description": "使用 ffuf 对 Web 路径进行模糊测试"},
                    {"type": "sql_injection_assessment", "name": "SQL 注入检测", "description": "使用 sqlmap 对 URL 参数做注入风险检测"},
                    {"type": "database_security_assessment", "name": "数据库安全检测", "description": "Redis/MySQL/MongoDB/Memcached/Oracle 未授权访问和空口令检测"},
                    {"type": "ssh_baseline_assessment", "name": "SSH/主机基线核查", "description": "对可登录主机执行 SSH 配置、密码策略、审计等基线核查"},
                    *extra_field_checks,
                ],
            },
            {
                "id": "remediation",
                "name": "整改加固",
                "order": 3,
                "required": True,
                "description": "基于 Finding 创建整改工单，支持 open 到 closed 以及 skipped",
                "depends_on": ["field_assessment"],
                "default_tasks": [
                    {"type": "remediation", "name": "整改工单跟踪", "description": "看板/列表跟踪责任人、优先级、状态和跳过原因"},
                ],
            },
            {
                "id": "retest",
                "name": "复测验证",
                "order": 4,
                "required": True,
                "description": "重新执行技术检测和文档检查，对比整改前后结果",
                "depends_on": ["remediation"],
                "default_tasks": [
                    {"type": "retest", "name": "整改复测对比", "description": "标记已修复、仍存在、新增问题、已跳过"},
                ],
            },
            {
                "id": "report",
                "name": "生成报告",
                "order": 5,
                "required": True,
                "description": "生成 HTML 报告，汇总问题、整改状态、解决时长和时间线",
                "depends_on": ["retest"],
                "default_tasks": [
                    {"type": "html_report", "name": "HTML 报告生成", "description": "输出企业自查 HTML 报告"},
                ],
            },
        ],
    }


LEVEL_2_TEMPLATE = _five_stage_template(2)
LEVEL_3_TEMPLATE = _five_stage_template(3)

FIVE_STAGE_PHASE_IDS = [phase["id"] for phase in LEVEL_3_TEMPLATE["phases_config"]]
FIVE_STAGE_PHASE_NAMES = [phase["name"] for phase in LEVEL_3_TEMPLATE["phases_config"]]


TASK_TYPES = {
    "asset_discovery": {"name": "资产发现", "description": "发现并记录信息资产", "icon": "radar"},
    "high_risk_port_scan": {"name": "高危端口扫描", "description": "扫描等保/安全检查常关注的高危端口", "icon": "radar"},
    "basic_vulnerability_scan": {"name": "基础漏洞扫描", "description": "nuclei 初步漏洞发现", "icon": "bug"},
    "basic_baseline_check": {"name": "配置/基线核查", "description": "主机配置和基线核查", "icon": "setting"},
    "basic_weak_password_scan": {"name": "弱口令检测", "description": "常见服务弱口令检测", "icon": "key"},
    "basic_ssl_tls_scan": {"name": "SSL/TLS 检测", "description": "证书、协议和套件风险检测", "icon": "lock"},
    "config_check": {"name": "配置核查", "description": "检查安全配置是否符合要求", "icon": "setting"},
    "vuln_scan": {"name": "漏洞扫描", "description": "扫描系统漏洞、Web 漏洞", "icon": "bug"},
    "web_scan": {"name": "Web 安全扫描", "description": "Web 漏洞/目录爆破/模糊测试", "icon": "global"},
    "full_asset_assessment": {"name": "全资产组合扫描", "description": "端口、SSL、漏洞、弱口令组合检测", "icon": "safety-certificate"},
    "web_vulnerability_assessment": {"name": "Web 漏洞扫描", "description": "常见 Web 漏洞检测", "icon": "global"},
    "directory_discovery_assessment": {"name": "目录爆破/路径发现", "description": "敏感路径和目录发现", "icon": "global"},
    "web_fuzz_assessment": {"name": "Web 模糊测试", "description": "ffuf 模糊测试", "icon": "global"},
    "sql_injection_assessment": {"name": "SQL 注入检测", "description": "SQL 注入风险检测", "icon": "database"},
    "database_security_assessment": {"name": "数据库安全检测", "description": "数据库未授权访问/空口令检测", "icon": "database"},
    "network_device_assessment": {"name": "网络设备检测", "description": "SNMP/网络设备配置检测", "icon": "cluster"},
    "windows_ad_smb_assessment": {"name": "Windows/AD/SMB 检测", "description": "Windows/AD/SMB 安全检测", "icon": "windows"},
    "ssh_baseline_assessment": {"name": "SSH/主机基线核查", "description": "SSH 白盒基线核查", "icon": "setting"},
    "ssl_check": {"name": "SSL/TLS 检测", "description": "检测 SSL/TLS 配置安全性", "icon": "lock"},
    "password_scan": {"name": "弱口令检测", "description": "检测 SSH/数据库等弱口令", "icon": "key"},
    "db_check": {"name": "数据库安全检测", "description": "检测数据库未授权访问/空口令", "icon": "database"},
    "network_check": {"name": "网络设备检测", "description": "SNMP/网络设备配置检测", "icon": "cluster"},
    "windows_check": {"name": "Windows/AD/SMB 检测", "description": "Windows/AD/SMB 安全检测", "icon": "windows"},
    "full_compliance_scan": {"name": "全量合规扫描", "description": "多工具组合扫描", "icon": "safety-certificate"},
    "doc_review": {"name": "文档检查", "description": "核心文档条款检查", "icon": "file-text"},
    "remediation": {"name": "整改跟踪", "description": "整改工单跟踪", "icon": "tool"},
    "retest": {"name": "复测验证", "description": "整改前后对比", "icon": "check-circle"},
    "html_report": {"name": "HTML 报告", "description": "生成 HTML 自查报告", "icon": "file-text"},
}
