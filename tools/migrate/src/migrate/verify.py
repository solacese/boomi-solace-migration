from __future__ import annotations

from .boomi import BoomiClient
from .config import ConnectorProfile
from .xml_util import iter_local, local_name, parse_xml


class VerificationError(Exception):
    pass


def verify_connection(client: BoomiClient, component_id: str, profile: ConnectorProfile) -> None:
    xml = client.get_component_xml(component_id)
    root = parse_xml(xml)

    if root.get("type") != "connector-settings":
        raise VerificationError(
            f"Connection {component_id}: type is '{root.get('type')}', expected 'connector-settings'"
        )

    for logical_name, field_id in profile.connection_fields.items():
        if logical_name == "password":
            continue
        found = False
        for elem in root.iter():
            if local_name(elem.tag) == "field" and elem.get("id") == field_id:
                value = elem.get("value", "")
                if not value:
                    raise VerificationError(
                        f"Connection {component_id}: field '{field_id}' ({logical_name}) is blank after creation"
                    )
                found = True
                break
        if not found:
            raise VerificationError(
                f"Connection {component_id}: field '{field_id}' ({logical_name}) not found in response"
            )


def verify_operation(
    client: BoomiClient,
    component_id: str,
    action: str,
    expected_destination: str,
    profile: ConnectorProfile,
) -> None:
    xml = client.get_component_xml(component_id)
    root = parse_xml(xml)

    if root.get("type") != "connector-action":
        raise VerificationError(
            f"Operation {component_id}: type is '{root.get('type')}', expected 'connector-action'"
        )

    dest_field_id = profile.operation_fields["destination"]
    found_dest = False
    for elem in root.iter():
        if local_name(elem.tag) == "field" and elem.get("id") == dest_field_id:
            value = elem.get("value", "")
            if not value:
                raise VerificationError(
                    f"Operation {component_id}: destination field is blank"
                )
            if value != expected_destination:
                raise VerificationError(
                    f"Operation {component_id}: destination is '{value}', expected '{expected_destination}'"
                )
            found_dest = True
            break
    if not found_dest:
        raise VerificationError(
            f"Operation {component_id}: destination field '{dest_field_id}' not found"
        )

    if action.lower() == "listen":
        for elem in root.iter():
            if local_name(elem.tag) == "GenericOperationConfig":
                op_type = elem.get("operationType", "")
                if op_type != "Listen":
                    raise VerificationError(
                        f"Operation {component_id}: Listen operation has operationType='{op_type}', must be 'Listen'"
                    )
                break


def verify_process(client: BoomiClient, component_id: str, source_connector_types: frozenset[str]) -> None:
    xml = client.get_component_xml(component_id)
    root = parse_xml(xml)

    if root.get("type") != "process":
        raise VerificationError(
            f"Process {component_id}: type is '{root.get('type')}', expected 'process'"
        )

    for elem in iter_local(root, "connectoraction"):
        ct = (elem.get("connectorType") or "").lower()
        if ct in source_connector_types:
            raise VerificationError(
                f"Process {component_id}: still contains source connector type '{ct}'"
            )
        action = (elem.get("actionType") or "").lower()
        if action in ("noaction", ""):
            continue
        conn_id = elem.get("connectionId", "")
        op_id = elem.get("operationId", "")
        if not conn_id and ct in ("wss", "http", ""):
            continue
        if not conn_id:
            raise VerificationError(f"Process {component_id}: connectoraction has empty connectionId")
        if not op_id:
            raise VerificationError(f"Process {component_id}: connectoraction has empty operationId")
