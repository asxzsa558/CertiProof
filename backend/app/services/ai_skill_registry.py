"""Prompt skills loaded on demand by the AI planning layer."""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class PromptSkill:
    name: str
    description: str
    intent_descriptions: Dict[str, str]
    intent_capabilities: Dict[str, Tuple[str, ...]]
    instructions: str
    context_fields: Tuple[str, ...] = ("project",)

    def capabilities_for(self, intents: Iterable[str]) -> Tuple[str, ...]:
        selected: List[str] = []
        for intent in intents:
            for capability in self.intent_capabilities.get(intent, ()):
                if capability not in selected:
                    selected.append(capability)
        if selected:
            return tuple(selected)
        for capabilities in self.intent_capabilities.values():
            for capability in capabilities:
                if capability not in selected:
                    selected.append(capability)
        return tuple(selected)


SECURITY_COMMON = """
- 只选择用户实际要求的检测能力；组合请求可以生成多个步骤。
- “所有资产”表示当前项目已授权资产，使用 target="项目资产"，不得引用其他项目或历史指令中的目标。
- 端口扫描默认 high-risk；明确端口范围时原样填写；全端口使用 1-65535。
- Web 安全扫描默认使用 nikto_scan；只有明确要求 SQL 注入且存在查询参数 URL 或 POST 数据时使用 sqlmap_scan。
- baseline_check 需要每个资产的 SSH 用户名以及密码或密钥；缺失时使用 chat 说明需要补充的凭据。
- 执行失败、超时、不可达和认证失败只是无法完成检测，不能描述为未发现风险。
""".strip()


