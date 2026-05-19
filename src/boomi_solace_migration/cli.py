from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .boomi_client import BoomiClient
from .detect import detect_queue_usage
from .execution import apply_plan, provision_solace_destinations, rollback_manifest
from .manifest import load_manifest
from .models import ConnectorProfile, MigrationConfig, NamingPolicy, load_yaml
from .planning import build_plan, load_plan
from .redaction import redact
from .reporting import write_report
from .validation import ValidationIssue, fail_on_issues, validate_json_schema

REPO_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except Exception as exc:
        print(f"error: {exc}")
        return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="boomi-solace")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="Inventory processes and Atom Queue usage")
    add_config_args(discover)
    discover.add_argument("--output", default="inventory.json")
    discover.add_argument("--online", action="store_true", help="Use Boomi API instead of local xml_path entries")
    discover.set_defaults(func=cmd_discover)

    plan = sub.add_parser("plan", help="Generate a deterministic offline migration plan")
    add_config_args(plan)
    plan.set_defaults(func=cmd_plan)

    pipeline = sub.add_parser("pipeline", help="Run the safe Solace migration pipeline")
    add_config_args(pipeline)
    pipeline.add_argument("--manifest", default="run-manifest.json")
    pipeline.add_argument("--provision-solace", action="store_true")
    pipeline.add_argument("--apply", action="store_true")
    pipeline.add_argument("--dry-run", action="store_true")
    pipeline.set_defaults(func=cmd_pipeline)

    validate = sub.add_parser("validate", help="Validate config, schemas, and optional plan")
    add_config_args(validate)
    validate.add_argument("--plan", default="")
    validate.add_argument("--offline-only", action="store_true")
    validate.set_defaults(func=cmd_validate)

    apply = sub.add_parser("apply", help="Apply a generated migration plan to Boomi")
    apply.add_argument("--plan", required=True)
    apply.add_argument("--manifest", default="run-manifest.json")
    apply.add_argument("--dry-run", action="store_true")
    apply.set_defaults(func=cmd_apply)

    rollback = sub.add_parser("rollback", help="Delete only components recorded in a manifest")
    rollback.add_argument("--manifest", required=True)
    rollback.add_argument("--dry-run", action="store_true")
    rollback.set_defaults(func=cmd_rollback)

    provision = sub.add_parser("provision-solace", help="Validate or create Solace queues via SEMP")
    provision.add_argument("--plan", required=True)
    provision.add_argument("--dry-run", action="store_true")
    provision.set_defaults(func=cmd_provision_solace)

    report = sub.add_parser("report", help="Generate markdown or JSON report from a manifest")
    report.add_argument("--manifest", required=True)
    report.add_argument("--output", required=True)
    report.set_defaults(func=cmd_report)
    return parser


def add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument("--connector-profile", required=True)
    parser.add_argument("--naming-policy", required=True)


def load_inputs(args: argparse.Namespace) -> tuple[MigrationConfig, ConnectorProfile, NamingPolicy]:
    return (
        MigrationConfig.from_yaml(args.config),
        ConnectorProfile.from_yaml(args.connector_profile),
        NamingPolicy.from_yaml(args.naming_policy),
    )


