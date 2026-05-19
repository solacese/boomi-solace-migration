from __future__ import annotations

import hashlib
import re

from .models import NamingPolicy, ProcessConfig


def stable_hash(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def slugify(value: str, *, separator: str = "_", case: str = "lower") -> str:
    text = value.strip()
    if case == "lower":
        text = text.lower()
    text = re.sub(r"[^A-Za-z0-9_.-]+", separator, text)
    text = re.sub(re.escape(separator) + r"+", separator, text)
    return text.strip(separator) or "unnamed"


def bounded_name(base: str, unique_source: str, *, max_length: int, hash_length: int) -> str:
    suffix = stable_hash(unique_source, hash_length)
    if len(base) + 1 + hash_length <= max_length:
        return f"{base}_{suffix}"
    trimmed = base[: max_length - hash_length - 1].rstrip("_.-/")
    return f"{trimmed}_{suffix}"


def queue_name_for_process(process: ProcessConfig, policy: NamingPolicy) -> str:
    queue_policy = policy.queue
    separator = str(queue_policy.get("separator", "_"))
    case = str(queue_policy.get("case", "lower"))
    prefix = str(queue_policy.get("prefix", "")).strip(separator)
    max_length = int(queue_policy.get("max_length", 80))
    hash_length = int(queue_policy.get("collision_hash_length", 8))
    base = slugify(process.name, separator=separator, case=case)
    if base.endswith(separator + "queue"):
        base = base[: -len(separator + "queue")]
    if prefix:
        base = f"{prefix}{separator}{base}"
    candidate = bounded_name(base, process.id, max_length=max_length, hash_length=hash_length)
    if candidate in policy.reserved_words:
        candidate = bounded_name(f"{candidate}{separator}q", process.id, max_length=max_length, hash_length=hash_length)
    return candidate


def topic_name_for_process(process: ProcessConfig, policy: NamingPolicy) -> str:
    topic_policy = policy.topic
    separator = str(topic_policy.get("separator", "/"))
    base = slugify(process.name, separator=separator, case="lower")
    topic = f"boomi/{base}/message/v1"
    max_length = int(topic_policy.get("max_length", 250))
    if len(topic) > max_length:
        topic = topic[:max_length].rstrip(separator)
    return topic


def destination_for_process(process: ProcessConfig, policy: NamingPolicy, *, send: bool) -> str:
    configured = process.send_destination if send else process.receive_destination
    if configured:
        return configured
    if process.destination_type == "TOPIC":
        return topic_name_for_process(process, policy)
    return queue_name_for_process(process, policy)


def ddp_to_user_property(ddp: str) -> str:
    name = re.sub(r"^DDP_", "", ddp, flags=re.IGNORECASE)
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", name.lower()) if part]
    if not parts:
        return "property"
    return parts[0] + "".join(part.capitalize() for part in parts[1:])
