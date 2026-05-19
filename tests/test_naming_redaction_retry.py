from __future__ import annotations

from dataclasses import replace

from boomi_solace_migration.http_retry import request_with_retry
from boomi_solace_migration.models import ProcessConfig
from boomi_solace_migration.naming import (
    ddp_to_user_property,
    queue_name_for_process,
    topic_name_for_process,
    validate_queue_name,
    validate_topic_name,
    validate_topic_subscription,
)
from boomi_solace_migration.redaction import REDACTED, redact


def test_ddp_to_user_property() -> None:
    assert ddp_to_user_property("DDP_ENTITY_ID") == "entityId"
    assert ddp_to_user_property("entity-region") == "entityRegion"


def test_queue_name_is_stable_and_bounded(naming_policy) -> None:  # type: ignore[no-untyped-def]
    process = ProcessConfig(
        id="process-guid-123",
        name="Sample Queue Process",
        folder_id="folder",
        target_folder_id="target",
        xml_path=None,
        send_destination="",
        receive_destination="",
        destination_type="QUEUE",
        delivery_mode="PERSISTENT",
        queue_access_type="exclusive",
        provision_dmq=True,
    )
    first = queue_name_for_process(process, naming_policy)
    second = queue_name_for_process(replace(process), naming_policy)
    assert first == second
    assert first.startswith("boomi_sample_queue_process_")
    assert len(first) <= 80


def test_topic_name_follows_solace_taxonomy(naming_policy) -> None:  # type: ignore[no-untyped-def]
    process = ProcessConfig(
        id="process-guid-123",
        name="Sample Event Process",
        folder_id="folder",
        target_folder_id="target",
        xml_path=None,
        send_destination="",
        receive_destination="",
        destination_type="TOPIC",
        delivery_mode="PERSISTENT",
        queue_access_type="exclusive",
        provision_dmq=True,
    )
    topic = topic_name_for_process(process, naming_policy)
    assert topic == "boomi/migration/sampleEventProcess/published/v1"
    assert validate_topic_name(topic, naming_policy) == []


def test_topic_validation_rejects_common_anti_patterns(naming_policy) -> None:  # type: ignore[no-untyped-def]
    issues = validate_topic_name("boomi/migration/dev/entity/traceId/v1", naming_policy)
    assert "topic must not include deployment environment levels" in issues
    assert "topic must not include tracing identifiers" in issues


def test_topic_generation_bounds_noun_without_cutting_root(naming_policy) -> None:  # type: ignore[no-untyped-def]
    process = ProcessConfig(
        id="process-guid-123",
        name="Very Long Process Name " * 40,
        folder_id="folder",
        target_folder_id="target",
        xml_path=None,
        send_destination="",
        receive_destination="",
        destination_type="TOPIC",
        delivery_mode="PERSISTENT",
        queue_access_type="exclusive",
        provision_dmq=True,
    )
    topic = topic_name_for_process(process, naming_policy)
    assert len(topic) <= 250
    assert topic.endswith("/published/v1")
    assert validate_topic_name(topic, naming_policy) == []


def test_queue_validation_rejects_solace_invalid_names(naming_policy) -> None:  # type: ignore[no-untyped-def]
    issues = validate_queue_name("bad>queue", naming_policy)
    assert "queue name contains Solace invalid characters" in issues


def test_subscription_validation_allows_wildcards_but_rejects_exceptions(naming_policy) -> None:  # type: ignore[no-untyped-def]
    assert validate_topic_subscription("boomi/migration/*/published/v1/>", naming_policy) == []
    issues = validate_topic_subscription("!boomi/migration/order/published/v1", naming_policy)
    assert "subscription exceptions require allow_subscription_exceptions" in issues


def test_redaction_recurses() -> None:
    data = {"apiToken": "abc", "nested": [{"password": "secret"}, {"ok": "value"}]}
    assert redact(data) == {
        "apiToken": REDACTED,
        "nested": [{"password": REDACTED}, {"ok": "value"}],
    }


class _Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.text = ""


class _Session:
    def __init__(self) -> None:
        self.statuses = [429, 500, 200]
        self.calls = 0

    def request(self, method: str, url: str, **kwargs):  # type: ignore[no-untyped-def]
        self.calls += 1
        return _Response(self.statuses.pop(0))


def test_request_with_retry_retries_retryable_statuses() -> None:
    session = _Session()
    response = request_with_retry(session, "GET", "https://placeholder.invalid", sleep=lambda _: None)  # type: ignore[arg-type]
    assert response.status_code == 200
    assert session.calls == 3
