from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass

from .config import ConnectorProfile
from .xml_util import BNS, iter_local, local_name, parse_xml, qname, remove_dangling_references, remove_read_only_attributes, tostring

ACTION_MAP = {"send": "Send", "listen": "Listen", "get": "Get"}


@dataclass(frozen=True)
class QueueOperation:
    action: str
    connector_type: str
    connection_id: str
    operation_id: str


@dataclass(frozen=True)
class DetectionResult:
    operations: list[QueueOperation]
    migration_type: str


def detect_queue_operations(xml_text: str, source_connector_types: frozenset[str]) -> DetectionResult:
    root = parse_xml(xml_text)
    operations: list[QueueOperation] = []
    for elem in iter_local(root, "connectoraction"):
        connector_type = (elem.get("connectorType") or "").lower()
        if connector_type not in source_connector_types:
            continue
        action = (elem.get("actionType") or "").lower()
        if action not in ACTION_MAP:
            continue
        operations.append(QueueOperation(
            action=action,
            connector_type=connector_type,
            connection_id=elem.get("connectionId", ""),
            operation_id=elem.get("operationId", ""),
        ))
    has_send = any(op.action == "send" for op in operations)
    has_receive = any(op.action in ("listen", "get") for op in operations)
    if has_send and has_receive:
        mtype = "mixed"
    elif has_send:
        mtype = "producer"
    elif has_receive:
        mtype = "consumer"
    else:
        mtype = "none"
    return DetectionResult(operations=operations, migration_type=mtype)


class TransformError(Exception):
    pass


def transform_process(
    *,
    original_xml: str,
    process_name: str,
    target_folder_id: str,
    source_connector_types: frozenset[str],
    profile: ConnectorProfile,
    connection_id: str,
    operation_ids: dict[str, str],
    connection_operation_map: dict[str, str] | None = None,
) -> str:
    """Transform process XML by swapping source connectors to Solace.

    operation_ids: maps action type ('send', 'listen', 'get') to a single operation ID.
    connection_operation_map: maps original connectionId to new operationId (for multi-destination).
        When provided, this takes precedence over operation_ids for matching connectors.
    """
    detection = detect_queue_operations(original_xml, source_connector_types)
    if not detection.operations:
        raise TransformError(f"Process '{process_name}' has no queue operations to migrate")

    root = parse_xml(original_xml)

    root.set("componentId", "")
    root.set("version", "1")
    root.set("type", "process")
    root.set("name", f"{root.get('name', process_name)} - Solace Migration")
    root.set("folderId", target_folder_id)
    remove_read_only_attributes(root)
    remove_dangling_references(root)

    transformed_count = 0
    for elem in iter_local(root, "connectoraction"):
        connector_type = (elem.get("connectorType") or "").lower()
        if connector_type not in source_connector_types:
            continue
        action_key = (elem.get("actionType") or "").lower()
        if action_key not in ACTION_MAP:
            continue

        orig_conn_id = elem.get("connectionId", "")
        if connection_operation_map and orig_conn_id in connection_operation_map:
            op_id = connection_operation_map[orig_conn_id]
        else:
            op_id = operation_ids.get(action_key)
            if not op_id:
                raise TransformError(f"No operation ID provided for action '{action_key}' (connectionId={orig_conn_id})")

        elem.set("connectorType", profile.sub_type)
        elem.set("actionType", ACTION_MAP[action_key])
        elem.set("connectionId", connection_id)
        elem.set("operationId", op_id)
        transformed_count += 1

    if transformed_count == 0:
        raise TransformError(f"Transform produced 0 connector swaps for '{process_name}'")

    result_xml = tostring(root)

    _verify_no_source_connectors(result_xml, source_connector_types, process_name)
    _verify_ids_populated(result_xml, process_name, target_sub_type=profile.sub_type)

    return result_xml


def _verify_no_source_connectors(xml_text: str, source_types: frozenset[str], name: str) -> None:
    root = parse_xml(xml_text)
    for elem in iter_local(root, "connectoraction"):
        ct = (elem.get("connectorType") or "").lower()
        if ct in source_types:
            raise TransformError(f"Transform failed for '{name}': source connector '{ct}' still present")


def _verify_ids_populated(xml_text: str, name: str, target_sub_type: str | None = None) -> None:
    root = parse_xml(xml_text)
    for elem in iter_local(root, "connectoraction"):
        action = (elem.get("actionType") or "").lower()
        if action in ("noaction", ""):
            continue
        ct = elem.get("connectorType", "")
        if target_sub_type and ct != target_sub_type:
            continue
        conn_id = elem.get("connectionId", "")
        op_id = elem.get("operationId", "")
        if not conn_id:
            raise TransformError(f"Transform failed for '{name}': empty connectionId on {ct} connector")
        if not op_id:
            raise TransformError(f"Transform failed for '{name}': empty operationId on {ct} connector")
