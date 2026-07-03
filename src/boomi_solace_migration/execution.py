from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _apply_single_process(
    *,
    process: dict[str, Any],
    profile: ConnectorProfile,
    connection: ConnectionConfig,
    source_connector_types: set[str],
    plan_id: str,
    manifest: ManifestStore,
    client: BoomiClient,
) -> dict[str, Any]:
    """Migrate a single process (connection + operations + transformed process)."""
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
                "plan_id": plan_id,
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
                    "plan_id": plan_id,
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
    return entry


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

    # Filter to processes not yet completed
    pending = [
        p for p in plan["processes"]
        if (manifest.entry_for_process(p["process_id"]) or {}).get("status") != "success"
    ]

    max_workers = int(os.environ.get("BOOMI_APPLY_WORKERS", "3"))
    if max_workers <= 1 or len(pending) <= 1:
        # Sequential fallback
        for process in pending:
            _apply_single_process(
                process=process,
                profile=profile,
                connection=connection,
                source_connector_types=source_connector_types,
                plan_id=str(plan["plan_id"]),
                manifest=manifest,
                client=client,
            )
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(pending))) as executor:
            futures = {
                executor.submit(
                    _apply_single_process,
                    process=process,
                    profile=profile,
                    connection=connection,
                    source_connector_types=source_connector_types,
                    plan_id=str(plan["plan_id"]),
                    manifest=manifest,
                    client=client,
                ): process
                for process in pending
            }
            for future in as_completed(futures):
                future.result()  # Raises if the process migration failed

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


def provision_solace_access_control(
    *,
    plan: dict[str, Any],
    dry_run: bool,
    client: SolaceSempClient | None = None,
) -> dict[str, Any]:
    """Provision client-username, client-profile, and ACL-profile for queue ownership."""
    if client is None and not dry_run:
        client = SolaceSempClient.from_env()
    # Determine owner from plan defaults or first process with queue_owner set
    owner = ""
    for process in plan.get("processes", []):
        owner = process.get("queue_owner", "")
        if owner:
            break
    if not owner:
        return {"dry_run": dry_run, "results": [], "skipped": "no queue_owner configured"}

    results: list[dict[str, Any]] = []
    if dry_run:
        results.append({"acl_profile": owner, "status": "would_create"})
        results.append({"client_profile": owner, "status": "would_create"})
        results.append({"client_username": owner, "status": "would_create"})
        return {"dry_run": True, "results": results}

    assert client is not None
    results.append(client.ensure_acl_profile(profile_name=owner, dry_run=False))
    results.append(client.ensure_client_profile(profile_name=owner, dry_run=False))
    results.append(
        client.ensure_client_username(
            username=owner,
            password=owner,
            client_profile_name=owner,
            acl_profile_name=owner,
            dry_run=False,
        )
    )
    return {"dry_run": False, "results": results}


def _provision_single_queue(
    *,
    client: SolaceSempClient,
    destination: str,
    process: dict[str, Any],
    monitor_queues: bool,
) -> list[dict[str, Any]]:
    """Provision a single queue (+ DMQ + subscriptions). Returns list of results."""
    results: list[dict[str, Any]] = []
    dmq_name = f"{destination}_dmq" if process.get("provision_dmq", True) else None
    if dmq_name:
        results.append(
            client.ensure_queue(
                queue_name=dmq_name,
                access_type="exclusive",
                permission="consume",
                max_spool_usage_mb=process.get("max_spool_usage_mb"),
                dry_run=False,
            )
        )
        if monitor_queues:
            results.append(_queue_monitor_result(client, dmq_name))
    results.append(
        client.ensure_queue(
            queue_name=destination,
            access_type=process.get("queue_access_type", "exclusive"),
            dmq_name=dmq_name,
            permission=process.get("queue_permission", "consume"),
            owner=process.get("queue_owner", ""),
            max_redelivery_count=int(process.get("max_redelivery_count", 0) or 0),
            max_ttl_seconds=int(process.get("max_ttl_seconds", 0) or 0),
            max_spool_usage_mb=process.get("max_spool_usage_mb"),
            dry_run=False,
        )
    )
    if monitor_queues:
        results.append(_queue_monitor_result(client, destination))
    for subscription in process.get("topic_subscriptions", []):
        results.append(
            client.ensure_queue_subscription(
                queue_name=destination,
                subscription=str(subscription),
                dry_run=False,
            )
        )
    return results


def provision_solace_destinations(
    *,
    plan: dict[str, Any],
    dry_run: bool,
    client: SolaceSempClient | None = None,
    monitor_queues: bool = False,
) -> dict[str, Any]:
    if client is None and not dry_run:
        client = SolaceSempClient.from_env()
    results: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Collect work items
    work_items: list[tuple[str, dict[str, Any]]] = []
    for process in plan["processes"]:
        for operation in process.get("operations", []):
            if operation.get("destination_type") != "QUEUE":
                continue
            destination = operation.get("destination", "")
            if not destination or destination in seen:
                continue
            seen.add(destination)
            if dry_run:
                dmq_name = f"{destination}_dmq" if process.get("provision_dmq", True) else None
                results.append(
                    {
                        "queue": destination,
                        "status": "would_validate_or_create",
                        "dmq": dmq_name,
                        "access_type": process.get("queue_access_type", "exclusive"),
                        "permission": process.get("queue_permission", "consume"),
                        "owner": process.get("queue_owner", ""),
                        "max_redelivery_count": process.get("max_redelivery_count", 0),
                        "max_ttl_seconds": process.get("max_ttl_seconds", 0),
                        "max_spool_usage_mb": process.get("max_spool_usage_mb"),
                        "topic_subscriptions": process.get("topic_subscriptions", []),
                    }
                )
            else:
                work_items.append((destination, process))

    if dry_run or not work_items:
        return {"dry_run": dry_run, "results": results}

    assert client is not None
    max_workers = int(os.environ.get("SOLACE_PROVISION_WORKERS", "5"))
    if max_workers <= 1 or len(work_items) <= 1:
        # Sequential fallback
        for destination, process in work_items:
            results.extend(
                _provision_single_queue(
                    client=client,
                    destination=destination,
                    process=process,
                    monitor_queues=monitor_queues,
                )
            )
    else:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(work_items))) as executor:
            futures = [
                executor.submit(
                    _provision_single_queue,
                    client=client,
                    destination=destination,
                    process=process,
                    monitor_queues=monitor_queues,
                )
                for destination, process in work_items
            ]
            for future in as_completed(futures):
                results.extend(future.result())

    return {"dry_run": dry_run, "results": results}


def _queue_monitor_result(client: SolaceSempClient, queue_name: str) -> dict[str, Any]:
    stats = client.queue_stats(queue_name)
    if stats is None:
        return {"queue": queue_name, "status": "monitor_missing"}
    summary_keys = {
        "bindCount",
        "currentMsgSpoolUsage",
        "msgSpoolUsage",
        "msgSpoolUsageBytes",
        "redeliveredMsgCount",
        "spooledMsgCount",
    }
    return {
        "queue": queue_name,
        "status": "monitor_found",
        "data": {key: stats[key] for key in sorted(summary_keys) if key in stats},
    }


def dump_json(data: dict[str, Any], output: str | Path) -> None:
    Path(output).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
