"""
Tech Domain Skill - CertiProof
Orchestrates nmap, nuclei, and ocr tools for technical compliance checking.
"""

import logging
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.agent.mcp_client import mcp_client

logger = logging.getLogger(__name__)


class TechDomainSkill:
    """
    Technical domain compliance checking skill.
    Executes nmap port scan, nuclei vulnerability scan, and orchestrates results
    into compliance findings.
    """

    def __init__(self):
        self.mcp_client = mcp_client

    async def execute(
        self,
        target: str,
        asset_type: str = "ip",
        compliance_level: str = "三级",
        check_items: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Execute technical domain compliance check.

        Args:
            target: Target IP or domain
            asset_type: Type of asset (ip, domain, cloud_resource)
            compliance_level: Compliance level (二级, 三级)
            check_items: Specific items to check (None = all)

        Returns:
            Dict with scan results and compliance findings
        """
        results = {
            "target": target,
            "asset_type": asset_type,
            "compliance_level": compliance_level,
            "scan_time": datetime.utcnow().isoformat(),
            "findings": [],
            "summary": {
                "total_findings": 0,
                "critical": 0,
                "high": 0,
                "medium": 0,
                "low": 0,
            },
            "errors": [],
        }

        # Default check items
        if check_items is None:
            check_items = ["port_scan", "vuln_scan"]

        # Execute port scan
        if "port_scan" in check_items:
            try:
                nmap_result = await self._run_port_scan(target)
                results["nmap_result"] = nmap_result
                results["findings"].extend(nmap_result.get("findings", []))
            except Exception as e:
                logger.error(f"Port scan failed for {target}: {e}")
                results["errors"].append({"tool": "nmap", "error": str(e)})

        # Execute vulnerability scan
        if "vuln_scan" in check_items:
            try:
                nuclei_result = await self._run_vuln_scan(target)
                results["nuclei_result"] = nuclei_result
                results["findings"].extend(nuclei_result.get("findings", []))
            except Exception as e:
                logger.error(f"Vulnerability scan failed for {target}: {e}")
                results["errors"].append({"tool": "nuclei", "error": str(e)})

        # Calculate summary
        for finding in results["findings"]:
            severity = finding.get("severity", "info")
            if severity in results["summary"]:
                results["summary"][severity] += 1
        results["summary"]["total_findings"] = len(results["findings"])

        return results

    async def _run_port_scan(self, target: str) -> Dict[str, Any]:
        """Run nmap port scan with compliance analysis."""
        logger.info(f"Running port scan on {target}")
        result = await self.mcp_client.call_nmap(
            target=target,
            port_range="1-1000",
            scan_type="syn",
            service_detection=True,
            os_detection=False,
        )
        return result

    async def _run_vuln_scan(self, target: str) -> Dict[str, Any]:
        """Run nuclei vulnerability scan with compliance analysis."""
        logger.info(f"Running vulnerability scan on {target}")
        result = await self.mcp_client.call_nuclei(
            target=target,
            templates="cve,misconfig,exposure",
            severity="critical,high,medium",
            rate_limit=100,
        )
        return result

    async def analyze_screenshot(
        self,
        image_base64: str,
        check_type: str,
        clause_id: Optional[str] = None,
        additional_context: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Analyze screenshot for compliance checking."""
        logger.info(f"Analyzing screenshot: type={check_type}, clause={clause_id}")
        result = await self.mcp_client.call_ocr_analyze(
            image_base64=image_base64,
            check_type=check_type,
            clause_id=clause_id,
            additional_context=additional_context,
        )

        # Convert to finding format
        if result.get("judgment") in ("fail", "partial"):
            finding = {
                "clause_id": clause_id or "unknown",
                "clause_name": check_type,
                "severity": "high" if result.get("judgment") == "fail" else "medium",
                "judgment": result.get("judgment"),
                "description": result.get("description", ""),
                "remediation": result.get("remediation"),
                "evidence": {
                    "tool": "ocr",
                    "check_type": check_type,
                    "extracted_info": result.get("extracted_info", []),
                },
            }
            result["finding"] = finding

        return result


# Singleton instance
tech_domain_skill = TechDomainSkill()
