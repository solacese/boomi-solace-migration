from __future__ import annotations

from dataclasses import dataclass

from .xml_io import iter_local, local_name, parse_xml

SUPPORTED_ACTIONS = {"send", "listen", "get"}


@dataclass(frozen=True)
class QueueOperation:
    action: str
    connector_type: str
    connection_id: str
    operation_id: str
    shape_label: str


@dataclass(frozen=True)
class DetectionResult:
    operations: list[QueueOperation]
    ddps: list[str]
    migration_type: str
    unknown_queue_like_connectors: list[str]
    unsupported_actions: list[str]


def _parent_labels(root: object) -> dict[int, str]:
    labels: dict[int, str] = {}
    # ElementTree does not expose parents; build just enough context for connector labels.
    for elem in root.iter():  # type: ignore[attr-defined]
        if local_name(elem.tag) == "shape":
            label = elem.get("userlabel", "")
            for child in elem.iter():
                labels[id(child)] = label
    return labels


def classify_migration(actions: set[str]) -> str:
    has_send = "send" in actions
    has_consumer = bool(actions & {"get", "listen"})
    if has_send and has_consumer:
        return "mixed"
    if has_send:
        return "producer"
    return "consumer"


def detect_queue_usage(xml: str, source_connector_types: set[str]) -> DetectionResult:
    root = parse_xml(xml)
    labels = _parent_labels(root)
    operations: list[QueueOperation] = []
    ddps: set[str] = set()
    unknown_queue_like: set[str] = set()
    unsupported_actions: set[str] = set()

    for elem in iter_local(root, "connectoraction"):
        connector_type = (elem.get("connectorType") or "").lower()
        action = (elem.get("actionType") or "").lower()
        label = labels.get(id(elem), "")
        if connector_type in source_connector_types:
            if action not in SUPPORTED_ACTIONS:
                unsupported_actions.add(action or "<missing>")
            operations.append(
                QueueOperation(
                    action=action,
                    connector_type=connector_type,
                    connection_id=elem.get("connectionId", ""),
                    operation_id=elem.get("operationId", ""),
                    shape_label=label,
                )
            )
        elif "queue" in connector_type or "queue" in label.lower():
            unknown_queue_like.add(connector_type or "<missing>")

    for elem in iter_local(root, "trackparameter"):
        property_id = elem.get("propertyId", "")
        if property_id.startswith("dynamicdocument."):
            ddps.add(property_id.split("dynamicdocument.", 1)[1])

    actions = {op.action for op in operations if op.action}
    migration_type = classify_migration(actions) if actions else "none"
    return DetectionResult(
        operations=operations,
        ddps=sorted(ddps),
        migration_type=migration_type,
        unknown_queue_like_connectors=sorted(unknown_queue_like),
        unsupported_actions=sorted(unsupported_actions),
    )
