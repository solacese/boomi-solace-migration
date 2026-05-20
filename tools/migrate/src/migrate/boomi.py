from __future__ import annotations

import base64
import time
import xml.etree.ElementTree as ET
from typing import Any

import requests

from .config import BoomiConfig

RETRYABLE = {429, 500, 502, 503, 504}
MAX_RETRIES = 3


class BoomiError(Exception):
    pass


class BoomiClient:
    def __init__(self, config: BoomiConfig) -> None:
        self.base = f"{config.base_url.rstrip('/')}/{config.account_id}"
        auth = base64.b64encode(f"BOOMI_TOKEN.{config.username}:{config.api_token}".encode()).decode("ascii")
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Basic {auth}"

    def check_auth(self) -> None:
        response = self._request(
            "POST",
            f"{self.base}/Folder/query",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"QueryFilter": {"expression": {"argument": ["Solace"], "operator": "EQUALS", "property": "name"}}},
        )
        if response.status_code in (401, 403):
            raise BoomiError(f"Boomi authentication failed: HTTP {response.status_code}")
        if response.status_code != 200:
            raise BoomiError(f"Boomi auth check failed: HTTP {response.status_code} — {response.text[:200]}")

    def list_folders(self) -> list[dict[str, Any]]:
        response = self._request(
            "POST",
            f"{self.base}/Folder/query",
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json={"QueryFilter": {"expression": {"operator": "and", "nestedExpression": []}}},
        )
        if response.status_code != 200:
            raise BoomiError(f"Folder query failed: HTTP {response.status_code}")
        return list(response.json().get("result", []))

    def get_component_xml(self, component_id: str) -> str:
        response = self._request(
            "GET",
            f"{self.base}/Component/{component_id}",
            headers={"Accept": "application/xml"},
        )
        if response.status_code != 200:
            raise BoomiError(f"GET Component/{component_id} failed: HTTP {response.status_code}")
        return response.text

    def create_component(self, xml_body: str) -> str:
        response = self._request(
            "POST",
            f"{self.base}/Component",
            headers={"Accept": "application/xml", "Content-Type": "application/xml"},
            data=xml_body.encode("utf-8"),
        )
        if response.status_code not in (200, 201):
            raise BoomiError(
                f"Create Component failed: HTTP {response.status_code} — {response.text[:500]}"
            )
        root = ET.fromstring(response.text)
        component_id = root.get("componentId", "")
        if not component_id:
            raise BoomiError("Create Component response missing componentId")
        return component_id

    def delete_component(self, component_id: str) -> None:
        response = self._request(
            "DELETE",
            f"{self.base}/Component/{component_id}",
            headers={"Accept": "application/json"},
        )
        if response.status_code not in (200, 204):
            raise BoomiError(f"DELETE Component/{component_id} failed: HTTP {response.status_code}")

    def _request(self, method: str, url: str, **kwargs: Any) -> requests.Response:
        kwargs.setdefault("timeout", 30)
        for attempt in range(MAX_RETRIES + 1):
            response = self.session.request(method, url, **kwargs)
            if response.status_code not in RETRYABLE:
                return response
            if attempt < MAX_RETRIES:
                time.sleep(0.5 * (2 ** attempt))
        return response
