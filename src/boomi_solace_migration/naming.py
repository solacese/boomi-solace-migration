from __future__ import annotations

import hashlib
import re

from .models import NamingPolicy, ProcessConfig

TOPIC_SPECIAL_CHARS = {"*", ">", "!"}
QUEUE_INVALID_CHARS = set("'<>*?&;")


def stable_hash(value: str, length: int = 8) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:length]


def slugify(value: str, *, separator: str = "_", case: str = "lower") -> str:
    text = value.strip()
    if case == "lower":
        text = text.lower()
    text = re.sub(r"[^A-Za-z0-9_.-]+", separator, text)
    text = re.sub(re.escape(separator) + r"+", separator, text)
    return text.strip(separator) or "unnamed"


def _words(value: str) -> list[str]:
    return [part for part in re.split(r"[^A-Za-z0-9]+", value.strip()) if part]


def topic_level(value: str, *, case: str) -> str:
    words = _words(value)
    if not words:
        return "unnamed"
    if case == "pascal":
        return "".join(part[:1].upper() + part[1:].lower() for part in words)
    if case == "camel":
        first = words[0].lower()
        rest = "".join(part[:1].upper() + part[1:].lower() for part in words[1:])
        return first + rest
    if case == "lower":
        return "".join(part.lower() for part in words)
    return "".join(words)


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
    case = str(topic_policy.get("case", "camel"))
    domain = str(topic_policy.get("domain", "boomi/migration")).strip(separator)
    verb = str(topic_policy.get("verb", "published")).strip(separator)
    version = str(topic_policy.get("version", "v1")).strip(separator)
    hash_length = int(topic_policy.get("collision_hash_length", 8))
    noun = topic_level(process.name, case=case)
    max_length = int(topic_policy.get("max_length", 250))
    static_length = len(domain) + len(verb) + len(version) + 3
    noun_max_length = max_length - static_length
    if noun_max_length < 1:
        return f"{domain}/{noun}/{verb}/{version}"
    if len(noun) > noun_max_length:
        suffix = stable_hash(process.id, hash_length)
        if noun_max_length <= hash_length:
            noun = suffix[:noun_max_length]
        else:
            noun = noun[: noun_max_length - hash_length] + suffix
    return f"{domain}/{noun}/{verb}/{version}"


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


def validate_topic_name(topic: str, policy: NamingPolicy) -> list[str]:
    topic_policy = policy.topic
    separator = str(topic_policy.get("separator", "/"))
    max_length = int(topic_policy.get("max_length", 250))
    max_levels = int(topic_policy.get("max_levels", 128))
    allowed_level_pattern = str(topic_policy.get("allowed_level_pattern", r"^[A-Za-z0-9]+$"))
    require_domain_prefix = bool(topic_policy.get("require_domain_prefix", True))
    domain = str(topic_policy.get("domain", "")).strip(separator)
    domain_levels = [level for level in domain.split(separator) if level]
    forbidden_levels = {str(level).lower() for level in topic_policy.get("forbidden_levels", [])}
    forbidden_terms = {str(term).lower() for term in topic_policy.get("forbidden_terms", [])}
    issues: list[str] = []

    if len(topic) > max_length:
        issues.append(f"topic exceeds {max_length} characters")
    levels = topic.split(separator)
    if len(levels) > max_levels:
        issues.append(f"topic exceeds {max_levels} levels")
    if len(levels) < 4:
        issues.append("topic must include Domain/Noun/Verb/Version")
    if any(not level for level in levels):
        issues.append("topic contains an empty level")
    if any(char.isspace() for char in topic):
        issues.append("topic must not contain spaces")
    if any(char in topic for char in TOPIC_SPECIAL_CHARS):
        issues.append("published topic must not contain *, >, or !")
    if levels and levels[0].startswith(("#", "_")):
        issues.append("application topic must not start with # or _")
    invalid_levels = [level for level in levels if level and not re.fullmatch(allowed_level_pattern, level)]
    if invalid_levels:
        issues.append(f"topic levels must match {allowed_level_pattern}: {invalid_levels}")
    if any(level.lower() in forbidden_levels for level in levels):
        issues.append("topic must not include deployment environment levels")
    lowered_topic = topic.lower()
    if any(term in lowered_topic for term in forbidden_terms):
        issues.append("topic must not include tracing identifiers")
    if require_domain_prefix and domain_levels and levels[: len(domain_levels)] != domain_levels:
        issues.append(f"topic must start with configured domain {domain}")
    version_index = len(domain_levels) + 2
    if len(levels) > version_index and not re.fullmatch(r"v[0-9]+", levels[version_index]):
        issues.append("topic version level must use vN format")
    return issues


