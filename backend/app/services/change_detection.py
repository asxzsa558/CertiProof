import json

from sqlalchemy import select

from app.models.asset import Asset
from app.models.change_snapshot import ChangeSnapshot


def normalize_ports(items) -> list[dict]:
    ports = {}
    for item in items or []:
        raw_port = item.get("port") if isinstance(item, dict) else item
        try:
            port = int(raw_port)
        except (TypeError, ValueError):
            continue
        protocol = (item.get("protocol") or "tcp") if isinstance(item, dict) else "tcp"
        ports[(port, protocol)] = {
            "port": port,
            "protocol": protocol,
            "service": (item.get("service") or item.get("name") or "") if isinstance(item, dict) else "",
            "version": (item.get("version") or item.get("product") or "") if isinstance(item, dict) else "",
        }
    return sorted(ports.values(), key=lambda item: (item["protocol"], item["port"]))


def detect_port_changes(previous: list[dict], current: list[dict]) -> dict:
    before = {(item["port"], item["protocol"]): item for item in normalize_ports(previous)}
    after = {(item["port"], item["protocol"]): item for item in normalize_ports(current)}
    added = [after[key] for key in sorted(after.keys() - before.keys())]
    removed = [before[key] for key in sorted(before.keys() - after.keys())]
    service_changed = [
        {"port": key[0], "protocol": key[1], "before": before[key], "after": after[key]}
        for key in sorted(before.keys() & after.keys())
        if (before[key]["service"], before[key]["version"]) != (after[key]["service"], after[key]["version"])
    ]
    return {
        "added_ports": added,
        "removed_ports": removed,
        "service_changes": service_changed,
        "changes_detected": bool(added or removed or service_changed),
    }


async def record_asset_snapshot(db, project_id: int) -> ChangeSnapshot:
    result = await db.execute(
        select(Asset).where(Asset.project_id == project_id, Asset.is_active.is_(True)).order_by(Asset.id)
    )
    current = [
        {"id": asset.id, "type": getattr(asset.asset_type, "value", asset.asset_type), "value": asset.value, "name": asset.name}
        for asset in result.scalars().all()
    ]
    previous_result = await db.execute(
        select(ChangeSnapshot)
        .where(ChangeSnapshot.project_id == project_id, ChangeSnapshot.snapshot_type == "asset")
        .order_by(ChangeSnapshot.id.desc())
        .limit(1)
    )
    previous = previous_result.scalar_one_or_none()
    previous_items = previous.snapshot.get("assets", []) if previous else current
    before = {(item["type"], item["value"]): item for item in previous_items}
    after = {(item["type"], item["value"]): item for item in current}
    changes = {
        "added_assets": [after[key] for key in sorted(after.keys() - before.keys())],
        "removed_assets": [before[key] for key in sorted(before.keys() - after.keys())],
    }
    changed = bool(changes["added_assets"] or changes["removed_assets"])
    snapshot = ChangeSnapshot(
        project_id=project_id,
        snapshot_type="asset",
        subject="project",
        scope="active-assets",
        snapshot={"assets": current},
        changes=changes,
        changes_detected=changed,
        reliable=True,
        reassessment_required=changed,
    )
    db.add(snapshot)
    await db.commit()
    return snapshot


def port_scope(capability: str, parameters: dict, data: dict) -> str:
    parameters = parameters or {}
    data = data or {}
    scope = {
        "capability": capability,
        "mode": parameters.get("scan_mode") or parameters.get("mode") or data.get("scan_mode"),
        "range": parameters.get("port_range") or parameters.get("ports") or data.get("port_range"),
        "protocol": parameters.get("protocol") or "tcp",
    }
    return json.dumps(scope, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


async def record_port_snapshots(db, project_id: int, scan_task_id: int, port_results: dict) -> list[dict]:
    summaries = []
    for target, item in (port_results or {}).items():
        data = item.get("data") or {}
        reliable = bool(
            item.get("status") in {"success", "completed"}
            and data.get("scan_completed") is not False
            and data.get("reachable") is not False
            and not data.get("tool_error")
        )
        scope = port_scope(item.get("capability") or "scan_ports", item.get("parameters") or {}, data)
        current = normalize_ports(data.get("open_ports"))
        previous_result = await db.execute(
            select(ChangeSnapshot)
            .where(
                ChangeSnapshot.project_id == project_id,
                ChangeSnapshot.snapshot_type == "port",
                ChangeSnapshot.subject == target,
                ChangeSnapshot.scope == scope,
                ChangeSnapshot.reliable.is_(True),
            )
            .order_by(ChangeSnapshot.id.desc())
            .limit(1)
        )
        previous = previous_result.scalar_one_or_none()
        changes = detect_port_changes(previous.snapshot.get("open_ports", []), current) if reliable and previous else {
            "added_ports": [],
            "removed_ports": [],
            "service_changes": [],
            "changes_detected": False,
        }
        changes["baseline"] = previous is None
        if not reliable:
            changes["reason"] = "扫描未完整成功，不判定端口变化"
        snapshot = ChangeSnapshot(
            project_id=project_id,
            scan_task_id=scan_task_id,
            snapshot_type="port",
            subject=target,
            scope=scope,
            snapshot={"open_ports": current},
            changes=changes,
            changes_detected=changes["changes_detected"],
            reliable=reliable,
            reassessment_required=reliable and changes["changes_detected"],
        )
        db.add(snapshot)
        summaries.append({
            "target": target,
            "reliable": reliable,
            "reassessment_required": snapshot.reassessment_required,
            **changes,
        })
    await db.flush()
    return summaries
