"""Verify scoped storage telemetry and destructive business-data cleanup."""

import asyncio
import uuid

from sqlalchemy import func, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.asset import Asset, AssetType, VerificationStatus
from app.models.document_knowledge import DocumentAnalysisRun, DocumentBlock, DocumentFile
from app.models.organization import Organization, OrganizationMember, OrganizationRole, OrgRole
from app.models.project import ComplianceLevel, Project, ProjectStatus
from app.models.scan_task import ScanTask, ScanTaskStatus, ScanTaskType, TriggeredBy
from app.models.user import User
from app.services.data_lifecycle import (
    clear_project_documents,
    delete_organization_records,
    delete_project_records,
    delete_storage_files,
    storage_usage,
)
from app.services.file_storage import file_storage
from app.services.flow_engine import get_flow_engine
from app.services.knowledge_graph import knowledge_graph


async def _count(db, model, *conditions) -> int:
    return int((await db.execute(select(func.count(model.id)).where(*conditions))).scalar_one())


async def main() -> None:
    marker = uuid.uuid4().hex[:10]
    org_id = project_id = None
    pending_files: list[str] = []
    async with AsyncSessionLocal() as db:
        try:
            user = (await db.execute(
                select(User).where(User.is_active.is_(True)).order_by(User.id).limit(1)
            )).scalar_one()
            standards_before = await knowledge_graph.status(db)
            assert standards_before["available"] and standards_before["standard_nodes"] > 0, standards_before

            organization = Organization(
                name=f"生命周期验收-{marker}",
                code=f"LIFECYCLE_{marker.upper()}",
                description="自动化临时数据，验收后删除",
            )
            db.add(organization)
            await db.flush()
            org_id = organization.id
            db.add_all([
                OrganizationMember(
                    organization_id=org_id,
                    user_id=user.id,
                    role=OrgRole.ADMIN,
                ),
                OrganizationRole(
                    organization_id=org_id,
                    name="生命周期验收角色",
                    description="验证初始化保留角色",
                    permissions="[]",
                    is_system=True,
                    created_by=user.id,
                ),
            ])
            project = Project(
                user_id=user.id,
                organization_id=org_id,
                owner_id=user.id,
                name=f"生命周期验收项目-{marker}",
                compliance_level=ComplianceLevel.LEVEL_3,
                status=ProjectStatus.ACTIVE,
            )
            db.add(project)
            await db.commit()
            project_id = project.id

            flow = get_flow_engine(db)
            templates = await flow.upsert_default_templates()
            template = next(item for item in templates if item.compliance_level == 3)
            assessment = await flow.create_assessment(project_id, template.id, owner_id=user.id)
            phases = await flow.get_phases(assessment.id)
            doc_task = next(
                task
                for task in await flow.get_tasks(phases[0].id)
                if task.task_type == "doc_review"
            )

            storage_path, digest, file_size = await file_storage.save_file(
                project_id,
                f"生命周期验收-{marker}.txt",
                "信息安全事件应急预案。责任人为安全负责人，每半年演练并保存审批和处置记录。".encode("utf-8"),
            )
            pending_files.append(storage_path)
            run = DocumentAnalysisRun(
                project_id=project_id,
                assessment_id=assessment.id,
                phase_id=phases[0].id,
                task_id=doc_task.id,
                requested_by=user.id,
                status="completed",
                progress={"stage": "completed", "percent": 100},
                result_summary={"verdict": "partial"},
            )
            db.add(run)
            await db.flush()
            document = DocumentFile(
                project_id=project_id,
                assessment_id=assessment.id,
                task_id=doc_task.id,
                uploaded_in_run_id=run.id,
                original_name=f"生命周期验收-{marker}.txt",
                storage_path=storage_path,
                mime_type="text/plain",
                size_bytes=file_size,
                sha256=digest,
                page_count=1,
                parse_status="completed",
            )
            db.add(document)
            await db.flush()
            block = DocumentBlock(
                project_id=project_id,
                assessment_id=assessment.id,
                analysis_run_id=run.id,
                document_file_id=document.id,
                ordinal=0,
                page_number=1,
                section_path=["应急响应"],
                block_type="paragraph",
                source="native",
                source_confidence=1.0,
                text="责任人为安全负责人，每半年演练并保存审批和处置记录。",
                content_sha256=digest,
                metadata_json={"verification": True},
                embedding_model="lifecycle-check",
                embedding=[0.01] * settings.DOCUMENT_EMBEDDING_DIMENSION,
            )
            db.add_all([
                block,
                Asset(
                    project_id=project_id,
                    asset_type=AssetType.IP,
                    value="192.0.2.10",
                    verification_status=VerificationStatus.VERIFIED,
                ),
                ScanTask(
                    project_id=project_id,
                    task_type=ScanTaskType.TARGETED,
                    status=ScanTaskStatus.COMPLETED,
                    triggered_by=TriggeredBy.MANUAL,
                    parameters={"capability": "scan_ports", "target": "192.0.2.10"},
                    progress={"stage": "completed", "percent": 100},
                    result_summary={"status": "success", "data": {"open_ports": [22]}},
                ),
            ])
            await db.flush()
            await knowledge_graph.sync_document_structure(
                db,
                project_id=project_id,
                assessment_id=assessment.id,
                phase_id=phases[0].id,
                task_id=doc_task.id,
                run_id=run.id,
                file_id=document.id,
                blocks=[{
                    "id": block.id,
                    "ordinal": 0,
                    "page_number": 1,
                    "section_path": ["应急响应"],
                    "block_type": "paragraph",
                    "source": "native",
                    "source_confidence": 1.0,
                    "content_sha256": digest,
                }],
            )
            await db.commit()

            before = await storage_usage(db, [project_id])
            assert before["categories"]["original_files"]["count"] == 1, before
            assert before["categories"]["parsed_content"]["count"] == 1, before
            assert before["categories"]["vectors"]["count"] == 1, before
            assert before["categories"]["scan_results"]["count"] == 1, before
            assert before["total_bytes"] > file_size, before

            document_cleanup = await clear_project_documents(db, project_id)
            await db.commit()
            file_cleanup = await delete_storage_files(document_cleanup["file_paths"])
            pending_files = file_cleanup["failed_file_paths"]
            assert not pending_files, file_cleanup
            assert await _count(db, DocumentFile, DocumentFile.project_id == project_id) == 0
            assert await _count(db, DocumentBlock, DocumentBlock.project_id == project_id) == 0
            assert await _count(db, Asset, Asset.project_id == project_id) == 1
            assert await _count(db, ScanTask, ScanTask.project_id == project_id) == 1
            after_documents = await storage_usage(db, [project_id])
            assert after_documents["categories"]["original_files"]["count"] == 0, after_documents
            assert after_documents["categories"]["vectors"]["count"] == 0, after_documents
            assert after_documents["categories"]["scan_results"]["count"] == 1, after_documents

            project = await db.get(Project, project_id)
            project_cleanup = await delete_project_records(db, project)
            await db.commit()
            project_files = await delete_storage_files(project_cleanup["file_paths"])
            assert not project_files["failed_file_paths"], project_files
            assert await db.get(Project, project_id) is None
            assert await db.get(Organization, org_id) is not None
            assert await _count(db, OrganizationMember, OrganizationMember.organization_id == org_id) == 1
            assert await _count(db, OrganizationRole, OrganizationRole.organization_id == org_id) == 1
            standards_after = await knowledge_graph.status(db)
            assert standards_after["standard_nodes"] == standards_before["standard_nodes"], (
                standards_before,
                standards_after,
            )

            organization = await db.get(Organization, org_id)
            organization_cleanup = await delete_organization_records(db, organization)
            await db.commit()
            assert await db.get(Organization, org_id) is None
            assert organization_cleanup["deleted_projects"] == 0
            print({
                "status": "passed",
                "storage_before_bytes": before["total_bytes"],
                "document_cleanup": document_cleanup,
                "project_deleted": project_id,
                "standard_nodes_preserved": standards_after["standard_nodes"],
            })
        except Exception:
            await db.rollback()
            if project_id:
                project = await db.get(Project, project_id)
                if project:
                    try:
                        cleanup = await delete_project_records(db, project)
                        pending_files.extend(cleanup["file_paths"])
                        await db.commit()
                    except Exception:
                        await db.rollback()
            if org_id:
                organization = await db.get(Organization, org_id)
                if organization:
                    cleanup = await delete_organization_records(db, organization)
                    pending_files.extend(cleanup["file_paths"])
                    await db.commit()
            await delete_storage_files(pending_files)
            raise


if __name__ == "__main__":
    asyncio.run(main())
