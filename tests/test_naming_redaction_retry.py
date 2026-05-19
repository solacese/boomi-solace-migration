from __future__ import annotations

from dataclasses import replace

from boomi_solace_migration.http_retry import request_with_retry
from boomi_solace_migration.models import ProcessConfig
from boomi_solace_migration.naming import ddp_to_user_property, queue_name_for_process
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
