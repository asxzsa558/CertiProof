"""
Small rule engine for 等保 document self-checks.

The standards library decides what must be checked. This engine only finds
evidence and scores coverage; it deliberately does not let an LLM invent the
final compliance result.
"""

from __future__ import annotations

import re
import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONTROL_FILE = Path(__file__).resolve().parents[3] / "reference" / "compliance" / "document_controls.yaml"
logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def load_document_controls() -> dict[str, Any]:
    with CONTROL_FILE.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


class DocumentControlEngine:
    def __init__(self, library: dict[str, Any] | None = None):
        self.library = library or load_document_controls()
        self.documents = self.library.get("documents", {})

    def analyze(self, text: str, file_name: str = "", expected_doc_name: str | None = None) -> dict[str, Any]:
        text = text or ""
        if not text.strip():
            return {
                "type": "document_control_analysis",
                "status": "unable",
                "file_name": file_name,
                "expected_document": expected_doc_name,
                "message": "未提取到可分析的文档正文。",
                "coverage": 0,
                "confidence": 0,
                "controls": [],
                "gaps": [],
            }

        chunks = [
            {
                "block_id": f"text-{index}",
                "text": chunk,
                "file_name": file_name,
                "source": "native",
                "confidence": 1.0,
            }
            for index, chunk in enumerate(self.chunk(text))
        ]
        return self._analyze_chunks(chunks, expected_doc_name, file_name)

    def analyze_blocks(self, blocks: list[dict[str, Any]], expected_doc_name: str) -> dict[str, Any]:
        chunks = [block for block in blocks if str(block.get("text") or "").strip()]
        if not chunks:
            return {
                "type": "document_control_analysis",
                "status": "unable",
                "expected_document": expected_doc_name,
                "message": "未提取到可分析的文档内容。",
                "coverage": 0,
                "confidence": 0,
                "controls": [],
                "gaps": [],
            }
        return self._analyze_chunks(chunks, expected_doc_name)

    def _analyze_chunks(
        self,
        chunks: list[dict[str, Any]],
        expected_doc_name: str | None,
        file_name: str = "",
    ) -> dict[str, Any]:
        matched = next(
            ((key, doc) for key, doc in self.documents.items() if doc.get("name") == expected_doc_name),
            None,
        )
        doc_key, doc_def = matched or (None, None)
        if not doc_def:
            return {
                "type": "document_control_analysis",
                "status": "unable",
                "file_name": file_name,
                "expected_document": expected_doc_name,
                "message": "当前任务未配置文档检查标准。",
                "coverage": 0,
                "confidence": 0,
                "controls": [],
                "gaps": [],
            }

        controls = [self._check_control(control, chunks) for control in doc_def.get("controls", [])]
        total_points = sum(c["total_points"] for c in controls)
        passed_points = sum(c["passed_points"] for c in controls)
        partial_points = sum(c["partial_points"] for c in controls)
        coverage = round((passed_points + partial_points * 0.5) / total_points, 2) if total_points else 0

        if coverage >= 0.85:
            status = "pass"
        elif coverage >= 0.45:
            status = "partial"
        else:
            status = "fail"

        gaps = [
            point["missing_judgement"]
            for control in controls
            for point in control["points"]
            if point["status"] == "fail"
        ]

        return {
            "type": "document_control_analysis",
            "status": status,
            "file_name": file_name,
            "document_key": doc_key,
            "document_name": doc_def.get("name"),
            "expected_document": expected_doc_name,
            "coverage": coverage,
            "confidence": round(0.6 + coverage * 0.4, 2),
            "total_controls": len(controls),
            "total_points": total_points,
            "passed_points": passed_points,
            "partial_points": partial_points,
            "failed_points": total_points - passed_points - partial_points,
            "controls": controls,
            "gaps": gaps,
        }

    async def review_with_llm(self, db, user_id: int, analysis: dict[str, Any]) -> dict[str, Any]:
        points = [
            (control, point)
            for control in analysis.get("controls", [])
            for point in control.get("points", [])
            if point.get("evidence")
        ][:12]
        if not points:
            analysis["evidence_engine"] = "rule"
            return analysis

        payload = [
            {
                "control_id": control.get("id"),
                "point_id": point.get("id"),
                "requirement": point.get("text"),
                "evidence": [e.get("text", "") for e in point.get("evidence", [])[:2]],
            }
            for control, point in points
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是等保文档证据复核器。只判断证据是否支持必检点，不直接给合规结论。"
                    "返回严格 JSON 数组，每项包含 control_id, point_id, "
                    "decision(pass|partial|fail|contradict), reason。contradict 表示证据明确违反要求。"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

        try:
            from app.services.llm_service import llm_service

            response = await llm_service.chat_with_fallback(
                db=db,
                user_id=user_id,
                messages=messages,
                task_type="document_evidence_review",
                timeout=45,
                temperature=0,
                max_tokens=1200,
            )
            decisions = self._parse_llm_json(response.get("content", ""))
        except Exception as exc:
            logger.info("document evidence LLM review skipped: %s", exc)
            analysis["evidence_engine"] = "rule"
            analysis["llm_review_error"] = str(exc)
            return analysis

        decision_map = {
            (item.get("control_id"), item.get("point_id")): item
            for item in decisions
            if item.get("decision") in {"pass", "partial", "fail", "contradict"}
        }
        for control in analysis.get("controls", []):
            for point in control.get("points", []):
                decision = decision_map.get((control.get("id"), point.get("id")))
                if decision:
                    point["status"] = "fail" if decision["decision"] == "contradict" else decision["decision"]
                    point["contradiction"] = decision["decision"] == "contradict"
                    point["llm_reason"] = decision.get("reason")

        self._recompute_analysis(analysis)
        analysis["evidence_engine"] = "hybrid"
        return analysis

    def chunk(self, text: str) -> list[str]:
        normalized = re.sub(r"\r\n?", "\n", text or "")
        parts = [p.strip() for p in re.split(r"\n\s*\n|(?=\n[一二三四五六七八九十]+[、.])|(?=\n\d+[.、])", normalized) if p.strip()]
        if not parts and normalized.strip():
            parts = [normalized.strip()]

        chunks = []
        for part in parts:
            if len(part) <= 800:
                chunks.append(part)
                continue
            for i in range(0, len(part), 700):
                chunks.append(part[i:i + 800])
        return chunks[:200]

    def _check_control(self, control: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
        points = [self._check_point(point, chunks) for point in control.get("required_points", [])]
        passed = sum(1 for p in points if p["status"] == "pass")
        partial = sum(1 for p in points if p["status"] == "partial")
        total = len(points)
        status = "pass" if passed == total else ("fail" if passed == 0 and partial == 0 else "partial")
        return {
            "id": control.get("id"),
            "title": control.get("title"),
            "status": status,
            "total_points": total,
            "passed_points": passed,
            "partial_points": partial,
            "points": points,
        }

    def _parse_llm_json(self, content: str) -> list[dict[str, Any]]:
        content = content.strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.S)
        match = re.search(r"\[.*\]", content, flags=re.S)
        return json.loads(match.group(0) if match else content)

    def _recompute_analysis(self, analysis: dict[str, Any]) -> None:
        total_points = 0
        passed_points = 0
        partial_points = 0
        gaps = []
        for control in analysis.get("controls", []):
            points = control.get("points", [])
            total = len(points)
            passed = sum(1 for p in points if p.get("status") == "pass")
            partial = sum(1 for p in points if p.get("status") == "partial")
            control["total_points"] = total
            control["passed_points"] = passed
            control["partial_points"] = partial
            control["status"] = "pass" if passed == total else ("fail" if passed == 0 and partial == 0 else "partial")
            total_points += total
            passed_points += passed
            partial_points += partial
            gaps.extend(p.get("missing_judgement", "未发现对应证据。") for p in points if p.get("status") == "fail")

        coverage = round((passed_points + partial_points * 0.5) / total_points, 2) if total_points else 0
        analysis["coverage"] = coverage
        analysis["status"] = "pass" if coverage >= 0.85 else ("partial" if coverage >= 0.45 else "fail")
        analysis["total_points"] = total_points
        analysis["passed_points"] = passed_points
        analysis["partial_points"] = partial_points
        analysis["failed_points"] = total_points - passed_points - partial_points
        analysis["gaps"] = gaps

    def _check_point(self, point: dict[str, Any], chunks: list[dict[str, Any]]) -> dict[str, Any]:
        keywords = point.get("evidence_keywords", [])
        evidence = []
        for chunk in chunks:
            text = str(chunk.get("text") or "")
            lowered = text.lower()
            matched = [
                kw for kw in keywords
                if kw.lower() in lowered
                or (
                    len(kw) >= 4
                    and kw[:2].lower() in lowered
                    and kw[-2:].lower() in lowered
                )
            ]
            if matched:
                evidence.append({
                    "matched_keywords": matched,
                    "text": self._trim_evidence(text, matched),
                    "block_id": chunk.get("block_id"),
                    "evidence_id": chunk.get("evidence_id"),
                    "file_name": chunk.get("file_name"),
                    "page": chunk.get("page"),
                    "section": chunk.get("section"),
                    "type": chunk.get("type"),
                    "source": chunk.get("source"),
                    "confidence": chunk.get("confidence"),
                    "bbox": chunk.get("bbox"),
                })
            if len(evidence) >= 3:
                break

        hit_count = len({kw for item in evidence for kw in item["matched_keywords"]})
        status = "pass" if hit_count >= 2 or (len(keywords) == 1 and hit_count == 1) else ("partial" if hit_count == 1 else "fail")
        return {
            "id": point.get("id"),
            "text": point.get("text"),
            "status": status,
            "evidence": evidence,
            "basis": point.get("basis") or self.library.get("basis", []),
            "required_evidence": point.get("required_evidence") or keywords,
            "severity": point.get("severity", "medium"),
            "remediation": point.get("remediation") or point.get("missing_judgement", "补充对应制度内容和可审计证据。"),
            "missing_judgement": point.get("missing_judgement", "未发现对应证据。"),
        }

    def _trim_evidence(self, chunk: str, keywords: list[str]) -> str:
        first = min((chunk.find(kw) for kw in keywords if kw in chunk), default=0)
        start = max(0, first - 80)
        end = min(len(chunk), first + 220)
        return chunk[start:end].strip()
