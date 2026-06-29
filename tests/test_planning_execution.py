from __future__ import annotations

import json
from pathlib import Path

from boomi_solace_migration.execution import (
    apply_plan,
    provision_solace_access_control,
    provision_solace_destinations,
    rollback_manifest,
)
from boomi_solace_migration.manifest import ManifestStore
from boomi_solace_migration.models import MigrationConfig
from boomi_solace_migration.planning import build_plan


def _config(tmp_path: Path) -> MigrationConfig:
    data = {
        "migration_version": "test",
        "output_dir": str(tmp_path / "out"),
        "target_folder_id": "target-folder",
        "connection": {
            "host": "smfs://example:55443",
            "vpn": "default",
            "username": "user",
            "password": "pass",
        },
        "defaults": {
            "send_destination_type": "TOPIC",
            "receive_destination_type": "QUEUE",
            "max_redelivery_count": 5,
            "max_ttl_seconds": 0,
            "max_spool_usage_mb": 5000,
        },
        "processes": [
            {
                "id": "producer-process",
                "name": "Sample Producer Process",
                "folder_id": "source-folder",
                "target_folder_id": "target-folder",
                "xml_path": "tests/fixtures/producer.xml",
            }
        ],
    }
    return MigrationConfig.from_dict(data, base_dir=tmp_path)


def _topic_to_queue_config(tmp_path: Path) -> MigrationConfig:
    data = {
        "migration_version": "test",
        "output_dir": str(tmp_path / "out"),
        "target_folder_id": "target-folder",
        "connection": {
            "host": "smfs://example:55443",
            "vpn": "default",
            "username": "user",
            "password": "pass",
        },
        "defaults": {
            "send_destination_type": "TOPIC",
            "receive_destination_type": "QUEUE",
            "max_redelivery_count": 5,
            "max_ttl_seconds": 0,
            "max_spool_usage_mb": 5000,
        },
        "processes": [
            {
                "id": "producer-process",
                "name": "Sample Producer Process",
                "folder_id": "source-folder",
                "target_folder_id": "target-folder",
                "xml_path": "tests/fixtures/producer.xml",
            },
            {
                "id": "consumer-process",
                "name": "Sample Consumer Process",
                "folder_id": "source-folder",
                "target_folder_id": "target-folder",
                "xml_path": "tests/fixtures/listen_consumer.xml",
                "topic_subscriptions": ["boomi/migration/sampleProducerProcess/published/v1"],
            },
        ],
    }
    return MigrationConfig.from_dict(data, base_dir=tmp_path)


def test_build_plan_is_deterministic(tmp_path, connector_profile, naming_policy) -> None:  # type: ignore[no-untyped-def]
    plan1 = build_plan(config=_config(tmp_path), connector_profile=connector_profile, naming_policy=naming_policy)
    plan2 = build_plan(config=_config(tmp_path), connector_profile=connector_profile, naming_policy=naming_policy)
    assert plan1["plan_id"] == plan2["plan_id"]
    assert Path(plan1["processes"][0]["planned_process_xml_path"]).read_text() == Path(
        plan2["processes"][0]["planned_process_xml_path"]
    ).read_text()


def test_plan_defaults_to_topic_publish_and_queue_consume(tmp_path, connector_profile, naming_policy) -> None:  # type: ignore[no-untyped-def]
    plan = build_plan(
        config=_topic_to_queue_config(tmp_path),
        connector_profile=connector_profile,
        naming_policy=naming_policy,
    )
    producer = plan["processes"][0]
    consumer = plan["processes"][1]

    assert producer["send_destination_type"] == "TOPIC"
    assert producer["operations"][0]["destination_type"] == "TOPIC"
    assert producer["send_destination"] == "boomi/migration/sampleProducerProcess/published/v1"
    assert consumer["receive_destination_type"] == "QUEUE"
    assert consumer["operations"][0]["destination_type"] == "QUEUE"
    assert consumer["topic_subscriptions"] == ["boomi/migration/sampleProducerProcess/published/v1"]


class FakeBoomiClient:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []

    def create_component(self, xml_body: str) -> str:
        component_id = f"id-{len(self.created) + 1}"
        self.created.append(xml_body)
        return component_id

    def delete_component(self, component_id: str) -> None:
        self.deleted.append(component_id)


def test_apply_plan_with_fake_client_and_rollback(tmp_path, connector_profile, naming_policy) -> None:  # type: ignore[no-untyped-def]
    plan = build_plan(config=_config(tmp_path), connector_profile=connector_profile, naming_policy=naming_policy)
    manifest_path = tmp_path / "run-manifest.json"
    client = FakeBoomiClient()
    manifest = apply_plan(
        plan=plan,
        manifest_path=manifest_path,
        dry_run=False,
        client=client,  # type: ignore[arg-type]
    )
    assert manifest["entries"][0]["status"] == "success"
    assert len(client.created) == 3

    rollback = rollback_manifest(
        manifest_path=manifest_path,
        dry_run=False,
        client=client,  # type: ignore[arg-type]
    )
    assert [item["component_id"] for item in rollback["deleted"]] == ["id-3", "id-2", "id-1"]
    assert client.deleted == ["id-3", "id-2", "id-1"]


