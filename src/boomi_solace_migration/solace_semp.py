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

    def vpn_config_url(self) -> str:
        vpn = quote(self.message_vpn, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}"

    def check_connectivity(self) -> dict[str, Any]:
        """Preflight check: verify SEMP credentials and VPN existence."""
        response = self._request("GET", self.vpn_config_url())
        if self._is_not_found(response):
            raise RuntimeError(f"Solace VPN '{self.message_vpn}' not found")
        if response.status_code != 200:
            raise RuntimeError(
                f"Solace SEMP connectivity check failed (HTTP {response.status_code}): "
                f"{redact_text(response.text[:300])}"
            )
        data = response.json().get("data", {})
        return {"vpn": self.message_vpn, "status": "ok", "state": data.get("state", "unknown")}

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
        if self._is_not_found(response):
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
            # Check if owner/permission need updating
            needs_update = False
            patch_body: dict[str, Any] = {}
            if owner and existing.get("owner", "") != owner:
                patch_body["owner"] = owner
                needs_update = True
            if existing.get("permission", "") != permission:
                patch_body["permission"] = permission
                needs_update = True
            if dmq_name and existing.get("deadMsgQueue", "") != dmq_name:
                patch_body["deadMsgQueue"] = dmq_name
                needs_update = True
            if needs_update:
                patch_response = self._request(
                    "PATCH", self.queue_config_url(queue_name), json=patch_body
                )
                self._raise_for_status(
                    patch_response, f"update queue {queue_name}", allowed={200}
                )
                patched_data = patch_response.json().get("data", {})
                return {
                    "queue": queue_name,
                    "status": "updated",
                    "patched": patch_body,
                    "data": patched_data,
                }
            return {"queue": queue_name, "status": "exists", "data": existing}
        response = self._request("POST", self.queue_collection_url(), json=body)
        if self._is_already_exists(response):
            # Race condition: queue was created between GET and POST
            existing = self.get_queue(queue_name)
            return {"queue": queue_name, "status": "exists", "data": existing or {}}
        self._raise_for_status(response, f"create queue {queue_name}", allowed={200, 201, 202})
        return {"queue": queue_name, "status": "created", "data": response.json().get("data", {})}

    def get_queue_subscription(self, queue_name: str, subscription: str) -> dict[str, Any] | None:
        response = self._request("GET", self.queue_subscription_config_url(queue_name, subscription))
        if self._is_not_found(response):
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
        if self._is_already_exists(response):
            return {
                "queue": queue_name,
                "subscription": subscription,
                "status": "exists",
            }
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

    # --- Access Control provisioning ---

    def acl_profile_url(self, profile_name: str) -> str:
        vpn = quote(self.message_vpn, safe="")
        name = quote(profile_name, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/aclProfiles/{name}"

    def acl_profile_collection_url(self) -> str:
        vpn = quote(self.message_vpn, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/aclProfiles"

    def client_profile_url(self, profile_name: str) -> str:
        vpn = quote(self.message_vpn, safe="")
        name = quote(profile_name, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/clientProfiles/{name}"

    def client_profile_collection_url(self) -> str:
        vpn = quote(self.message_vpn, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/clientProfiles"

    def client_username_url(self, username: str) -> str:
        vpn = quote(self.message_vpn, safe="")
        name = quote(username, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/clientUsernames/{name}"

    def client_username_collection_url(self) -> str:
        vpn = quote(self.message_vpn, safe="")
        return f"{self.base_url}/SEMP/v2/config/msgVpns/{vpn}/clientUsernames"

    def ensure_acl_profile(
        self,
        *,
        profile_name: str,
        client_connect_default_action: str = "allow",
        publish_topic_default_action: str = "allow",
        subscribe_topic_default_action: str = "allow",
        subscribe_share_name_default_action: str = "allow",
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "aclProfileName": profile_name,
            "clientConnectDefaultAction": client_connect_default_action,
            "publishTopicDefaultAction": publish_topic_default_action,
            "subscribeTopicDefaultAction": subscribe_topic_default_action,
            "subscribeShareNameDefaultAction": subscribe_share_name_default_action,
        }
        if dry_run:
            return {"acl_profile": profile_name, "status": "would_create", "body": body}
        response = self._request("GET", self.acl_profile_url(profile_name))
        if not self._is_not_found(response) and response.status_code == 200:
            return {"acl_profile": profile_name, "status": "exists", "data": response.json().get("data", {})}
        response = self._request("POST", self.acl_profile_collection_url(), json=body)
        if self._is_already_exists(response):
            return {"acl_profile": profile_name, "status": "exists"}
        self._raise_for_status(response, f"create ACL profile {profile_name}", allowed={200, 201, 202})
        return {"acl_profile": profile_name, "status": "created", "data": response.json().get("data", {})}

    def ensure_client_profile(
        self,
        *,
        profile_name: str,
        allow_guaranteed_msg_send: bool = True,
        allow_guaranteed_msg_receive: bool = True,
        allow_transacted_sessions: bool = True,
        allow_bridge_connections: bool = False,
        allow_guaranteed_endpoint_create: bool = False,
        max_connection_count: int = 200,
        max_egress_flow_count: int = 1000,
        max_ingress_flow_count: int = 1000,
        max_subscription_count: int = 500000,
        max_transacted_session_count: int = 10,
        max_transaction_count: int = 50,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "clientProfileName": profile_name,
            "allowGuaranteedMsgSendEnabled": allow_guaranteed_msg_send,
            "allowGuaranteedMsgReceiveEnabled": allow_guaranteed_msg_receive,
            "allowTransactedSessionsEnabled": allow_transacted_sessions,
            "allowBridgeConnectionsEnabled": allow_bridge_connections,
            "allowGuaranteedEndpointCreateEnabled": allow_guaranteed_endpoint_create,
            "maxConnectionCountPerClientUsername": max_connection_count,
            "maxEgressFlowCount": max_egress_flow_count,
            "maxIngressFlowCount": max_ingress_flow_count,
            "maxSubscriptionCount": max_subscription_count,
            "maxTransactedSessionCount": max_transacted_session_count,
            "maxTransactionCount": max_transaction_count,
        }
        if dry_run:
            return {"client_profile": profile_name, "status": "would_create", "body": body}
        response = self._request("GET", self.client_profile_url(profile_name))
        if not self._is_not_found(response) and response.status_code == 200:
            return {"client_profile": profile_name, "status": "exists", "data": response.json().get("data", {})}
        response = self._request("POST", self.client_profile_collection_url(), json=body)
        if self._is_already_exists(response):
            return {"client_profile": profile_name, "status": "exists"}
        self._raise_for_status(response, f"create client profile {profile_name}", allowed={200, 201, 202})
        return {"client_profile": profile_name, "status": "created", "data": response.json().get("data", {})}

    def ensure_client_username(
        self,
        *,
        username: str,
        password: str = "",
        client_profile_name: str = "default",
        acl_profile_name: str = "default",
        enabled: bool = True,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "clientUsername": username,
            "password": password,
            "enabled": enabled,
            "clientProfileName": client_profile_name,
            "aclProfileName": acl_profile_name,
        }
        if dry_run:
            return {"client_username": username, "status": "would_create", "body": body}
        response = self._request("GET", self.client_username_url(username))
        if not self._is_not_found(response) and response.status_code == 200:
            return {"client_username": username, "status": "exists", "data": response.json().get("data", {})}
        response = self._request("POST", self.client_username_collection_url(), json=body)
        if self._is_already_exists(response):
            return {"client_username": username, "status": "exists"}
        self._raise_for_status(response, f"create client username {username}", allowed={200, 201, 202})
        return {"client_username": username, "status": "created", "data": response.json().get("data", {})}

    def queue_stats(self, queue_name: str) -> dict[str, Any] | None:
        response = self._request("GET", self.queue_monitor_url(queue_name))
        if self._is_not_found(response):
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
    def _is_not_found(response: requests.Response) -> bool:
        """Solace Cloud returns 400 with NOT_FOUND instead of 404."""
        if response.status_code == 404:
            return True
        if response.status_code == 400:
            try:
                status = response.json().get("meta", {}).get("error", {}).get("status", "")
                return status == "NOT_FOUND"
            except (ValueError, KeyError, AttributeError):
                pass
        return False

    @staticmethod
    def _is_already_exists(response: requests.Response) -> bool:
        """Solace returns 400 with ALREADY_EXISTS if the resource already exists on POST."""
        if response.status_code == 400:
            try:
                status = response.json().get("meta", {}).get("error", {}).get("status", "")
                return status == "ALREADY_EXISTS"
            except (ValueError, KeyError, AttributeError):
                pass
        return False

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str, *, allowed: set[int] | None = None) -> None:
        allowed_codes = allowed or {200}
        if response.status_code not in allowed_codes:
            raise RuntimeError(
                f"SEMP {operation} failed with {response.status_code}: "
                f"{redact_text(response.text[:500])}"
            )