def validate_topic_subscription(subscription: str, policy: NamingPolicy) -> list[str]:
    topic_policy = policy.topic
    separator = str(topic_policy.get("separator", "/"))
    max_length = int(topic_policy.get("max_length", 250))
    max_levels = int(topic_policy.get("max_levels", 128))
    allow_exceptions = bool(topic_policy.get("allow_subscription_exceptions", False))
    forbidden_levels = {str(level).lower() for level in topic_policy.get("forbidden_levels", [])}
    forbidden_terms = {str(term).lower() for term in topic_policy.get("forbidden_terms", [])}
    issues: list[str] = []

    if subscription.startswith("!"):
        if not allow_exceptions:
            issues.append("subscription exceptions require allow_subscription_exceptions")
        subscription = subscription[1:]
    if len(subscription) > max_length:
        issues.append(f"subscription exceeds {max_length} characters")
    levels = subscription.split(separator)
    if len(levels) > max_levels:
        issues.append(f"subscription exceeds {max_levels} levels")
    if any(not level for level in levels):
        issues.append("subscription contains an empty level")
    if any(char.isspace() for char in subscription):
        issues.append("subscription must not contain spaces")
    for index, level in enumerate(levels):
        if ">" in level and not (level == ">" and index == len(levels) - 1):
            issues.append("subscription wildcard > must be the final level")
        if "*" in level and level != "*":
            issues.append("subscription wildcard * must occupy a full level")
    literal_levels = [level for level in levels if level not in {"*", ">"}]
    if any(level.lower() in forbidden_levels for level in literal_levels):
        issues.append("subscription must not include deployment environment levels")
    lowered_subscription = subscription.lower()
    if any(term in lowered_subscription for term in forbidden_terms):
        issues.append("subscription must not include tracing identifiers")
    return issues


def validate_queue_name(queue_name: str, policy: NamingPolicy) -> list[str]:
    queue_policy = policy.queue
    max_length = int(queue_policy.get("max_length", queue_policy.get("solace_max_length", 200)))
    solace_max_length = int(queue_policy.get("solace_max_length", 200))
    allowed_pattern = str(queue_policy.get("allowed_pattern", r"^[A-Za-z0-9_.-/]+$"))
    issues: list[str] = []

    if not queue_name:
        issues.append("queue name is required")
        return issues
    if len(queue_name) > max_length:
        issues.append(f"queue name exceeds policy limit of {max_length} characters")
    if len(queue_name) > solace_max_length:
        issues.append(f"queue name exceeds Solace limit of {solace_max_length} characters")
    if queue_name.startswith("#"):
        issues.append("application queue must not start with #")
    if any(char in queue_name for char in QUEUE_INVALID_CHARS):
        issues.append("queue name contains Solace invalid characters")
    if queue_name.startswith("/") or queue_name.endswith("/") or "//" in queue_name:
        issues.append("queue hierarchy levels must not be empty")
    if not re.fullmatch(allowed_pattern, queue_name):
        issues.append(f"queue name must match {allowed_pattern}")
    if queue_name in policy.reserved_words:
        issues.append("queue name is reserved")
    return issues
