"""Small encrypted envelope for short-lived worker credentials."""

import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings


def _fernet() -> Fernet:
    if not settings.SECRET_KEY:
        raise ValueError("服务端未配置 SECRET_KEY，无法安全排队凭证任务")
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_json(value: dict) -> str:
    return _fernet().encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()


def decrypt_json(value: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(value.encode()).decode())
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("任务凭证已失效或无法解密，请重新发起检测") from exc
