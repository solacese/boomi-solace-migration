from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

from .config import SolaceSempConfig

RETRYABLE = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


class SolaceError(Exception):
    pass


class SolaceClient:
    def __init__(self, config: SolaceSempConfig) -> None:
        self.base_url = config.base_url.rstrip("/")
        self.vpn = config.message_vpn
        self.session = requests.Session()
        self.session.auth = (config.username, config.password)
        self._last_request_at = 0.0
        self._min_interval = 0.11

    def check_auth(self) -> None:
        url = f"{self.base_url}/SEMP/v2/config/msgVpns/{quote(self.vpn, safe='')}"
        response = self._request("GET", url)
        if self._is_not_found(response):
            raise SolaceError(f"Solace VPN '{self.vpn}' not found")
        if response.status_code not in (200,):
            raise SolaceError(f"Solace auth check failed: HTTP {response.status_code} — {response.text[:200]}")

    def ensure_queue(self, queue_name: str, *, access_type: str = "exclusive") -> dict[str, Any]:
        existing = self._get_queue(queue_name)
        if existing is not None:
            return {"queue": queue_name, "status": "exists"}
        body = {
            "queueName": queue_name,
            "accessType": access_type,
            "egressEnabled": True,
            "ingressEnabled": True,
            "permission": "consume",
        }
        url = f"{self.base_url}/SEMP/v2/config/msgVpns/{quote(self.vpn, safe='')}/queues"
        response = self._request("POST", url, json=body)
        if response.status_code not in (200, 201):
            raise SolaceError(f"Create queue '{queue_name}' failed: HTTP {response.status_code} — {response.text[:300]}")
        return {"queue": queue_name, "status": "created"}

    def ensure_subscription(self, queue_name: str, topic: str) -> dict[str, Any]:
        existing = self._get_subscription(queue_name, topic)
        if existing is not None:
            return {"queue": queue_name, "subscription": topic, "status": "exists"}
        url = (
            f"{self.base_url}/SEMP/v2/config/msgVpns/{quote(self.vpn, safe='')}"
            f"/queues/{quote(queue_name, safe='')}/subscriptions"
        )
        body = {"subscriptionTopic": topic}
        response = self._request("POST", url, json=body)
        if response.status_code not in (200, 201):
            raise SolaceError(
                f"Create subscription '{topic}' on '{queue_name}' failed: "
                f"HTTP {response.status_code} — {response.text[:300]}"
            )
        return {"queue": queue_name, "subscription": topic, "status": "created"}

    def _get_queue(self, queue_name: str) -> dict[str, Any] | None:
        url = (
            f"{self.base_url}/SEMP/v2/config/msgVpns/{quote(self.vpn, safe='')}"
            f"/queues/{quote(queue_name, safe='')}"
        )
        response = self._request("GET", url)
        if self._is_not_found(response):
            return None
        if response.status_code != 200:
            raise SolaceError(f"GET queue '{queue_name}' failed: HTTP {response.status_code} — {response.text[:300]}")
        return response.json().get("data", {})

    def _get_subscription(self, queue_name: str, topic: str) -> dict[str, Any] | None:
        url = (
            f"{self.base_url}/SEMP/v2/config/msgVpns/{quote(self.vpn, safe='')}"
            f"/queues/{quote(queue_name, safe='')}/subscriptions/{quote(topic, safe='')}"
        )
        response = self._request("GET", url)
        if self._is_not_found(response):
            return None
        if response.status_code != 200:
            raise SolaceError(f"GET subscription failed: HTTP {response.status_code} — {response.text[:300]}")
        return response.json().get("data", {})

    def _is_not_found(self, response: requests.Response) -> bool:
        if response.status_code == 404:
            return True
        if response.status_code == 400:
            try:
                status = response.json().get("meta", {}).get("error", {}).get("status", "")
                return status == "NOT_FOUND"
            except (ValueError, KeyError, AttributeError):
                pass
        return False

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        for attempt in range(MAX_RETRIES + 1):
            response = self.session.request(method, url, **kwargs)
            self._last_request_at = time.monotonic()
            if response.status_code not in RETRYABLE:
                return response
            if attempt < MAX_RETRIES:
                time.sleep(0.5 * (2 ** attempt))
        return response
