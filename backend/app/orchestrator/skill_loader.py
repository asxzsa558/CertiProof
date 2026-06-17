"""
Skill Loader - 加载和解析 Skill YAML 文件
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
                        skills.append({
                            "name": config.get("name", file.stem),
                            "file": str(file),
                            "standard": config.get("standard", ""),
                            "level": config.get("level", 0),
                            "description": config.get("description", ""),
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
