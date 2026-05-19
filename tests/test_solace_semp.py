from __future__ import annotations

from typing import Any

from boomi_solace_migration.solace_semp import SolaceSempClient


class _Response:
    def __init__(self, status_code: int, data: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self.text = ""
        self._data = data or {"data": {}}

    def json(self) -> dict[str, Any]:
        return self._data


class _Session:
    def __init__(self, statuses: list[int]) -> None:
        self.statuses = statuses
        self.calls: list[dict[str, Any]] = []

    def request(self, method: str, url: str, **kwargs: Any) -> _Response:
        self.calls.append({"method": method, "url": url, "kwargs": kwargs})
        return _Response(self.statuses.pop(0))


def test_ensure_queue_uses_durable_dmq_and_redelivery_settings() -> None:
    session = _Session([404, 201])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.ensure_queue(
        queue_name="boomi_order_queue",
        access_type="non-exclusive",
        dmq_name="boomi_order_queue_dmq",
        permission="consume",
        owner="boomi-client",
        max_redelivery_count=5,
        max_ttl_seconds=3600,
        max_spool_usage_mb=5000,
    )

    assert result["status"] == "created"
    body = session.calls[1]["kwargs"]["json"]
    assert body["queueName"] == "boomi_order_queue"
    assert body["accessType"] == "non-exclusive"
    assert body["deadMsgQueue"] == "boomi_order_queue_dmq"
    assert body["maxRedeliveryCount"] == 5
    assert body["redeliveryEnabled"] is True
    assert body["maxTtl"] == 3600
    assert body["respectTtlEnabled"] is True
    assert body["maxMsgSpoolUsage"] == 5000
    assert body["permission"] == "consume"
    assert body["owner"] == "boomi-client"


def test_ensure_queue_subscription_is_idempotent() -> None:
    session = _Session([404, 201])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.ensure_queue_subscription(
        queue_name="boomi_order_queue",
        subscription="boomi/migration/order/published/v1",
    )

    assert result["status"] == "created"
    assert session.calls[0]["method"] == "GET"
    assert "boomi%2Fmigration%2Forder%2Fpublished%2Fv1" in session.calls[0]["url"]
    assert session.calls[1]["kwargs"]["json"] == {
        "subscriptionTopic": "boomi/migration/order/published/v1"
    }
