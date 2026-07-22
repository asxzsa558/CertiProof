import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.document_knowledge import KnowledgeGraphRevision


LIBRARY_NAME = "document_controls"
CONTROL_BUNDLE = Path(__file__).resolve().parents[3] / "reference" / "compliance" / "document_controls.yaml"
MIPING_LIBRARY_NAME = "miping_document_controls"
MIPING_CONTROL_BUNDLE = Path(__file__).resolve().parents[3] / "reference" / "compliance" / "miping_document_controls.yaml"
STANDARD_BUNDLES = {
    "dengbao": (LIBRARY_NAME, CONTROL_BUNDLE),
    "miping": (MIPING_LIBRARY_NAME, MIPING_CONTROL_BUNDLE),
}
_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_]{0,62}$")


def _literal(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _agtype(value: Any) -> Any:
    if value is None or not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value.strip('"')


class KnowledgeGraphService:
    """Apache AGE graph index backed by the application's PostgreSQL database."""

    def __init__(self, graph_name: str | None = None):
        self.graph_name = graph_name or settings.GRAPH_NAME
        if not _IDENTIFIER.fullmatch(self.graph_name):
            raise ValueError("GRAPH_NAME 只能包含小写字母、数字和下划线，且必须以字母开头")

    @staticmethod
    def enabled(db: AsyncSession) -> bool:
        return db.bind is not None and db.bind.dialect.name == "postgresql"

    async def prepare(self, db: AsyncSession) -> bool:
        if not self.enabled(db):
            if settings.GRAPH_REQUIRED:
                raise RuntimeError("当前数据库不支持 Apache AGE，但 GRAPH_REQUIRED=true")
            return False
        await db.execute(text("LOAD 'age'"))
        await db.execute(text('SET LOCAL search_path = ag_catalog, "$user", public'))
        exists = (await db.execute(
            text("SELECT 1 FROM ag_catalog.ag_graph WHERE name = :name"),
            {"name": self.graph_name},
        )).scalar()
        if not exists:
            await db.execute(text("SELECT ag_catalog.create_graph(:name)"), {"name": self.graph_name})
        return True

    async def _cypher(self, db: AsyncSession, query: str) -> None:
        if not await self.prepare(db):
            return
        connection = await db.connection()
        await connection.exec_driver_sql(
            f"SELECT * FROM ag_catalog.cypher('{self.graph_name}', $cypher$ {query} $cypher$) "
            "AS (ignored ag_catalog.agtype)"
        )

    async def _cypher_rows(self, db: AsyncSession, query: str, columns: tuple[str, ...]) -> list[dict[str, Any]]:
        if not await self.prepare(db):
            return []
        definitions = ", ".join(f"{column} ag_catalog.agtype" for column in columns)
        sql = (
            f"SELECT {', '.join(f'{column}::text AS {column}' for column in columns)} "
            f"FROM ag_catalog.cypher('{self.graph_name}', $cypher$ {query} $cypher$) AS ({definitions})"
        )
        connection = await db.connection()
        rows = (await connection.exec_driver_sql(sql)).mappings().all()
        return [{key: _agtype(value) for key, value in row.items()} for row in rows]

    async def seed_standard_bundle(
        self,
        db: AsyncSession,
        bundle_path: Path = CONTROL_BUNDLE,
        library_name: str = LIBRARY_NAME,
    ) -> dict[str, Any]:
        raw = bundle_path.read_bytes()
        # Include graph schema generation so an unchanged YAML is reseeded after node UID/property changes.
        digest = hashlib.sha256(raw + f"\n{library_name}:schema-v3".encode()).hexdigest()
        library = yaml.safe_load(raw) or {}
        version = str(library.get("version") or "unversioned")
        defaults = library.get("requirement_defaults") or {}
        revision = (await db.execute(select(KnowledgeGraphRevision).where(
            KnowledgeGraphRevision.graph_name == self.graph_name,
            KnowledgeGraphRevision.library_name == library_name,
        ))).scalar_one_or_none()
        if revision and revision.content_sha256 == digest:
            return {"status": "current", "version": version, "nodes": revision.node_count, "edges": revision.edge_count}
        if not await self.prepare(db):
            return {"status": "disabled", "version": version, "nodes": 0, "edges": 0}

        standard_uid = f"standard:{library_name}:{version}"
        basis = library.get("basis") or []
        await self._cypher(db, f"MATCH (s:StandardEdition) WHERE s.library_name = {_literal(library_name)} SET s.active = false")
        await self._cypher(db, f"""
            MERGE (s:StandardEdition {{uid: {_literal(standard_uid)}}})
            SET s.version = {_literal(version)},
                s.basis = {_literal(basis)},
                s.library_name = {_literal(library_name)},
                s.digest = {_literal(digest)},
                s.active = true
        """)
        node_count = 1
        edge_count = 0
        for document_key, document in (library.get("documents") or {}).items():
            document_basis = document.get("basis") or basis
            document_applicability = document.get("applicability") or defaults.get("applicability") or ""
            document_boundary = document.get("automation_boundary") or defaults.get("automation_boundary") or ""
            document_uid = f"document:{library_name}:{version}:{document_key}"
            await self._cypher(db, f"""
                MATCH (s:StandardEdition {{uid: {_literal(standard_uid)}}})
                MERGE (d:DocumentType {{uid: {_literal(document_uid)}}})
                SET d.key = {_literal(document_key)}, d.name = {_literal(document.get('name') or document_key)},
                    d.aliases = {_literal(document.get('aliases') or [])}, d.standard_version = {_literal(version)},
                    d.basis = {_literal(document_basis)}, d.applicability = {_literal(document_applicability)},
                    d.automation_boundary = {_literal(document_boundary)}
                MERGE (s)-[:DEFINES]->(d)
            """)
            node_count += 1
            edge_count += 1
            for control in document.get("controls") or []:
                control_basis = control.get("basis") or document_basis
                control_applicability = control.get("applicability") or document_applicability
                control_boundary = control.get("automation_boundary") or document_boundary
                control_id = str(control["id"])
                control_uid = f"control:{library_name}:{version}:{control_id}"
                await self._cypher(db, f"""
                    MATCH (d:DocumentType {{uid: {_literal(document_uid)}}})
                    MERGE (c:Control {{uid: {_literal(control_uid)}}})
                    SET c.control_id = {_literal(control_id)}, c.title = {_literal(control.get('title') or control_id)},
                        c.standard_version = {_literal(version)}, c.basis = {_literal(control_basis)},
                        c.applicability = {_literal(control_applicability)},
                        c.automation_boundary = {_literal(control_boundary)}
                    MERGE (d)-[:CONTAINS]->(c)
                """)
                node_count += 1
                edge_count += 1
                for point in control.get("required_points") or []:
                    requirement_uid = f"requirement:{library_name}:{version}:{control_id}:{point['id']}"
                    required_evidence = point.get("required_evidence") or control.get("required_evidence") or document.get("required_evidence") or defaults.get("required_evidence") or point.get("evidence_keywords") or []
                    completeness = point.get("completeness") or control.get("completeness") or document.get("completeness") or defaults.get("completeness") or "必须存在可定位的支持证据且无矛盾证据"
                    negative_conditions = point.get("negative_conditions") or control.get("negative_conditions") or document.get("negative_conditions") or defaults.get("negative_conditions") or []
                    severity = point.get("severity") or control.get("severity") or document.get("severity") or defaults.get("severity") or "medium"
                    point_basis = point.get("basis") or control_basis
                    point_applicability = point.get("applicability") or control_applicability
                    point_boundary = point.get("automation_boundary") or control_boundary
                    remediation = point.get("remediation") or str(
                        defaults.get("remediation_template") or "补充“{requirement}”相关制度条款和可审计证据。"
                    ).format(requirement=point.get("text") or "该要求")
                    decision_uid = f"decision:{library_name}:{version}:{control_id}:{point['id']}"
                    remediation_uid = f"remediation:{library_name}:{version}:{control_id}:{point['id']}"
                    await self._cypher(db, f"""
                        MATCH (c:Control {{uid: {_literal(control_uid)}}})
                        MERGE (r:EvidenceRequirement {{uid: {_literal(requirement_uid)}}})
                        SET r.point_id = {_literal(str(point['id']))}, r.text = {_literal(point.get('text') or '')},
                            r.keywords = {_literal(point.get('evidence_keywords') or [])},
                            r.required_evidence = {_literal(required_evidence)},
                            r.negative_conditions = {_literal(negative_conditions)},
                            r.completeness = {_literal(completeness)},
                            r.missing_judgement = {_literal(point.get('missing_judgement') or '未发现必需证据')},
                            r.severity = {_literal(severity)}, r.basis = {_literal(point_basis)},
                            r.applicability = {_literal(point_applicability)},
                            r.automation_boundary = {_literal(point_boundary)}
                        MERGE (rule:DecisionRule {{uid: {_literal(decision_uid)}}})
                        SET rule.pass_condition = {_literal('必需证据完整且无矛盾')},
                            rule.partial_condition = {_literal('存在支持证据但完整性不足')},
                            rule.fail_condition = {_literal('可靠提取后仍缺失或存在矛盾')},
                            rule.unable_condition = {_literal('提取、检索或判证依赖不可用')}
                        MERGE (guidance:RemediationGuidance {{uid: {_literal(remediation_uid)}}})
                        SET guidance.text = {_literal(remediation)}, guidance.severity = {_literal(severity)}
                        MERGE (c)-[:REQUIRES]->(r)
                        MERGE (r)-[:DECIDED_BY]->(rule)
                        MERGE (r)-[:REMEDIATED_BY]->(guidance)
                    """)
                    node_count += 3
                    edge_count += 3

        if revision:
            revision.version = version
            revision.content_sha256 = digest
            revision.node_count = node_count
            revision.edge_count = edge_count
        else:
            db.add(KnowledgeGraphRevision(
                graph_name=self.graph_name,
                library_name=library_name,
                version=version,
                content_sha256=digest,
                node_count=node_count,
                edge_count=edge_count,
            ))
        await db.flush()
        return {"status": "seeded", "version": version, "nodes": node_count, "edges": edge_count}

    async def load_standard_library(self, db: AsyncSession, library_name: str = LIBRARY_NAME) -> dict[str, Any]:
        rows = await self._cypher_rows(db, f"""
            MATCH (s:StandardEdition)-[:DEFINES]->(d:DocumentType)-[:CONTAINS]->(c:Control)-[:REQUIRES]->(r:EvidenceRequirement)
            MATCH (r)-[:DECIDED_BY]->(rule:DecisionRule)
            MATCH (r)-[:REMEDIATED_BY]->(guidance:RemediationGuidance)
            WHERE s.active = true AND s.library_name = {_literal(library_name)}
            RETURN s.version, s.basis, d.key, d.name, d.aliases,
                   c.uid, c.control_id, c.title,
                   r.uid, r.point_id, r.text, r.keywords, r.required_evidence,
                   r.negative_conditions, r.completeness, r.missing_judgement, r.severity,
                   r.basis, r.applicability, r.automation_boundary,
                   rule.pass_condition, rule.partial_condition, rule.fail_condition, rule.unable_condition,
                   guidance.text
            ORDER BY d.key, c.control_id, r.point_id
        """, (
            "version", "basis", "document_key", "document_name", "aliases",
            "control_uid", "control_id", "control_title", "requirement_uid",
            "point_id", "requirement_text", "keywords", "required_evidence", "negative_conditions",
            "completeness", "missing_judgement", "severity", "requirement_basis", "applicability",
            "automation_boundary", "pass_condition",
            "partial_condition", "fail_condition", "unable_condition", "remediation",
        ))
        if not rows:
            raise RuntimeError("标准图谱为空，请先运行数据库迁移和标准库初始化")

        documents: dict[str, Any] = {}
        for row in rows:
            document = documents.setdefault(row["document_key"], {
                "name": row["document_name"],
                "aliases": row["aliases"] or [],
                "controls": [],
            })
            control = next((item for item in document["controls"] if item["uid"] == row["control_uid"]), None)
            if control is None:
                control = {
                    "uid": row["control_uid"],
                    "id": row["control_id"],
                    "title": row["control_title"],
                    "required_points": [],
                }
                document["controls"].append(control)
            control["required_points"].append({
                "uid": row["requirement_uid"],
                "id": row["point_id"],
                "text": row["requirement_text"],
                "evidence_keywords": row["keywords"] or [],
                "required_evidence": row["required_evidence"] or [],
                "negative_conditions": row["negative_conditions"] or [],
                "completeness": row["completeness"],
                "missing_judgement": row["missing_judgement"],
                "severity": row["severity"],
                "basis": row["requirement_basis"] or row["basis"] or [],
                "applicability": row["applicability"],
                "automation_boundary": row["automation_boundary"],
                "remediation": row["remediation"],
                "decision_rule": {
                    "pass": row["pass_condition"],
                    "partial": row["partial_condition"],
                    "fail": row["fail_condition"],
                    "unable": row["unable_condition"],
                },
            })
        return {
            "version": rows[0]["version"],
            "basis": rows[0]["basis"] or [],
            "documents": documents,
        }

    async def sync_document_structure(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        assessment_id: int,
        phase_id: int,
        task_id: int | None,
        run_id: int,
        file_id: int,
        blocks: list[dict[str, Any]],
    ) -> None:
        file_uid = f"file:{file_id}"
        await self._cypher(db, f"""
            MERGE (p:Project {{uid: {_literal(f'project:{project_id}')}}})
            SET p.project_id = {int(project_id)}
            MERGE (a:Assessment {{uid: {_literal(f'assessment:{assessment_id}')}}})
            SET a.assessment_id = {int(assessment_id)}
            MERGE (run:DocumentRun {{uid: {_literal(f'run:{run_id}')}}})
            SET run.run_id = {int(run_id)}, run.project_id = {int(project_id)}, run.assessment_id = {int(assessment_id)},
                run.phase_id = {int(phase_id)}, run.task_id = {int(task_id) if task_id is not None else 'null'}
            MERGE (f:Document {{uid: {_literal(file_uid)}}})
            SET f.file_id = {int(file_id)}, f.project_id = {int(project_id)}, f.assessment_id = {int(assessment_id)},
                f.phase_id = {int(phase_id)}, f.task_id = {int(task_id) if task_id is not None else 'null'}, f.run_id = {int(run_id)}
            MERGE (p)-[:HAS_ASSESSMENT]->(a)
            MERGE (a)-[:HAS_RUN]->(run)
            MERGE (run)-[:CONTAINS]->(f)
        """)
        previous_uid = None
        for block in blocks:
            block_id = int(block["id"])
            block_uid = f"block:{int(block_id)}"
            previous_match = ""
            previous_relation = ""
            if previous_uid:
                previous_match = f"MATCH (previous:Block {{uid: {_literal(previous_uid)}}})"
                previous_relation = "MERGE (previous)-[:NEXT]->(b)"
            page_number = block.get("page_number")
            page_relation = ""
            if page_number is not None:
                page_uid = f"page:{run_id}:{file_id}:{int(page_number)}"
                page_relation = f"""
                    MERGE (page:Page {{uid: {_literal(page_uid)}}})
                    SET page.file_id = {int(file_id)}, page.page_number = {int(page_number)},
                        page.project_id = {int(project_id)}, page.assessment_id = {int(assessment_id)},
                        page.phase_id = {int(phase_id)}, page.task_id = {int(task_id) if task_id is not None else 'null'},
                        page.run_id = {int(run_id)}
                    MERGE (f)-[:CONTAINS]->(page)
                    MERGE (page)-[:CONTAINS]->(b)
                """
            section_path = block.get("section_path") or []
            section_relation = ""
            if section_path:
                section_name = " / ".join(str(value) for value in section_path)
                section_key = hashlib.sha256(section_name.encode()).hexdigest()[:20]
                section_uid = f"section:{run_id}:{file_id}:{section_key}"
                section_relation = f"""
                    MERGE (section:Section {{uid: {_literal(section_uid)}}})
                    SET section.file_id = {int(file_id)}, section.name = {_literal(section_name)},
                        section.project_id = {int(project_id)}, section.assessment_id = {int(assessment_id)},
                        section.phase_id = {int(phase_id)}, section.task_id = {int(task_id) if task_id is not None else 'null'},
                        section.run_id = {int(run_id)}
                    MERGE (f)-[:CONTAINS]->(section)
                    MERGE (section)-[:CONTAINS]->(b)
                """
            await self._cypher(db, f"""
                MATCH (f:Document {{uid: {_literal(file_uid)}}})
                {previous_match}
                MERGE (b:Block {{uid: {_literal(block_uid)}}})
                SET b.block_id = {int(block_id)}, b.project_id = {int(project_id)},
                    b.assessment_id = {int(assessment_id)}, b.phase_id = {int(phase_id)},
                    b.task_id = {int(task_id) if task_id is not None else 'null'}, b.run_id = {int(run_id)},
                    b.file_id = {int(file_id)}, b.ordinal = {int(block.get('ordinal') or 0)},
                    b.block_type = {_literal(block.get('block_type') or 'text')},
                    b.content_sha256 = {_literal(block.get('content_sha256') or '')}
                MERGE (f)-[:CONTAINS]->(b)
                {page_relation}
                {section_relation}
                {previous_relation}
            """)
            previous_uid = block_uid

    async def expand_block_ids(self, db: AsyncSession, block_ids: list[int], limit: int = 24) -> list[int]:
        """Return graph-adjacent context without copying raw document text into AGE."""
        ids = sorted({int(value) for value in block_ids if value is not None})
        if not ids:
            return []
        rows = await self._cypher_rows(db, f"""
            MATCH (seed:Block)-[:NEXT]-(related:Block)
            WHERE seed.block_id IN {_literal(ids)} AND related.block_id <> seed.block_id
            RETURN DISTINCT related.block_id
            UNION
            MATCH (section:Section)-[:CONTAINS]->(seed:Block), (section)-[:CONTAINS]->(related:Block)
            WHERE seed.block_id IN {_literal(ids)} AND related.block_id <> seed.block_id
            RETURN DISTINCT related.block_id
        """, ("block_id",))
        return [int(row["block_id"]) for row in rows if row.get("block_id") is not None][
            :max(1, min(int(limit), 100))
        ]

    async def sync_evidence_link(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        assessment_id: int,
        phase_id: int,
        task_id: int | None,
        run_id: int,
        result_id: int,
        control_uid: str,
        requirement_uid: str,
        block_id: int,
        stance: str,
        confidence: float,
    ) -> None:
        relation = {
            "support": "SUPPORTS",
            "partial": "PARTIALLY_SUPPORTS",
            "contradict": "CONTRADICTS",
            "missing": "MISSING_FOR",
        }.get(stance)
        if not relation:
            raise ValueError(f"Unsupported evidence stance: {stance}")
        await self._cypher(db, f"""
            MATCH (c:Control {{uid: {_literal(control_uid)}}})-[:REQUIRES]->(r:EvidenceRequirement {{uid: {_literal(requirement_uid)}}})
            MATCH (b:Block {{uid: {_literal(f'block:{int(block_id)}')}}})
            MERGE (result:ControlResult {{uid: {_literal(f'result:{int(result_id)}')}}})
            SET result.result_id = {int(result_id)}, result.project_id = {int(project_id)},
                result.assessment_id = {int(assessment_id)}, result.phase_id = {int(phase_id)},
                result.task_id = {int(task_id) if task_id is not None else 'null'}, result.run_id = {int(run_id)}
            MERGE (result)-[:EVALUATES]->(c)
            MERGE (b)-[e:{relation}]->(r)
            SET e.result_id = {int(result_id)}, e.confidence = {float(confidence):.6f}
        """)

    async def sync_missing_requirement(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        assessment_id: int,
        phase_id: int,
        task_id: int | None,
        run_id: int,
        result_id: int,
        control_uid: str,
        requirement_uid: str,
    ) -> None:
        await self._cypher(db, f"""
            MATCH (c:Control {{uid: {_literal(control_uid)}}})-[:REQUIRES]->(r:EvidenceRequirement {{uid: {_literal(requirement_uid)}}})
            MERGE (result:ControlResult {{uid: {_literal(f'result:{int(result_id)}')}}})
            SET result.result_id = {int(result_id)}, result.project_id = {int(project_id)},
                result.assessment_id = {int(assessment_id)}, result.phase_id = {int(phase_id)},
                result.task_id = {int(task_id) if task_id is not None else 'null'}, result.run_id = {int(run_id)}
            MERGE (result)-[:EVALUATES]->(c)
            MERGE (result)-[:MISSING_FOR]->(r)
        """)

    async def purge_assessment(self, db: AsyncSession, assessment_id: int) -> None:
        await self._cypher(db, f"""
            MATCH (n) WHERE n.assessment_id = {int(assessment_id)} DETACH DELETE n
        """)

    async def purge_phase(self, db: AsyncSession, phase_id: int) -> None:
        await self._cypher(db, f"""
            MATCH (n) WHERE n.phase_id = {int(phase_id)} DETACH DELETE n
        """)

    async def purge_task(self, db: AsyncSession, task_id: int) -> None:
        await self._cypher(db, f"""
            MATCH (n) WHERE n.task_id = {int(task_id)} DETACH DELETE n
        """)

    async def purge_file(self, db: AsyncSession, file_id: int) -> None:
        await self._cypher(db, f"""
            MATCH (n) WHERE n.file_id = {int(file_id)} DETACH DELETE n
        """)

    async def purge_project(self, db: AsyncSession, project_id: int) -> None:
        await self._cypher(db, f"""
            MATCH (n) WHERE n.project_id = {int(project_id)} DETACH DELETE n
        """)

    async def reset_all_business_graph(self, db: AsyncSession) -> None:
        # AGE does not support Neo4j's `NOT n:Label` predicate. Business and
        # standards nodes use disjoint labels, so remove each business label
        # explicitly and keep the versioned standards graph untouched.
        for label in (
            "ControlResult",
            "Block",
            "Section",
            "Page",
            "Document",
            "DocumentRun",
            "Assessment",
            "Project",
        ):
            await self._cypher(db, f"MATCH (n:{label}) DETACH DELETE n")

    async def status(self, db: AsyncSession) -> dict[str, Any]:
        if not self.enabled(db):
            return {"available": False, "required": settings.GRAPH_REQUIRED, "reason": "not_postgresql"}
        try:
            await self.prepare(db)
            revision = (await db.execute(select(KnowledgeGraphRevision).where(
                KnowledgeGraphRevision.graph_name == self.graph_name,
                KnowledgeGraphRevision.library_name == LIBRARY_NAME,
            ))).scalar_one_or_none()
            return {
                "available": True,
                "required": settings.GRAPH_REQUIRED,
                "engine": "apache-age",
                "graph": self.graph_name,
                "standard_version": revision.version if revision else None,
                "standard_nodes": revision.node_count if revision else 0,
                "standard_edges": revision.edge_count if revision else 0,
            }
        except Exception as exc:
            return {"available": False, "required": settings.GRAPH_REQUIRED, "reason": str(exc)}


knowledge_graph = KnowledgeGraphService()
