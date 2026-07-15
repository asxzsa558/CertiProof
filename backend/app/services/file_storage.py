"""
文件存储服务
负责文件的存储、检索、删除
"""
import os
import hashlib
import logging
import aiofiles
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime

from app.core.config import settings

logger = logging.getLogger(__name__)


class FileStorageService:
    """文件存储服务"""
    
    def __init__(self, base_path: str | None = None):
        """
        初始化文件存储服务
        
        Args:
            base_path: 文件存储根目录
        """
        self.base_path = Path(base_path or settings.UPLOAD_DIR)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"FileStorageService initialized with base_path: {self.base_path}")
    
    def _generate_file_path(self, project_id: int, file_name: str) -> Path:
        """
        生成文件存储路径
        格式: {base_path}/{project_id}/{year}/{month}/{timestamp}_{file_name}
        """
        now = datetime.utcnow()
        year = now.strftime("%Y")
        month = now.strftime("%m")
        timestamp = now.strftime("%Y%m%d_%H%M%S_%f")
        
        # 清理文件名，避免路径注入
        safe_name = self._sanitize_filename(file_name)
        
        # 生成路径
        relative_path = Path(str(project_id)) / year / month / f"{timestamp}_{safe_name}"
        full_path = self.base_path / relative_path
        
        # 确保目录存在
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        return full_path, str(relative_path)
    
    def _sanitize_filename(self, file_name: str) -> str:
        """清理文件名，移除危险字符"""
        # 只保留安全字符
        safe_chars = []
        for char in file_name:
            if char.isalnum() or char in "._-":
                safe_chars.append(char)
            else:
                safe_chars.append("_")
        
        safe_name = "".join(safe_chars)
        
        # 限制长度
        if len(safe_name) > 100:
            name, ext = os.path.splitext(safe_name)
            safe_name = name[:95] + ext
        
        return safe_name
    
    async def save_file(
        self,
        project_id: int,
        file_name: str,
        content: bytes
    ) -> Tuple[str, str, int]:
        """
        保存文件
        
        Args:
            project_id: 项目ID
            file_name: 文件名
            content: 文件内容
        
        Returns:
            (file_path, hash_sha256, file_size)
        """
        # 生成文件路径
        full_path, relative_path = self._generate_file_path(project_id, file_name)
        
        # 计算 SHA-256 哈希
        hash_sha256 = hashlib.sha256(content).hexdigest()
        
        # 异步写入文件
        async with aiofiles.open(full_path, 'wb') as f:
            await f.write(content)
        
        file_size = len(content)
        
        logger.info(f"Saved file: {relative_path} ({file_size} bytes, hash={hash_sha256[:8]}...)")
        
        return relative_path, hash_sha256, file_size
    
    async def read_file(self, file_path: str) -> Optional[bytes]:
        """
        读取文件
        
        Args:
            file_path: 相对路径
        
        Returns:
            文件内容，如果文件不存在则返回 None
        """
        full_path = self.base_path / file_path
        
        if not full_path.exists():
            logger.warning(f"File not found: {file_path}")
            return None
        
        async with aiofiles.open(full_path, 'rb') as f:
            content = await f.read()
        
        return content
    
    async def delete_file(self, file_path: str) -> bool:
        """
        删除文件
        
        Args:
            file_path: 相对路径
        
        Returns:
            是否删除成功
        """
        full_path = self.base_path / file_path
        
        if not full_path.exists():
            logger.warning(f"File not found for deletion: {file_path}")
            return False
        
        try:
            full_path.unlink()
            logger.info(f"Deleted file: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete file {file_path}: {e}")
            return False
    
    def get_file_size(self, file_path: str) -> Optional[int]:
        """获取文件大小"""
        full_path = self.base_path / file_path
        
        if not full_path.exists():
            return None
        
        return full_path.stat().st_size


# 全局单例
file_storage = FileStorageService()
