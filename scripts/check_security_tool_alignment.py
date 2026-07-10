"""Static alignment check for frontend/security-tool capability names.

Run from repo root:
    python3 scripts/check_security_tool_alignment.py
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

EXPECTED_CAPABILITIES = {
    "scan_ports",
    "masscan_scan",
    "fping_scan",
    "scan_ssl",
    "scan_vulnerabilities",
    "scan_weak_passwords",
    "baseline_check",
    "ssh_config_check",
    "nikto_scan",
    "sqlmap_scan",
    "gobuster_scan",
    "ffuf_scan",
    "web_discovery_scan",
    "redis_check",
    "mysql_check",
    "mongodb_check",
    "oracle_check",
    "memcached_check",
    "database_security_scan",
    "snmp_walk",
    "snmp_bruteforce",
    "snmp_get",
    "network_device_scan",
    "enum4linux_scan",
    "crackmapexec_scan",
    "smb_enum",
    "windows_security_scan",
    "full_compliance_scan",
    "tech_assessment",
    "ping_asset",
}

INTERNAL_SUBTOOLS = set()

ENGINE_ONLY_CAPABILITIES = {
    "full_compliance_scan",
    "tech_assessment",
    "database_security_scan",
    "web_discovery_scan",
    "network_device_scan",
    "windows_security_scan",
    "baseline_check",
    "ssh_config_check",
}

FRONTEND_ALLOWED_ALIASES = {
    "ping_host": "ping_asset",
}


def read(path: str) -> str:
    return (ROOT / path).read_text()


def registered_capabilities() -> set[str]:
    text = read("backend/app/services/capability_registry.py")
    return set(re.findall(r'name="([^"]+)"', text))


def execution_dispatches() -> set[str]:
    text = read("backend/app/services/execution_engine.py")
    return set(re.findall(r'capability_name == "([^"]+)"', text))


def gateway_tools() -> set[str]:
    text = read("mcp-servers/gateway/server.py")
    routes = set(re.findall(r'^\s*"([^"]+)":\s*"http://', text, flags=re.MULTILINE))
    aliases = set(re.findall(r'^\s*"([^"]+)":\s*"[^"]+",?$', text, flags=re.MULTILINE))
    return routes | aliases


def frontend_capabilities() -> set[str]:
    text = read("frontend/src/components/toolCatalog.js")
    block = re.search(r"TOOL_CATALOG = \[(?P<body>.*?)\n\]", text, flags=re.DOTALL)
    assert block, "TOOL_CATALOG not found"
    return set(re.findall(r"capability:\s*'([^']+)'", block.group("body")))


def main():
    registry = registered_capabilities()
    dispatch = execution_dispatches()
    gateway = gateway_tools()
    frontend = {FRONTEND_ALLOWED_ALIASES.get(c, c) for c in frontend_capabilities()}

    missing_registry = EXPECTED_CAPABILITIES - registry
    missing_dispatch = EXPECTED_CAPABILITIES - dispatch
    missing_gateway = {
        c for c in EXPECTED_CAPABILITIES
        if c not in gateway and c not in ENGINE_ONLY_CAPABILITIES
    }
    missing_frontend = {
        c for c in EXPECTED_CAPABILITIES
        if c not in frontend and c not in INTERNAL_SUBTOOLS and c not in {"ping_asset"}
    }

    assert not missing_registry, f"Not registered: {sorted(missing_registry)}"
    assert not missing_dispatch, f"Not dispatched: {sorted(missing_dispatch)}"
    assert not missing_gateway, f"Not routed by gateway: {sorted(missing_gateway)}"
    assert not missing_frontend, f"Not exposed in frontend commands: {sorted(missing_frontend)}"


if __name__ == "__main__":
    main()
