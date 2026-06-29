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


def test_is_not_found_handles_solace_cloud_400() -> None:
    """Solace Cloud returns 400 with NOT_FOUND instead of 404."""
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    # Standard 404
    r404 = _Response(404)
    assert client._is_not_found(r404) is True  # noqa: SLF001

    # Solace Cloud 400 + NOT_FOUND
    r400_nf = _Response(400, {"meta": {"error": {"status": "NOT_FOUND"}}})
    assert client._is_not_found(r400_nf) is True  # noqa: SLF001

    # Regular 400 (not NOT_FOUND)
    r400_other = _Response(400, {"meta": {"error": {"status": "BAD_REQUEST"}}})
    assert client._is_not_found(r400_other) is False  # noqa: SLF001

    # 200 is not "not found"
    r200 = _Response(200)
    assert client._is_not_found(r200) is False  # noqa: SLF001


def test_is_already_exists() -> None:
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    r400_ae = _Response(400, {"meta": {"error": {"status": "ALREADY_EXISTS"}}})
    assert client._is_already_exists(r400_ae) is True  # noqa: SLF001

    r400_other = _Response(400, {"meta": {"error": {"status": "NOT_FOUND"}}})
    assert client._is_already_exists(r400_other) is False  # noqa: SLF001


def test_ensure_queue_patches_existing_with_wrong_owner() -> None:
    """If queue exists but owner/permission differ, PATCH to update."""

    class _PatchSession:
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self._responses = [
                # GET queue → exists with wrong owner
                _Response(200, {"data": {"queueName": "q1", "owner": "", "permission": "consume"}}),
                # PATCH → updated
                _Response(200, {"data": {"queueName": "q1", "owner": "boomi_user", "permission": "no-access"}}),
            ]

        def request(self, method: str, url: str, **kwargs: Any) -> _Response:
            self.calls.append({"method": method, "url": url, "kwargs": kwargs})
            return self._responses.pop(0)

    session = _PatchSession()
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.ensure_queue(
        queue_name="q1",
        owner="boomi_user",
        permission="no-access",
    )

    assert result["status"] == "updated"
    assert result["patched"] == {"owner": "boomi_user", "permission": "no-access"}
    assert session.calls[1]["method"] == "PATCH"


def test_ensure_acl_profile_creates_when_not_found() -> None:
    session = _Session([404, 201])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.ensure_acl_profile(profile_name="boomi_user")

    assert result["status"] == "created"
    assert session.calls[1]["method"] == "POST"
    body = session.calls[1]["kwargs"]["json"]
    assert body["aclProfileName"] == "boomi_user"
    assert body["publishTopicDefaultAction"] == "allow"


def test_ensure_client_profile_creates_when_not_found() -> None:
    session = _Session([404, 201])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.ensure_client_profile(profile_name="boomi_user")

    assert result["status"] == "created"
    body = session.calls[1]["kwargs"]["json"]
    assert body["clientProfileName"] == "boomi_user"
    assert body["allowGuaranteedMsgSendEnabled"] is True
    assert body["allowGuaranteedEndpointCreateEnabled"] is False


def test_ensure_client_username_creates_when_not_found() -> None:
    session = _Session([404, 201])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="default",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.ensure_client_username(
        username="boomi_user",
        password="boomi_user",
        client_profile_name="boomi_user",
        acl_profile_name="boomi_user",
    )

    assert result["status"] == "created"
    body = session.calls[1]["kwargs"]["json"]
    assert body["clientUsername"] == "boomi_user"
    assert body["clientProfileName"] == "boomi_user"
    assert body["aclProfileName"] == "boomi_user"


def test_check_connectivity_success() -> None:
    session = _Session([200])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="test-vpn",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    result = client.check_connectivity()
    assert result["status"] == "ok"
    assert result["vpn"] == "test-vpn"


def test_check_connectivity_vpn_not_found() -> None:
    session = _Session([404])
    client = SolaceSempClient(
        base_url="https://broker.invalid",
        message_vpn="bad-vpn",
        min_request_interval_seconds=0,
    )
    client.session = session  # type: ignore[assignment]

    try:
        client.check_connectivity()
        raise AssertionError("Should have raised")
    except RuntimeError as exc:
        assert "not found" in str(exc).lower()