def cmd_discover(args: argparse.Namespace) -> None:
    config, _, _ = load_inputs(args)
    processes: list[dict[str, Any]] = []
    if args.online:
        client = BoomiClient.from_env()
        for proc in client.list_processes():
            xml = client.get_component_xml(proc["id"])
            detection = detect_queue_usage(xml, config.source_connector_types)
            if detection.operations:
                processes.append(
                    {
                        "id": proc["id"],
                        "name": proc.get("name", ""),
                        "folder_id": proc.get("folderId", ""),
                        "migration_type": detection.migration_type,
                        "operations": [op.__dict__ for op in detection.operations],
                        "ddps": detection.ddps,
                    }
                )
    else:
        for configured_process in config.processes:
            if configured_process.xml_path is None:
                continue
            path = (
                configured_process.xml_path
                if configured_process.xml_path.is_absolute()
                else Path.cwd() / configured_process.xml_path
            )
            xml = path.read_text(encoding="utf-8")
            detection = detect_queue_usage(xml, config.source_connector_types)
            processes.append(
                {
                    "id": configured_process.id,
                    "name": configured_process.name,
                    "folder_id": configured_process.folder_id,
                    "xml_path": str(path),
                    "migration_type": detection.migration_type,
                    "operations": [op.__dict__ for op in detection.operations],
                    "ddps": detection.ddps,
                    "unknown_queue_like_connectors": detection.unknown_queue_like_connectors,
                    "unsupported_actions": detection.unsupported_actions,
                }
            )
    output = {
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "processes": processes,
    }
    Path(args.output).write_text(json.dumps(redact(output), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(args.output)


def cmd_plan(args: argparse.Namespace) -> None:
    config, profile, naming_policy = load_inputs(args)
    plan = build_plan(config=config, connector_profile=profile, naming_policy=naming_policy)
    print(config.output_dir / "migration-plan.json")
    print(f"plan_id={plan['plan_id']}")


def cmd_pipeline(args: argparse.Namespace) -> None:
    config, profile, naming_policy = load_inputs(args)
    issues: list[ValidationIssue] = []
    issues.extend(validate_json_schema(load_yaml(args.config), REPO_ROOT / "schemas/migration.schema.json"))
    issues.extend(
        validate_json_schema(
            load_yaml(args.connector_profile),
            REPO_ROOT / "schemas/connector-profile.schema.json",
        )
    )
    issues.extend(
        validate_json_schema(
            load_yaml(args.naming_policy),
            REPO_ROOT / "schemas/naming-policy.schema.json",
        )
    )
    fail_on_issues(issues)
    plan = build_plan(config=config, connector_profile=profile, naming_policy=naming_policy)
    plan_path = config.output_dir / "migration-plan.json"
    print(f"planned={plan_path}")
    print(f"plan_id={plan['plan_id']}")

    if args.provision_solace:
        provision_result = provision_solace_destinations(plan=plan, dry_run=bool(args.dry_run))
        print(json.dumps(redact({"solace": provision_result}), indent=2, sort_keys=True))

    if args.apply:
        apply_result = apply_plan(
            plan=plan,
            manifest_path=args.manifest,
            dry_run=bool(args.dry_run),
        )
        print(json.dumps(redact({"boomi": apply_result}), indent=2, sort_keys=True))
    else:
        print("apply_skipped=true")


def cmd_validate(args: argparse.Namespace) -> None:
    issues: list[ValidationIssue] = []
    issues.extend(validate_json_schema(load_yaml(args.config), REPO_ROOT / "schemas/migration.schema.json"))
    issues.extend(
        validate_json_schema(
            load_yaml(args.connector_profile),
            REPO_ROOT / "schemas/connector-profile.schema.json",
        )
    )
    issues.extend(
        validate_json_schema(
            load_yaml(args.naming_policy),
            REPO_ROOT / "schemas/naming-policy.schema.json",
        )
    )
    if args.plan:
        plan = load_plan(args.plan)
        issues.extend(validate_json_schema(plan, REPO_ROOT / "schemas/plan.schema.json"))
    fail_on_issues(issues)
    print("validation ok")


def cmd_apply(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    result = apply_plan(plan=plan, manifest_path=args.manifest, dry_run=bool(args.dry_run))
    print(json.dumps(redact(result), indent=2, sort_keys=True))


def cmd_rollback(args: argparse.Namespace) -> None:
    result = rollback_manifest(manifest_path=args.manifest, dry_run=bool(args.dry_run))
    print(json.dumps(result, indent=2, sort_keys=True))


def cmd_provision_solace(args: argparse.Namespace) -> None:
    plan = load_plan(args.plan)
    result = provision_solace_destinations(plan=plan, dry_run=bool(args.dry_run))
    print(json.dumps(redact(result), indent=2, sort_keys=True))


def cmd_report(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    write_report(manifest, args.output)
    print(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
