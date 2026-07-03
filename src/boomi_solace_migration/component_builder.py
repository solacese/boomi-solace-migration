from __future__ import annotations

import xml.etree.ElementTree as ET

from .models import ConnectorProfile
from .naming import ddp_to_user_property
from .xml_io import BNS, qname, tostring


def _component_root(
    *,
    name: str,
    component_type: str,
    sub_type: str,
    folder_id: str,
) -> ET.Element:
    return ET.Element(
        qname(BNS, "Component"),
        {
            "version": "1",
            "name": name,
            "type": component_type,
            "subType": sub_type,
            "folderId": folder_id,
        },
    )


def _description(root: ET.Element, text: str) -> None:
    elem = ET.SubElement(root, qname(BNS, "description"))
    elem.text = text


def build_connection_component_xml(
    *,
    component_name: str,
    folder_id: str,
    profile: ConnectorProfile,
    values: dict[str, str],
    metadata: dict[str, str],
) -> str:
    root = _component_root(
        name=component_name,
        component_type="connector-settings",
        sub_type=profile.sub_type,
        folder_id=folder_id,
    )
    encrypted = ET.SubElement(root, qname(BNS, "encryptedValues"))
    password_field = profile.connection_fields["password"]
    ET.SubElement(
        encrypted,
        qname(BNS, "encryptedValue"),
        {"isSet": "true", "path": f"//GenericConnectionConfig/field[@id='{password_field}']"},
    )
    _description(root, _metadata_description(metadata))
    obj = ET.SubElement(root, qname(BNS, "object"))
    config = ET.SubElement(obj, "GenericConnectionConfig")
    field_map = {
        "host": values["host"],
        "vpn": values["vpn"],
        "username": values["username"],
        "password": values["password"],
    }
    for logical_name, value in field_map.items():
        field_type = "password" if logical_name == "password" else "string"
        ET.SubElement(
            config,
            "field",
            {
                "id": profile.connection_fields[logical_name],
                "type": field_type,
                "value": value,
            },
        )
    return tostring(root)


def build_operation_component_xml(
    *,
    action: str,
    component_name: str,
    folder_id: str,
    profile: ConnectorProfile,
    destination: str,
    destination_type: str,
    delivery_mode: str,
    metadata: dict[str, str],
) -> str:
    action_key = action.lower()
    if action_key not in {"send", "listen", "get"}:
        raise ValueError(f"Unsupported operation action: {action}")

    root = _component_root(
        name=component_name,
        component_type="connector-action",
        sub_type=profile.sub_type,
        folder_id=folder_id,
    )
    ET.SubElement(root, qname(BNS, "encryptedValues"))
    _description(root, _metadata_description(metadata))
    obj = ET.SubElement(root, qname(BNS, "object"))

    if action_key == "send":
        operation_attrs = {"returnApplicationErrors": "false", "trackResponse": "false"}
        generic_attrs = {
            "customOperationType": "SEND",
            "operationType": "EXECUTE",
            "requestProfileType": "binary",
            "responseProfileType": "none",
        }
    elif action_key == "listen":
        operation_attrs = {"returnApplicationErrors": "false", "trackResponse": "true"}
        generic_attrs = {
            "customOperationType": "LISTEN",
            "operationType": "Listen",
            "requestProfileType": "none",
            "responseProfileType": "binary",
        }
    else:
        operation_attrs = {"returnApplicationErrors": "false", "trackResponse": "true"}
        generic_attrs = {
            "customOperationType": "GET",
            "operationType": "EXECUTE",
            "requestProfileType": "none",
            "responseProfileType": "binary",
        }

    operation = ET.SubElement(obj, "Operation", operation_attrs)
    ET.SubElement(operation, "Archiving", {"directory": "", "enabled": "false"})
    configuration = ET.SubElement(operation, "Configuration")
    generic = ET.SubElement(configuration, "GenericOperationConfig", generic_attrs)
    ET.SubElement(
        generic,
        "field",
        {"id": profile.operation_fields["destination"], "type": "string", "value": destination},
    )
    ET.SubElement(
        generic,
        "field",
        {
            "id": profile.operation_fields["destination_type"],
            "type": "string",
            "value": destination_type,
        },
    )
    if action_key == "send":
        ET.SubElement(
            generic,
            "field",
            {
                "id": profile.operation_fields["delivery_mode"],
                "type": "string",
                "value": delivery_mode,
            },
        )
    ET.SubElement(generic, "Options")
    tracking = ET.SubElement(operation, "Tracking")
    ET.SubElement(tracking, "TrackedFields")
    ET.SubElement(operation, "Caching")
    return tostring(root)


def build_consumer_set_properties_snippet(ddps: list[str], profile: ConnectorProfile) -> str:
    connector_operation = profile.user_properties.get("connector_operation")
    connector_source = profile.user_properties.get("connector_source")
    if not ddps or not connector_operation or not connector_source:
        return ""
    shape = ET.Element("shape", {"shapetype": "documentproperties", "userlabel": "Extract User Properties"})
    setproperties = ET.SubElement(shape, "setproperties")
    for ddp in ddps:
        property_value = ET.SubElement(
            setproperties,
            "propertyvalue",
            {"childKey": ddp, "valueType": "connector"},
        )
        ET.SubElement(
            property_value,
            "connectorparameter",
            {
                "connectorOperation": connector_operation,
                "connectorProperty": ddp_to_user_property(ddp),
                "connectorSource": connector_source,
            },
        )
    return ET.tostring(shape, encoding="unicode")


def _metadata_description(metadata: dict[str, str]) -> str:
    if not metadata:
        return "Generated by boomi-solace-migration."
    pairs = [f"{key}={value}" for key, value in sorted(metadata.items())]
    return "Generated by boomi-solace-migration; " + "; ".join(pairs)
