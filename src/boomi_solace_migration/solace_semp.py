from __future__ import annotations

import os
import time
from collections.abc import Callable
from typing import Any, cast
from urllib.parse import quote

import requests

from .http_retry import request_with_retry
from .redaction import redact_text


class SolaceSempClient:
    def __init__(
        self,
        *,
        base_url: str,
        message_vpn: str,
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
        min_request_interval_seconds: float = 0.11,
        request_timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.message_vpn = message_vpn
        self.session = requests.Session()
        self.min_request_interval_seconds = min_request_interval_seconds
        self.request_timeout_seconds = request_timeout_seconds
        self.sleep = sleep
        self._last_request_at = 0.0
        if bearer_token:
            self.session.headers.update({"Authorization": f"Bearer {bearer_token}"})
        elif username is not None and password is not None:
            self.session.auth = (username, password)

    @classmethod
    def from_env(cls) -> SolaceSempClient:
        base_url = os.environ.get("SOLACE_SEMP_BASE_URL")
        message_vpn = os.environ.get("SOLACE_MESSAGE_VPN")
        if not base_url or not message_vpn:
            raise ValueError("SOLACE_SEMP_BASE_URL and SOLACE_MESSAGE_VPN are required")
        return cls(
            base_url=base_url,
            message_vpn=message_vpn,
            username=os.environ.get("SOLACE_SEMP_USERNAME"),
            password=os.environ.get("SOLACE_SEMP_PASSWORD"),
            bearer_token=os.environ.get("SOLACE_SEMP_TOKEN"),
            min_request_interval_seconds=float(os.environ.get("SOLACE_SEMP_MIN_INTERVAL_SECONDS", "0.11")),
            request_timeout_seconds=float(os.environ.get("SOLACE_SEMP_TIMEOUT_SECONDS", "30")),
        )

    def queue_config_url(self, queue_name: str) -> str:
        vpn = quote(self.message_vpn, safe="")
        queue = quote(queue_name, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/queues/{queue}"

    def queue_collection_url(self) -> str:
        vpn = quote(self.message_vpn, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/queues"

    def queue_monitor_url(self, queue_name: str) -> str:
        vpn = quote(self.message_vpn, safe="")
        queue = quote(queue_name, safe="")
        return f"{self.base_url}/SEMP/v2/monitor/msgVpns/{vpn}/queues/{queue}"

    def queue_subscription_collection_url(self, queue_name: str) -> str:
        vpn = quote(self.message_vpn, safe="")
        queue = quote(queue_name, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/queues/{queue}/subscriptions"

    def queue_subscription_config_url(self, queue_name: str, subscription: str) -> str:
        topic = quote(subscription, safe="")
        return f"{self.queue_subscription_collection_url(queue_name)}/{topic}"

    def get_queue(self, queue_name: str) -> dict[str, Any] | None:
        response = self._request("GET", self.queue_config_url(queue_name))
        if response.status_code == 404:
            return None
        self._raise_for_status(response, f"get queue {queue_name}")
        data = response.json().get("data", {})
        return cast(dict[str, Any], data if isinstance(data, dict) else {})

    def ensure_queue(
        self,
        *,
        queue_name: str,
        access_type: str = "exclusive",
        dmq_name: str | None = None,
        permission: str = "consume",
        owner: str = "",
        max_redelivery_count: int = 0,
        max_ttl_seconds: int = 0,
        max_spool_usage_mb: int | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "queueName": queue_name,
            "accessType": access_type,
            "egressEnabled": True,
            "ingressEnabled": True,
            "permission": permission,
        }
        if owner:
            body["owner"] = owner
        if dmq_name:
            body["deadMsgQueue"] = dmq_name
        if max_redelivery_count > 0:
            body["maxRedeliveryCount"] = max_redelivery_count
            body["redeliveryEnabled"] = True
        if max_ttl_seconds > 0:
            body["maxTtl"] = max_ttl_seconds
            body["respectTtlEnabled"] = True
        if max_spool_usage_mb is not None:
            body["maxMsgSpoolUsage"] = max_spool_usage_mb
        if dry_run:
            return {"queue": queue_name, "status": "would_create", "body": body}
        existing = self.get_queue(queue_name)
        if existing:
            return {"queue": queue_name, "status": "exists", "data": existing}
        response = self._request("POST", self.queue_collection_url(), json=body)
        self._raise_for_status(response, f"create queue {queue_name}", allowed={200, 201, 202})
        return {"queue": queue_name, "status": "created", "data": response.json().get("data", {})}

    def get_queue_subscription(self, queue_name: str, subscription: str) -> dict[str, Any] | None:
        response = self._request("GET", self.queue_subscription_config_url(queue_name, subscription))
        if response.status_code == 404:
            return None
        self._raise_for_status(response, f"get queue subscription {queue_name} {subscription}")
        data = response.json().get("data", {})
        return cast(dict[str, Any], data if isinstance(data, dict) else {})

    def ensure_queue_subscription(
        self,
        *,
        queue_name: str,
        subscription: str,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body = {"subscriptionTopic": subscription}
        if dry_run:
            return {
                "queue": queue_name,
                "subscription": subscription,
                "status": "would_create",
                "body": body,
            }
        existing = self.get_queue_subscription(queue_name, subscription)
        if existing:
            return {
                "queue": queue_name,
                "subscription": subscription,
                "status": "exists",
                "data": existing,
            }
        response = self._request("POST", self.queue_subscription_collection_url(queue_name), json=body)
        self._raise_for_status(
            response,
            f"create queue subscription {queue_name} {subscription}",
            allowed={200, 201, 202},
        )
        return {
            "queue": queue_name,
            "subscription": subscription,
            "status": "created",
            "data": response.json().get("data", {}),
        }

    def queue_stats(self, queue_name: str) -> dict[str, Any] | None:
        response = self._request("GET", self.queue_monitor_url(queue_name))
        if response.status_code == 404:
            return None
        self._raise_for_status(response, f"monitor queue {queue_name}")
        data = response.json().get("data", {})
        return cast(dict[str, Any], data if isinstance(data, dict) else {})

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.request_timeout_seconds
        if self.min_request_interval_seconds > 0:
            elapsed = time.monotonic() - self._last_request_at
            wait_for = self.min_request_interval_seconds - elapsed
            if wait_for > 0:
                self.sleep(wait_for)
        response = request_with_retry(self.session, method, url, **kwargs)
        self._last_request_at = time.monotonic()
        return response

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str, *, allowed: set[int] | None = None) -> None:
        allowed_codes = allowed or {200}
        if response.status_code not in allowed_codes:
            raise RuntimeError(
                f"SEMP {operation} failed with {response.status_code}: "
                f"{redact_text(response.text[:500])}"
            )
