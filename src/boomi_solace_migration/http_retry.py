from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    retries: int = 3,
    backoff_seconds: float = 0.5,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs: Any,
) -> requests.Response:
    last_response: requests.Response | None = None
    for attempt in range(retries + 1):
        response = session.request(method, url, **kwargs)
        if response.status_code not in RETRYABLE_STATUS_CODES:
            return response
        last_response = response
        if attempt < retries:
            sleep(backoff_seconds * (2**attempt))
    assert last_response is not None
    return last_response
