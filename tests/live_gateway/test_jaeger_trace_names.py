# -*- coding: utf-8 -*-
"""Location: ./tests/live_gateway/test_jaeger_trace_names.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise synthetic MCP calls through an isolated gateway and inspect Jaeger.

Run ``python -m tests.live_gateway.test_jaeger_trace_names`` with observability and
llmchat extras installed. Jaeger must expose query port 16688 and OTLP port 14318.
"""

import asyncio
import os
from pathlib import Path
import secrets
import socket
import subprocess
import tempfile
import time
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[2]
PYTHON = str(ROOT / ".venv/bin/python")
JAEGER = "http://127.0.0.1:16688"


def free_port() -> int:
    """Find an available loopback port for an isolated test service."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(url: str, process: subprocess.Popen[bytes]) -> None:
    """Wait for the test service to answer requests or exit."""
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"Service exited: {process.returncode}")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise TimeoutError(url)


async def call_tool(url: str, token: str, tool_name: str, arguments: dict[str, Any]) -> Any:
    """Discover and invoke a tool twice through one MCP session."""
    from fastmcp import Client
    from fastmcp.client.transports import StreamableHttpTransport

    async with Client(StreamableHttpTransport(url, headers={"Authorization": f"Bearer {token}"})) as client:
        tools = await client.list_tools()
        assert tool_name in [tool.name for tool in tools]
        result = await client.call_tool(tool_name, arguments)
        assert not result.is_error
        return await client.call_tool(tool_name, arguments)


def test_virtual_server_trace_names() -> None:
    """Run a gateway and upstream to verify exported titles, payloads and authorization."""
    processes = []
    with tempfile.TemporaryDirectory(prefix="memphis-jaeger-e2e-") as work:
        try:
            base = Path(work)
            gateway_port, upstream_port = free_port(), free_port()
            password = "E2e-" + secrets.token_urlsafe(24) + "!"  # pragma: allowlist secret
            service = "contextforge-jaeger-check-" + secrets.token_hex(4)
            env = dict(os.environ)
            for key in list(env):
                if key.startswith(("OTEL_", "LANGFUSE_")):
                    env.pop(key)
            env.update(
                PYTHONPATH=str(ROOT),
                ENVIRONMENT="development",
                DATABASE_URL=f"sqlite:///{base / 'gateway.db'}",
                JWT_SECRET_KEY=secrets.token_urlsafe(48),
                AUTH_ENCRYPTION_SECRET=secrets.token_urlsafe(48),
                PLATFORM_ADMIN_EMAIL="jaeger-test@example.com",
                PLATFORM_ADMIN_PASSWORD=password,
                DEFAULT_USER_PASSWORD="Different-" + secrets.token_urlsafe(24) + "!",  # pragma: allowlist secret
                AUTH_REQUIRED="true",
                MCP_REQUIRE_AUTH="true",
                EMAIL_AUTH_ENABLED="true",
                MCPGATEWAY_ADMIN_API_ENABLED="true",
                MCPGATEWAY_UI_ENABLED="true",
                DB_POOL_SIZE="6",
                DB_MAX_OVERFLOW="4",
                DB_POOL_TIMEOUT="2",
                CACHE_TYPE="memory",
                REDIS_URL="",
                PLUGINS_ENABLED="false",
                SSRF_ALLOW_LOCALHOST="true",
                USE_STATEFUL_SESSIONS="true",
                MCPGATEWAY_SESSION_AFFINITY_ENABLED="false",
                LOG_LEVEL="WARNING",
                OBSERVABILITY_ENABLED="true",
                OTEL_ENABLE_OBSERVABILITY="true",
                OTEL_TRACES_EXPORTER="otlp",
                OTEL_EXPORTER_OTLP_ENDPOINT="http://127.0.0.1:14318",
                OTEL_EXPORTER_OTLP_PROTOCOL="grpc",
                OTEL_EXPORTER_OTLP_INSECURE="true",
                OTEL_EMIT_LANGFUSE_ATTRIBUTES="true",
                OTEL_CAPTURE_IDENTITY_ATTRIBUTES="false",
                OTEL_CAPTURE_INPUT_SPANS="tool.invoke",
                OTEL_CAPTURE_OUTPUT_SPANS="tool.invoke",
                OTEL_BSP_SCHEDULE_DELAY="100",
                OTEL_SERVICE_NAME=service,
            )
            upstream = base / "upstream.py"
            upstream.write_text(
                "from fastmcp import FastMCP\n"
                'mcp = FastMCP("Jaeger synthetic check")\n'
                "@mcp.tool\n"
                "def appointment_echo(department: str, api_key: str) -> dict:\n"
                '    return {"appointment_id": "TEST-123", "department": department, "status": "confirmed", "access_token": "synthetic-output-secret"}\n'
                f'mcp.run(transport="http", host="127.0.0.1", port={upstream_port})\n'
            )
            upstream_log = (ROOT / ".context/trace-names-live-upstream.log").open("w")
            proc = subprocess.Popen([PYTHON, str(upstream)], cwd=work, stdout=upstream_log, stderr=subprocess.STDOUT, env=env)
            processes.append(proc)
            wait_ready(f"http://127.0.0.1:{upstream_port}/mcp", proc)
            gateway_log = (ROOT / ".context/trace-names-live-gateway.log").open("w")
            proc = subprocess.Popen(
                [PYTHON, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)], cwd=work, stdout=gateway_log, stderr=subprocess.STDOUT, env=env
            )
            processes.append(proc)
            url = f"http://127.0.0.1:{gateway_port}"
            wait_ready(url + "/health", proc)
            with httpx.Client(base_url=url, timeout=90) as client:
                assert client.get("/gateways").status_code in (401, 403)
                print("PASS unauthenticated gateway access rejected", flush=True)
                r = client.post("/auth/email/login", json={"email": "jaeger-test@example.com", "password": password})
                r.raise_for_status()
                token = r.json()["access_token"]
                client.headers["Authorization"] = "Bearer " + token
                r = client.post("/gateways", json={"name": "jaeger-synthetic", "url": f"http://127.0.0.1:{upstream_port}/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"})
                r.raise_for_status()
                gateway = r.json()
                r = client.get("/tools", params={"limit": 0})
                r.raise_for_status()
                data = r.json()
                tools = data if isinstance(data, list) else data["items"]
                tool = next(t for t in tools if t.get("gatewayId") == gateway["id"])
                r = client.post("/servers", json={"server": {"name": "jaeger-synthetic", "associated_tools": [tool["id"]], "visibility": "public"}})
                r.raise_for_status()
                server = r.json()
                arguments = {"department": "cardiology", "api_key": "synthetic-input-secret"}  # pragma: allowlist secret
                result = asyncio.run(call_tool(url + f"/servers/{server['id']}/mcp", token, tool["name"], arguments))
                assert not result.is_error
                print("PASS first virtual-server MCP call", flush=True)
                r = client.put("/servers/" + server["id"], json={"name": "Clinic Renamed"})
                r.raise_for_status()
                result = asyncio.run(call_tool(url + f"/servers/{server['id']}/mcp", token, tool["name"], arguments))
                assert not result.is_error
                r = client.post("/servers", json={"server": {"name": "Clinic Second", "associated_tools": [tool["id"]], "visibility": "public"}})
                r.raise_for_status()
                second = r.json()

                async def dashboard_with_tools() -> None:
                    """Load dashboard partials while an MCP tool executes."""
                    paths = ["/admin/overview/partial", "/admin/servers/partial", "/admin/tools/partial", "/admin/resources/partial"]
                    async with httpx.AsyncClient(base_url=url, headers={"Authorization": "Bearer " + token}, timeout=30) as dashboard:
                        responses = await asyncio.gather(
                            *(dashboard.get(path) for path in paths),
                            call_tool(url + f"/servers/{second['id']}/mcp", token, tool["name"], arguments),  # pragma: allowlist secret
                        )
                    assert all(response.status_code == 200 for response in responses[:-1])
                    assert not responses[-1].is_error

                asyncio.run(dashboard_with_tools())
                print("PASS dashboard loads during tool execution with a ten-connection pool", flush=True)
                assert not result.is_error
                r = client.post(
                    "/servers/" + second["id"] + "/mcp", headers={"Authorization": ""}, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool["name"], "arguments": {}}}
                )
                assert r.status_code in (401, 403)
                print("PASS renamed server, second server, and unauthenticated denial", flush=True)
            # The Query API uses protobuf field names in query parameters.
            query: dict[str, str | int] = {
                "query.service_name": service,
                "query.num_traces": 200,
                "query.start_time_min": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() - 300)),
                "query.start_time_max": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 60)),
            }
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                response = httpx.get(JAEGER + "/api/v3/traces", params=query, timeout=5)
                if response.status_code != 200:
                    raise RuntimeError(f"Jaeger query: {response.status_code} {response.text[:500]}")
                text = response.text
                if all(name in text for name in ("jaeger-synthetic / appointment_echo", "Clinic Renamed / appointment_echo", "Clinic Second / appointment_echo")):
                    break
                time.sleep(1)
            else:
                raise AssertionError("No captured tool output in Jaeger: " + text[:400])
            assert all(name in text for name in ("jaeger-synthetic / appointment_echo", "Clinic Renamed / appointment_echo", "Clinic Second / appointment_echo"))
            print("PASS Jaeger exported titles for both servers and server rename", flush=True)
            assert "cardiology" in text and "TEST-123" in text
            assert "synthetic-input-secret" not in text and "synthetic-output-secret" not in text
            assert "jaeger-test@example.com" not in text
            (ROOT / ".context/trace-names-live-traces.json").write_text(text)
            (ROOT / ".context/jaeger-service.txt").write_text(service)
            print("PASS Jaeger stores input and output; synthetic secrets and caller identity excluded", flush=True)
            print("Jaeger service: " + service, flush=True)
        finally:
            for proc in reversed(processes):
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


if __name__ == "__main__":
    test_virtual_server_trace_names()
