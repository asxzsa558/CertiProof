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


def encrypt_secret(value: str) -> str:
    if value.startswith("enc:"):
        return value
    return "enc:" + _fernet().encrypt(value.encode()).decode()


def decrypt_secret(value: str | None) -> str:
    if not value:
        return ""
    if not value.startswith("enc:"):
        return value
    try:
        return _fernet().decrypt(value[4:].encode()).decode()
    except InvalidToken as exc:
        raise ValueError("模型密钥无法解密，请管理员重新配置") from exc
