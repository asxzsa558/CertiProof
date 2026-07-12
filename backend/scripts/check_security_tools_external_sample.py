"""Limited public-asset regression sample for an authorized CertiProof project asset."""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.mcp.gateway_client import MCPGatewayClient


TARGET = os.getenv("EXTERNAL_ASSET", "121.40.95.31")


def _validate(tool: str, result: dict) -> dict:
    data = result.get("data")
    assert isinstance(data, dict), (tool, result)
    assert isinstance(result.get("metadata"), dict), (tool, result)
    if data.get("scan_completed") is False:
        assert data.get("tool_error") or result.get("error") or result["metadata"].get("error"), (tool, result)
    return data


async def _run() -> None:
    client = MCPGatewayClient()
    port_result = await client.call("nmap_scan", {
        "target": TARGET,
        "port_range": "high-risk",
        "host_timeout": 60,
    })
    ssl_result = await client.call("testssl_scan", {"target": TARGET, "port": 443, "timeout": 90})
    web_result = await client.call("nikto_scan", {"target": TARGET, "port": 80, "timeout": 120})

    ports = _validate("nmap_scan", port_result)
    ssl = _validate("testssl_scan", ssl_result)
    web = _validate("nikto_scan", web_result)
    payload = {
        "status": "authorized public sample ok",
        "target": TARGET,
        "ports": {
            "host_status": ports.get("host_status"),
            "open_ports": ports.get("open_ports", []),
            "filtered_count": ports.get("filtered_count", 0),
        },
        "ssl": {
            "scan_completed": ssl.get("scan_completed"),
            "tls_version": ssl.get("tls_version"),
            "issues": len(ssl.get("issues", [])),
            "vulnerabilities": len(ssl.get("vulnerabilities", [])),
            "tool_error": ssl.get("tool_error"),
        },
        "web": {
            "scan_completed": web.get("scan_completed"),
            "findings": web.get("total_findings", web.get("finding_count", 0)),
            "tool_error": web.get("tool_error"),
        },
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    output_path = os.getenv("PUBLIC_SAMPLE_OUTPUT")
    if output_path:
        Path(output_path).write_text(serialized, encoding="utf-8")
    print(serialized)


async def main() -> None:
    try:
        await _run()
    except Exception as exc:
        output_path = os.getenv("PUBLIC_SAMPLE_OUTPUT")
        if output_path:
            Path(output_path).write_text(json.dumps({
                "status": "authorized public sample failed",
                "target": TARGET,
                "error": str(exc),
                "error_type": type(exc).__name__,
            }, ensure_ascii=False), encoding="utf-8")
        raise


if __name__ == "__main__":
    asyncio.run(main())
