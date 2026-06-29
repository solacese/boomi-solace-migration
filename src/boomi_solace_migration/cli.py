from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .boomi_client import BoomiClient
from .detect import detect_queue_usage
from .execution import apply_plan, provision_solace_access_control, provision_solace_destinations, rollback_manifest
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
    plan.add_argument("--summary", action="store_true", help="Print human-readable plan summary")
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

    run = sub.add_parser("run", help="Run the full migration: plan → provision → apply → report")
    add_config_args(run)
    run.add_argument("--manifest", default="run-manifest.json")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--skip-provision", action="store_true", help="Skip Solace provisioning")
    run.add_argument("--report-output", default="migration-report.md")
    run.set_defaults(func=cmd_run)

    report = sub.add_parser("report", help="Generate markdown or JSON report from a manifest")
    report.add_argument("--manifest", required=True)
    report.add_argument("--output", required=True)
    report.set_defaults(func=cmd_report)
    return parser


DEFAULT_NAMING_POLICY: dict[str, Any] = {
    "queue": {
        "prefix": "boomi",
        "separator": "_",
        "max_length": 80,
        "solace_max_length": 200,
        "case": "lower",
        "collision_hash_length": 8,
        "allowed_pattern": "^[a-z0-9_.-]+$",
    },
    "topic": {
        "separator": "/",
        "max_length": 250,
        "max_levels": 128,
        "case": "camel",
        "collision_hash_length": 8,
        "domain": "boomi/migration",
        "verb": "published",
        "version": "v1",
        "taxonomy": "Domain/Noun/Verb/Version/Properties",
        "allowed_level_pattern": "^[A-Za-z0-9]+$",
        "require_domain_prefix": True,
        "allow_subscription_exceptions": False,
        "forbidden_levels": ["dev", "qa", "prod", "production", "staging"],
        "forbidden_terms": ["traceid", "spanid", "trace"],
    },
    "reserved_words": ["#DEAD_MSG_QUEUE", "default"],
}


def add_config_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True)
    parser.add_argument(
        "--connector-profile", default="",
        help="Path to connector profile YAML (optional if inline in config)",
    )
    parser.add_argument(
        "--naming-policy", default="",
        help="Path to naming policy YAML (optional — uses built-in defaults)",
    )


def load_inputs(args: argparse.Namespace) -> tuple[MigrationConfig, ConnectorProfile, NamingPolicy]:
    config = MigrationConfig.from_yaml(args.config)
    # Connector profile: CLI arg > inline in config > error
    if args.connector_profile:
        connector_profile = ConnectorProfile.from_yaml(args.connector_profile)
    elif config.inline_connector_profile:
        connector_profile = ConnectorProfile.from_dict(config.inline_connector_profile)
    else:
        raise ValueError(
            "Connector profile required: provide --connector-profile or include "
            "connector_profile section in the migration config"
        )
    # Naming policy: CLI arg > inline in config > built-in defaults
    if args.naming_policy:
        naming_policy = NamingPolicy.from_yaml(args.naming_policy)
    elif config.inline_naming_policy:
        naming_policy = NamingPolicy.from_dict(config.inline_naming_policy)
    else:
        naming_policy = NamingPolicy.from_dict(DEFAULT_NAMING_POLICY)
    return (config, connector_profile, naming_policy)


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
    if getattr(args, "summary", False):
        _print_plan_summary(plan)


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
        access_control_result = provision_solace_access_control(plan=plan, dry_run=bool(args.dry_run))
        print(json.dumps(redact({"solace_access_control": access_control_result}), indent=2, sort_keys=True))
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
    access_control_result = provision_solace_access_control(plan=plan, dry_run=bool(args.dry_run))
    print(json.dumps(redact(access_control_result), indent=2, sort_keys=True))
    result = provision_solace_destinations(plan=plan, dry_run=bool(args.dry_run))
    print(json.dumps(redact(result), indent=2, sort_keys=True))


def cmd_run(args: argparse.Namespace) -> None:
    """Full migration pipeline: plan → provision access control → provision queues → apply → report."""
    config, profile, naming_policy = load_inputs(args)
    issues: list[ValidationIssue] = []
    issues.extend(validate_json_schema(load_yaml(args.config), REPO_ROOT / "schemas/migration.schema.json"))
    fail_on_issues(issues)

    # 1. Plan
    plan = build_plan(config=config, connector_profile=profile, naming_policy=naming_policy)
    plan_path = config.output_dir / "migration-plan.json"
    print(f"✓ plan generated: {plan_path}")
    print(f"  plan_id={plan['plan_id']}")

    # 2. Summary
    _print_plan_summary(plan)

    # 3. Provision Solace (unless skipped)
    if not args.skip_provision:
        ac_result = provision_solace_access_control(plan=plan, dry_run=bool(args.dry_run))
        _print_provision_summary("access_control", ac_result)
        provision_result = provision_solace_destinations(plan=plan, dry_run=bool(args.dry_run))
        _print_provision_summary("queues", provision_result)
    else:
        print("  ⊘ Solace provisioning skipped")

    # 4. Apply to Boomi
    apply_result = apply_plan(
        plan=plan,
        manifest_path=args.manifest,
        dry_run=bool(args.dry_run),
    )
    successes = sum(1 for e in apply_result.get("entries", []) if e.get("status") == "success")
    failures = sum(1 for e in apply_result.get("entries", []) if e.get("status") == "failed")
    print(f"✓ apply complete: {successes} succeeded, {failures} failed")

    # 5. Report
    if not args.dry_run:
        manifest = load_manifest(args.manifest)
        write_report(manifest, args.report_output)
        print(f"✓ report: {args.report_output}")
    else:
        print("  (dry-run — no report generated)")


def _print_plan_summary(plan: dict[str, Any]) -> None:
    """Print a human-readable summary of the migration plan."""
    print("\n┌─ Migration Plan Summary ─────────────────────────────────")
    print(f"│ Processes: {len(plan['processes'])}")
    for proc in plan["processes"]:
        ops = ", ".join(f"{op['action']}→{op['destination']}" for op in proc["operations"])
        owner_info = f" [owner={proc.get('queue_owner')}]" if proc.get("queue_owner") else ""
        print(f"│   • {proc['process_name']}: {ops}{owner_info}")
    print("└──────────────────────────────────────────────────────────\n")


def _print_provision_summary(label: str, result: dict[str, Any]) -> None:
    if result.get("skipped"):
        print(f"  ⊘ {label}: {result['skipped']}")
        return
    items = result.get("results", [])
    created = sum(1 for r in items if r.get("status") == "created")
    exists = sum(1 for r in items if r.get("status") == "exists")
    updated = sum(1 for r in items if r.get("status") == "updated")
    dry_count = sum(1 for r in items if "would_" in r.get("status", ""))
    parts = []
    if created:
        parts.append(f"{created} created")
    if exists:
        parts.append(f"{exists} existing")
    if updated:
        parts.append(f"{updated} updated")
    if dry_count:
        parts.append(f"{dry_count} would-create")
    print(f"✓ {label}: {', '.join(parts) or 'none'}")


def cmd_report(args: argparse.Namespace) -> None:
    manifest = load_manifest(args.manifest)
    write_report(manifest, args.output)
    print(args.output)


if __name__ == "__main__":
    raise SystemExit(main())
