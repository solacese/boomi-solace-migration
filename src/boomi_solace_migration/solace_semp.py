from __future__ import annotations

import os
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
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.message_vpn = message_vpn
        self.session = requests.Session()
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

    def get_queue(self, queue_name: str) -> dict[str, Any] | None:
        response = request_with_retry(self.session, "GET", self.queue_config_url(queue_name))
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
        dry_run: bool = False,
    ) -> dict[str, Any]:
        existing = self.get_queue(queue_name)
        if existing:
            return {"queue": queue_name, "status": "exists", "data": existing}
        body: dict[str, Any] = {
            "queueName": queue_name,
            "accessType": access_type,
            "egressEnabled": True,
            "ingressEnabled": True,
            "permission": "consume",
        }
        if dmq_name:
            body["deadMsgQueue"] = dmq_name
            body["respectTtlEnabled"] = True
        if dry_run:
            return {"queue": queue_name, "status": "would_create", "body": body}
        response = request_with_retry(self.session, "POST", self.queue_collection_url(), json=body)
        self._raise_for_status(response, f"create queue {queue_name}", allowed={200, 201, 202})
        return {"queue": queue_name, "status": "created", "data": response.json().get("data", {})}

    def queue_stats(self, queue_name: str) -> dict[str, Any] | None:
        response = request_with_retry(self.session, "GET", self.queue_monitor_url(queue_name))
        if response.status_code == 404:
            return None
        self._raise_for_status(response, f"monitor queue {queue_name}")
        data = response.json().get("data", {})
        return cast(dict[str, Any], data if isinstance(data, dict) else {})

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str, *, allowed: set[int] | None = None) -> None:
        allowed_codes = allowed or {200}
        if response.status_code not in allowed_codes:
            raise RuntimeError(
                f"SEMP {operation} failed with {response.status_code}: "
                f"{redact_text(response.text[:500])}"
            )
