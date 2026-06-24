"""
Nuclei MCP Server - VeriSure
Exposes nuclei vulnerability scanning as an MCP tool.
Uses standardized /execute endpoint for gateway integration.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import time

app = FastAPI(title="Nuclei MCP Server", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ExecuteRequest(BaseModel):
    """Standardized execute request"""
    tool: str
    params: Dict[str, Any]


def parse_nuclei_jsonl(jsonl_output: str, target: str) -> Dict[str, Any]:
    """Parse nuclei JSONL output into structured result."""
    findings = []
    critical_count = 0
    high_count = 0
    medium_count = 0
    low_count = 0
    info_count = 0

    for line in jsonl_output.strip().split("\n"):
        if not line.strip():
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue

        # Nuclei outputs different event types
        if data.get("type") != "template":
            continue

        severity = data.get("info", {}).get("severity", "info").lower()
        finding = {
            "template_id": data.get("template-id", data.get("templateID", "unknown")),
            "name": data.get("info", {}).get("name", "Unknown"),
            "severity": severity,
            "type": data.get("type", "unknown"),
            "host": data.get("host", target),
            "matched_at": data.get("matched-at"),
            "description": data.get("info", {}).get("description"),
            "reference": data.get("info", {}).get("reference"),
            "curl_command": data.get("curl-command"),
            "extracted_results": data.get("extracted-results"),
            "timestamp": data.get("timestamp", datetime.utcnow().isoformat()),
        }
        findings.append(finding)

        if severity == "critical":
            critical_count += 1
        elif severity == "high":
            high_count += 1
        elif severity == "medium":
            medium_count += 1
        elif severity == "low":
            low_count += 1
        else:
            info_count += 1

    return {
        "target": target,
        "findings": findings,
        "total_findings": len(findings),
        "critical_count": critical_count,
        "high_count": high_count,
        "medium_count": medium_count,
        "low_count": low_count,
        "info_count": info_count,
    }


async def nuclei_scan(params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute nuclei scan against target."""
    target = params.get("target")
    if not target:
        raise ValueError("Missing required parameter: target")

    templates = params.get("templates")
    severity = params.get("severity")
    rate_limit = params.get("rate_limit", 150)
    timeout = params.get("timeout", 600)

    # Build nuclei command
    cmd = ["nuclei", "-target", target, "-jsonl", "-silent"]

    # Templates
    if templates:
        cmd.extend(["-tags", templates])

    # Severity filter
    if severity:
        cmd.extend(["-severity", severity])

    # Rate limit
    if rate_limit:
        cmd.extend(["-rate-limit", str(rate_limit)])

    # Timeout
    cmd.extend(["-timeout", str(min(timeout, 30))])
    cmd.extend(["-retries", "2"])

    start_time = time.time()

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=timeout + 60,
        )

        output = stdout.decode("utf-8", errors="replace")
        parsed = parse_nuclei_jsonl(output, target)

        duration_ms = int((time.time() - start_time) * 1000)

        # Return standardized format
        return {
            "tool": "nuclei_scan",
            "version": "1.0",
            "status": "success",
            "data": parsed,
            "metadata": {
                "duration_ms": duration_ms,
                "scan_time": datetime.utcnow().isoformat(),
            },
        }

    except asyncio.TimeoutError:
        raise ValueError(f"nuclei scan timeout after {timeout}s")
    except FileNotFoundError:
        raise ValueError("nuclei is not installed")
    except Exception as e:
        raise ValueError(f"nuclei scan error: {e}")


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": "Nuclei MCP Server",
        "version": "1.0.0",
        "tools": ["nuclei_scan", "vuln_scan"],
    }


@app.get("/health")
async def health():
    """Health check"""
    # Check if nuclei is available
    try:
        proc = await asyncio.create_subprocess_exec(
            "nuclei", "-version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        nuclei_available = True
    except:
        nuclei_available = False

    return {
        "status": "healthy" if nuclei_available else "degraded",
        "tools": ["nuclei_scan", "vuln_scan"],
        "nuclei_available": nuclei_available,
    }


@app.post("/execute")
async def execute(request: ExecuteRequest):
    """Execute tool - standardized endpoint for gateway"""
    tool_name = request.tool
    params = request.params

    if tool_name in ["nuclei_scan", "vuln_scan"]:
        return await nuclei_scan(params)

    raise HTTPException(
        status_code=404,
        detail=f"Unknown tool: {tool_name}"
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8003)
