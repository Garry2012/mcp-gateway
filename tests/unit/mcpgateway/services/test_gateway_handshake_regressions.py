# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/services/test_gateway_handshake_regressions.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Regression checks for administrative upstream MCP negotiation.
"""

# Standard
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import httpx
import httpx2
import pytest

# First-Party
from mcpgateway.config import settings
from mcpgateway.schemas import GatewayHandshakeRequest
from mcpgateway.services import gateway_service as gs
from mcpgateway.utils.retry_manager import ResilientHttpClient


@pytest.fixture
def probe_transport(monkeypatch):
    """Replace HTTP transports while retaining the real MCP negotiation code."""
    requests = []
    redirect = False

    def respond(request: Any, response_type: Any) -> Any:
        """Serve a synthetic MCP endpoint with the adapter's Accept requirement."""
        payload = json.loads(request.content) if request.content else {}
        method = payload.get("method")
        requests.append((request.url.scheme, method))
        assert request.url.path == "/mcp/"
        if redirect:
            return response_type(307, headers={"Location": "http://example.com/mcp"})
        if request.method != "POST":
            return response_type(405)
        if method == "server/discover":
            if "text/event-stream" not in request.headers.get("accept", ""):
                return response_type(406)
            result = {
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "synthetic", "version": "1"}},
                "supportedVersions": ["2026-07-28"],
                "capabilities": {"tools": {}},
                "resultType": "complete",
                "ttlMs": 0,
                "cacheScope": "private",
            }
        elif method == "initialize":
            result = {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "synthetic", "version": "1"}}
        elif method == "notifications/initialized":
            return response_type(202)
        elif method == "tools/list":
            result = {"tools": [], "resultType": "complete", "ttlMs": 0, "cacheScope": "private"}
        else:
            pytest.fail(f"Unexpected MCP method: {method}")
        return response_type(200, json={"jsonrpc": "2.0", "id": payload["id"], "result": result})

    def resilient_client(client_args: dict[str, Any] | None = None) -> ResilientHttpClient:
        """Inject the mock transport into the manual discovery client."""
        return ResilientHttpClient(client_args={**(client_args or {}), "transport": httpx.MockTransport(lambda request: respond(request, httpx.Response))})

    target = {
        "validated_base_url": "https://example.com/mcp/",
        "validated_hostname": "example.com",
        "pinned_base_url": "https://192.0.2.1/mcp/",
        "resolved_ip": "192.0.2.1",
        "original_authority": "example.com",
    }
    monkeypatch.setattr(gs, "_validate_gateway_test_target", AsyncMock(return_value=target))
    monkeypatch.setattr(gs, "ResilientHttpClient", resilient_client)
    monkeypatch.setattr(gs, "_SniPinningTransport", lambda **kwargs: httpx2.MockTransport(lambda request: respond(request, httpx2.Response)))
    monkeypatch.setattr(settings, "health_check_timeout", 3)
    db = MagicMock()
    db.execute.return_value.scalars.return_value.first.return_value = None

    async def run(mode, *, unsafe_redirect=False):
        """Run the administrative probe against the synthetic endpoint."""
        nonlocal redirect
        redirect = unsafe_redirect
        requests.clear()
        monkeypatch.setattr(settings, "mcp_client_connect_mode", mode)
        result = await gs.test_gateway_handshake(GatewayHandshakeRequest(base_url=target["validated_base_url"]), None, {"email": "synthetic@example.com"}, db)
        return result, requests

    return run


def test_registered_endpoint_keeps_trailing_slash():
    """Preserve the registered path to avoid redirects behind TLS termination."""
    url = "https://example.com/mcp/"
    assert gs._gateway_test_endpoint_url(url, "") == url
    assert gs._gateway_test_endpoint_url("https://example.com/base?key=value", "mcp/") == "https://example.com/base/mcp?key=value"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,version,path", [("auto", "2026-07-28", "server_discover"), ("legacy", "2025-11-25", "initialize")])
async def test_probe_negotiates_supported_protocol(probe_transport, mode, version, path):
    """Use modern discovery in auto mode and retain legacy initialization."""
    result, requests = await probe_transport(mode)
    assert result.success, result.error
    assert result.protocol_version == version
    assert result.negotiation_path == path
    assert result.component_counts == {"tools": 0}
    methods = [method for _, method in requests]
    assert "tools/list" in methods
    assert ("initialize" in methods) == (mode == "legacy")
    assert ("server/discover" in methods) == (mode == "auto")


@pytest.mark.asyncio
async def test_probe_rejects_https_downgrade(probe_transport):
    """Reject an insecure redirect without sending plaintext HTTP requests."""
    for mode in ("auto", "legacy"):
        result, requests = await probe_transport(mode, unsafe_redirect=True)
        assert not result.success
        assert requests
        assert all(scheme == "https" for scheme, _ in requests)
        assert all(method != "tools/list" for _, method in requests)


def test_http_client_errors_keep_their_failure_class():
    """Classify connection failures and denied authentication for both clients."""
    for error in (httpx.ConnectError("synthetic connection failure"), httpx2.ConnectError("synthetic connection failure")):
        assert gs._classify_handshake_error(error)[0] == "transport"
    request_v1 = httpx.Request("POST", "https://example.com/mcp")
    request_v2 = httpx2.Request("POST", "https://example.com/mcp")
    for status in (401, 403):
        for auth_error in (
            httpx.HTTPStatusError("synthetic authentication failure", request=request_v1, response=httpx.Response(status, request=request_v1)),
            httpx2.HTTPStatusError("synthetic authentication failure", request=request_v2, response=httpx2.Response(status, request=request_v2)),
        ):
            assert gs._classify_handshake_error(auth_error)[0] == "auth"
