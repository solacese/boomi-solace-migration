from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


class ConfigError(Exception):
    pass


PLACEHOLDER_PATTERNS = ("replace-me", "placeholder.invalid", "account-placeholder")


def _validate(value: str, field_name: str) -> str:
    if not value or not value.strip():
        raise ConfigError(f"{field_name} is blank or missing")
    cleaned = value.strip()
    for pattern in PLACEHOLDER_PATTERNS:
        if pattern in cleaned.lower():
            raise ConfigError(f"{field_name} still contains placeholder '{pattern}'")
    return cleaned


def _resolve_env(data: dict[str, Any], key: str, field_name: str) -> str:
    env_key = data.get(key, "")
    if not env_key:
        raise ConfigError(f"{field_name}: env key '{key}' not specified in config")
    value = os.environ.get(env_key)
    if value is None:
        raise ConfigError(f"{field_name}: environment variable {env_key} is not set")
    return _validate(value, f"{field_name} (from ${env_key})")


@dataclass(frozen=True)
class BoomiConfig:
    account_id: str
    username: str
    api_token: str
    base_url: str = "https://api.boomi.com/api/rest/v1"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BoomiConfig:
        account_id = _resolve_env(data, "account_id_env", "boomi.account_id")
        username = _resolve_env(data, "username_env", "boomi.username")
        api_token = _resolve_env(data, "api_token_env", "boomi.api_token")
        base_url = data.get("base_url", "https://api.boomi.com/api/rest/v1")
        return cls(account_id=account_id, username=username, api_token=api_token, base_url=base_url)


@dataclass(frozen=True)
class SolaceSempConfig:
    base_url: str
    message_vpn: str
    username: str
    password: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SolaceSempConfig:
        return cls(
            base_url=_resolve_env(data, "base_url_env", "solace_semp.base_url"),
            message_vpn=_resolve_env(data, "message_vpn_env", "solace_semp.message_vpn"),
            username=_resolve_env(data, "username_env", "solace_semp.username"),
            password=_resolve_env(data, "password_env", "solace_semp.password"),
        )


@dataclass(frozen=True)
class ConnectorProfile:
    sub_type: str
    connection_fields: dict[str, str]
    operation_fields: dict[str, str]

    REQUIRED_CONNECTION = ("host", "vpn", "username", "password")
    REQUIRED_OPERATION = ("destination", "destination_type", "delivery_mode")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectorProfile:
        sub_type = _validate(str(data.get("sub_type", "")), "connector_profile.sub_type")
        connection_fields = {str(k): str(v) for k, v in data.get("connection_fields", {}).items()}
        operation_fields = {str(k): str(v) for k, v in data.get("operation_fields", {}).items()}
        missing_conn = [k for k in cls.REQUIRED_CONNECTION if k not in connection_fields]
        if missing_conn:
            raise ConfigError(f"connector_profile.connection_fields missing: {missing_conn}")
        missing_op = [k for k in cls.REQUIRED_OPERATION if k not in operation_fields]
        if missing_op:
            raise ConfigError(f"connector_profile.operation_fields missing: {missing_op}")
        for logical, field_id in connection_fields.items():
            _validate(field_id, f"connector_profile.connection_fields.{logical}")
        for logical, field_id in operation_fields.items():
            _validate(field_id, f"connector_profile.operation_fields.{logical}")
        return cls(sub_type=sub_type, connection_fields=connection_fields, operation_fields=operation_fields)


@dataclass(frozen=True)
class ConnectionValues:
    host: str
    vpn: str
    username: str
    password: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionValues:
        return cls(
            host=_resolve_env(data, "host_env", "connection.host"),
            vpn=_resolve_env(data, "vpn_env", "connection.vpn"),
            username=_resolve_env(data, "username_env", "connection.username"),
            password=_resolve_env(data, "password_env", "connection.password"),
        )


@dataclass(frozen=True)
class OperationMapping:
    original_connection_id: str
    destination: str
    destination_type: str
    delivery_mode: str


@dataclass(frozen=True)
class ProcessEntry:
    id: str
    name: str
    send_destination: str
    send_destination_type: str
    receive_destination: str
    receive_destination_type: str
    delivery_mode: str
    provision_queue: bool
    operation_mappings: tuple[OperationMapping, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any], index: int) -> ProcessEntry:
        prefix = f"processes[{index}]"
        process_id = _validate(str(data.get("id", "")), f"{prefix}.id")
        name = _validate(str(data.get("name", "")), f"{prefix}.name")
        send_dest = str(data.get("send_destination", ""))
        recv_dest = str(data.get("receive_destination", ""))
        raw_mappings = data.get("operation_mappings", [])
        if not send_dest and not recv_dest and not raw_mappings:
            raise ConfigError(f"{prefix}: at least one of send_destination, receive_destination, or operation_mappings is required")
        mappings: list[OperationMapping] = []
        for j, m in enumerate(raw_mappings):
            mappings.append(OperationMapping(
                original_connection_id=_validate(str(m.get("original_connection_id", "")), f"{prefix}.operation_mappings[{j}].original_connection_id"),
                destination=_validate(str(m.get("destination", "")), f"{prefix}.operation_mappings[{j}].destination"),
                destination_type=str(m.get("destination_type", "QUEUE")).upper(),
                delivery_mode=str(m.get("delivery_mode", "PERSISTENT")).upper(),
            ))
        return cls(
            id=process_id,
            name=name,
            send_destination=send_dest,
            send_destination_type=str(data.get("send_destination_type", "TOPIC")).upper(),
            receive_destination=recv_dest,
            receive_destination_type=str(data.get("receive_destination_type", "QUEUE")).upper(),
            delivery_mode=str(data.get("delivery_mode", "PERSISTENT")).upper(),
            provision_queue=bool(data.get("provision_queue", True)),
            operation_mappings=tuple(mappings),
        )


@dataclass(frozen=True)
class MigrationConfig:
    boomi: BoomiConfig
    solace_semp: SolaceSempConfig
    connector_profile: ConnectorProfile
    connection: ConnectionValues
    target_folder_id: str
    source_connector_types: frozenset[str]
    processes: tuple[ProcessEntry, ...]

    @classmethod
    def load(cls, path: str | Path) -> MigrationConfig:
        config_path = Path(path)
        if not config_path.exists():
            raise ConfigError(f"Config file not found: {config_path}")
        with config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{config_path} must contain a YAML mapping")

        boomi = BoomiConfig.from_dict(data.get("boomi", {}))
        solace_semp = SolaceSempConfig.from_dict(data.get("solace_semp", {}))
        connector_profile = ConnectorProfile.from_dict(data.get("connector_profile", {}))
        connection = ConnectionValues.from_dict(data.get("connection", {}))
        target_folder_id = _validate(str(data.get("target_folder_id", "")), "target_folder_id")
        source_types = frozenset(
            str(item).lower() for item in data.get("source_connector_types", ["atomqueue", "queue"])
        )
        raw_processes = data.get("processes", [])
        if not raw_processes:
            raise ConfigError("At least one process is required")
        processes = tuple(ProcessEntry.from_dict(p, i) for i, p in enumerate(raw_processes))
        return cls(
            boomi=boomi,
            solace_semp=solace_semp,
            connector_profile=connector_profile,
            connection=connection,
            target_folder_id=target_folder_id,
            source_connector_types=source_types,
            processes=processes,
        )
