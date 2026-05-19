from __future__ import annotations

import pytest

from boomi_solace_migration.component_builder import (
    build_connection_component_xml,
    build_consumer_set_properties_snippet,
    build_operation_component_xml,
)
from boomi_solace_migration.transform import transform_process_xml
from boomi_solace_migration.validation import (
    validate_connection_xml,
    validate_operation_xml,
    validate_transformed_process_xml,
)


def test_transform_producer_adds_user_properties(fixture_dir, connector_profile) -> None:  # type: ignore[no-untyped-def]
    xml = (fixture_dir / "producer.xml").read_text(encoding="utf-8")
    result = transform_process_xml(
        original_xml=xml,
        process_name="Sample Producer Process",
        target_folder_id="target-folder",
        source_connector_types={"atomqueue", "queue"},
        profile=connector_profile,
        connection_id="new-conn",
        operation_ids={"send": "new-send-op"},
    )
    assert 'connectorType="officialboomi-solace-pubsubplus"' in result.xml
    assert 'connectionId="new-conn"' in result.xml
    assert 'operationId="new-send-op"' in result.xml
    assert 'childKey="entityId"' in result.xml
    assert "currentVersion" not in result.xml
    assert not validate_transformed_process_xml(
        result.xml,
        profile=connector_profile,
        source_connector_types={"atomqueue", "queue"},
    )


def test_transform_does_not_duplicate_existing_user_property(fixture_dir, connector_profile) -> None:  # type: ignore[no-untyped-def]
    xml = (fixture_dir / "existing_dynamic_properties.xml").read_text(encoding="utf-8")
    result = transform_process_xml(
        original_xml=xml,
        process_name="Sample Dynamic Property Fixture",
        target_folder_id="target-folder",
        source_connector_types={"atomqueue", "queue"},
        profile=connector_profile,
        connection_id="new-conn",
        operation_ids={"send": "new-send-op"},
    )
    assert result.xml.count('childKey="entityId"') == 1


def test_unknown_queue_like_connector_fails(fixture_dir, connector_profile) -> None:  # type: ignore[no-untyped-def]
    xml = (fixture_dir / "unsupported_queue_variant.xml").read_text(encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown queue-like"):
        transform_process_xml(
            original_xml=xml,
            process_name="Sample Unsupported Connector Fixture",
            target_folder_id="target-folder",
            source_connector_types={"atomqueue", "queue"},
            profile=connector_profile,
            connection_id="new-conn",
            operation_ids={"send": "new-send-op"},
        )


def test_component_builders_validate(connector_profile) -> None:  # type: ignore[no-untyped-def]
    connection_xml = build_connection_component_xml(
        component_name="Test Connection",
        folder_id="folder",
        profile=connector_profile,
        values={
            "host": "smfs://example:55443",
            "vpn": "default",
            "username": "user",
            "password": "pass",
        },
        metadata={"source_process_id": "p1"},
    )
    assert not validate_connection_xml(connection_xml, connector_profile)

    listen_xml = build_operation_component_xml(
        action="listen",
        component_name="Listen",
        folder_id="folder",
        profile=connector_profile,
        destination="sample-queue",
        destination_type="QUEUE",
        delivery_mode="PERSISTENT",
        metadata={},
    )
    assert 'operationType="Listen"' in listen_xml
    assert not validate_operation_xml(listen_xml)


def test_consumer_set_properties_snippet(connector_profile) -> None:  # type: ignore[no-untyped-def]
    snippet = build_consumer_set_properties_snippet(["DDP_ENTITY_ID"], connector_profile)
    assert 'connectorSource="User Properties"' in snippet
    assert 'connectorProperty="entityId"' in snippet
