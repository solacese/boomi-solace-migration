from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from typing import Any

from .boomi import BoomiClient, BoomiError
from .component import build_connection_xml, build_operation_xml
from .config import ConfigError, MigrationConfig, ProcessEntry
from .solace import SolaceClient, SolaceError
from .transform import TransformError, detect_queue_operations, transform_process
from .verify import VerificationError, verify_connection, verify_operation, verify_process


@dataclass
class MigrationResult:
    process_name: str
    connection_id: str
    operation_ids: dict[str, str]
    process_id: str


def migrate(config: MigrationConfig, *, dry_run: bool = False) -> list[MigrationResult]:
    print("=== Boomi → Solace Migration ===\n")

    boomi = BoomiClient(config.boomi)
    solace = SolaceClient(config.solace_semp)

    print("[1/5] Checking Boomi authentication...")
    boomi.check_auth()
    print("      OK\n")

    print("[2/5] Checking Solace SEMP connectivity...")
    solace.check_auth()
    print("      OK\n")

    print(f"[3/5] Migrating {len(config.processes)} process(es)...\n")

    results: list[MigrationResult] = []
    created_components: list[str] = []

    for i, proc in enumerate(config.processes, 1):
        print(f"  --- Process {i}/{len(config.processes)}: {proc.name} ---")
        try:
            result = _migrate_process(
                proc=proc,
                config=config,
                boomi=boomi,
                solace=solace,
                dry_run=dry_run,
                created_components=created_components,
            )
            results.append(result)
            print(f"      DONE: process_id={result.process_id}\n")
        except (BoomiError, SolaceError, TransformError, VerificationError) as exc:
            print(f"\n  FAILED: {exc}", file=sys.stderr)
            if created_components:
                print(f"\n  Components created before failure (may need cleanup):", file=sys.stderr)
                for cid in created_components:
                    print(f"    - {cid}", file=sys.stderr)
            raise

    print("[4/5] All processes migrated successfully.\n")
    print("[5/5] Summary:")
    for r in results:
        print(f"  {r.process_name}:")
        print(f"    connection = {r.connection_id}")
        for action, op_id in r.operation_ids.items():
            print(f"    {action}_operation = {op_id}")
        print(f"    process = {r.process_id}")
    print()
    return results