SKILLS: Tuple[PromptSkill, ...] = (
    PromptSkill(
        name="project-status",
        description="查询当前项目的资产、合规状态、通过准备度、主要差距、管理层摘要和历史检测事实。",
        intent_descriptions={
            "query_project_status": "整体合规状态、评分、覆盖率、测评进度或当前阶段",
            "query_compliance_readiness": "当前能否通过、是否具备测评准备条件或是否已经合规",
            "query_major_gaps": "主要差距、首要风险、优先整改项或最需要解决的问题",
            "query_executive_summary": "面向管理层、领导或决策者的项目摘要",
            "query_findings": "当前问题、待处理项、已修复项或无法验证项",
            "query_open_ports": "已经确认的开放端口和服务",
            "query_vulnerabilities": "已经发现的漏洞",
            "query_scan_history": "检测历史、之前执行过什么",
        },
        intent_capabilities={
            "query_project_status": ("view_project_status",),
            "query_compliance_readiness": ("view_project_status",),
            "query_major_gaps": ("view_project_status",),
            "query_executive_summary": ("view_project_status",),
            "query_findings": ("view_findings",),
            "query_open_ports": ("view_open_ports",),
            "query_vulnerabilities": ("view_vulnerabilities",),
            "query_scan_history": ("view_scan_history",),
        },
        instructions="""
- 整体状态、通过准备度、主要差距和管理层摘要都读取同一份 view_project_status 事实快照，但必须使用对应的 view 参数。
- “能否通过”必须先给直接结论，再说明事实依据；只能表达内部自查准备度，不承诺通过正式测评。
- “主要差距”必须展示真实待处理 Finding，不得只重复总数。
- “管理层摘要”必须包含总体判断、主要风险和下一步，不输出工具内部名称。
- 不得从历史对话复用旧分数，也不得把流程完成度当成合规评分。
""".strip(),
        context_fields=("project", "assessment", "thread"),
    ),
    PromptSkill(
        name="security-scan",
        description="对项目资产执行网络、Web、主机、数据库和协议安全检测。",
        intent_descriptions={
            "scan_ports": "端口、高危端口、定制端口或全端口扫描",
            "scan_web": "Web、Nikto 或 SQL 注入检测",
            "scan_vulnerabilities": "Nuclei 漏洞扫描",
            "scan_baseline": "主机安全基线或 SSH 配置检查",
            "scan_passwords": "弱口令或密码安全检测",
            "scan_tls": "SSL/TLS 检测",
            "scan_database": "数据库安全或具体数据库协议检测",
            "scan_network_device": "SNMP 或网络设备检测",
            "scan_windows": "Windows、AD 或 SMB 检测",
            "scan_web_discovery": "目录发现、目录爆破或 Web 模糊测试",
            "scan_reachability": "Ping、批量存活或网段探测",
            "scan_comprehensive": "组合安全扫描或全面技术检测",
        },
        intent_capabilities={
            "scan_ports": ("scan_ports", "masscan_scan"),
            "scan_web": ("nikto_scan", "sqlmap_scan"),
            "scan_vulnerabilities": ("scan_vulnerabilities",),
            "scan_baseline": ("baseline_check", "ssh_config_check"),
            "scan_passwords": ("scan_weak_passwords",),
            "scan_tls": ("scan_ssl",),
            "scan_database": (
                "database_security_scan", "redis_check", "mysql_check", "mongodb_check",
                "memcached_check", "oracle_check",
            ),
            "scan_network_device": ("network_device_scan", "snmp_walk", "snmp_get", "snmp_bruteforce"),
            "scan_windows": ("windows_security_scan", "enum4linux_scan", "smb_enum", "crackmapexec_scan"),
            "scan_web_discovery": ("web_discovery_scan", "gobuster_scan", "ffuf_scan"),
            "scan_reachability": ("ping_asset", "fping_scan"),
            "scan_comprehensive": ("full_compliance_scan", "tech_assessment"),
        },
        instructions=SECURITY_COMMON,
        context_fields=("project", "assets", "thread"),
    ),
    PromptSkill(
        name="assessment-flow",
        description="解释或推进差距分析、现场测评、整改与复测、生成报告四阶段流程。",
        intent_descriptions={
            "assessment_start": "开始或启动当前项目等保测评",
            "assessment_retest": "开始整改复测或重新验证当前问题",
            "assessment_reset": "完全重置当前测评数据并重新开始",
            "assessment_status": "询问当前阶段、下一步或如何继续测评",
            "assessment_technical": "执行测评流程内的基础或现场技术检测",
            "assessment_explain": "解释阶段、进度、评分和流程规则",
        },
        intent_capabilities={
            "assessment_start": ("assessment_flow_action",),
            "assessment_retest": ("assessment_flow_action",),
            "assessment_reset": ("assessment_flow_action",),
            "assessment_status": ("view_project_status", "chat"),
            "assessment_technical": ("full_compliance_scan", "tech_assessment"),
            "assessment_explain": ("chat",),
        },
        instructions="""
- 四阶段顺序为差距分析、现场测评、整改与复测、生成报告。
- 开始测评使用 assessment_flow_action(action=start)。
- 开始复测使用 assessment_flow_action(action=retest)，先返回可复测的技术和文档问题范围；文档问题没有改进材料时不得伪造复测。
- 重置使用 assessment_flow_action(action=reset)。只有用户本轮明确确认彻底清空时 confirm=true，否则只返回影响说明和确认要求。
- 询问“现在该做什么”时结合当前持久化阶段回答；不要假装已经执行按钮或上传材料。
- 流程进度、合规评分和待处理问题是三个独立事实。
- 正式测评写入必须经过 Flow Engine；交互扫描不能冒充正式测评任务。
""".strip(),
        context_fields=("project", "assessment", "thread"),
    ),
    PromptSkill(
        name="document-compliance",
        description="说明文档上传、归类、解析、证据检索和合规判定。",
        intent_descriptions={
            "document_check": "上传或检查制度文档、批量材料、文件夹或压缩包",
            "document_explain": "解释 OCR、归类、证据、标准库或无法分析原因",
        },
        intent_capabilities={
            "document_check": ("chat",),
            "document_explain": ("chat",),
        },
        instructions="""
- 文档检查通过项目测评界面的材料上传执行；当前聊天能力不能伪造上传或分析任务。
- 原生解析优先，轻量 OCR 补充，完整视觉模型按配置交叉验证；提取失败必须标记 unable。
- 文档归类、证据召回、模型判证和规则裁决是不同步骤，不得只凭文件名或模型自由判断合规。
""".strip(),
        context_fields=("project", "assessment", "thread"),
    ),
    PromptSkill(
        name="remediation-retest",
        description="解释文档替换、技术复测和问题状态变化。",
        intent_descriptions={
            "remediation_action": "询问如何整改、重新提交材料或重新检测",
        },
        intent_capabilities={
            "remediation_action": ("view_findings", "chat"),
        },
        instructions="""
- 先展示真实 Finding，再说明对应的文档替换或技术复测入口。
- 只有真实重新检查可以把问题改为已修复；文字确认和聊天回复不能关闭问题。
- open 和 still_present 都属于待处理，unable 单独展示。
""".strip(),
        context_fields=("project", "assessment", "thread"),
    ),
    PromptSkill(
        name="report-explanation",
        description="生成或解释当前项目的正式 HTML 报告及版本状态。",
        intent_descriptions={
            "report_generate": "生成正式报告",
            "report_explain": "解释报告、版本、过期原因或报告中的评分",
        },
        intent_capabilities={
            "report_generate": ("generate_html_report",),
            "report_explain": ("view_project_status", "chat"),
        },
        instructions="""
- 正式格式为 HTML；报告必须使用当前测评事实快照并经过流程门禁。
- 独立聊天扫描不使当前报告过期；测评重跑、材料、复测、阶段重开或重置会使报告过期。
- 不生成虚构版本、趋势或评分。
""".strip(),
        context_fields=("project", "assessment", "thread"),
    ),
    PromptSkill(
        name="asset-management",
        description="查询和管理项目、资产、授权范围与权属验证。",
        intent_descriptions={
            "asset_list": "当前项目有哪些资产、资产数量或归属",
            "asset_add": "添加资产",
            "asset_verify": "验证资产权属",
            "project_list": "列出项目",
            "project_manage": "创建、修改或删除项目",
        },
        intent_capabilities={
            "asset_list": ("list_assets",),
            "asset_add": ("add_asset",),
            "asset_verify": ("verify_asset",),
            "project_list": ("list_projects",),
            "project_manage": ("create_project", "update_project", "delete_project"),
        },
        instructions="""
- 资产清单必须调用 list_assets，返回当前项目真实名称、类型、地址和验证状态。
- “所有资产”始终限定为当前项目资产，不能混入其他项目或历史对话目标。
- 缺少项目名、资产地址等必填信息时使用 chat 明确询问，不自动编造。
""".strip(),
        context_fields=("project", "assets", "thread"),
    ),
    PromptSkill(
        name="scope-guard",
        description="提供 CertiProof 使用帮助，并拒绝产品业务范围外的问题。",
        intent_descriptions={
            "help": "询问系统能做什么或如何使用",
            "out_of_scope": "与当前项目查询、安全检测、测评流程或产品使用无关的问题",
        },
        intent_capabilities={
            "help": ("help",),
            "out_of_scope": ("chat",),
        },
        instructions="""
- 帮助只介绍项目查询、检测执行、测评流程和材料/报告操作。
- 范围外问题不得尝试回答，明确说明 CertiProof 当前支持范围。
""".strip(),
        context_fields=("project", "thread"),
    ),
)


