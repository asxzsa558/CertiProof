"""
MCP Client - CertiProof
Client for calling MCP tool servers (nmap, nuclei, ocr).
"""

import httpx
from typing import Optional, Dict, Any
from app.core.config import settings


class MCPClient:
    """Client for communicating with MCP tool servers."""

    def __init__(self):
        self.timeout = 600.0  # 10 minutes default timeout

    async def call_nmap(
        self,
        target: str,
        port_range: str = "1-1000",
        scan_type: str = "syn",
        service_detection: bool = True,
        os_detection: bool = False,
    ) -> Dict[str, Any]:
        """Call nmap MCP server to scan target."""
        url = f"http://{settings.MCP_SERVER_HOST}:{settings.MCP_SERVER_PORT}/scan/analyze"
        payload = {
            "target": target,
            "port_range": port_range,
            "scan_type": scan_type,
            "service_detection": service_detection,
            "os_detection": os_detection,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def call_nuclei(
        self,
        target: str,
        templates: Optional[str] = None,
        severity: Optional[str] = None,
        rate_limit: int = 150,
    ) -> Dict[str, Any]:
        """Call nuclei MCP server to scan target."""
        url = f"http://{settings.MCP_SERVER_HOST}:8002/scan/analyze"
        payload = {
            "target": target,
            "templates": templates,
            "severity": severity,
            "rate_limit": rate_limit,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()

    async def call_ocr_analyze(
        self,
        image_base64: str,
        check_type: str,
        clause_id: Optional[str] = None,
        additional_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Call OCR MCP server to analyze screenshot."""
        url = f"http://{settings.MCP_SERVER_HOST}:8003/analyze"
        payload = {
            "image_base64": image_base64,
            "check_type": check_type,
            "clause_id": clause_id,
            "additional_context": additional_context,
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            return response.json()


# Singleton instance
mcp_client = MCPClient()
