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
            lines.append(f"- {cap.name}({params_str}): {cap.description[:50]}")
        
        return "\n".join(lines)
    
    def _register_all_capabilities(self):
        """注册所有能力"""
        
        # ========== 扫描类能力 ==========
        
        self.register(Capability(
            name="scan_ports",
            description="对目标资产进行端口扫描，发现开放的端口和服务。可以指定端口范围，默认扫描全部端口（1-65535）。",
            parameters={
                "type": "object",
                "properties": {
                    "target": {"type": "string", "description": "目标资产（IP地址、域名或主机名）"},
                    "port_range": {"type": "string", "description": "端口范围，如 '1-65535'、'80,443'、'22'，不指定则扫描全部端口"},
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
        
        # ========== 整改管理类能力 ==========
        
        self.register(Capability(
            name="create_remediation_ticket",
            description="为发现的问题创建整改工单。",
            parameters={
                "type": "object",
                "properties": {
                    "finding_id": {"type": "integer", "description": "发现ID"},
                    "title": {"type": "string", "description": "工单标题"},
                    "description": {"type": "string", "description": "工单描述"},
                    "priority": {"type": "string", "description": "优先级：'low'、'medium'、'high'、'critical'"},
                },
                "required": ["finding_id", "title"]
            },
            category="remediation"
        ))
        
        self.register(Capability(
            name="list_remediation_tickets",
            description="列出整改工单，可以按状态过滤。",
            parameters={
                "type": "object",
                "properties": {
                    "status": {"type": "string", "description": "状态过滤：'open'、'in_progress'、'resolved'、'verified'"},
                },
                "required": []
            },
            category="remediation"
        ))
        
        self.register(Capability(
            name="update_ticket_status",
            description="更新整改工单状态。",
            parameters={
                "type": "object",
                "properties": {
                    "ticket_id": {"type": "integer", "description": "工单ID"},
                    "status": {"type": "string", "description": "新状态：'in_progress'、'resolved'、'verified'、'closed'"},
                    "resolution_notes": {"type": "string", "description": "解决说明"},
                },
                "required": ["ticket_id", "status"]
            },
            category="remediation"
        ))
        
        # ========== 报告生成类能力 ==========
        
        self.register(Capability(
            name="generate_pdf_report",
            description="生成 PDF 格式的等保合规报告。",
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
