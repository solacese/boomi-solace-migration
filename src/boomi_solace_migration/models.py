from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a YAML object")
    return data


def env_or_value(data: dict[str, Any], value_key: str, env_key: str, *, redacted: bool) -> str:
    if value_key in data and data[value_key] not in (None, ""):
        return str(data[value_key])
    env_name = str(data.get(env_key, "") or "")
    if not env_name:
        return ""
    if redacted:
        return f"<env:{env_name}>"
    value = os.environ.get(env_name)
    if value is None:
        raise ValueError(f"Required environment variable is not set: {env_name}")
    return value


def optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


@dataclass(frozen=True)
class ConnectorProfile:
    name: str
    sub_type: str
    display_name: str
    connection_fields: dict[str, str]
    operation_fields: dict[str, str]
    user_properties: dict[str, str] = field(default_factory=dict)

    REQUIRED_CONNECTION_FIELDS: ClassVar[tuple[str, ...]] = ("host", "vpn", "username", "password")
    REQUIRED_OPERATION_FIELDS: ClassVar[tuple[str, ...]] = (
        "destination",
        "destination_type",
        "delivery_mode",
    )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectorProfile:
        connection_fields = {str(k): str(v) for k, v in data.get("connection_fields", {}).items()}
        operation_fields = {str(k): str(v) for k, v in data.get("operation_fields", {}).items()}
        missing_connection = [k for k in cls.REQUIRED_CONNECTION_FIELDS if k not in connection_fields]
        missing_operation = [k for k in cls.REQUIRED_OPERATION_FIELDS if k not in operation_fields]
        if missing_connection:
            raise ValueError(f"Connector profile missing connection fields: {missing_connection}")
        if missing_operation:
            raise ValueError(f"Connector profile missing operation fields: {missing_operation}")
        sub_type = str(data.get("sub_type", "")).strip()
        if not sub_type:
            raise ValueError("Connector profile requires sub_type")
        return cls(
            name=str(data.get("name", "solace-pubsub-plus")),
            sub_type=sub_type,
            display_name=str(data.get("display_name", "Solace PubSub+")),
            connection_fields=connection_fields,
            operation_fields=operation_fields,
            user_properties={str(k): str(v) for k, v in data.get("user_properties", {}).items()},
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> ConnectorProfile:
        return cls.from_dict(load_yaml(path))


@dataclass(frozen=True)
class NamingPolicy:
    queue: dict[str, Any]
    topic: dict[str, Any]
    reserved_words: set[str]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NamingPolicy:
        return cls(
            queue=dict(data.get("queue", {})),
            topic=dict(data.get("topic", {})),
            reserved_words={str(item) for item in data.get("reserved_words", [])},
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> NamingPolicy:
        return cls.from_dict(load_yaml(path))


@dataclass(frozen=True)
class ProcessConfig:
    id: str
    name: str
    folder_id: str
    target_folder_id: str
    xml_path: Path | None
    send_destination: str
    receive_destination: str
    destination_type: str
    delivery_mode: str
    queue_access_type: str
    provision_dmq: bool
    topic_subscriptions: tuple[str, ...] = ()
    queue_permission: str = "consume"
    queue_owner: str = ""
    max_redelivery_count: int = 0
    max_ttl_seconds: int = 0
    max_spool_usage_mb: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], defaults: dict[str, Any], target_folder_id: str) -> ProcessConfig:
        process_id = str(data.get("id", "")).strip()
        name = str(data.get("name", "")).strip()
        if not process_id or not name:
            raise ValueError("Each process requires id and name")
        xml_path_raw = data.get("xml_path")
        topic_subscriptions_raw = data.get("topic_subscriptions", defaults.get("topic_subscriptions", []))
        if not isinstance(topic_subscriptions_raw, list):
            raise ValueError("topic_subscriptions must be a list")
        max_spool_usage = data.get("max_spool_usage_mb", defaults.get("max_spool_usage_mb"))
        return cls(
            id=process_id,
            name=name,
            folder_id=str(data.get("folder_id", "")),
            target_folder_id=str(data.get("target_folder_id") or target_folder_id),
            xml_path=Path(str(xml_path_raw)) if xml_path_raw else None,
            send_destination=str(data.get("send_destination", "")),
            receive_destination=str(data.get("receive_destination", "")),
            destination_type=str(data.get("destination_type") or defaults.get("destination_type", "QUEUE")).upper(),
            delivery_mode=str(data.get("delivery_mode") or defaults.get("delivery_mode", "PERSISTENT")).upper(),
            queue_access_type=str(data.get("queue_access_type") or defaults.get("queue_access_type", "exclusive")),
            provision_dmq=bool(data.get("provision_dmq", defaults.get("provision_dmq", True))),
            topic_subscriptions=tuple(str(item) for item in topic_subscriptions_raw),
            queue_permission=str(data.get("queue_permission") or defaults.get("queue_permission", "consume")),
            queue_owner=str(data.get("queue_owner") or defaults.get("queue_owner", "")),
            max_redelivery_count=int(data.get("max_redelivery_count", defaults.get("max_redelivery_count", 0))),
            max_ttl_seconds=int(data.get("max_ttl_seconds", defaults.get("max_ttl_seconds", 0))),
            max_spool_usage_mb=optional_int(max_spool_usage),
        )


@dataclass(frozen=True)
class ConnectionConfig:
    name: str
    raw: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ConnectionConfig:
        return cls(name=str(data.get("name", "solace-connection")), raw=dict(data))

    def values(self, *, redacted: bool) -> dict[str, str]:
        return {
            "host": env_or_value(self.raw, "host", "host_env", redacted=redacted),
            "vpn": env_or_value(self.raw, "vpn", "vpn_env", redacted=redacted),
            "username": env_or_value(self.raw, "username", "username_env", redacted=redacted),
            "password": env_or_value(self.raw, "password", "password_env", redacted=redacted),
        }


@dataclass(frozen=True)
class MigrationConfig:
    migration_version: str
    output_dir: Path
    target_folder_id: str
    source_connector_types: set[str]
    connection: ConnectionConfig
    defaults: dict[str, Any]
    processes: list[ProcessConfig]

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, base_dir: Path) -> MigrationConfig:
        target_folder_id = str(data.get("target_folder_id", "")).strip()
        if not target_folder_id:
            raise ValueError("migration config requires target_folder_id")
        defaults = dict(data.get("defaults", {}))
        processes = [
            ProcessConfig.from_dict(item, defaults, target_folder_id)
            for item in data.get("processes", [])
        ]
        if not processes:
            raise ValueError("migration config requires at least one process")
        output_dir = Path(str(data.get("output_dir", "out/plan")))
        if not output_dir.is_absolute():
            output_dir = base_dir / output_dir
        return cls(
            migration_version=str(data.get("migration_version", "0")).strip(),
            output_dir=output_dir,
            target_folder_id=target_folder_id,
            source_connector_types={
                str(item).lower() for item in data.get("source_connector_types", ["atomqueue", "queue"])
            },
            connection=ConnectionConfig.from_dict(dict(data.get("connection", {}))),
            defaults=defaults,
            processes=processes,
        )

    @classmethod
    def from_yaml(cls, path: str | Path) -> MigrationConfig:
        config_path = Path(path)
        return cls.from_dict(load_yaml(config_path), base_dir=config_path.parent)
