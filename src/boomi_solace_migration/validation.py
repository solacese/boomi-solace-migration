from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from .models import ConnectorProfile
from .xml_io import iter_local, parse_xml


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: str = "error"


def validate_json_schema(data: dict[str, Any], schema_path: str | Path) -> list[ValidationIssue]:
    schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
    validator = Draft202012Validator(schema)
    return [
        ValidationIssue("schema", f"{'.'.join(str(p) for p in error.path)}: {error.message}")
        for error in sorted(validator.iter_errors(data), key=lambda item: list(item.path))
    ]


def validate_transformed_process_xml(
    xml: str,
    *,
    profile: ConnectorProfile,
    source_connector_types: set[str],
) -> list[ValidationIssue]:
    root = parse_xml(xml)
    issues: list[ValidationIssue] = []
    for elem in iter_local(root, "connectoraction"):
        connector_type = elem.get("connectorType", "")
        if connector_type.lower() in source_connector_types:
            issues.append(ValidationIssue("atomqueue_remaining", "Atom Queue connector remains after transform"))
        if connector_type == profile.sub_type:
            if not elem.get("connectionId"):
                issues.append(ValidationIssue("missing_connection_id", "Solace connector missing connectionId"))
            if not elem.get("operationId"):
                issues.append(ValidationIssue("missing_operation_id", "Solace connector missing operationId"))
    return issues


def validate_connection_xml(xml: str, profile: ConnectorProfile) -> list[ValidationIssue]:
    password_field = profile.connection_fields["password"]
    expected = f"//GenericConnectionConfig/field[@id='{password_field}']"
    root = parse_xml(xml)
    for elem in iter_local(root, "encryptedValue"):
        if elem.get("path") == expected and elem.get("isSet") == "true":
            return []
    return [ValidationIssue("missing_encrypted_password", f"Missing encrypted value path {expected}")]


def validate_operation_xml(xml: str) -> list[ValidationIssue]:
    root = parse_xml(xml)
    issues: list[ValidationIssue] = []
    for elem in iter_local(root, "GenericOperationConfig"):
        if elem.get("customOperationType") == "LISTEN" and elem.get("operationType") != "Listen":
            issues.append(ValidationIssue("bad_listen_operation_type", "Listen operationType must be Listen"))
    return issues


def fail_on_issues(issues: list[ValidationIssue]) -> None:
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise ValueError("; ".join(f"{issue.code}: {issue.message}" for issue in errors))
