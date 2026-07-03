from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .detect import DetectionResult, detect_queue_usage
from .models import ConnectorProfile
from .naming import ddp_to_user_property
from .xml_io import find_child_local, iter_local, local_name, parse_xml, remove_read_only_attributes, tostring

ACTION_MAP = {"send": "Send", "listen": "Listen", "get": "Get"}
LABEL_MAP = {"send": "Send Message", "listen": "Listen on Solace Queue", "get": "Receive from Solace Queue"}


@dataclass(frozen=True)
class TransformResult:
    xml: str
    detection: DetectionResult
    ddp_user_properties: dict[str, str]


def transform_process_xml(
    *,
    original_xml: str,
    process_name: str,
    target_folder_id: str,
    source_connector_types: set[str],
    profile: ConnectorProfile,
    connection_id: str,
    operation_ids: dict[str, str],
    strict: bool = True,
) -> TransformResult:
    detection = detect_queue_usage(original_xml, source_connector_types)
    if strict:
        if detection.unknown_queue_like_connectors:
            raise ValueError(
                "Unknown queue-like connectors found: "
                + ", ".join(detection.unknown_queue_like_connectors)
            )
        if detection.unsupported_actions:
            raise ValueError("Unsupported Atom Queue actions found: " + ", ".join(detection.unsupported_actions))
        if not detection.operations:
            raise ValueError("No Atom Queue operations found")

    root = parse_xml(original_xml)
    root.set("componentId", "")
    root.set("version", "1")
    # Keep original process name — do not rename migrated processes
    root.set("folderId", target_folder_id)
    remove_read_only_attributes(root)

    ddp_user_properties = {ddp: ddp_to_user_property(ddp) for ddp in detection.ddps}

    for elem in iter_local(root, "connectoraction"):
        connector_type = (elem.get("connectorType") or "").lower()
        if connector_type not in source_connector_types:
            continue
        action_key = (elem.get("actionType") or "").lower()
        if action_key not in ACTION_MAP:
            if strict:
                raise ValueError(f"Unsupported Atom Queue action: {action_key}")
            continue
        operation_id = operation_ids.get(action_key)
        if not operation_id and strict:
            raise ValueError(f"Missing operation id for action: {action_key}")

        elem.set("connectorType", profile.sub_type)
        elem.set("actionType", ACTION_MAP[action_key])
        elem.set("connectionId", connection_id)
        elem.set("operationId", operation_id or "")
        if action_key == "send" and detection.ddps:
            _add_user_property_mappings(elem, ddp_user_properties)

    for shape in iter_local(root, "shape"):
        label = shape.get("userlabel", "")
        if "queue" not in label.lower():
            continue
        action_key = _shape_action(shape)
        if action_key in LABEL_MAP:
            shape.set("userlabel", LABEL_MAP[action_key])

    return TransformResult(xml=tostring(root), detection=detection, ddp_user_properties=ddp_user_properties)


def _shape_action(shape: ET.Element) -> str:
    for child in shape.iter():
        if local_name(child.tag) == "connectoraction":
            return (child.get("actionType") or "").lower()
    return ""


def _add_user_property_mappings(
    connector_action: ET.Element,
    ddp_user_properties: dict[str, str],
) -> None:
    dynamic_properties = find_child_local(connector_action, "dynamicProperties")
    if dynamic_properties is None:
        dynamic_properties = ET.SubElement(connector_action, "dynamicProperties")
    existing = {
        child.get("childKey", "")
        for child in dynamic_properties
        if local_name(child.tag) == "propertyvalue" and child.get("key") == "userProperties"
    }
    for ddp, user_property in ddp_user_properties.items():
        if user_property in existing:
            continue
        property_value = ET.SubElement(
            dynamic_properties,
            "propertyvalue",
            {
                "childKey": user_property,
                "key": "userProperties",
                "name": "User Properties",
                "valueType": "track",
            },
        )
        ET.SubElement(
            property_value,
            "trackparameter",
            {
                "defaultValue": "",
                "propertyId": f"dynamicdocument.{ddp}",
                "propertyName": f"Dynamic Document Property - {ddp}",
            },
        )
