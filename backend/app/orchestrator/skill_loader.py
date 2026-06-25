"""
Skill Loader - 加载和解析 Skill YAML 文件
支持基础条款库 + 扩展条款库的合并加载
"""

import os
import yaml
from typing import Dict, List, Optional, Any
from pathlib import Path


class SkillLoader:
    """Skill 加载器 - 从 reference/ 目录加载 Skill YAML"""
    
    def __init__(self, reference_dir: Optional[str] = None):
        if reference_dir is None:
            # 默认使用项目根目录下的 reference/ 目录
            self.reference_dir = Path(__file__).parent.parent.parent.parent / "reference"
        else:
            self.reference_dir = Path(reference_dir)
        
        self.skills_cache: Dict[str, dict] = {}
    
    def load(self, skill_name: str) -> dict:
        """
        加载 Skill
        
        Args:
            skill_name: Skill 名称，如 "dengbao_level3"
        
        Returns:
            Skill 配置字典
        """
        # 检查缓存
        if skill_name in self.skills_cache:
            return self.skills_cache[skill_name]
        
        # 查找 Skill 文件
        skill_file = self._find_skill_file(skill_name)
        if not skill_file:
            raise ValueError(f"Skill not found: {skill_name}")
        
        # 加载 YAML
        with open(skill_file, 'r', encoding='utf-8') as f:
            skill_config = yaml.safe_load(f)
        
        # 验证 Skill 配置
        self._validate_skill(skill_config)
        
        # 缓存
        self.skills_cache[skill_name] = skill_config
        
        return skill_config
    
    def load_with_extensions(self, base_name: str, level: int) -> dict:
        """
        加载基础条款库并合并指定等级的扩展条款
        
        Args:
            base_name: 基础条款库名称，如 "dengbao_base"
            level: 等保等级（2 或 3）
        
        Returns:
            合并后的条款库配置字典
        """
        cache_key = f"{base_name}_level{level}"
        
        # 检查缓存
        if cache_key in self.skills_cache:
            return self.skills_cache[cache_key]
        
        # 加载基础条款库
        base_config = self.load(base_name)
        
        # 查找并加载扩展条款库
        ext_name = f"dengbao_level{level}_ext"
        ext_file = self._find_skill_file(ext_name)
        
        if ext_file:
            with open(ext_file, 'r', encoding='utf-8') as f:
                ext_config = yaml.safe_load(f)
            
            # 合并条款
            merged_config = self._merge_clauses(base_config, ext_config, level)
        else:
            # 如果没有扩展文件，只返回基础条款中适用于该等级的部分
            merged_config = self._filter_clauses_by_level(base_config, level)
        
        # 缓存
        self.skills_cache[cache_key] = merged_config
        
        return merged_config
    
    def _merge_clauses(self, base_config: dict, ext_config: dict, level: int) -> dict:
        """
        合并基础条款和扩展条款
        
        Args:
            base_config: 基础条款库配置
            ext_config: 扩展条款库配置
            level: 等保等级
        
        Returns:
            合并后的配置
        """
        merged = base_config.copy()
        
        # 过滤基础条款中适用于该等级的条款
        base_clauses = [
            clause for clause in base_config.get("clauses", [])
            if level in clause.get("level", [])
        ]
        
        # 获取扩展条款
        ext_clauses = ext_config.get("clauses", [])
        
        # 合并条款（扩展条款优先级更高）
        clause_ids = {clause["id"]: clause for clause in base_clauses}
        for clause in ext_clauses:
            clause_ids[clause["id"]] = clause
        
        merged["clauses"] = list(clause_ids.values())
        
        # 合并评分规则（扩展覆盖基础）
        if "scoring" in ext_config:
            merged["scoring"] = ext_config["scoring"]
        
        # 更新元数据
        merged["level"] = level
        merged["name"] = f"{base_config['name']} - {level}级"
        
        return merged
    
    def _filter_clauses_by_level(self, config: dict, level: int) -> dict:
        """
        根据等级过滤条款
        
        Args:
            config: 条款库配置
            level: 等保等级
        
        Returns:
            过滤后的配置
        """
        filtered = config.copy()
        
        # 过滤条款
        filtered["clauses"] = [
            clause for clause in config.get("clauses", [])
            if level in clause.get("level", [])
        ]
        
        # 更新元数据
        filtered["level"] = level
        filtered["name"] = f"{config['name']} - {level}级"
        
        return filtered
    
    def get_clauses_by_pillar(self, config: dict, pillar: str) -> List[dict]:
        """
        获取指定支柱的条款
        
        Args:
            config: 条款库配置
            pillar: 支柱 ID
        
        Returns:
            条款列表
        """
        return [
            clause for clause in config.get("clauses", [])
            if clause.get("pillar") == pillar
        ]
    
    def get_clauses_by_check_type(self, config: dict, check_type: str) -> List[dict]:
        """
        获取指定检查类型的条款
        
        Args:
            config: 条款库配置
            check_type: 检查类型（scan/questionnaire/document）
        
        Returns:
            条款列表
        """
        return [
            clause for clause in config.get("clauses", [])
            if clause.get("check_type") == check_type
        ]
    
    def _find_skill_file(self, skill_name: str) -> Optional[Path]:
        """查找 Skill 文件"""
        # 搜索路径
        search_paths = [
            self.reference_dir / "compliance" / f"{skill_name}.yaml",
            self.reference_dir / "workflow" / f"{skill_name}.yaml",
            self.reference_dir / f"{skill_name}.yaml",
        ]
        
        for path in search_paths:
            if path.exists():
                return path
        
        return None
    
    def _validate_skill(self, skill_config: dict):
        """验证 Skill 配置"""
        # 新版条款库不需要 workflow 字段
        if "clauses" in skill_config:
            # 新版条款库格式
            required_fields = ["name", "standard", "clauses"]
            for field in required_fields:
                if field not in skill_config:
                    raise ValueError(f"Skill missing required field: {field}")
            
            # 验证条款结构
            for clause in skill_config["clauses"]:
                if "id" not in clause or "name" not in clause or "pillar" not in clause:
                    raise ValueError(f"Clause missing required fields: {clause}")
        else:
            # 旧版 workflow 格式（向后兼容）
            required_fields = ["name", "workflow", "safety_boundaries", "scoring"]
            
            for field in required_fields:
                if field not in skill_config:
                    raise ValueError(f"Skill missing required field: {field}")
            
            # 验证 workflow 结构
            workflow = skill_config["workflow"]
            if "parallel_groups" not in workflow:
                raise ValueError("Skill workflow missing 'parallel_groups'")
            
            for group in workflow["parallel_groups"]:
                if "id" not in group or "steps" not in group:
                    raise ValueError("Skill parallel_group missing 'id' or 'steps'")
                
                for step in group["steps"]:
                    if "id" not in step or "clause" not in step or "tools" not in step:
                        raise ValueError(f"Skill step missing required fields: {step}")
    
    def list_skills(self) -> List[dict]:
        """列出所有可用的 Skill"""
        skills = []
        
        # 扫描 compliance/ 目录
        compliance_dir = self.reference_dir / "compliance"
        if compliance_dir.exists():
            for file in compliance_dir.glob("*.yaml"):
                try:
                    with open(file, 'r', encoding='utf-8') as f:
                        config = yaml.safe_load(f)
                        
                        # 新版条款库格式
                        if "clauses" in config:
                            # 基础条款库
                            if "base" not in config:
                                skills.append({
                                    "name": config.get("name", file.stem),
                                    "file": str(file),
                                    "standard": config.get("standard", ""),
                                    "level": config.get("level", 0),
                                    "description": config.get("description", ""),
                                    "type": "base",
                                    "clause_count": len(config.get("clauses", [])),
                                })
                            # 扩展条款库
                            else:
                                level = config.get("level", 0)
                                skills.append({
                                    "name": config.get("name", file.stem),
                                    "file": str(file),
                                    "standard": config.get("standard", ""),
                                    "level": level,
                                    "description": config.get("description", ""),
                                    "type": "extension",
                                    "base": config.get("base", ""),
                                    "clause_count": len(config.get("clauses", [])),
                                })
                        # 旧版 workflow 格式
                        else:
                            skills.append({
                                "name": config.get("name", file.stem),
                                "file": str(file),
                                "standard": config.get("standard", ""),
                                "level": config.get("level", 0),
                                "description": config.get("description", ""),
                                "type": "workflow",
                            })
                except Exception as e:
                    print(f"Error loading skill {file}: {e}")
        
        return skills
    
    def get_safety_rules(self, skill_config: dict) -> List[dict]:
        """获取 Skill 的安全红线规则"""
        return skill_config.get("safety_boundaries", [])
    
    def get_scoring_rules(self, skill_config: dict) -> dict:
        """获取 Skill 的评分规则"""
        return skill_config.get("scoring", {})
    
    def get_parallel_groups(self, skill_config: dict) -> List[dict]:
        """获取 Skill 的并行组"""
        return skill_config.get("workflow", {}).get("parallel_groups", [])
    
    def resolve_params(self, params: dict, context: dict) -> dict:
        """
        解析参数模板
        
        Args:
            params: 参数字典，可能包含 {{variable}} 模板
            context: 上下文变量
        
        Returns:
            解析后的参数字典
        """
        resolved = {}
        
        for key, value in params.items():
            if isinstance(value, str):
                # 替换 {{variable}} 模板
                for var_name, var_value in context.items():
                    value = value.replace(f"{{{{{var_name}}}}}", str(var_value))
                resolved[key] = value
            elif isinstance(value, dict):
                # 递归解析
                resolved[key] = self.resolve_params(value, context)
            else:
                resolved[key] = value
        
        return resolved


# 全局单例
skill_loader = SkillLoader()
