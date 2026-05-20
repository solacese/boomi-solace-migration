import pytest

from migrate.config import ConnectorProfile
from migrate.verify import VerificationError, verify_connection, verify_operation, verify_process


PROFILE = ConnectorProfile(
    sub_type="officialboomi-solace-pubsubplus",
    connection_fields={"host": "host", "vpn": "vpn", "username": "clientUsername", "password": "clientPassword"},
    operation_fields={"destination": "destination", "destination_type": "destinationType", "delivery_mode": "deliveryMode"},
)


class FakeBoomiClient:
    def __init__(self, xml_response: str) -> None:
        self._xml = xml_response

    def get_component_xml(self, component_id: str) -> str:
        return self._xml


class TestVerifyConnection:
    def test_passes_valid_connection(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="c1" type="connector-settings" subType="officialboomi-solace-pubsubplus" name="Conn" folderId="f" version="1">
          <bns:object>
            <GenericConnectionConfig>
              <field id="host" type="string" value="tcp://broker:55555"/>
              <field id="vpn" type="string" value="default"/>
              <field id="clientUsername" type="string" value="admin"/>
              <field id="clientPassword" type="password" value="secret"/>
            </GenericConnectionConfig>
          </bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        verify_connection(client, "c1", PROFILE)

    def test_fails_on_blank_field(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="c1" type="connector-settings" subType="x" name="Conn" folderId="f" version="1">
          <bns:object>
            <GenericConnectionConfig>
              <field id="host" type="string" value=""/>
              <field id="vpn" type="string" value="default"/>
              <field id="clientUsername" type="string" value="admin"/>
              <field id="clientPassword" type="password" value="secret"/>
            </GenericConnectionConfig>
          </bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="blank"):
            verify_connection(client, "c1", PROFILE)

    def test_fails_on_wrong_type(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="c1" type="connector-action" name="X" folderId="f" version="1">
          <bns:object><GenericConnectionConfig/></bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="connector-settings"):
            verify_connection(client, "c1", PROFILE)


class TestVerifyOperation:
    def test_passes_valid_send(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="o1" type="connector-action" subType="x" name="Op" folderId="f" version="1">
          <bns:object>
            <Operation>
              <Configuration>
                <GenericOperationConfig customOperationType="SEND" operationType="EXECUTE">
                  <field id="destination" type="string" value="my/topic/v1"/>
                  <field id="destinationType" type="string" value="TOPIC"/>
                  <field id="deliveryMode" type="string" value="PERSISTENT"/>
                </GenericOperationConfig>
              </Configuration>
            </Operation>
          </bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        verify_operation(client, "o1", "send", "my/topic/v1", PROFILE)

    def test_fails_on_wrong_destination(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="o1" type="connector-action" subType="x" name="Op" folderId="f" version="1">
          <bns:object>
            <Operation>
              <Configuration>
                <GenericOperationConfig customOperationType="SEND" operationType="EXECUTE">
                  <field id="destination" type="string" value="wrong/topic"/>
                </GenericOperationConfig>
              </Configuration>
            </Operation>
          </bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="expected"):
            verify_operation(client, "o1", "send", "correct/topic/v1", PROFILE)

    def test_fails_on_listen_wrong_operation_type(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="o1" type="connector-action" subType="x" name="Op" folderId="f" version="1">
          <bns:object>
            <Operation>
              <Configuration>
                <GenericOperationConfig customOperationType="LISTEN" operationType="EXECUTE">
                  <field id="destination" type="string" value="my_queue"/>
                </GenericOperationConfig>
              </Configuration>
            </Operation>
          </bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="Listen"):
            verify_operation(client, "o1", "listen", "my_queue", PROFILE)


class TestVerifyProcess:
    def test_passes_valid_process(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="p1" type="process" name="Migrated" folderId="f" version="1">
          <bns:object><process><shapes>
            <shape shapetype="connectoraction">
              <connectoraction actionType="Send" connectorType="officialboomi-solace-pubsubplus" connectionId="c1" operationId="o1"/>
            </shape>
          </shapes></process></bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        verify_process(client, "p1", frozenset({"atomqueue", "queue"}))

    def test_fails_if_source_connector_remains(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="p1" type="process" name="Bad" folderId="f" version="1">
          <bns:object><process><shapes>
            <shape shapetype="connectoraction">
              <connectoraction actionType="send" connectorType="atomqueue" connectionId="c" operationId="o"/>
            </shape>
          </shapes></process></bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="source connector"):
            verify_process(client, "p1", frozenset({"atomqueue", "queue"}))

    def test_fails_if_not_process_type(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="p1" type="connector-settings" name="Bad" folderId="f" version="1">
          <bns:object/></bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="expected 'process'"):
            verify_process(client, "p1", frozenset({"atomqueue"}))

    def test_fails_on_empty_ids(self) -> None:
        xml = """<?xml version='1.0' encoding='UTF-8'?>
        <bns:Component xmlns:bns="http://api.platform.boomi.com/" componentId="p1" type="process" name="Bad" folderId="f" version="1">
          <bns:object><process><shapes>
            <shape shapetype="connectoraction">
              <connectoraction actionType="Send" connectorType="solace" connectionId="" operationId="o1"/>
            </shape>
          </shapes></process></bns:object>
        </bns:Component>"""
        client = FakeBoomiClient(xml)
        with pytest.raises(VerificationError, match="empty connectionId"):
            verify_process(client, "p1", frozenset({"atomqueue"}))
