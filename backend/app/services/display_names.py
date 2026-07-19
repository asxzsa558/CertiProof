"""User-facing names for scan capabilities and assessment task types."""

from app.services.assessment_templates import TASK_TYPES


CAPABILITY_DISPLAY_NAMES = {
    "scan_ports": "端口扫描",
    "masscan_scan": "高速端口扫描",
    "fping_scan": "批量存活检测",
    "scan_ssl": "SSL/TLS 检测",
    "scan_vulnerabilities": "漏洞扫描",
    "scan_weak_passwords": "弱口令检测",
    "baseline_check": "安全基线核查",
    "linux_baseline": "安全基线核查",
    "ssh_config_check": "SSH 配置检查",
    "nikto_scan": "Web 安全扫描",
    "sqlmap_scan": "SQL 注入检测",
    "gobuster_scan": "目录爆破",
    "ffuf_scan": "Web 模糊测试",
    "web_discovery_scan": "Web 目录发现",
    "database_security_scan": "数据库安全检测",
    "redis_check": "Redis 未授权检测",
    "mysql_check": "MySQL 空口令检测",
    "mongodb_check": "MongoDB 未授权检测",
    "oracle_check": "Oracle 检测",
    "memcached_check": "Memcached 检测",
    "snmp_walk": "SNMP 检测",
    "snmp_bruteforce": "SNMP 团体字检测",
    "snmp_get": "SNMP OID 读取",
    "network_device_scan": "网络设备检测",
    "enum4linux_scan": "Windows/AD/SMB 子项",
    "crackmapexec_scan": "Windows SID 枚举",
    "smb_enum": "Windows/AD/SMB 子项",
    "windows_security_scan": "Windows/AD/SMB 检测",
    "full_compliance_scan": "全量合规扫描",
    "tech_assessment": "现场技术测评",
    "ping_host": "Ping 检测",
    "ping_asset": "Ping 检测",
}


def scan_display_name(internal_name: str | None) -> str:
    """Resolve an internal capability/task enum without leaking unknown enums."""
    if not internal_name:
        return "安全检测"
    if internal_name in CAPABILITY_DISPLAY_NAMES:
        return CAPABILITY_DISPLAY_NAMES[internal_name]
    task = TASK_TYPES.get(internal_name)
    return task["name"] if task else "安全检测"
