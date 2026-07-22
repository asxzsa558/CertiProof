"""
Small rule engine for 等保 document self-checks.

The standards library decides what must be checked. This engine only finds
evidence and scores coverage; it deliberately does not let an LLM invent the
final compliance result.
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)


DocumentKey = Literal[
    "security_management_policy", "security_org_setup", "personnel_security_policy",
    "secure_construction_policy", "security_operations_policy", "incident_response_plan",
    "incident_management_policy", "security_audit_policy", "system_security_plan", "security_strategy",
    "system_crypto_scope", "crypto_application_plan", "crypto_algorithm_protocol_inventory",
    "crypto_management_policy", "key_management_policy", "crypto_product_inventory",
    "crypto_personnel_records", "crypto_operation_records", "crypto_incident_plan",
    "physical_environment_evidence", "network_communication_evidence",
    "device_computing_evidence", "application_data_evidence",
]


class DocumentClassificationContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary_key: Optional[DocumentKey]
    confidence: float = Field(ge=0, le=1)
    reason: str


class EvidenceDecisionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    control_id: str
    point_id: str
    decision: Literal["pass", "partial", "fail", "contradict"]
    confidence: float = Field(ge=0, le=1)
    reason: str


class DocumentEvidenceReviewContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decisions: list[EvidenceDecisionContract]


class DocumentControlEngine:
    def __init__(self, library: dict[str, Any]):
        if not library.get("documents"):
            raise ValueError("DocumentControlEngine requires a non-empty standards library")
        self.library = library
        self.documents = self.library.get("documents", {})
        defaults = self.library.get("requirement_defaults") or {}
        for document in self.documents.values():
            document_basis = document.get("basis") or self.library.get("basis") or []
            for control in document.get("controls") or []:
                inherited = {
                    "basis": control.get("basis") or document_basis,
                    "required_evidence": control.get("required_evidence") or document.get("required_evidence") or defaults.get("required_evidence"),
                    "completeness": control.get("completeness") or document.get("completeness") or defaults.get("completeness"),
                    "negative_conditions": control.get("negative_conditions") or document.get("negative_conditions") or defaults.get("negative_conditions"),
                    "severity": control.get("severity") or document.get("severity") or defaults.get("severity") or "medium",
                    "applicability": control.get("applicability") or document.get("applicability") or defaults.get("applicability"),
                    "automation_boundary": control.get("automation_boundary") or document.get("automation_boundary") or defaults.get("automation_boundary"),
                }
                for point in control.get("required_points") or []:
                    for key, value in inherited.items():
                        if point.get(key) is None and value is not None:
                            point[key] = value

    @classmethod
    async def from_graph(cls, db, assessment_type_code: str = "dengbao"):
        from app.services.knowledge_graph import STANDARD_BUNDLES, knowledge_graph

        library_name, _ = STANDARD_BUNDLES.get(assessment_type_code, STANDARD_BUNDLES["dengbao"])
        return cls(await knowledge_graph.load_standard_library(db, library_name))

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

    async def analyze_retrieved(self, db, run_id: int, expected_doc_name: str) -> dict[str, Any]:
        """Run hybrid exact/vector retrieval, then add graph-adjacent context."""
        from sqlalchemy import select

        from app.models.document_knowledge import DocumentBlock, DocumentFile
        from app.core.config import settings
        from app.services.knowledge_graph import knowledge_graph
        from app.services.llm_service import llm_service

        rows = (await db.execute(
            select(DocumentBlock, DocumentFile)
            .join(DocumentFile, DocumentFile.id == DocumentBlock.document_file_id)
            .where(DocumentBlock.analysis_run_id == run_id, DocumentBlock.is_active.is_(True))
            .order_by(DocumentBlock.document_file_id, DocumentBlock.ordinal)
        )).all()
        chunks = [self._block_payload(block, document) for block, document in rows]
        if not chunks:
            return self.analyze_blocks([], expected_doc_name)

        matched = next(
            ((key, document) for key, document in self.documents.items() if document.get("name") == expected_doc_name),
            None,
        )
        document_key, document = matched or (None, None)
        if not document:
            return self._analyze_chunks(chunks, expected_doc_name)

        controls_source = document.get("controls") or []
        requirements = [point for control in controls_source for point in control.get("required_points") or []]
        semantic_error = None
        query_vectors: dict[str, list[float]] = {}
        try:
            embedded = await llm_service.embed_with_fallback(
                db,
                [self._requirement_query(point) for point in requirements],
                dimensions=settings.DOCUMENT_EMBEDDING_DIMENSION,
                input_type="query",
            )
            query_vectors = {
                point.get("uid") or f"{point.get('id')}:{index}": vector
                for index, (point, vector) in enumerate(zip(requirements, embedded["embeddings"]))
            }
            embedding_model = embedded.get("model")
        except Exception as exc:
            semantic_error = str(exc)
            embedding_model = None

        controls = []
        requirement_index = 0
        for control in controls_source:
            points = []
            for point in control.get("required_points") or []:
                exact = self._exact_candidates(point, chunks)
                vector = query_vectors.get(point.get("uid") or f"{point.get('id')}:{requirement_index}")
                semantic = await self._vector_candidates(db, run_id, vector) if vector is not None else []
                requirement_index += 1
                candidates = self._merge_candidates(exact, semantic)
                seed_ids = [item.get("block_id") for item in candidates[:6] if item.get("block_id")]
                context_ids = await knowledge_graph.expand_block_ids(db, seed_ids, limit=12) if seed_ids else []
                by_id = {chunk.get("block_id"): chunk for chunk in chunks}
                selected_ids = {item.get("block_id") for item in candidates}
                for block_id in context_ids:
                    if block_id in selected_ids or block_id not in by_id:
                        continue
                    context = dict(by_id[block_id])
                    context["retrieval_score"] = 0.001
                    context["retrieval_sources"] = ["graph_context"]
                    candidates.append(context)
                points.append(self._check_point(
                    point,
                    candidates[:10],
                    candidate_mode=True,
                    retrieval_complete=semantic_error is None,
                ))
            passed = sum(1 for point in points if point["status"] == "pass")
            partial = sum(1 for point in points if point["status"] == "partial")
            unable = sum(1 for point in points if point["status"] == "unable")
            controls.append({
                "uid": control.get("uid"),
                "id": control.get("id"),
                "title": control.get("title"),
                "status": "unable" if unable else ("pass" if passed == len(points) else ("fail" if not passed and not partial else "partial")),
                "total_points": len(points),
                "passed_points": passed,
                "partial_points": partial,
                "unable_points": unable,
                "points": points,
            })

        analysis = {
            "type": "document_control_analysis",
            "status": "partial",
            "document_key": document_key,
            "document_name": document.get("name"),
            "expected_document": expected_doc_name,
            "controls": controls,
            "retrieval": {
                "engine": "pgvector+exact+apache-age" if not semantic_error else "exact+apache-age",
                "embedding_model": embedding_model,
                "semantic_available": semantic_error is None,
                "semantic_error": semantic_error,
            },
        }
        self._recompute_analysis(analysis)
        return analysis

    @staticmethod
    def _block_payload(block, document) -> dict[str, Any]:
        return {
            "block_id": block.id,
            "document_file_id": document.id,
            "file_name": document.original_name,
            "page": block.page_number,
            "section": block.section_path[-1] if block.section_path else None,
            "type": block.block_type,
            "bbox": block.bbox,
            "text": block.text,
            "table": block.table_data,
            "source": block.source,
            "confidence": block.source_confidence,
        }

    @staticmethod
    def _requirement_query(point: dict[str, Any]) -> str:
        return "；".join(filter(None, [
            str(point.get("text") or ""),
            str(point.get("completeness") or ""),
            "、".join(point.get("required_evidence") or []),
        ]))

    def _exact_candidates(self, point: dict[str, Any], chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        keywords = [str(value) for value in point.get("evidence_keywords") or [] if value]
        ranked = []
        for chunk in chunks:
            lowered = str(chunk.get("text") or "").lower()
            matched = [keyword for keyword in keywords if keyword.lower() in lowered]
            if not matched:
                continue
            candidate = dict(chunk)
            candidate["matched_keywords"] = matched
            candidate["retrieval_score"] = len(set(matched)) / max(1, len(keywords))
            candidate["retrieval_sources"] = ["exact"]
            ranked.append(candidate)
        return sorted(ranked, key=lambda item: item["retrieval_score"], reverse=True)[:10]

    async def _vector_candidates(self, db, run_id: int, query_vector: list[float]) -> list[dict[str, Any]]:
        if not query_vector or db.bind is None or db.bind.dialect.name != "postgresql":
            return []
        from sqlalchemy import select

        from app.models.document_knowledge import DocumentBlock, DocumentFile

        distance = DocumentBlock.embedding.cosine_distance(query_vector).label("distance")
        rows = (await db.execute(
            select(DocumentBlock, DocumentFile, distance)
            .join(DocumentFile, DocumentFile.id == DocumentBlock.document_file_id)
            .where(
                DocumentBlock.analysis_run_id == run_id,
                DocumentBlock.is_active.is_(True),
                DocumentBlock.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(10)
        )).all()
        result = []
        for block, document, value in rows:
            if value is None or float(value) > 0.48:
                continue
            candidate = self._block_payload(block, document)
            candidate["retrieval_score"] = max(0.0, 1 - float(value))
            candidate["retrieval_sources"] = ["vector"]
            result.append(candidate)
        return result

    @staticmethod
    def _merge_candidates(exact: list[dict[str, Any]], semantic: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: dict[Any, dict[str, Any]] = {}
        scores: dict[Any, float] = {}
        for candidates in (exact, semantic):
            for rank, candidate in enumerate(candidates, start=1):
                block_id = candidate.get("block_id")
                if block_id is None:
                    continue
                if block_id not in merged:
                    merged[block_id] = dict(candidate)
                    merged[block_id]["retrieval_sources"] = list(candidate.get("retrieval_sources") or [])
                else:
                    merged[block_id]["retrieval_sources"] = list(dict.fromkeys([
                        *merged[block_id].get("retrieval_sources", []),
                        *(candidate.get("retrieval_sources") or []),
                    ]))
                    merged[block_id]["matched_keywords"] = list(dict.fromkeys([
                        *merged[block_id].get("matched_keywords", []),
                        *(candidate.get("matched_keywords") or []),
                    ]))
                scores[block_id] = scores.get(block_id, 0) + 1 / (60 + rank)
        for block_id, candidate in merged.items():
            candidate["retrieval_score"] = round(scores[block_id], 6)
        return sorted(merged.values(), key=lambda item: item["retrieval_score"], reverse=True)

    def classify_blocks(self, file_name: str, blocks: list[dict[str, Any]]) -> dict[str, Any]:
        """Classify a document using its name/title, with content only as supporting evidence."""
        file_value = self._normalize_document_name(Path(file_name or "document").stem)
        title_values = [
            self._normalize_document_name(re.split(r"[\r\n]+", str(block.get("text") or ""), maxsplit=1)[0][:160])
            for block in blocks[:12]
            if block.get("type") in {"text", "heading", "header"}
            and block.get("page") in {None, 1}
            and str(block.get("text") or "").strip()
        ][:3]
        full_text = "\n".join(str(block.get("text") or "") for block in blocks).lower()
        candidates = []

        for key, document in self.documents.items():
            aliases = list(dict.fromkeys([document.get("name", ""), *(document.get("aliases") or [])]))
            normalized_aliases = [self._normalize_document_name(alias) for alias in aliases if alias]
            name_score = max((self._name_similarity(file_value, alias) for alias in normalized_aliases), default=0)
            title_score = max((
                self._title_similarity(title_value, alias)
                for title_value in title_values
                for alias in normalized_aliases
            ), default=0)
            keywords = {
                str(keyword).lower()
                for control in document.get("controls", [])
                for point in control.get("required_points", [])
                for keyword in point.get("evidence_keywords", [])
                if keyword
            }
            keyword_hits = sum(1 for keyword in keywords if keyword in full_text)
            content_score = min(keyword_hits / 6, 1.0)
            identity_score = max(name_score, title_score)
            candidates.append({
                "document_key": key,
                "document_name": document.get("name"),
                "name_score": round(name_score, 3),
                "title_score": round(title_score, 3),
                "content_score": round(content_score, 3),
                "score": round(identity_score * 0.85 + content_score * 0.15, 3),
            })

        candidates.sort(
            key=lambda item: (item["score"], item["name_score"], item["title_score"]),
            reverse=True,
        )
        best = candidates[0] if candidates else None
        second = candidates[1] if len(candidates) > 1 else None
        name_match = bool(best and best["name_score"] >= 0.72)
        title_match = bool(best and best["title_score"] >= 0.82 and best["content_score"] > 0)
        ambiguous = bool(
            best and second and best["score"] - second["score"] < 0.06
            and best["name_score"] < 0.98 and best["title_score"] < 0.98
        )
        classified = bool(best and (name_match or title_match) and not ambiguous)
        if classified:
            naming_status = "matched" if name_match else "filename_warning"
            reason = "文件名与标准文档名称相符" if name_match else "文件名不规范，但正文标题和内容可确认文档类型"
        elif ambiguous:
            naming_status = "ambiguous"
            reason = "文件可能对应多个文档类型，无法可靠归类"
        else:
            naming_status = "unclassified"
            reason = "文件名和正文标题均未与标准文档名称形成可靠匹配"
        return {
            "status": "classified" if classified else "unclassified",
            "document_key": best["document_key"] if classified else None,
            "document_name": best["document_name"] if classified else None,
            "confidence": best["score"] if best else 0,
            "naming_status": naming_status,
            "reason": reason,
            "candidates": candidates[:3],
        }

    async def classify_with_llm(
        self,
        db,
        user_id: int,
        file_name: str,
        blocks: list[dict[str, Any]],
        rule_result: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        result = rule_result or self.classify_blocks(file_name, blocks)
        if result.get("status") == "classified" and float(result.get("confidence") or 0) >= 0.88:
            result["classifier"] = "rule"
            return result

        excerpts = [
            {
                "page": block.get("page"),
                "section": block.get("section"),
                "text": str(block.get("text") or "")[:500],
            }
            for block in blocks[:10]
            if str(block.get("text") or "").strip()
        ]
        allowed = [{"key": key, "name": value.get("name"), "aliases": value.get("aliases") or []} for key, value in self.documents.items()]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是文档归类器。只能从 allowed_documents 中选择 primary_key；"
                    "文件名不规范不阻止按正文归类。返回严格 JSON 对象："
                    "{primary_key, confidence, reason}。无法可靠归类时 primary_key 为 null。"
                ),
            },
            {
                "role": "user",
                "content": json.dumps({
                    "file_name": file_name,
                    "allowed_documents": allowed,
                    "rule_candidates": result.get("candidates") or [],
                    "excerpts": excerpts,
                }, ensure_ascii=False),
            },
        ]
        try:
            from app.services.llm_service import llm_service

            response = await llm_service.chat_with_fallback(
                db=db,
                user_id=user_id,
                messages=messages,
                task_type="document_classification",
                timeout=40,
                temperature=0,
                max_tokens=1600,
                response_model=DocumentClassificationContract,
                business_validator=self._validate_classification_contract,
            )
            payload = response.get("validated") or self._parse_llm_object(response.get("content", ""))
            document_key = payload.get("primary_key")
            confidence = max(0.0, min(float(payload.get("confidence") or 0), 1.0))
            document = self.documents.get(document_key)
            if document and confidence >= 0.65:
                file_value = self._normalize_document_name(Path(file_name or "document").stem)
                aliases = [document.get("name", ""), *(document.get("aliases") or [])]
                naming_match = any(self._name_similarity(file_value, self._normalize_document_name(alias)) >= 0.72 for alias in aliases if alias)
                return {
                    **result,
                    "status": "classified",
                    "document_key": document_key,
                    "document_name": document.get("name"),
                    "confidence": confidence,
                    "naming_status": "matched" if naming_match else "filename_warning",
                    "reason": payload.get("reason") or "正文内容与标准文档类型相符",
                    "classifier": "hybrid",
                }
            return {
                **result,
                "status": "unclassified",
                "document_key": None,
                "document_name": None,
                "confidence": confidence,
                "reason": payload.get("reason") or "模型未能可靠确认文档类型",
                "classifier": "hybrid",
            }
        except Exception as exc:
            return {
                **result,
                "classifier": "rule_fallback",
                "classification_warning": f"内容分类模型不可用：{exc}",
            }

    @staticmethod
    def _normalize_document_name(value: str) -> str:
        value = re.sub(r"(?i)(?:v(?:ersion)?\s*\d+(?:\.\d+)*|20\d{2}(?:[-_.]\d{1,2}){0,2})", "", value or "")
        value = re.sub(r"(?:修订|正式|最终|发布|试行|暂行|新版|终版|草案|定稿)版?", "", value)
        return re.sub(r"[\W_]+", "", value).lower()

    @staticmethod
    def _name_similarity(value: str, alias: str) -> float:
        if not value or not alias:
            return 0
        if value == alias:
            return 1.0
        if alias in value:
            return 0.65 + 0.2 * len(alias) / len(value)
        if value in alias:
            return 0.62 + 0.18 * len(value) / len(alias)
        return SequenceMatcher(None, value, alias).ratio() * 0.85

    @staticmethod
    def _title_similarity(value: str, alias: str) -> float:
        if not value or not alias:
            return 0
        if alias in value:
            return 1.0
        return SequenceMatcher(None, value[:120], alias).ratio() * 0.85

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

        if total_points and passed_points == total_points:
            status = "pass"
        elif passed_points or partial_points:
            status = "partial"
        else:
            status = "fail"

        gap_items = [
            {
                "uid": point.get("uid") or f"{control.get('id')}:{point.get('id')}",
                "control_id": control.get("id"),
                "point_id": point.get("id"),
                "status": point.get("status"),
                "reason": point.get("llm_reason") or point.get("missing_judgement") or point.get("text") or "证据不足",
            }
            for control in controls
            for point in control["points"]
            if point["status"] in {"fail", "partial"}
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
            "gaps": [item["reason"] for item in gap_items],
            "gap_items": gap_items,
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
                "completeness": point.get("completeness"),
                "negative_conditions": point.get("negative_conditions") or [],
                "evidence": [e.get("text", "") for e in point.get("evidence", [])[:2]],
            }
            for control, point in points
        ]
        messages = [
            {
                "role": "system",
                "content": (
                    "你是企业合规文档证据复核器。只判断证据是否支持当前标准库必检点，不直接给合规结论。"
                    "返回严格 JSON 对象 {decisions: [...]}，数组每项包含 control_id, point_id, "
                    "decision(pass|partial|fail|contradict), confidence(0到1), reason。"
                    "contradict 表示证据明确违反要求；reason 不超过 60 个汉字。"
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

        response = None
        try:
            from app.services.llm_service import llm_service

            response = await llm_service.chat_with_fallback(
                db=db,
                user_id=user_id,
                messages=messages,
                task_type="document_evidence_review",
                timeout=90,
                temperature=0,
                max_tokens=4096,
                response_model=DocumentEvidenceReviewContract,
                business_validator=lambda value: self._validate_evidence_contract(value, points),
            )
            decisions = (response.get("validated") or {}).get("decisions") or self._parse_llm_json(response.get("content", ""))
        except Exception as exc:
            logger.info("document evidence LLM review skipped: %s", exc)
            analysis["evidence_engine"] = "unavailable"
            truncated = bool(response and response.get("finish_reason") in {"length", "max_tokens"})
            invalid_structure = "模型未返回 JSON" in str(exc) or "Expecting" in str(exc)
            analysis["llm_review_error"] = (
                "判证模型输出超过长度上限，结构化结果不完整。" if truncated
                else "所有判证模型均未返回有效结构化结果。" if invalid_structure
                else str(exc)
            )
            analysis["status"] = "unable"
            analysis["message"] = (
                "判证模型输出被截断，本次不能生成可信合规结论。"
                if truncated else "判证模型未返回有效结构化结果，本次不能生成可信合规结论。"
                if invalid_structure else "候选证据已召回，但判证模型不可用，本次不能生成可信合规结论。"
            )
            analysis["confidence"] = 0
            return analysis

        decision_map = {}
        for item in decisions:
            if item.get("decision") not in {"pass", "partial", "fail", "contradict"}:
                continue
            try:
                confidence = float(item.get("confidence"))
            except (TypeError, ValueError):
                continue
            if not 0 <= confidence <= 1:
                continue
            decision_map[(item.get("control_id"), item.get("point_id"))] = {
                **item,
                "confidence": confidence,
            }
        expected = {
            (control.get("id"), point.get("id"))
            for control, point in points
        }
        if not expected.issubset(decision_map):
            analysis["evidence_engine"] = "unavailable"
            analysis["status"] = "unable"
            analysis["message"] = "判证模型返回不完整，部分候选证据未获得结构化结论。"
            analysis["confidence"] = 0
            return analysis
        for control in analysis.get("controls", []):
            for point in control.get("points", []):
                decision = decision_map.get((control.get("id"), point.get("id")))
                if decision:
                    point["status"] = "fail" if decision["decision"] == "contradict" else decision["decision"]
                    point["contradiction"] = decision["decision"] == "contradict"
                    point["decision_confidence"] = decision["confidence"]
                    point["llm_reason"] = decision.get("reason")

        self._recompute_analysis(analysis)
        analysis["evidence_engine"] = "hybrid"
        return analysis

    def _validate_classification_contract(self, value: DocumentClassificationContract) -> None:
        if value.primary_key is not None and value.primary_key not in self.documents:
            raise ValueError(f"文档类型 {value.primary_key} 不在标准库中")

    @staticmethod
    def _validate_evidence_contract(value: DocumentEvidenceReviewContract, points) -> None:
        expected = {(str(control.get("id")), str(point.get("id"))) for control, point in points}
        actual = {(item.control_id, item.point_id) for item in value.decisions}
        if len(actual) != len(value.decisions):
            raise ValueError("判证结果包含重复检查点")
        if actual != expected:
            missing = expected - actual
            extra = actual - expected
            detail = []
            if missing:
                detail.append(f"缺少 {len(missing)} 个检查点")
            if extra:
                detail.append(f"包含 {len(extra)} 个未知检查点")
            raise ValueError("判证结果不完整：" + "，".join(detail))

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
            "uid": control.get("uid"),
            "id": control.get("id"),
            "title": control.get("title"),
            "status": status,
            "total_points": total,
            "passed_points": passed,
            "partial_points": partial,
            "points": points,
        }

    def _parse_llm_json(self, content: str) -> list[dict[str, Any]]:
        payloads = self._decode_json_values(content)
        for payload in payloads:
            if isinstance(payload, list):
                return payload
            if isinstance(payload, dict):
                for key in ("decisions", "results", "items"):
                    if isinstance(payload.get(key), list):
                        return payload[key]
        raise ValueError("模型未返回 JSON 数组")

    @staticmethod
    def _parse_llm_object(content: str) -> dict[str, Any]:
        for payload in DocumentControlEngine._decode_json_values(content):
            if isinstance(payload, dict):
                return payload
        raise ValueError("模型未返回 JSON 对象")

    @staticmethod
    def _decode_json_values(content: str) -> list[Any]:
        """Decode JSON embedded in fences, think blocks or provider prose."""
        text = re.sub(r"<think>[\s\S]*?</think>", "", content or "", flags=re.I)
        text = re.sub(r"```(?:json)?|```", "", text, flags=re.I)
        decoder = json.JSONDecoder()
        values = []
        for index, char in enumerate(text):
            if char not in "[{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            values.append(value)
        if not values and text.strip():
            values.append(json.loads(text.strip()))
        return values

    def _recompute_analysis(self, analysis: dict[str, Any]) -> None:
        total_points = 0
        passed_points = 0
        partial_points = 0
        unable_points = 0
        confidence_values = []
        gap_items = []
        for control in analysis.get("controls", []):
            points = control.get("points", [])
            total = len(points)
            passed = sum(1 for p in points if p.get("status") == "pass")
            partial = sum(1 for p in points if p.get("status") == "partial")
            unable = sum(1 for p in points if p.get("status") == "unable")
            control["total_points"] = total
            control["passed_points"] = passed
            control["partial_points"] = partial
            control["unable_points"] = unable
            control["status"] = "unable" if unable else ("pass" if passed == total else ("fail" if passed == 0 and partial == 0 else "partial"))
            total_points += total
            passed_points += passed
            partial_points += partial
            unable_points += unable
            for point in points:
                if point.get("status") == "unable":
                    continue
                if point.get("decision_confidence") is not None:
                    point_confidence = float(point["decision_confidence"])
                elif point.get("status") == "fail" and not point.get("evidence") and point.get("retrieval_complete"):
                    point_confidence = 0.9
                else:
                    sources = [
                        float(item.get("confidence"))
                        for item in point.get("evidence") or []
                        if item.get("confidence") is not None
                    ]
                    point_confidence = sum(sources) / len(sources) if sources else 0.65
                point["decision_confidence"] = round(max(0.0, min(point_confidence, 1.0)), 3)
                confidence_values.append(point["decision_confidence"])
            gap_items.extend({
                "uid": point.get("uid") or f"{control.get('id')}:{point.get('id')}",
                "control_id": control.get("id"),
                "point_id": point.get("id"),
                "status": point.get("status"),
                "reason": point.get("llm_reason") or point.get("missing_judgement") or point.get("text") or "证据不足",
            } for point in points if point.get("status") in {"fail", "partial"})

        coverage = round((passed_points + partial_points * 0.5) / total_points, 2) if total_points else 0
        analysis["coverage"] = coverage
        analysis["status"] = (
            "unable" if unable_points
            else "pass" if total_points and passed_points == total_points
            else ("partial" if passed_points or partial_points else "fail")
        )
        analysis["total_points"] = total_points
        analysis["passed_points"] = passed_points
        analysis["partial_points"] = partial_points
        analysis["unable_points"] = unable_points
        analysis["failed_points"] = total_points - passed_points - partial_points - unable_points
        analysis["gaps"] = [item["reason"] for item in gap_items]
        analysis["gap_items"] = gap_items
        analysis["confidence"] = 0 if unable_points else (
            round(sum(confidence_values) / len(confidence_values), 2) if confidence_values else 0
        )

    def _check_point(
        self,
        point: dict[str, Any],
        chunks: list[dict[str, Any]],
        candidate_mode: bool = False,
        retrieval_complete: bool = True,
    ) -> dict[str, Any]:
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
            if matched or (candidate_mode and chunk.get("retrieval_sources")):
                evidence.append({
                    "matched_keywords": chunk.get("matched_keywords") or matched,
                    "text": self._trim_evidence(text, matched),
                    "block_id": chunk.get("block_id"),
                    "document_file_id": chunk.get("document_file_id"),
                    "file_name": chunk.get("file_name"),
                    "page": chunk.get("page"),
                    "section": chunk.get("section"),
                    "type": chunk.get("type"),
                    "source": chunk.get("source"),
                    "confidence": chunk.get("confidence"),
                    "bbox": chunk.get("bbox"),
                    "retrieval_score": chunk.get("retrieval_score"),
                    "retrieval_sources": chunk.get("retrieval_sources") or (["exact"] if matched else []),
                })
            if len(evidence) >= 3:
                break

        hit_count = len({kw for item in evidence for kw in item["matched_keywords"]})
        if candidate_mode:
            status = "partial" if evidence else ("fail" if retrieval_complete else "unable")
        else:
            status = "pass" if hit_count >= 2 or (len(keywords) == 1 and hit_count == 1) else ("partial" if hit_count == 1 else "fail")
        return {
            "uid": point.get("uid"),
            "id": point.get("id"),
            "text": point.get("text"),
            "status": status,
            "evidence": evidence,
            "basis": point.get("basis") or self.library.get("basis", []),
            "required_evidence": point.get("required_evidence") or keywords,
            "completeness": point.get("completeness"),
            "negative_conditions": point.get("negative_conditions") or [],
            "severity": point.get("severity", "medium"),
            "applicability": point.get("applicability"),
            "automation_boundary": point.get("automation_boundary"),
            "remediation": point.get("remediation") or point.get("missing_judgement", "补充对应制度内容和可审计证据。"),
            "missing_judgement": point.get("missing_judgement", "未发现对应证据。"),
            "retrieval_complete": retrieval_complete,
        }

    def _trim_evidence(self, chunk: str, keywords: list[str]) -> str:
        first = min((chunk.find(kw) for kw in keywords if kw in chunk), default=0)
        start = max(0, first - 80)
        end = min(len(chunk), first + 220)
        return chunk[start:end].strip()
