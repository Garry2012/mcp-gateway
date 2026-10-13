# -*- coding: utf-8 -*-
"""Verify call sessions through a local gateway and a local OTLP collector.

Run with ``python -m tests.live_gateway.test_call_sessions`` and observability extras.
The test creates isolated synthetic services and never uses Azure credentials.
"""

# Standard
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
from threading import Thread
import time

# Third-Party
import httpx
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    """Find an available loopback port for an isolated test service."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_ready(url: str, process: subprocess.Popen[bytes]) -> None:
    """Wait for a test service to answer requests or exit.

    Args:
        url: Local readiness endpoint.
        process: Test service process.

    Raises:
        RuntimeError: The service exits before it becomes ready.
        TimeoutError: The service does not respond within 100 seconds.
    """
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


def test_call_sessions() -> None:
    """Export separate call sessions through one persistent MCP connection."""
    spans = []

    class Collector(BaseHTTPRequestHandler):
        """Collect synthetic spans through the real OTLP HTTP exporter."""

        def do_POST(self):  # noqa: N802
            """Decode a protobuf trace export and acknowledge it."""
            payload = ExportTraceServiceRequest.FromString(self.rfile.read(int(self.headers["Content-Length"])))
            for resource in payload.resource_spans:
                for scope in resource.scope_spans:
                    for span in scope.spans:
                        attrs = {a.key: a.value.string_value for a in span.attributes}
                        spans.append((span.name, span.trace_id.hex(), attrs))
            self.send_response(200)
            self.end_headers()

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            """Suppress request logging for the synthetic collector."""

    collector = ThreadingHTTPServer(("127.0.0.1", 0), Collector)
    Thread(target=collector.serve_forever, daemon=True).start()
    processes = []
    with tempfile.TemporaryDirectory(prefix="call-session-e2e-") as work:
        try:
            base = Path(work)
            gateway_port, upstream_port = free_port(), free_port()
            password = secrets.token_urlsafe(32)
            env = {k: v for k, v in os.environ.items() if not k.startswith(("OTEL_", "LANGFUSE_"))}
            env.update(
                PYTHONPATH=str(ROOT),
                ENVIRONMENT="development",
                DATABASE_URL=f"sqlite:///{base / 'gateway.db'}",
                JWT_SECRET_KEY=secrets.token_urlsafe(48),
                AUTH_ENCRYPTION_SECRET=secrets.token_urlsafe(48),
                PLATFORM_ADMIN_EMAIL="call-test@example.com",
                PLATFORM_ADMIN_PASSWORD=password,
                DEFAULT_USER_PASSWORD=secrets.token_urlsafe(32),
                AUTH_REQUIRED="true",
                MCP_REQUIRE_AUTH="true",
                EMAIL_AUTH_ENABLED="true",
                MCPGATEWAY_ADMIN_API_ENABLED="true",
                CACHE_TYPE="memory",
                REDIS_URL="",
                PLUGINS_ENABLED="false",
                SSRF_ALLOW_LOCALHOST="true",
                USE_STATEFUL_SESSIONS="true",
                MCPGATEWAY_SESSION_AFFINITY_ENABLED="false",
                LOG_LEVEL="ERROR",
                MCP_CLIENT_CONNECT_MODE="legacy",
                MCP_INBOUND_PROTOCOL_MODE="legacy",
                OTEL_ENABLE_OBSERVABILITY="true",
                OTEL_TRACES_EXPORTER="otlp",
                OTEL_EXPORTER_OTLP_ENDPOINT=f"http://127.0.0.1:{collector.server_port}/v1/traces",
                OTEL_EXPORTER_OTLP_PROTOCOL="http",
                OTEL_EXPORTER_OTLP_INSECURE="true",
                OTEL_EMIT_LANGFUSE_ATTRIBUTES="true",
                OTEL_CAPTURE_IDENTITY_ATTRIBUTES="false",
                OTEL_HTTPX_INSTRUMENTATION_ENABLED="true",
                OTEL_BSP_SCHEDULE_DELAY="100",
            )
            upstream = base / "upstream.py"
            upstream.write_text(
                'from fastmcp import FastMCP\nmcp = FastMCP("call-session-test")\n'
                "@mcp.tool\ndef echo(value: str) -> str:\n    return value\n"
                f'mcp.run(transport="http", host="127.0.0.1", port={upstream_port})\n'
            )
            with (base / "upstream.log").open("w") as log:
                processes.append(subprocess.Popen([sys.executable, str(upstream)], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT))
            wait_ready(f"http://127.0.0.1:{upstream_port}/mcp", processes[-1])
            with (base / "gateway.log").open("w") as log:
                processes.append(
                    subprocess.Popen(
                        [sys.executable, "-m", "uvicorn", "mcpgateway.main:app", "--host", "127.0.0.1", "--port", str(gateway_port)], cwd=work, env=env, stdout=log, stderr=subprocess.STDOUT
                    )
                )
            url = f"http://127.0.0.1:{gateway_port}"
            wait_ready(url + "/health", processes[-1])
            with httpx.Client(base_url=url, timeout=60, follow_redirects=True) as client:
                response = client.post("/auth/email/login", json={"email": "call-test@example.com", "password": password})
                response.raise_for_status()
                client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
                response = client.post("/gateways", json={"name": "session-test", "url": f"http://127.0.0.1:{upstream_port}/mcp", "transport": "STREAMABLEHTTP", "visibility": "public"})
                response.raise_for_status()
                response = client.get("/tools", params={"limit": 0})
                response.raise_for_status()
                tools = response.json()
                tool = (tools if isinstance(tools, list) else tools["items"])[0]
                response = client.post("/servers", json={"server": {"name": "Session Clinic", "associated_tools": [tool["id"]], "visibility": "public"}})
                response.raise_for_status()
                endpoint = f"/servers/{response.json()['id']}/mcp"
                client.headers["Accept"] = "application/json, text/event-stream"
                response = client.post(
                    endpoint,
                    headers={"X-Call-Id": "initialization-call"},
                    json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "session-test", "version": "1"}}},
                )
                response.raise_for_status()
                session_id = response.headers["mcp-session-id"]
                client.headers["Mcp-Session-Id"] = session_id
                client.headers["MCP-Protocol-Version"] = "2025-03-26"
                response = client.post(endpoint, json={"jsonrpc": "2.0", "method": "notifications/initialized"})
                response.raise_for_status()
                expected = {}
                for index, call_id in enumerate(["call-a", "call-b", None], 2):
                    trace_id = secrets.token_hex(16)
                    headers = {"traceparent": f"00-{trace_id}-{secrets.token_hex(8)}-01"}
                    if call_id:
                        headers["X-Call-Id"] = call_id
                    response = client.post(
                        endpoint, headers=headers, json={"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": {"name": tool["name"], "arguments": {"value": f"echo-{index}"}}}
                    )
                    response.raise_for_status()
                    body = response.text
                    result = json.loads(next(line[6:] for line in body.splitlines() if line.startswith("data: "))) if body.startswith("event:") else response.json()
                    assert "error" not in result and not result["result"].get("isError"), result
                    expected[trace_id] = call_id
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    ready = all(
                        any(name == "tool.invoke" and tid == trace_id for name, tid, _attrs in spans)
                        and any(name.startswith("Session Clinic /") and tid == trace_id for name, tid, _attrs in spans)
                        and (call_id is None or any(name == "POST" and tid == trace_id and attrs.get("langfuse.session.id") == call_id for name, tid, attrs in spans))
                        for trace_id, call_id in expected.items()
                    )
                    if ready:
                        break
                    time.sleep(0.1)
                for trace_id, call_id in expected.items():
                    related = [(name, attrs) for name, tid, attrs in spans if tid == trace_id]
                    invoked = [attrs for name, attrs in related if name == "tool.invoke"]
                    assert len(invoked) == 1, related
                    if call_id:
                        assert invoked[0].get("langfuse.session.id") == call_id, related
                        assert all(attrs.get("langfuse.session.id") in {None, call_id} for _name, attrs in related), related
                        assert any(name == "POST" and attrs.get("langfuse.session.id") == call_id for name, attrs in related), related
                        assert any(name.startswith("Session Clinic /") and attrs.get("langfuse.session.id") == call_id for name, attrs in related), related
                    else:
                        assert all(attrs.get("langfuse.session.id") not in {"call-a", "call-b", "initialization-call"} for _name, attrs in related), related
                print("PASS: one persistent MCP session keeps call-a, call-b, and headerless tool requests separate; roots and HTTP child spans retain call IDs.")
        finally:
            for process in reversed(processes):
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            collector.shutdown()
            collector.server_close()


if __name__ == "__main__":
    test_call_sessions()