class PromptSkillRegistry:
    def __init__(self, skills: Sequence[PromptSkill] = SKILLS):
        self._skills = {skill.name: skill for skill in skills}
        self._intent_to_skill = {
            intent: skill.name
            for skill in skills
            for intent in skill.intent_descriptions
        }

    def catalog_for_router(self) -> str:
        lines = []
        for skill in self._skills.values():
            intents = "; ".join(
                f"{name}={description}"
                for name, description in skill.intent_descriptions.items()
            )
            lines.append(f"- {skill.name}: {skill.description}\n  intents: {intents}")
        return "\n".join(lines)

    def resolve(self, requested: Iterable[str], intents: Iterable[str]) -> Tuple[PromptSkill, ...]:
        names: List[str] = []
        for intent in intents:
            name = self._intent_to_skill.get(intent)
            if name and name not in names:
                names.append(name)
        for name in requested:
            if name in self._skills and name not in names:
                names.append(name)
        if not names:
            names.append("scope-guard")
        return tuple(self._skills[name] for name in names[:3])

    def format_for_planner(self, skills: Sequence[PromptSkill], intents: Iterable[str], capability_registry) -> str:
        intent_list = tuple(intents)
        blocks = []
        for skill in skills:
            blocks.append(
                f"### Skill: {skill.name}\n{skill.description}\n{skill.instructions}"
            )
        capability_names = self.capability_names_for(skills, intent_list)

        capability_blocks = []
        for name in capability_names:
            capability = capability_registry.get(name)
            if capability:
                capability_blocks.append(capability.to_prompt_format())

        return (
            "## 已加载业务 Skill\n"
            + "\n\n".join(blocks)
            + "\n\n## 本次允许使用的 Capability\n"
            + ("\n".join(capability_blocks) if capability_blocks else "仅允许澄清当前需求")
        )

    def capability_names_for(self, skills: Sequence[PromptSkill], intents: Iterable[str]) -> Tuple[str, ...]:
        intent_list = tuple(intents)
        names: List[str] = []
        for skill in skills:
            for name in skill.capabilities_for(intent_list):
                if name not in names:
                    names.append(name)
        return tuple(names)


prompt_skill_registry = PromptSkillRegistry()
