from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .boomi_client import BoomiClient
from .component_builder import build_connection_component_xml, build_operation_component_xml
from .manifest import ManifestStore, load_manifest, now_iso
from .models import ConnectionConfig, ConnectorProfile
from .redaction import redact
from .solace_semp import SolaceSempClient
from .transform import transform_process_xml
from .validation import fail_on_issues, validate_transformed_process_xml


def apply_plan(
    *,
    plan: dict[str, Any],
    manifest_path: str | Path,
    dry_run: bool,
    client: BoomiClient | None = None,
) -> dict[str, Any]:
    profile = ConnectorProfile.from_dict(plan["connector_profile"])
    connection = ConnectionConfig.from_dict(plan.get("connection", {}))
    source_connector_types = {str(item).lower() for item in plan.get("source_connector_types", [])}
    manifest = ManifestStore(manifest_path, plan_id=str(plan["plan_id"]))
    if dry_run:
        return {"plan_id": plan["plan_id"], "dry_run": True, "processes": plan["processes"]}
    if client is None:
        client = BoomiClient.from_env()

    for process in plan["processes"]:
        existing = manifest.entry_for_process(process["process_id"])
        if existing and existing.get("status") == "success":
            continue
        entry: dict[str, Any] = {
            "process_id": process["process_id"],
            "process_name": process["process_name"],
            "status": "running",
            "started_at": now_iso(),
            "created_components": [],
            "source_hash": process["source_hash"],
            "send_destination": process["send_destination"],
            "receive_destination": process["receive_destination"],
        }
        manifest.upsert_entry(entry)
        try:
            connection_xml = build_connection_component_xml(
                component_name=process["connection"]["component_name"],
                folder_id=process["target_folder_id"],
                profile=profile,
                values=connection.values(redacted=False),
                metadata={
                    "source_process_id": process["process_id"],
                    "source_hash": process["source_hash"][:16],
                    "plan_id": str(plan["plan_id"]),
                },
            )
            connection_id = client.create_component(connection_xml)
            entry["created_components"].append({"kind": "connection", "component_id": connection_id})

            operation_ids: dict[str, str] = {}
            for operation in process["operations"]:
                operation_xml = build_operation_component_xml(
                    action=operation["action"],
                    component_name=operation["component_name"],
                    folder_id=process["target_folder_id"],
                    profile=profile,
                    destination=operation["destination"],
                    destination_type=operation["destination_type"],
                    delivery_mode=operation["delivery_mode"],
                    metadata={
                        "source_process_id": process["process_id"],
                        "source_hash": process["source_hash"][:16],
                        "plan_id": str(plan["plan_id"]),
                    },
                )
                operation_id = client.create_component(operation_xml)
                operation_ids[operation["action"]] = operation_id
                entry["created_components"].append(
                    {"kind": f"{operation['action']}_operation", "component_id": operation_id}
                )

            original_xml = Path(process["source_xml_path"]).read_text(encoding="utf-8")
            transformed = transform_process_xml(
                original_xml=original_xml,
                process_name=process["process_name"],
                target_folder_id=process["target_folder_id"],
                source_connector_types=source_connector_types,
                profile=profile,
                connection_id=connection_id,
                operation_ids=operation_ids,
            )
            fail_on_issues(
                validate_transformed_process_xml(
                    transformed.xml,
                    profile=profile,
                    source_connector_types=source_connector_types,
                )
            )
            migrated_process_id = client.create_component(transformed.xml)
            entry["created_components"].append({"kind": "process", "component_id": migrated_process_id})
            entry["new_process_id"] = migrated_process_id
            entry["status"] = "success"
            entry["completed_at"] = now_iso()
        except Exception as exc:
            entry["status"] = "failed"
            entry["error"] = str(redact({"error": str(exc)})["error"])
            entry["completed_at"] = now_iso()
            manifest.upsert_entry(entry)
            raise
        manifest.upsert_entry(entry)
    manifest.complete()
    return manifest.data


def rollback_manifest(
    *,
    manifest_path: str | Path,
    dry_run: bool,
    client: BoomiClient | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    deleted: list[dict[str, str]] = []
    components: list[dict[str, str]] = []
    for entry in manifest.get("entries", []):
        components.extend(entry.get("created_components", []))
    for component in reversed(components):
        component_id = component.get("component_id", "")
        if not component_id:
            continue
        deleted.append({"component_id": component_id, "kind": component.get("kind", "")})
        if not dry_run:
            if client is None:
                client = BoomiClient.from_env()
            client.delete_component(component_id)
    return {"dry_run": dry_run, "deleted": deleted}


def provision_solace_destinations(
    *,
    plan: dict[str, Any],
    dry_run: bool,
    client: SolaceSempClient | None = None,
) -> dict[str, Any]:
    if client is None and not dry_run:
        client = SolaceSempClient.from_env()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for process in plan["processes"]:
        for operation in process.get("operations", []):
            if operation.get("destination_type") != "QUEUE":
                continue
            destination = operation.get("destination", "")
            if not destination or destination in seen:
                continue
            seen.add(destination)
            dmq_name = f"{destination}_dmq" if process.get("provision_dmq", True) else None
            if dry_run:
                results.append(
                    {
                        "queue": destination,
                        "status": "would_validate_or_create",
                        "dmq": dmq_name,
                        "access_type": process.get("queue_access_type", "exclusive"),
                    }
                )
                continue
            assert client is not None
            if dmq_name:
                results.append(
                    client.ensure_queue(
                        queue_name=dmq_name,
                        access_type="exclusive",
                        dry_run=False,
                    )
                )
            results.append(
                client.ensure_queue(
                    queue_name=destination,
                    access_type=process.get("queue_access_type", "exclusive"),
                    dmq_name=dmq_name,
                    dry_run=False,
                )
            )
    return {"dry_run": dry_run, "results": results}


def dump_json(data: dict[str, Any], output: str | Path) -> None:
    Path(output).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