def test_manifest_store_upserts(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "manifest.json"
    store = ManifestStore(path, plan_id="abc")
    store.upsert_entry({"process_id": "p1", "status": "running"})
    store.upsert_entry({"process_id": "p1", "status": "success"})
    data = json.loads(path.read_text(encoding="utf-8"))
    assert len(data["entries"]) == 1
    assert data["entries"][0]["status"] == "success"


def test_provision_solace_dry_run(tmp_path, connector_profile, naming_policy) -> None:  # type: ignore[no-untyped-def]
    plan = build_plan(
        config=_topic_to_queue_config(tmp_path),
        connector_profile=connector_profile,
        naming_policy=naming_policy,
    )
    result = provision_solace_destinations(plan=plan, dry_run=True)
    assert result["dry_run"] is True
    assert result["results"][0]["status"] == "would_validate_or_create"
    assert result["results"][0]["max_redelivery_count"] == 5
    assert result["results"][0]["topic_subscriptions"] == ["boomi/migration/sampleProducerProcess/published/v1"]


def test_operation_mappings_parsed_from_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = {
        "migration_version": "test",
        "output_dir": str(tmp_path / "out"),
        "target_folder_id": "target-folder",
        "connection": {"host": "smf://h:55555", "vpn": "v", "username": "u", "password": "p"},
        "processes": [
            {
                "id": "multi-dest",
                "name": "Multi Destination Process",
                "folder_id": "src-folder",
                "xml_path": "tests/fixtures/producer.xml",
                "operation_mappings": [
                    {
                        "original_connection_id": "conn-1",
                        "destination": "queue_a",
                        "destination_type": "QUEUE",
                        "delivery_mode": "PERSISTENT",
                    },
                    {
                        "original_connection_id": "conn-2",
                        "destination": "topic/b/published/v1",
                        "destination_type": "TOPIC",
                        "delivery_mode": "NON_PERSISTENT",
                    },
                ],
            }
        ],
    }
    config = MigrationConfig.from_dict(data, base_dir=tmp_path)
    proc = config.processes[0]
    assert len(proc.operation_mappings) == 2
    assert proc.operation_mappings[0].original_connection_id == "conn-1"
    assert proc.operation_mappings[0].destination == "queue_a"
    assert proc.operation_mappings[0].destination_type == "QUEUE"
    assert proc.operation_mappings[1].destination == "topic/b/published/v1"
    assert proc.operation_mappings[1].delivery_mode == "NON_PERSISTENT"


def test_inline_connector_profile_in_config(tmp_path) -> None:  # type: ignore[no-untyped-def]
    data = {
        "migration_version": "test",
        "output_dir": str(tmp_path / "out"),
        "target_folder_id": "target-folder",
        "connection": {"host": "smf://h:55555", "vpn": "v", "username": "u", "password": "p"},
        "connector_profile": {
            "sub_type": "inline-solace-connector",
            "connection_fields": {"host": "host", "vpn": "vpn", "username": "user", "password": "pw"},
            "operation_fields": {"destination": "dest", "destination_type": "dt", "delivery_mode": "dm"},
        },
        "naming_policy": {
            "queue": {"prefix": "test", "separator": "_", "max_length": 80, "case": "lower"},
            "topic": {"separator": "/", "max_length": 250, "case": "camel", "domain": "test/migration"},
        },
        "processes": [
            {"id": "p1", "name": "Proc One", "folder_id": "f1", "xml_path": "tests/fixtures/producer.xml"}
        ],
    }
    config = MigrationConfig.from_dict(data, base_dir=tmp_path)
    assert config.inline_connector_profile is not None
    assert config.inline_connector_profile["sub_type"] == "inline-solace-connector"
    assert config.inline_naming_policy is not None
    assert config.inline_naming_policy["queue"]["prefix"] == "test"


def test_provision_access_control_dry_run(tmp_path, connector_profile, naming_policy) -> None:  # type: ignore[no-untyped-def]
    # Override defaults to include queue_owner
    data = {
        "migration_version": "test",
        "output_dir": str(tmp_path / "out"),
        "target_folder_id": "target-folder",
        "connection": {"host": "smf://h:55555", "vpn": "v", "username": "u", "password": "p"},
        "defaults": {"queue_owner": "boomi_user", "queue_permission": "no-access"},
        "processes": [
            {"id": "p1", "name": "Proc", "folder_id": "f1", "xml_path": "tests/fixtures/producer.xml"}
        ],
    }
    config = MigrationConfig.from_dict(data, base_dir=tmp_path)
    plan = build_plan(config=config, connector_profile=connector_profile, naming_policy=naming_policy)
    result = provision_solace_access_control(plan=plan, dry_run=True)
    assert result["dry_run"] is True
    assert len(result["results"]) == 3
    assert result["results"][0]["acl_profile"] == "boomi_user"
    assert result["results"][1]["client_profile"] == "boomi_user"
    assert result["results"][2]["client_username"] == "boomi_user"


def test_provision_access_control_skips_when_no_owner(tmp_path, connector_profile, naming_policy) -> None:  # type: ignore[no-untyped-def]
    plan = build_plan(
        config=_config(tmp_path), connector_profile=connector_profile, naming_policy=naming_policy
    )
    result = provision_solace_access_control(plan=plan, dry_run=True)
    assert "skipped" in result
