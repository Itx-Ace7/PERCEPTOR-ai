from __future__ import annotations

import hmac

from fastapi import HTTPException, Request

from app import runtime

HEADER = "x-api-key"
QUERY = "api_key"


def require_token(request: Request) -> None:
    """Reject requests that lack the configured token. A no-op while no token is configured.

    Browsers cannot attach headers to EventSource or plain links, so the token is also
    accepted as a query parameter.
    """
    settings = runtime.settings
    expected = settings.api_token if settings else ""
    if not expected:
        return
    supplied = request.headers.get(HEADER) or request.query_params.get(QUERY) or ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Missing or invalid API token")