def _migrate_process(
    *,
    proc: ProcessEntry,
    config: MigrationConfig,
    boomi: BoomiClient,
    solace: SolaceClient,
    dry_run: bool,
    created_components: list[str],
) -> MigrationResult:
    print(f"      Fetching original process XML...")
    original_xml = boomi.get_component_xml(proc.id)

    print(f"      Detecting queue operations...")
    detection = detect_queue_operations(original_xml, config.source_connector_types)
    if not detection.operations:
        raise TransformError(f"No queue operations found in process '{proc.name}'")
    actions = sorted({op.action for op in detection.operations})
    print(f"      Found: {len(detection.operations)} operations, actions={', '.join(actions)} ({detection.migration_type})")

    if proc.provision_queue:
        _provision_queues(proc, solace, dry_run)

    if dry_run:
        print("      [DRY RUN] Would create connection, operations, and process")
        return MigrationResult(
            process_name=proc.name,
            connection_id="<dry-run>",
            operation_ids={a: "<dry-run>" for a in actions},
            process_id="<dry-run>",
        )

    print(f"      Creating Solace connection component...")
    connection_xml = build_connection_xml(
        name=f"{proc.name} - Solace Connection",
        folder_id=config.target_folder_id,
        profile=config.connector_profile,
        values=config.connection,
    )
    connection_id = boomi.create_component(connection_xml)
    created_components.append(connection_id)
    print(f"      → connection_id={connection_id}")

    print(f"      Verifying connection...")
    verify_connection(boomi, connection_id, config.connector_profile)
    print(f"      → verified")

    operation_ids: dict[str, str] = {}
    connection_operation_map: dict[str, str] = {}

    if proc.operation_mappings:
        for mapping in proc.operation_mappings:
            dest = mapping.destination
            dest_type = mapping.destination_type
            print(f"      Creating send operation (dest={dest}, type={dest_type})...")
            op_xml = build_operation_xml(
                name=f"{proc.name} - Solace Send {dest}",
                folder_id=config.target_folder_id,
                profile=config.connector_profile,
                action="send",
                destination=dest,
                destination_type=dest_type,
                delivery_mode=mapping.delivery_mode,
            )
            op_id = boomi.create_component(op_xml)
            connection_operation_map[mapping.original_connection_id] = op_id
            created_components.append(op_id)
            print(f"      → operation_id={op_id} (for conn {mapping.original_connection_id})")

            print(f"      Verifying operation...")
            verify_operation(boomi, op_id, "send", dest, config.connector_profile)
            print(f"      → verified")
    else:
        for action in actions:
            dest = proc.send_destination if action == "send" else proc.receive_destination
            dest_type = proc.send_destination_type if action == "send" else proc.receive_destination_type
            if not dest:
                raise TransformError(
                    f"Process '{proc.name}': action '{action}' requires a destination but none configured"
                )
            print(f"      Creating {action} operation (dest={dest}, type={dest_type})...")
            op_xml = build_operation_xml(
                name=f"{proc.name} - Solace {action.title()} Operation",
                folder_id=config.target_folder_id,
                profile=config.connector_profile,
                action=action,
                destination=dest,
                destination_type=dest_type,
                delivery_mode=proc.delivery_mode,
            )
            op_id = boomi.create_component(op_xml)
            operation_ids[action] = op_id
            created_components.append(op_id)
            print(f"      → {action}_operation_id={op_id}")

            print(f"      Verifying {action} operation...")
            verify_operation(boomi, op_id, action, dest, config.connector_profile)
            print(f"      → verified")

    print(f"      Transforming process XML...")
    transformed_xml = transform_process(
        original_xml=original_xml,
        process_name=proc.name,
        target_folder_id=config.target_folder_id,
        source_connector_types=config.source_connector_types,
        profile=config.connector_profile,
        connection_id=connection_id,
        operation_ids=operation_ids,
        connection_operation_map=connection_operation_map or None,
    )

    print(f"      Creating migrated process...")
    process_id = boomi.create_component(transformed_xml)
    created_components.append(process_id)
    print(f"      → process_id={process_id}")

    print(f"      Verifying process...")
    verify_process(boomi, process_id, config.source_connector_types)
    print(f"      → verified")

    return MigrationResult(
        process_name=proc.name,
        connection_id=connection_id,
        operation_ids=operation_ids if operation_ids else connection_operation_map,
        process_id=process_id,
    )


def _provision_queues(proc: ProcessEntry, solace: SolaceClient, dry_run: bool) -> None:
    queues_to_provision: list[str] = []
    if proc.receive_destination and proc.receive_destination_type == "QUEUE":
        queues_to_provision.append(proc.receive_destination)
    if proc.send_destination and proc.send_destination_type == "QUEUE":
        queues_to_provision.append(proc.send_destination)
    for mapping in proc.operation_mappings:
        if mapping.destination_type == "QUEUE":
            queues_to_provision.append(mapping.destination)

    for queue_name in queues_to_provision:
        if dry_run:
            print(f"      [DRY RUN] Would ensure queue: {queue_name}")
            continue
        print(f"      Ensuring Solace queue: {queue_name}")
        result = solace.ensure_queue(queue_name)
        print(f"      → {result['status']}")


def cli() -> int:
    parser = argparse.ArgumentParser(
        prog="boomi-solace-migrate",
        description="Migrate Boomi Atom Queue processes to Solace PubSub+",
    )
    parser.add_argument("--config", required=True, help="Path to migration.yaml")
    parser.add_argument("--dry-run", action="store_true", help="Validate and print actions without executing")
    args = parser.parse_args()

    try:
        config = MigrationConfig.load(args.config)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 1

    try:
        migrate(config, dry_run=args.dry_run)
    except (BoomiError, SolaceError, TransformError, VerificationError) as exc:
        print(f"\nMigration failed: {exc}", file=sys.stderr)
        return 1

    return 0
