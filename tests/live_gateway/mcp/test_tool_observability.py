# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/mcp/test_tool_observability.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Black-box tool recording parity against an isolated running Python gateway.

Run with MCP_OBSERVABILITY_E2E=true and MCP_CLI_BASE_URL pointing at the test gateway.
The gateway needs OBSERVABILITY_ENABLED=true, DB_METRICS_RECORDING_ENABLED=true,
MCPGATEWAY_DIRECT_PROXY_ENABLED=true, SSRF_ALLOW_LOCALHOST=true and TOOL_TIMEOUT=2.
Use METRICS_BUFFER_FLUSH_INTERVAL=5 and METRICS_CACHE_TTL_SECONDS=1 for fast feedback.
The fixture admin must have completed any required password change.
The deterministic upstream runs locally; the gateway must be able to reach its port.

    pytest tests/live_gateway/mcp/test_tool_observability.py -v
"""

# Standard
import asyncio
from collections.abc import Iterator
from datetime import timedelta
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any
import uuid

# Third-Party
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from mcp.types import CallToolResult
import pytest

# Local
from ..helpers.mcp_test_helpers import ADMIN_EMAIL, BASE_URL, JWT_SECRET, skip_no_gateway
from tests.helpers.auth import make_auth_headers, make_test_jwt

ObservationCatalog = tuple[httpx.Client, dict[str, str], str, str, dict[str, dict[str, Any]]]

pytestmark = [pytest.mark.e2e, skip_no_gateway, pytest.mark.skipif(os.getenv("MCP_OBSERVABILITY_E2E") != "true", reason="Requires an isolated observability test gateway")]

_UPSTREAM = '''
import asyncio
import sys
from mcp.server.fastmcp import FastMCP
server = FastMCP("observation-fixture", host="127.0.0.1", port=int(sys.argv[1]), stateless_http=True)
@server.tool()
async def echo(value: str, outcome: str = "ok") -> dict:
    """Echo a value, or produce a deterministic MCP error or timeout."""
    if outcome == "error":
        raise ValueError("fixture tool failure")
    if outcome == "timeout":
        await asyncio.sleep(10)
    return {"value": value}
@server.tool()
async def unregistered_echo(value: str) -> dict:
    """Remain callable upstream after removing the local catalog row."""
    return {"value": value}
server.run(transport="streamable-http")
'''


@pytest.fixture
def observation_catalog(tmp_path: Path) -> Iterator[ObservationCatalog]:
    """Register a disposable deterministic upstream and virtual server through public APIs."""
    port = int(os.getenv("MCP_OBSERVABILITY_UPSTREAM_PORT", "18446"))
    headers = make_auth_headers(make_test_jwt(ADMIN_EMAIL, is_admin=True, teams=None, secret=JWT_SECRET))
    with (tmp_path / "upstream.log").open("w") as log:
        upstream = subprocess.Popen([sys.executable, "-c", _UPSTREAM, str(port)], stdout=log, stderr=log)
        gateway_id = server_id = None
        try:
            with httpx.Client(base_url=BASE_URL, headers=headers, timeout=30) as client:
                deadline = time.monotonic() + 20
                while True:
                    assert upstream.poll() is None, "Upstream exited during startup"
                    try:
                        httpx.get(f"http://127.0.0.1:{port}/mcp", timeout=1)
                        break
                    except httpx.TransportError:
                        assert time.monotonic() < deadline, "Upstream did not start"
                        time.sleep(0.1)
                uid = uuid.uuid4().hex[:12]
                response = client.post("/gateways", json={"name": f"observation-{uid}", "url": f"http://127.0.0.1:{port}/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"})
                response.raise_for_status()
                gateway_id = response.json()["id"]
                response = client.get("/tools", params={"limit": 1000})
                response.raise_for_status()
                payload = response.json()
                tools = payload if isinstance(payload, list) else payload["tools"]
                tools = {t.get("originalName", t.get("original_name")): t for t in tools if t.get("gatewayId", t.get("gateway_id")) == gateway_id}
                assert set(tools) == {"echo", "unregistered_echo"}
                response = client.post("/servers", json={"server": {"name": f"observation-{uid}", "associated_tools": [t["id"] for t in tools.values()]}, "visibility": "public"})
                response.raise_for_status()
                server_id = response.json()["id"]
                assert isinstance(gateway_id, str) and isinstance(server_id, str)
                yield client, headers, gateway_id, server_id, tools
        finally:
            # Always reap the fixture process, even if API cleanup fails.
            upstream.terminate()
            try:
                upstream.wait(timeout=10)
            except subprocess.TimeoutExpired:
                upstream.kill()
                upstream.wait(timeout=5)
            with httpx.Client(base_url=BASE_URL, headers=headers, timeout=10) as client:
                if server_id:
                    client.delete(f"/servers/{server_id}")
                if gateway_id:
                    client.delete(f"/gateways/{gateway_id}")


def _metrics(client: httpx.Client, resource: str, resource_id: str, server_id: str | None = None) -> dict[str, Any]:
    """Fetch metrics from the existing resource read API."""
    path = f"/servers/{server_id}/tools" if resource == "tools" else "/servers"
    response = client.get(path, params={"include_metrics": "true", "limit": 1000})
    response.raise_for_status()
    payload = response.json()
    rows = payload if isinstance(payload, list) else payload[resource]
    metrics: dict[str, Any] = next(row["metrics"] or {} for row in rows if row["id"] == resource_id)
    return metrics


def _total(metrics: dict[str, Any]) -> int:
    """Accept the API's alias spelling without changing its counter semantics."""
    value = metrics.get("totalExecutions", metrics.get("total_executions", 0))
    return int(value) if value is not None else 0


