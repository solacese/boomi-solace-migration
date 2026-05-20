import pytest

from migrate.config import ConnectorProfile
from migrate.transform import TransformError, detect_queue_operations, transform_process
from migrate.xml_util import iter_local, parse_xml


SOURCE_TYPES = frozenset({"atomqueue", "queue"})
PROFILE = ConnectorProfile(
    sub_type="officialboomi-solace-pubsubplus",
    connection_fields={"host": "host", "vpn": "vpn", "username": "clientUsername", "password": "clientPassword"},
    operation_fields={"destination": "destination", "destination_type": "destinationType", "delivery_mode": "deliveryMode"},
)


class TestDetection:
    def test_detects_producer(self, producer_xml: str) -> None:
        result = detect_queue_operations(producer_xml, SOURCE_TYPES)
        assert result.migration_type == "producer"
        assert len(result.operations) == 1
        assert result.operations[0].action == "send"
        assert result.operations[0].connector_type == "atomqueue"

    def test_detects_consumer_mixed(self, consumer_xml: str) -> None:
        result = detect_queue_operations(consumer_xml, SOURCE_TYPES)
        assert result.migration_type == "consumer"
        assert len(result.operations) == 2
        actions = {op.action for op in result.operations}
        assert actions == {"listen", "get"}

    def test_ignores_non_queue_connectors(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="" version="1" name="Test" type="process" folderId="f">
          <bns:object><process><shapes>
            <shape shapetype="connectoraction">
              <connectoraction actionType="send" connectorType="http" connectionId="c" operationId="o"/>
            </shape>
          </shapes></process></bns:object>
        </bns:Component>"""
        result = detect_queue_operations(xml, SOURCE_TYPES)
        assert result.migration_type == "none"
        assert len(result.operations) == 0


class TestTransform:
    def test_transforms_producer(self, producer_xml: str) -> None:
        result_xml = transform_process(
            original_xml=producer_xml,
            process_name="Sample Producer",
            target_folder_id="target-folder-guid",
            source_connector_types=SOURCE_TYPES,
            profile=PROFILE,
            connection_id="new-conn-123",
            operation_ids={"send": "new-op-send-456"},
        )
        root = parse_xml(result_xml)
        assert root.get("componentId") == ""
        assert root.get("version") == "1"
        assert root.get("type") == "process"
        assert root.get("folderId") == "target-folder-guid"
        assert "Solace Migration" in root.get("name", "")
        assert root.get("folderFullPath") is None
        assert root.get("createdDate") is None

        for elem in iter_local(root, "connectoraction"):
            if elem.get("connectorType") == "officialboomi-solace-pubsubplus":
                assert elem.get("connectionId") == "new-conn-123"
                assert elem.get("operationId") == "new-op-send-456"
                assert elem.get("actionType") == "Send"

    def test_transforms_consumer(self, consumer_xml: str) -> None:
        result_xml = transform_process(
            original_xml=consumer_xml,
            process_name="Sample Consumer",
            target_folder_id="target-folder-guid",
            source_connector_types=SOURCE_TYPES,
            profile=PROFILE,
            connection_id="new-conn-789",
            operation_ids={"listen": "new-op-listen-111", "get": "new-op-get-222"},
        )
        root = parse_xml(result_xml)
        connectors = iter_local(root, "connectoraction")
        solace_connectors = [e for e in connectors if e.get("connectorType") == PROFILE.sub_type]
        assert len(solace_connectors) == 2

    def test_fails_on_no_operations(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="" version="1" name="Empty" type="process" folderId="f">
          <bns:object><process><shapes/></process></bns:object>
        </bns:Component>"""
        with pytest.raises(TransformError, match="no queue operations"):
            transform_process(
                original_xml=xml,
                process_name="Empty",
                target_folder_id="f",
                source_connector_types=SOURCE_TYPES,
                profile=PROFILE,
                connection_id="c",
                operation_ids={},
            )

    def test_fails_on_missing_operation_id(self, producer_xml: str) -> None:
        with pytest.raises(TransformError, match="No operation ID provided"):
            transform_process(
                original_xml=producer_xml,
                process_name="Test",
                target_folder_id="f",
                source_connector_types=SOURCE_TYPES,
                profile=PROFILE,
                connection_id="c",
                operation_ids={},
            )

    def test_no_source_connectors_remain(self, producer_xml: str) -> None:
        result_xml = transform_process(
            original_xml=producer_xml,
            process_name="Test",
            target_folder_id="f",
            source_connector_types=SOURCE_TYPES,
            profile=PROFILE,
            connection_id="c",
            operation_ids={"send": "op"},
        )
        root = parse_xml(result_xml)
        for elem in iter_local(root, "connectoraction"):
            ct = (elem.get("connectorType") or "").lower()
            assert ct not in SOURCE_TYPES
