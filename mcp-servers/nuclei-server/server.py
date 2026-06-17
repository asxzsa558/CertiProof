"""
Nuclei MCP Server - CertiProof
Exposes nuclei vulnerability scanning as an MCP tool.
"""

import asyncio
import json
from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, Field
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Nuclei MCP Server", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Models ---

class NucleiScanRequest(BaseModel):
    target: str = Field(..., description="Target URL or IP")
    templates: Optional[str] = Field(None, description="Template tags to use (e.g. 'cve,misconfig')")
    severity: Optional[str] = Field(None, description="Filter by severity: critical,high,medium,low,info")
    rate_limit: Optional[int] = Field(150, description="Requests per second")
    timeout: Optional[int] = Field(600, description="Timeout in seconds")


class VulnFinding(BaseModel):
    template_id: str
    name: str
    severity: str
    type: str  # vulnerability type
    host: str
    matched_at: Optional[str] = None
    description: Optional[str] = None
    reference: Optional[List[str]] = None
    curl_command: Optional[str] = None
    extracted_results: Optional[List[str]] = None
    timestamp: str = ""


class NucleiScanResult(BaseModel):
    target: str
    scan_time: str
    findings: List[VulnFinding] = []
    total_findings: int = 0
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    info_count: int = 0
    error: Optional[str] = None


# Severity mapping for compliance
SEVERITY_TO_COMPLIANCE = {
    "critical": ("critical", "8.1.3.3", "入侵防范"),
    "high": ("high", "8.1.3.3", "入侵防范"),
    "medium": ("medium", "8.1.4.4", "入侵防范"),
    "low": ("low", "8.1.4.4", "入侵防范"),
    "info": ("info", None, None),
}


def parse_nuclei_jsonl(jsonl_output: str, target: str) -> NucleiScanResult:
    """Parse nuclei JSONL output into structured result."""
    result = NucleiScanResult(
        target=target,
        scan_time=datetime.utcnow().isoformat(),
    )

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
        finding = VulnFinding(
            template_id=data.get("template-id", data.get("templateID", "unknown")),
            name=data.get("info", {}).get("name", "Unknown"),
            severity=severity,
            type=data.get("type", "unknown"),
            host=data.get("host", target),
            matched_at=data.get("matched-at"),
            description=data.get("info", {}).get("description"),
            reference=data.get("info", {}).get("reference"),
            curl_command=data.get("curl-command"),
            extracted_results=data.get("extracted-results"),
            timestamp=data.get("timestamp", datetime.utcnow().isoformat()),
        )
        result.findings.append(finding)

        if severity == "critical":
            result.critical_count += 1
        elif severity == "high":
            result.high_count += 1
        elif severity == "medium":
            result.medium_count += 1
        elif severity == "low":
            result.low_count += 1
        else:
            result.info_count += 1

    result.total_findings = len(result.findings)
    return result


def generate_compliance_findings(scan_result: NucleiScanResult) -> list:
    """Generate compliance findings from nuclei scan results."""
    findings = []

    # Group by severity
    critical_vulns = [f for f in scan_result.findings if f.severity == "critical"]
    high_vulns = [f for f in scan_result.findings if f.severity == "high"]

    if critical_vulns:
        vuln_names = ", ".join([f.name for f in critical_vulns[:5]])
        if len(critical_vulns) > 5:
            vuln_names += f" 等共{len(critical_vulns)}个"
        findings.append({
            "clause_id": "8.1.3.3",
            "clause_name": "入侵防范",
            "severity": "critical",
            "judgment": "fail",
            "description": f"发现{len(critical_vulns)}个严重漏洞: {vuln_names}。存在被入侵的高风险。",
            "remediation": "立即修复严重漏洞，升级相关组件到最新版本。",
            "evidence": {
                "tool": "nuclei",
                "target": scan_result.target,
                "vulns": [{"name": f.name, "template": f.template_id, "matched_at": f.matched_at} for f in critical_vulns],
            },
        })

    if high_vulns:
        vuln_names = ", ".join([f.name for f in high_vulns[:5]])
        if len(high_vulns) > 5:
            vuln_names += f" 等共{len(high_vulns)}个"
        findings.append({
            "clause_id": "8.1.3.3",
            "clause_name": "入侵防范",
            "severity": "high",
            "judgment": "fail",
            "description": f"发现{len(high_vulns)}个高危漏洞: {vuln_names}。",
            "remediation": "尽快修复高危漏洞，制定修复计划。",
            "evidence": {
                "tool": "nuclei",
                "target": scan_result.target,
                "vulns": [{"name": f.name, "template": f.template_id, "matched_at": f.matched_at} for f in high_vulns],
            },
        })

    return findings


# --- API ---

@app.get("/")
async def root():
    return {"name": "Nuclei MCP Server", "version": "0.1.0", "status": "running"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/scan", response_model=NucleiScanResult)
async def scan(request: NucleiScanRequest):
    """Execute nuclei scan against target."""
    target = request.target.strip()

    if not target:
        raise HTTPException(status_code=400, detail="Target is required")

    # Build nuclei command
    cmd = ["nuclei", "-target", target, "-jsonl", "-silent"]

    # Templates
    if request.templates:
        cmd.extend(["-tags", request.templates])

    # Severity filter
    if request.severity:
        cmd.extend(["-severity", request.severity])

    # Rate limit
    if request.rate_limit:
        cmd.extend(["-rate-limit", str(request.rate_limit)])

    # Timeout
    cmd.extend(["-timeout", str(min(request.timeout, 30))])
    cmd.extend(["-retries", "2"])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(),
            timeout=request.timeout + 60,
        )

        output = stdout.decode("utf-8", errors="replace")
        result = parse_nuclei_jsonl(output, target)

        if proc.returncode != 0 and not result.findings:
            error_msg = stderr.decode("utf-8", errors="replace")
            if error_msg:
                result.error = error_msg[:500]

        return result

    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail=f"nuclei scan timed out after {request.timeout}s")
    except FileNotFoundError:
        raise HTTPException(
            status_code=500,
            detail="nuclei is not installed. Install from: https://github.com/projectdiscovery/nuclei",
        )


@app.post("/scan/analyze")
async def scan_and_analyze(request: NucleiScanRequest):
    """Execute nuclei scan and return compliance analysis."""
    scan_result = await scan(request)
    findings = generate_compliance_findings(scan_result)

    return {
        "scan_result": scan_result.model_dump(),
        "findings": findings,
        "summary": {
            "total_findings": len(findings),
            "critical": len([f for f in findings if f["severity"] == "critical"]),
            "high": len([f for f in findings if f["severity"] == "high"]),
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8002)
