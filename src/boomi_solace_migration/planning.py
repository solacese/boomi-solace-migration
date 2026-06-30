from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, cast

from .component_builder import (
    build_connection_component_xml,
    build_consumer_set_properties_snippet,
    build_operation_component_xml,
)
from .detect import detect_queue_usage
from .models import ConnectorProfile, MigrationConfig, NamingPolicy, ProcessConfig
from .naming import (
    destination_for_process,
    destination_type_for_process,
    stable_hash,
    validate_queue_name,
    validate_topic_name,
    validate_topic_subscription,
)
from .transform import transform_process_xml
from .validation import (
    fail_on_issues,
    validate_connection_xml,
    validate_operation_xml,
    validate_transformed_process_xml,
)
from .xml_io import canonical_xml, sha256_text


def safe_file_stem(value: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_")
    return stem[:80] or "process"


def build_plan(
    *,
    config: MigrationConfig,
    connector_profile: ConnectorProfile,
    naming_policy: NamingPolicy,
) -> dict[str, Any]:
    output_dir = config.output_dir
    components_dir = output_dir / "components"
    processes_dir = output_dir / "processes"
    snippets_dir = output_dir / "snippets"
    for directory in (components_dir, processes_dir, snippets_dir):
        directory.mkdir(parents=True, exist_ok=True)

    entries: list[dict[str, Any]] = []
    for process in config.processes:
        entries.append(
            _plan_process(
                process=process,
                config=config,
                profile=connector_profile,
                naming_policy=naming_policy,
                components_dir=components_dir,
                processes_dir=processes_dir,
                snippets_dir=snippets_dir,
            )
        )

    identity = {
        "migration_version": config.migration_version,
        "connector_sub_type": connector_profile.sub_type,
        "source_connector_types": sorted(config.source_connector_types),
        "processes": [
            {
                "process_id": entry["process_id"],
                "source_hash": entry["source_hash"],
                "send_destination": entry["send_destination"],
                "send_destination_type": entry["send_destination_type"],
                "receive_destination": entry["receive_destination"],
                "receive_destination_type": entry["receive_destination_type"],
                "queue_access_type": entry["queue_access_type"],
                "queue_permission": entry["queue_permission"],
                "queue_owner": entry["queue_owner"],
                "provision_dmq": entry["provision_dmq"],
                "topic_subscriptions": entry["topic_subscriptions"],
                "max_redelivery_count": entry["max_redelivery_count"],
                "max_ttl_seconds": entry["max_ttl_seconds"],
                "max_spool_usage_mb": entry["max_spool_usage_mb"],
                "operations": entry["operations"],
            }
            for entry in entries
        ],
    }
    plan_id = stable_hash(json.dumps(identity, sort_keys=True), 16)
    plan = {
        "plan_id": plan_id,
        "migration_version": config.migration_version,
        "connector_profile": asdict(connector_profile),
        "source_connector_types": sorted(config.source_connector_types),
        "connection": config.connection.raw,
        "processes": entries,
    }
    plan_path = output_dir / "migration-plan.json"
    plan_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return plan


def _plan_process(
    *,
    process: ProcessConfig,
    config: MigrationConfig,
    profile: ConnectorProfile,
    naming_policy: NamingPolicy,
    components_dir: Path,
    processes_dir: Path,
    snippets_dir: Path,
) -> dict[str, Any]:
    if process.xml_path is None:
        raise ValueError(f"Process {process.id} requires xml_path for offline planning")
    source_path = process.xml_path if process.xml_path.is_absolute() else Path.cwd() / process.xml_path
    original_xml = source_path.read_text(encoding="utf-8")
    detection = detect_queue_usage(original_xml, config.source_connector_types)
    if detection.unknown_queue_like_connectors:
        raise ValueError(
            f"{process.id}: unknown queue-like connectors: {detection.unknown_queue_like_connectors}"
        )
    if detection.unsupported_actions:
        raise ValueError(f"{process.id}: unsupported queue actions: {detection.unsupported_actions}")
    if not detection.operations:
        raise ValueError(f"{process.id}: no Atom Queue operations found")

    source_hash = sha256_text(original_xml)
    short = stable_hash(f"{process.id}:{source_hash}", 10)
    stem = safe_file_stem(f"{process.name}_{short}")
    actions = sorted({op.action for op in detection.operations})
    _validate_queue_runtime_settings(process)
    send_destination = destination_for_process(process, naming_policy, send=True)
    receive_destination = destination_for_process(process, naming_policy, send=False)
    send_destination_type = destination_type_for_process(process, send=True)
    receive_destination_type = destination_type_for_process(process, send=False)
    _validate_destination_type(process.id, send_destination_type, "send_destination_type")
    _validate_destination_type(process.id, receive_destination_type, "receive_destination_type")
    destinations_by_type: dict[str, list[str]] = {}
    if "send" in actions:
        destinations_by_type.setdefault(send_destination_type, []).append(send_destination)
    if any(action in {"listen", "get"} for action in actions):
        destinations_by_type.setdefault(receive_destination_type, []).append(receive_destination)
    for destination in destinations_by_type.get("TOPIC", []):
        topic_issues = validate_topic_name(destination, naming_policy)
        if topic_issues:
            raise ValueError(f"{process.id}: invalid topic {destination}: {topic_issues}")
    for destination in destinations_by_type.get("QUEUE", []):
        queue_issues = validate_queue_name(destination, naming_policy)
        if queue_issues:
            raise ValueError(f"{process.id}: invalid queue {destination}: {queue_issues}")
        if process.provision_dmq:
            dmq_issues = validate_queue_name(f"{destination}_dmq", naming_policy)
            if dmq_issues:
                raise ValueError(f"{process.id}: invalid DMQ {destination}_dmq: {dmq_issues}")
    for subscription in process.topic_subscriptions:
        subscription_issues = validate_topic_subscription(subscription, naming_policy)
        if subscription_issues:
            raise ValueError(f"{process.id}: invalid queue subscription {subscription}: {subscription_issues}")

    metadata = {
        "source_process_id": process.id,
        "source_hash": source_hash[:16],
        "migration_version": config.migration_version,
    }
    connection_values = config.connection.values(redacted=True)
    connection_name = f"{process.name} - Connection [{short}]"
    connection_xml = build_connection_component_xml(
        component_name=connection_name,
        folder_id=process.target_folder_id,
        profile=profile,
        values=connection_values,
        metadata=metadata,
    )
    fail_on_issues(validate_connection_xml(connection_xml, profile))
    connection_xml_path = components_dir / f"{stem}_connection.xml"
    connection_xml_path.write_text(canonical_xml(connection_xml) + "\n", encoding="utf-8")

    operation_ids = {action: f"PLAN_OP_{action.upper()}_{short}" for action in actions}
    operations: list[dict[str, Any]] = []
    for action in actions:
        destination = send_destination if action == "send" else receive_destination
        destination_type = send_destination_type if action == "send" else receive_destination_type
        operation_name = f"{process.name} - {action.title()} {destination} [{short}]"
        operation_xml = build_operation_component_xml(
            action=action,
            component_name=operation_name,
            folder_id=process.target_folder_id,
            profile=profile,
            destination=destination,
            destination_type=destination_type,
            delivery_mode=process.delivery_mode,
            metadata=metadata,
        )
        fail_on_issues(validate_operation_xml(operation_xml))
        operation_xml_path = components_dir / f"{stem}_{action}_operation.xml"
        operation_xml_path.write_text(canonical_xml(operation_xml) + "\n", encoding="utf-8")
        operations.append(
            {
                "action": action,
                "destination": destination,
                "destination_type": destination_type,
                "delivery_mode": process.delivery_mode,
                "component_name": operation_name,
                "xml_path": str(operation_xml_path),
                "placeholder_id": operation_ids[action],
            }
        )

    transformed = transform_process_xml(
        original_xml=original_xml,
        process_name=process.name,
        target_folder_id=process.target_folder_id,
        source_connector_types=config.source_connector_types,
        profile=profile,
        connection_id=f"PLAN_CONN_{short}",
        operation_ids=operation_ids,
    )
    fail_on_issues(
        validate_transformed_process_xml(
            transformed.xml,
            profile=profile,
            source_connector_types=config.source_connector_types,
        )
    )
    process_xml_path = processes_dir / f"{stem}_process.xml"
    process_xml_path.write_text(canonical_xml(transformed.xml) + "\n", encoding="utf-8")

    snippet_path = ""
    if detection.migration_type in {"consumer", "mixed"} and transformed.detection.ddps:
        snippet = build_consumer_set_properties_snippet(transformed.detection.ddps, profile)
        if snippet:
            snippet_file = snippets_dir / f"{stem}_consumer_set_properties.xml"
            snippet_file.write_text(canonical_xml(snippet) + "\n", encoding="utf-8")
            snippet_path = str(snippet_file)

    return {
        "process_id": process.id,
        "process_name": process.name,
        "folder_id": process.folder_id,
        "target_folder_id": process.target_folder_id,
        "source_xml_path": str(source_path),
        "source_hash": source_hash,
        "migration_type": detection.migration_type,
        "ddps": transformed.detection.ddps,
        "ddp_user_properties": transformed.ddp_user_properties,
        "send_destination": send_destination,
        "send_destination_type": send_destination_type,
        "receive_destination": receive_destination,
        "receive_destination_type": receive_destination_type,
        "queue_access_type": process.queue_access_type,
        "provision_dmq": process.provision_dmq,
        "topic_subscriptions": list(process.topic_subscriptions),
        "queue_permission": process.queue_permission,
        "queue_owner": process.queue_owner,
        "max_redelivery_count": process.max_redelivery_count,
        "max_ttl_seconds": process.max_ttl_seconds,
        "max_spool_usage_mb": process.max_spool_usage_mb,
        "connection": {
            "component_name": connection_name,
            "xml_path": str(connection_xml_path),
            "placeholder_id": f"PLAN_CONN_{short}",
        },
        "operations": operations,
        "planned_process_xml_path": str(process_xml_path),
        "consumer_set_properties_snippet_path": snippet_path,
    }


def load_plan(path: str | Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(Path(path).read_text(encoding="utf-8")))


def _validate_queue_runtime_settings(process: ProcessConfig) -> None:
    if process.queue_access_type not in {"exclusive", "non-exclusive"}:
        raise ValueError(f"{process.id}: queue_access_type must be exclusive or non-exclusive")
    if process.queue_permission not in {"no-access", "read-only", "consume", "modify-topic", "delete"}:
        raise ValueError(f"{process.id}: queue_permission is not a supported Solace permission")
    if not 0 <= process.max_redelivery_count <= 255:
        raise ValueError(f"{process.id}: max_redelivery_count must be between 0 and 255")
    if process.max_ttl_seconds < 0:
        raise ValueError(f"{process.id}: max_ttl_seconds must be greater than or equal to 0")
    if process.max_spool_usage_mb is not None and process.max_spool_usage_mb <= 0:
        raise ValueError(f"{process.id}: max_spool_usage_mb must be greater than 0")


def _validate_destination_type(process_id: str, value: str, field_name: str) -> None:
    if value not in {"QUEUE", "TOPIC"}:
        raise ValueError(f"{process_id}: {field_name} must be QUEUE or TOPIC")
