from __future__ import annotations

import base64
import os
from typing import Any

import requests

from .http_retry import request_with_retry
from .redaction import redact_text


class BoomiClient:
    def __init__(
        self,
        *,
        account_id: str,
        username: str,
        api_token: str,
        base_url: str = "https://api.boomi.com/api/rest/v1",
    ) -> None:
        self.account_id = account_id
        self.base = f"{base_url.rstrip('/')}/{account_id}"
        auth = base64.b64encode(f"BOOMI_TOKEN.{username}:{api_token}".encode()).decode("ascii")
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Basic {auth}"})

    @classmethod
    def from_env(cls) -> BoomiClient:
        required = ["BOOMI_ACCOUNT_ID", "BOOMI_USERNAME", "BOOMI_API_TOKEN"]
        missing = [key for key in required if not os.environ.get(key)]
        if missing:
            raise ValueError(f"Missing Boomi environment variables: {', '.join(missing)}")
        return cls(
            account_id=os.environ["BOOMI_ACCOUNT_ID"],
            username=os.environ["BOOMI_USERNAME"],
            api_token=os.environ["BOOMI_API_TOKEN"],
            base_url=os.environ.get("BOOMI_BASE_URL", "https://api.boomi.com/api/rest/v1"),
        )

    def _json_headers(self) -> dict[str, str]:
        return {"Accept": "application/json", "Content-Type": "application/json"}

    def _xml_headers(self) -> dict[str, str]:
        return {"Accept": "application/xml", "Content-Type": "application/xml"}

    def list_processes(self) -> list[dict[str, Any]]:
        body: dict[str, Any] = {"QueryFilter": {"expression": {"operator": "and", "nestedExpression": []}}}
        response = request_with_retry(
            self.session,
            "POST",
            f"{self.base}/Process/query",
            headers=self._json_headers(),
            json=body,
        )
        self._raise_for_status(response, "Process/query")
        data = response.json()
        results = list(data.get("result", []))
        token = data.get("queryToken")
        while token and data.get("numberOfResults", 0) > 0:
            response = request_with_retry(
                self.session,
                "POST",
                f"{self.base}/Process/query/more/{token}",
                headers=self._json_headers(),
            )
            self._raise_for_status(response, "Process/query/more")
            data = response.json()
            results.extend(data.get("result", []))
            token = data.get("queryToken") if data.get("numberOfResults", 0) > 0 else None
        return results

    def get_component_xml(self, component_id: str) -> str:
        response = request_with_retry(
            self.session,
            "GET",
            f"{self.base}/Component/{component_id}",
            headers={"Accept": "application/xml"},
        )
        self._raise_for_status(response, f"Component/{component_id}")
        return response.text

    def create_component(self, xml_body: str) -> str:
        response = request_with_retry(
            self.session,
            "POST",
            f"{self.base}/Component",
            headers=self._xml_headers(),
            data=xml_body.encode("utf-8"),
        )
        self._raise_for_status(response, "Component create")
        import xml.etree.ElementTree as ET

        root = ET.fromstring(response.text)
        component_id = root.get("componentId", "")
        if not component_id:
            raise RuntimeError("Boomi create component response did not include componentId")
        return component_id

    def find_component_by_name(self, name: str, folder_id: str, component_type: str) -> str | None:
        """Find a component by exact name in a folder. Returns componentId or None."""
        response = request_with_retry(
            self.session,
            "POST",
            f"{self.base}/ComponentMetadata/query",
            headers=self._json_headers(),
            json={
                "QueryFilter": {
                    "expression": {
                        "operator": "and",
                        "nestedExpression": [
                            {"argument": [name], "operator": "EQUALS", "property": "name"},
                            {"argument": [folder_id], "operator": "EQUALS", "property": "folderId"},
                            {"argument": [component_type], "operator": "EQUALS", "property": "type"},
                        ],
                    }
                }
            },
        )
        if response.status_code != 200:
            return None
        data = response.json()
        results = data.get("result", [])
        for result in results:
            if result.get("name") == name and result.get("folderId") == folder_id:
                cid: str | None = result.get("componentId")
                return cid
        return None

    def create_or_reuse_component(self, xml_body: str) -> str:
        """Create a component, or reuse an existing one with the same name/folder/type."""
        import xml.etree.ElementTree as ET

        root = ET.fromstring(xml_body)
        name = root.get("name", "")
        folder_id = root.get("folderId", "")
        component_type = root.get("type", "")
        if name and folder_id and component_type:
            existing_id = self.find_component_by_name(name, folder_id, component_type)
            if existing_id:
                return existing_id
        return self.create_component(xml_body)

    def delete_component(self, component_id: str) -> None:
        response = request_with_retry(
            self.session,
            "DELETE",
            f"{self.base}/Component/{component_id}",
            headers={"Accept": "application/json"},
        )
        self._raise_for_status(response, f"Component delete {component_id}", allowed={200, 202, 204, 404})

    @staticmethod
    def _raise_for_status(response: requests.Response, operation: str, *, allowed: set[int] | None = None) -> None:
        allowed_codes = allowed or {200, 201}
        if response.status_code not in allowed_codes:
            raise RuntimeError(
                f"Boomi {operation} failed with {response.status_code}: "
                f"{redact_text(response.text[:500])}"
            )