@pytest.mark.asyncio
async def test_tool_observability_parity(observation_catalog: ObservationCatalog) -> None:
    """Real protocol calls produce named spans and independent tool/server metric deltas."""
    client, headers, gateway_id, server_id, tools = observation_catalog
    echo = tools["echo"]
    tool_before = _total(_metrics(client, "tools", echo["id"], server_id))
    server_before = _total(_metrics(client, "servers", server_id))
    endpoint = f"{BASE_URL}/servers/{server_id}/mcp/"

    async def invoke(name: str, outcome: str = "ok", direct: bool = False, scoped: bool = True, arguments: dict[str, Any] | None = None) -> CallToolResult:
        call_headers = dict(headers)
        if direct:
            call_headers["X-Context-Forge-Gateway-Id"] = gateway_id
        async with streamablehttp_client(endpoint if scoped else f"{BASE_URL}/mcp/", headers=call_headers, timeout=15) as (read, write, _):
            async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=15)) as session:
                await session.initialize()
                await session.list_tools()
                args = {"value": "fixture"}
                if name != "unregistered_echo":
                    args["outcome"] = outcome
                return await session.call_tool(name, args if arguments is None else arguments)

    normal = await invoke(echo["name"])
    assert not normal.isError
    assert not (await invoke(echo["name"], scoped=False)).isError
    rejected = await invoke(echo["name"], arguments={"private": "private-customer-value"})
    assert rejected.isError
    assert "private-customer-value" not in str(rejected)
    assert (await invoke(echo["name"], "timeout")).isError
    response = client.put(f"/gateways/{gateway_id}", json={"gateway_mode": "direct_proxy"})
    response.raise_for_status()
    direct = await invoke("echo", direct=True)
    assert not direct.isError
    assert direct.structuredContent == normal.structuredContent
    assert (await invoke("echo", "error", direct=True)).isError

    # A caller-supplied /rpc server ID is not validated endpoint context, even if it exists.
    for supplied_server_id in (server_id, uuid.uuid4().hex):
        response = client.post(
            "/rpc",
            headers={"X-Context-Forge-Gateway-Id": gateway_id},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "echo", "arguments": {"value": "fixture"}, "server_id": supplied_server_id}},
        )
        response.raise_for_status()
        assert "error" not in response.json()

    # The transport's unscoped fallback must not become a foreign key in the metrics batch.
    assert not (await invoke("echo", direct=True, scoped=False)).isError

    response = client.delete(f"/tools/{tools['unregistered_echo']['id']}")
    response.raise_for_status()
    assert not (await invoke("unregistered_echo", direct=True)).isError

    # A rejected unauthenticated request must not contribute execution metrics.
    response = httpx.post(endpoint, json={"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "echo", "arguments": {"value": "denied"}}})
    assert response.status_code == 401

    deadline = time.monotonic() + 90
    while True:
        tool_count = _total(_metrics(client, "tools", echo["id"], server_id)) - tool_before
        server_count = _total(_metrics(client, "servers", server_id)) - server_before
        if (tool_count, server_count) == (9, 6):
            break
        assert time.monotonic() < deadline, f"Expected (9, 6) metric deltas, got {(tool_count, server_count)}"
        await asyncio.sleep(2)

    response = client.get("/observability/spans", params={"resource_type": "tool", "resource_name": echo["name"], "limit": 100})
    response.raise_for_status()
    spans = [s for s in response.json() if s["name"] == "tool.invoke"]
    assert len(spans) == 9
    rejected_spans = [s for s in spans if s["attributes"].get("tool.failure_reason") == "invalid_arguments"]
    assert len(rejected_spans) == 1
    assert "private-customer-value" not in str(rejected_spans)
    assert sorted(s["status"] for s in spans) == ["error", "error", "error", "ok", "ok", "ok", "ok", "ok", "ok"]
    assert sum(s["attributes"].get("server.id") == server_id for s in spans) == 5
    assert sum(s["attributes"].get("server.id") is None for s in spans) == 4
    assert {s["attributes"].get("tool.execution_mode") for s in spans} == {"catalog", "direct_proxy"}
    assert all(s.get("resourceId", s.get("resource_id")) == echo["id"] for s in spans)
    # The real admin HTML exposes tool outcomes and names, including HTTP-200 MCP errors.
    response = client.get("/admin/observability/traces", params={"tool_name": "echo", "time_range": "1h"})
    response.raise_for_status()
    assert echo["name"] in response.text
    assert "Succeeded" in response.text and "Failed" in response.text
    assert "HTTP 200" in response.text
    response = client.get(f"/admin/observability/trace/{spans[0].get('trace_id', spans[0].get('traceId'))}")
    response.raise_for_status()
    assert "Tool invocations" in response.text
    assert "Catalog name:" in response.text

    response = client.get("/observability/spans", params={"resource_type": "tool", "resource_name": "unregistered_echo", "limit": 100})
    response.raise_for_status()
    unknown = [s for s in response.json() if s["attributes"].get("server.id") == server_id]
    assert len(unknown) == 1
    assert unknown[0]["attributes"]["tool.catalog_match"] == "unregistered"
