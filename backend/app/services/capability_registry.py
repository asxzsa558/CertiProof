"""
能力注册表 - 注册系统所有能力，供 AI 决策引擎使用
"""

import logging
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class Capability:
    """能力定义"""
    name: str
    description: str
    parameters: Dict  # JSON Schema
    execute: Callable = None  # 异步执行函数
    category: str = "system"  # 能力分类
    
    def to_prompt_format(self) -> str:
        """格式化为 prompt 中可用的描述"""
        param_desc = []
        props = self.parameters.get("properties", {})
        required = self.parameters.get("required", [])
        
        for name, schema in props.items():
            req = "必填" if name in required else "可选"
            desc = schema.get("description", "")
            param_desc.append(f"    - {name} ({req}): {desc}")
        
        params_str = "\n".join(param_desc) if param_desc else "    无参数"
        
        return f"""### {self.name}
{self.description}
参数：
{params_str}
"""


class CapabilityRegistry:
    """能力注册表"""
    
    def __init__(self):
        self.capabilities: Dict[str, Capability] = {}
        self._register_all_capabilities()
    
    def register(self, capability: Capability):
        """注册能力"""
        self.capabilities[capability.name] = capability
        logger.info(f"Registered capability: {capability.name}")
    
    def get(self, name: str) -> Optional[Capability]:
        """获取能力"""
        return self.capabilities.get(name)
    
    def get_all(self) -> List[Capability]:
        """获取所有能力"""
        return list(self.capabilities.values())
    
    def get_by_category(self, category: str) -> List[Capability]:
        """按分类获取能力"""
        return [c for c in self.capabilities.values() if c.category == category]
    
    def format_for_prompt(self) -> str:
        """格式化所有能力用于 prompt"""
        categories = {}
        for cap in self.capabilities.values():
            if cap.category not in categories:
                categories[cap.category] = []
            categories[cap.category].append(cap)
        
        category_names = {
            "scan": "扫描类能力",
            "query": "数据查询类能力",
            "project": "项目管理类能力",
            "asset": "资产管理类能力",
            "remediation": "整改管理类能力",
            "report": "报告生成类能力",
            "monitoring": "监控管理类能力",
            "system": "系统类能力",
        }
        
        result = []
        for cat_key, cat_name in category_names.items():
            if cat_key in categories:
                result.append(f"\n## {cat_name}")
                for cap in categories[cat_key]:
                    result.append(cap.to_prompt_format())
        
        return "\n".join(result)
    
    def format_compact_for_prompt(self) -> str:
        """压缩格式的能力描述，用于减少 prompt token 数"""
        lines = []
        for cap in self.capabilities.values():
            props = cap.parameters.get("properties", {})
            required = cap.parameters.get("required", [])
            
            params = []
            for name, schema in props.items():
                req = "*" if name in required else ""
                params.append(f"{name}{req}")
            
            params_str = ", ".join(params) if params else "无参数"
            lines.append(f"- {cap.name}({params_str}): {cap.description[:100]}")
        
        return "\n".join(lines)
    
    def _register_all_capabilities(self):
        """注册所有能力"""
        
        # ========== 扫描类能力 ==========
        
        self.register(Capability(
            name="scan_ports",
            description="对目标资产进行端口扫描，发现开放的端口和服务。默认扫描等保/安全检查常关注的高危端口；定制检测可传 port_range='30-3000'，全端口扫描传 port_range='1-65535'。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标资产（IP地址、域名或主机名）"},
                    "port_range": {"type": "string", "description": "端口范围，如 'high-risk'、'30-3000'、'1-65535'、'80,443'、'22'，不指定则扫描高危端口"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="masscan_scan",
            description="使用 masscan 进行超高速全端口扫描（比 nmap 快 10x）。适合快速发现开放端口，但不做服务版本识别。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标资产（IP地址、域名或主机名）"},
                    "port_range": {"type": "string", "description": "端口范围，默认 '1-65535'"},
                    "rate": {"type": "integer", "description": "每秒发包数，默认 2000"},
                    "banner_grab": {"type": "boolean", "description": "是否抓取 banner，默认 false"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="fping_scan",
            description="使用 fping 进行批量存活检测。支持 CIDR 网段格式，快速发现网段内存活主机。",
            parameters={
                "type": "object",
                "properties": {
                    "network": {"type": "string", "description": "CIDR 网段，如 '192.168.1.0/24'"},
                    "targets": {"type": "array", "items": {"type": "string"}, "description": "目标 IP 列表"},
                },
                "required": []
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="nikto_scan",
            description="使用 nikto 进行 Web 服务器漏洞扫描。检测已知漏洞、危险文件、CGI 脚本、服务器配置问题等。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机（IP 或域名）"},
                    "port": {"type": "integer", "description": "端口，默认 80"},
                    "ssl": {"type": "boolean", "description": "是否使用 HTTPS，默认 false"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="sqlmap_scan",
            description="使用 sqlmap 进行 SQL 注入检测。自动检测和利用 SQL 注入漏洞。",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL，包含参数，如 'http://example.com/page?id=1'"},
                    "data": {"type": "string", "description": "POST 数据"},
                    "level": {"type": "integer", "description": "检测级别 1-5，默认 1"},
                    "risk": {"type": "integer", "description": "风险级别 1-3，默认 1"},
                },
                "required": ["url"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="gobuster_scan",
            description="使用 gobuster 进行目录/文件爆破。发现 Web 应用中隐藏的目录和文件。",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL"},
                    "wordlist": {"type": "string", "description": "字典文件路径，默认 /usr/share/wordlists/dirb/common.txt"},
                    "extensions": {"type": "string", "description": "文件扩展名，如 'php,asp,html'"},
                    "threads": {"type": "integer", "description": "线程数，默认 10"},
                },
                "required": ["url"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="ffuf_scan",
            description="使用 ffuf 进行 Web 模糊测试。高速 Web 路径/参数发现工具。",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL，包含 FUZZ 占位符"},
                    "wordlist": {"type": "string", "description": "字典文件路径"},
                    "method": {"type": "string", "description": "HTTP 方法，默认 GET"},
                },
                "required": ["url"]
            },
            category="scan"
        ))

        self.register(Capability(
            name="web_discovery_scan",
            description="Web 路径/目录发现组合检测，内部执行 gobuster 目录爆破和 ffuf 模糊测试，统一返回发现的路径/端点。",
            parameters={
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "目标 URL 或主机"},
                    "target": {"type": "string", "description": "目标 URL 或主机"},
                },
                "required": []
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="snmp_walk",
            description="使用 snmpwalk 获取网络设备 SNMP 信息。读取设备接口流量、路由表、系统信息等。对应等保 2.2 安全通信网络。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标设备 IP"},
                    "community": {"type": "string", "description": "SNMP 团体字，默认 public"},
                    "version": {"type": "string", "description": "SNMP 版本，默认 2c"},
                    "oid": {"type": "string", "description": "OID，默认 1.3.6.1.2.1 (MIB-2)"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="snmp_bruteforce",
            description="使用 onesixtyone 进行 SNMP 团体字爆破。检测默认或弱团体字配置。对应等保 2.2 安全通信网络。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标设备 IP"},
                    "wordlist": {"type": "string", "description": "字典文件路径"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="snmp_get",
            description="使用 snmpget 获取单个 SNMP OID 值。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标设备 IP"},
                    "oid": {"type": "string", "description": "OID"},
                    "community": {"type": "string", "description": "SNMP 团体字，默认 public"},
                    "version": {"type": "string", "description": "SNMP 版本，默认 2c"},
                },
                "required": ["target", "oid"]
            },
            category="scan"
        ))

        self.register(Capability(
            name="network_device_scan",
            description="网络设备安全检测组合能力，内部执行 SNMP 信息读取和默认/弱团体字检测。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标网络设备 IP"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="enum4linux_scan",
            description="使用 enum4linux 进行 Windows 信息枚举。获取用户列表、共享、密码策略等。对应等保 2.4.1 身份鉴别。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标 Windows 主机 IP"},
                    "username": {"type": "string", "description": "用户名（可选）"},
                    "password": {"type": "string", "description": "密码（可选）"},
                    "scan_type": {"type": "string", "description": "扫描类型: all/users/shares/password_policy，默认 all"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="crackmapexec_scan",
            description="使用 crackmapexec 进行 SMB/Windows 枚举。获取用户、共享、密码策略、会话等。对应等保 2.4.1 身份鉴别。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标 Windows 主机 IP"},
                    "username": {"type": "string", "description": "用户名"},
                    "password": {"type": "string", "description": "密码"},
                    "scan_type": {"type": "string", "description": "扫描类型: all/users/shares/pass_pol/sessions，默认 all"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="smb_enum",
            description="使用 smbclient 枚举 SMB 共享。检测匿名/guest 访问和共享权限。对应等保 2.4.2 访问控制。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标 Windows 主机 IP"},
                    "username": {"type": "string", "description": "用户名，默认 guest"},
                    "password": {"type": "string", "description": "密码"},
                },
                "required": ["target"]
            },
            category="scan"
        ))

        self.register(Capability(
            name="windows_security_scan",
            description="Windows/AD 安全检测组合能力，内部执行用户/组枚举、SID 枚举和 SMB 共享枚举。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标 Windows 主机 IP"},
                    "username": {"type": "string", "description": "用户名（可选）"},
                    "password": {"type": "string", "description": "密码（可选）"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="redis_check",
            description="检查 Redis 未授权访问。尝试无密码连接获取服务器信息。对应等保 2.4.6 数据库安全。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP"},
                    "port": {"type": "integer", "description": "Redis 端口，默认 6379"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="oracle_check",
            description="检查 Oracle TNS 版本信息泄露。对应等保 2.4.6 数据库安全。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP"},
                    "port": {"type": "integer", "description": "Oracle TNS 端口，默认 1521"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="mongodb_check",
            description="检查 MongoDB 未授权访问。对应等保 2.4.6 数据库安全。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP"},
                    "port": {"type": "integer", "description": "MongoDB 端口，默认 27017"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="memcached_check",
            description="检查 Memcached 未授权访问。对应等保 2.4.6 数据库安全。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP"},
                    "port": {"type": "integer", "description": "Memcached 端口，默认 11211"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="mysql_check",
            description="检查 MySQL 空口令。对应等保 2.4.6 数据库安全。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP"},
                    "port": {"type": "integer", "description": "MySQL 端口，默认 3306"},
                    "username": {"type": "string", "description": "用户名，默认 root"},
                },
                "required": ["target"]
            },
            category="scan"
        ))

        self.register(Capability(
            name="database_security_scan",
            description="执行数据库安全组合检测，包括 Redis、MySQL、MongoDB、Memcached 和 Oracle。对应等保 2.4.6 数据库安全。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="scan_ssl",
            description="对目标进行 SSL/TLS 配置分析，检查 TLS 版本、加密套件、证书信息等。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标地址（IP或域名）"},
                    "port": {"type": "integer", "description": "端口号，默认 443"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="scan_vulnerabilities",
            description="对目标进行漏洞扫描，检测 CVE 漏洞、错误配置、暴露信息等。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标地址（URL或IP）"},
                    "templates": {"type": "string", "description": "模板标签，如 'cve'、'misconfig'、'exposure'"},
                    "severity": {"type": "string", "description": "严重级别过滤，如 'critical,high'"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="scan_weak_passwords",
            description="对目标服务进行弱口令检测，尝试发现弱密码。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标地址"},
                    "service": {"type": "string", "description": "服务类型，如 'ssh'、'ftp'，默认 ssh"},
                    "port": {"type": "integer", "description": "端口号，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="full_compliance_scan",
            description="执行完整的等保合规扫描，包括端口扫描、SSL检测、漏洞扫描、弱口令检测等所有检查项。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标资产地址"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="tech_assessment",
            description="等保技术要求测评（10 项检查）：端口扫描、安全基线、漏洞扫描、Web 漏洞、弱口令、SSL、数据库安全 (Redis/MySQL/MongoDB)、网络设备检测。仅安全基线检查需要 SSH 凭据。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标资产地址"},
                    "ssh_username": {"type": "string", "description": "SSH 用户名（仅用于安全基线检查）"},
                    "ssh_password": {"type": "string", "description": "SSH 密码（仅用于安全基线检查）"},
                    "ssh_key_file": {"type": "string", "description": "SSH 私钥路径（仅用于安全基线检查）"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        # ========== SSH 白盒配置核查能力 ==========

        self.register(Capability(
            name="baseline_check",
            description="安全基线核查。通过 SSH 登录目标主机后自动识别操作系统；Linux 执行密码策略、SSH配置、审计配置、服务端口、文件权限、SELinux/AppArmor 等检查，非 Linux 返回明确跳过原因。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码（与 key_file 二选一）"},
                    "key_file": {"type": "string", "description": "SSH 私钥文件路径（与 password 二选一）"},
                    "ssh_username": {"type": "string", "description": "SSH 用户名"},
                    "ssh_password": {"type": "string", "description": "SSH 密码"},
                    "ssh_key_file": {"type": "string", "description": "SSH 私钥路径"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                    "ssh_port": {"type": "integer", "description": "SSH 端口，默认 22"},
                    "categories": {"type": "array", "items": {"type": "string"}, "description": "检查类别列表，可选: password, ssh, audit, service, file_perm, mac。默认全部"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="linux_baseline",
            description="Linux 安全基线全量检查。通过 SSH 远程登录目标主机，检查密码策略、SSH配置、审计配置、服务端口、文件权限、SELinux/AppArmor 等。覆盖等保安全计算环境核心要求。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码（与 key_file 二选一）"},
                    "key_file": {"type": "string", "description": "SSH 私钥文件路径（与 password 二选一）"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                    "categories": {"type": "array", "items": {"type": "string"}, "description": "检查类别列表，可选: password, ssh, audit, service, file_perm, mac。默认全部"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="password_policy_check",
            description="密码策略检查。通过 SSH 远程检查 Linux 密码复杂度策略、密码过期策略、空口令账户等。对应等保 8.1.4.1 身份鉴别。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="ssh_config_check",
            description="SSH 配置检查。通过 SSH 远程检查 sshd_config 配置，包括 root 登录、密码认证、最大尝试次数等。对应等保 8.1.4.1 身份鉴别。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="audit_config_check",
            description="审计配置检查。通过 SSH 远程检查 auditd 服务状态、审计规则、rsyslog 配置、远程日志等。对应等保 8.1.4.3 安全审计。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="service_port_check",
            description="服务端口检查。通过 SSH 远程检查监听端口列表、高危端口、不必要服务等。对应等保 8.1.4.4 入侵防范。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="file_permission_check",
            description="文件权限检查。通过 SSH 远程检查 SUID/SGID 文件、全局可写文件、关键文件权限等。对应等保 8.1.4.2 访问控制。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        self.register(Capability(
            name="mac_check",
            description="强制访问控制检查。通过 SSH 远程检查 SELinux/AppArmor 状态。对应等保 8.1.4.4 入侵防范。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标主机 IP 或域名"},
                    "username": {"type": "string", "description": "SSH 用户名，默认 root"},
                    "password": {"type": "string", "description": "SSH 密码"},
                    "port": {"type": "integer", "description": "SSH 端口，默认 22"},
                },
                "required": ["target"]
            },
            category="scan"
        ))
        
        # ========== 数据查询类能力 ==========
        
        self.register(Capability(
            name="view_scan_results",
            description="查看之前的扫描结果，包括开放的端口、发现的漏洞、SSL问题等。如果不指定参数，返回最近的扫描结果。",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "查询内容，如'开放端口'、'安全问题'、'所有结果'"},
                    "target": {"type": "string", "description": "指定目标的扫描结果"},
                },
                "required": []
            },
            category="query"
        ))
        
        self.register(Capability(
            name="view_open_ports",
            description="查看开放端口列表，显示哪些端口是开放的，运行什么服务。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "指定目标，不指定则使用最近扫描的目标"},
                },
                "required": []
            },
            category="query"
        ))
        
        self.register(Capability(
            name="view_vulnerabilities",
            description="查看发现的漏洞列表，可以按严重级别过滤。",
            parameters={
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "description": "严重级别过滤，如 'critical'、'high'、'medium'、'low'"},
                },
                "required": []
            },
            category="query"
        ))
        
        self.register(Capability(
            name="view_findings",
            description="查看所有合规发现，包括通过、失败、部分通过的项目。",
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "状态过滤，如 'open'、'resolved'"},
                },
                "required": []
            },
            category="query"
        ))
        
        self.register(Capability(
            name="view_compliance_score",
            description="查看项目合规评分，显示当前合规分数和等级。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID，不指定则使用当前项目"},
                },
                "required": []
            },
            category="query"
        ))
        
        self.register(Capability(
            name="view_scan_history",
            description="查看扫描历史记录，显示过去执行过的所有扫描任务。",
            parameters={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "description": "返回数量限制，默认 10"},
                },
                "required": []
            },
            category="query"
        ))
        
        # ========== 项目管理类能力 ==========
        
        self.register(Capability(
            name="create_project",
            description="创建新的等保合规项目。",
            parameters={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "项目名称"},
                    "description": {"type": "string", "description": "项目描述"},
                    "compliance_level": {"type": "string", "description": "等保等级，'二级' 或 '三级'，默认 '三级'"},
                },
                "required": ["name"]
            },
            category="project"
        ))
        
        self.register(Capability(
            name="list_projects",
            description="列出所有项目，显示项目名称、等保等级、合规分数等。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            category="project"
        ))
        
        self.register(Capability(
            name="update_project",
            description="更新项目信息，如名称、描述等。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                    "name": {"type": "string", "description": "新名称"},
                    "description": {"type": "string", "description": "新描述"},
                },
                "required": ["project_id"]
            },
            category="project"
        ))
        
        self.register(Capability(
            name="delete_project",
            description="删除项目及其所有相关数据。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                },
                "required": ["project_id"]
            },
            category="project"
        ))
        
        # ========== 资产管理类能力 ==========
        
        self.register(Capability(
            name="add_asset",
            description="添加资产到项目，资产可以是 IP 地址、域名或云资源。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                    "asset_type": {"type": "string", "description": "资产类型：'ip'、'domain'、'cloud_resource'"},
                    "value": {"type": "string", "description": "资产值（IP地址、域名等）"},
                    "name": {"type": "string", "description": "资产名称（可选）"},
                },
                "required": ["project_id", "asset_type", "value"]
            },
            category="asset"
        ))
        
        self.register(Capability(
            name="list_assets",
            description="列出项目中的所有资产。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                },
                "required": ["project_id"]
            },
            category="asset"
        ))
        
        self.register(Capability(
            name="verify_asset",
            description="验证资产所有权。",
            parameters={
                "type": "object",
                "properties": {
                    "asset_id": {"type": "integer", "description": "资产ID"},
                    "verification_method": {"type": "string", "description": "验证方法：'dns_txt'、'file'、'port_response'"},
                },
                "required": ["asset_id"]
            },
            category="asset"
        ))
        
        self.register(Capability(
            name="ping_asset",
            description="检测资产是否可达（ping）。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标 IP 或域名"},
                    "count": {"type": "integer", "description": "ping 次数，默认 3"},
                },
                "required": ["target"]
            },
            category="asset"
        ))
        
        # ========== 报告生成类能力 ==========
        
        self.register(Capability(
            name="generate_html_report",
            description="生成 HTML 格式的等保自查报告。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                },
                "required": ["project_id"]
            },
            category="report"
        ))
        
        self.register(Capability(
            name="generate_json_report",
            description="生成 JSON 格式的等保合规报告。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                },
                "required": ["project_id"]
            },
            category="report"
        ))
        
        # ========== 监控管理类能力 ==========
        
        self.register(Capability(
            name="create_scheduled_scan",
            description="创建定时扫描任务，可以设置每日、每周或每月执行。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID"},
                    "asset_id": {"type": "integer", "description": "资产ID"},
                    "name": {"type": "string", "description": "定时任务名称"},
                    "frequency": {"type": "string", "description": "频率：'daily'、'weekly'、'monthly'"},
                },
                "required": ["project_id", "asset_id", "frequency"]
            },
            category="monitoring"
        ))
        
        self.register(Capability(
            name="list_scheduled_scans",
            description="列出所有定时扫描任务。",
            parameters={
                "type": "object",
                "properties": {
                    "project_id": {"type": "integer", "description": "项目ID（可选）"},
                },
                "required": []
            },
            category="monitoring"
        ))
        
        self.register(Capability(
            name="trigger_scheduled_scan",
            description="手动触发定时扫描任务立即执行。",
            parameters={
                "type": "object",
                "properties": {
                    "scan_id": {"type": "integer", "description": "定时扫描任务ID"},
                },
                "required": ["scan_id"]
            },
            category="monitoring"
        ))
        
        # ========== 系统类能力 ==========
        
        self.register(Capability(
            name="help",
            description="显示系统帮助信息，介绍系统功能和使用方法。",
            parameters={
                "type": "object",
                "properties": {},
                "required": []
            },
            category="system"
        ))
        
        self.register(Capability(
            name="chat",
            description="普通对话，回答用户问题或进行闲聊。当用户的问题不需要调用其他能力时使用。",
            parameters={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "回复消息"},
                },
                "required": ["message"]
            },
            category="system"
        ))


# 全局单例
capability_registry = CapabilityRegistry()
