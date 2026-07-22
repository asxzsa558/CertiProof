"""One validation boundary for every network-capable execution step."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.asset_scope import list_scannable_assets, require_scannable_target


NETWORK_CAPABILITIES = {
    "scan_ports", "masscan_scan", "fping_scan", "nikto_scan", "sqlmap_scan",
    "gobuster_scan", "ffuf_scan", "web_discovery_scan", "snmp_walk",
    "snmp_bruteforce", "snmp_get", "network_device_scan", "enum4linux_scan",
    "crackmapexec_scan", "smb_enum", "windows_security_scan", "redis_check",
    "oracle_check", "mongodb_check", "memcached_check", "mysql_check",
    "database_security_scan", "scan_ssl", "scan_vulnerabilities",
    "scan_weak_passwords", "full_compliance_scan", "tech_assessment",
    "baseline_check", "password_policy_check", "ssh_config_check", "audit_config_check",
    "service_port_check", "file_permission_check", "mac_check", "ping_asset",
    "crypto_transport_scan", "crypto_certificate_check", "crypto_onsite_assessment",
}

_PORT_RANGE = re.compile(r"^\d{1,5}(?:-\d{1,5})?(?:,\d{1,5}(?:-\d{1,5})?)*$")
_SAFE_EXTENSION_LIST = re.compile(r"^[A-Za-z0-9,._-]{1,120}$")
_SAFE_METHOD = {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"}
_SAFE_SERVICES = {"ssh", "ftp", "rdp", "smb", "http", "https", "mysql", "redis", "telnet", "postgresql", "oracle"}
_PROJECT_ASSET_PLACEHOLDERS = {"项目资产", "全部项目资产", "所有项目资产", "项目中的资产"}
_NETWORK_PLACEHOLDERS = {"项目资产网段", "项目网段", "资产网段"}


def _clean_text(value: object, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} 必须是字符串")
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{label} 不能为空")
    if any(char in cleaned for char in ("\x00", "\r", "\n", "`", ";", "|", "<", ">")):
        raise ValueError(f"{label} 包含不允许的控制字符")
    return cleaned


def _validate_url(value: object) -> str:
    url = _clean_text(value, "URL")
    if not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("URL 必须是无账号密码的 HTTP/HTTPS 地址")
    try:
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("URL 端口必须在 1-65535 范围内")
    except ValueError as exc:
        raise ValueError("URL 端口无效") from exc
    return url


def _validate_port(value: object, label: str = "端口") -> int:
    try:
        port = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} 必须是 1-65535 的整数") from exc
    if not 1 <= port <= 65535:
        raise ValueError(f"{label} 必须在 1-65535 范围内")
    return port


def _validate_port_range(value: object) -> str:
    text = _clean_text(value, "端口范围").lower()
    if text in {"high-risk", "high_risk", "full", "all", "1-65535"}:
        return "1-65535" if text in {"full", "all"} else text
    if not _PORT_RANGE.fullmatch(text):
        raise ValueError("端口范围仅支持 high-risk、1-65535、单端口、区间或逗号分隔端口")
    for part in text.split(","):
        start_end = [int(item) for item in part.split("-")]
        if any(port < 1 or port > 65535 for port in start_end) or len(start_end) == 2 and start_end[0] > start_end[1]:
            raise ValueError("端口范围必须在 1-65535 内且起止顺序正确")
    return text


def _validate_limited_int(parameters: dict, key: str, minimum: int, maximum: int) -> None:
    if key not in parameters:
        return
    try:
        value = int(parameters[key])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} 必须是整数") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{key} 必须在 {minimum}-{maximum} 范围内")
    parameters[key] = value


async def validate_execution_parameters(
    capability_name: str,
    parameters: dict,
    *,
    project_id: int | None,
    db: AsyncSession | None,
) -> dict:
    """Return validated copies of parameters before a tool can be invoked."""
    if not isinstance(parameters, dict):
        raise ValueError("工具参数必须是对象")
    params = dict(parameters)

    if "target" in params:
        target = _clean_text(params["target"], "目标地址")
        params["target"] = _validate_url(target) if "://" in target else target
    if "url" in params:
        params["url"] = _validate_url(params["url"])
    if "targets" in params:
        if not isinstance(params["targets"], list) or not params["targets"] or len(params["targets"]) > 256:
            raise ValueError("targets 必须是 1-256 个目标组成的数组")
        params["targets"] = [_clean_text(value, "目标地址") for value in params["targets"]]
    if "network" in params:
        params["network"] = _clean_text(params["network"], "网络目标")
    if "port" in params:
        params["port"] = _validate_port(params["port"])
    if "ssh_port" in params:
        params["ssh_port"] = _validate_port(params["ssh_port"], "SSH 端口")
    if "port_range" in params:
        params["port_range"] = _validate_port_range(params["port_range"])
    for key, minimum, maximum in (("rate", 1, 10000), ("threads", 1, 64), ("timeout", 1, 3600), ("level", 1, 5), ("risk", 1, 3), ("count", 1, 10)):
        _validate_limited_int(params, key, minimum, maximum)
    if "method" in params:
        method = _clean_text(params["method"], "HTTP 方法").upper()
        if method not in _SAFE_METHOD:
            raise ValueError("HTTP 方法不受支持")
        params["method"] = method
    if "service" in params:
        service = _clean_text(params["service"], "服务类型").lower()
        if service not in _SAFE_SERVICES:
            raise ValueError("服务类型不受支持")
        params["service"] = service
    if "extensions" in params and not _SAFE_EXTENSION_LIST.fullmatch(_clean_text(params["extensions"], "扩展名")):
        raise ValueError("扩展名格式无效")
    if "key_file" in params:
        key_file = _clean_text(params["key_file"], "密钥文件")
        if not key_file.startswith("/app/uploads/") or ".." in key_file:
            raise ValueError("密钥文件必须来自已上传文件")
        params["key_file"] = key_file
    if "ssh_key_file" in params:
        key_file = _clean_text(params["ssh_key_file"], "SSH 密钥文件")
        if not key_file.startswith("/app/uploads/") or ".." in key_file:
            raise ValueError("SSH 密钥文件必须来自已上传文件")
        params["ssh_key_file"] = key_file

    if capability_name not in NETWORK_CAPABILITIES or not project_id or db is None:
        return params

    targets = []
    if params.get("target") and params["target"] not in _PROJECT_ASSET_PLACEHOLDERS:
        targets.append(params["target"])
    if params.get("url"):
        targets.append(params["url"])
    targets.extend(params.get("targets") or [])
    for target in targets:
        await require_scannable_target(db, project_id, target)

    network = params.get("network")
    if network and network not in _NETWORK_PLACEHOLDERS:
        assets = await list_scannable_assets(db, project_id)
        if not any(str(asset.value).strip().lower() == network.lower() for asset in assets):
            raise ValueError("网络目标必须是当前项目的启用资产")
    return params
