# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_tool_trace_names.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify exported request names and isolation across MCP task boundaries.
"""

# Standard
import asyncio
from contextvars import Context
import re
from typing import Any, cast

# Third-Party
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway import observability


@pytest.fixture
def tracing(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Export real SDK spans and resolve server names from an isolated database."""
    trace_sdk = pytest.importorskip("opentelemetry.sdk.trace")
    if not hasattr(trace_sdk, "TracerProvider"):
        pytest.skip("OpenTelemetry SDK is not installed")
    # Third-Party
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    # First-Party
    from mcpgateway.transports import streamablehttp_transport as transport

    exporter = InMemorySpanExporter()
    provider = trace_sdk.TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("trace-name-test"))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE servers (id TEXT PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO servers VALUES ('a', 'Clinic Alpha'), ('b', 'Clinic Beta')"))
    monkeypatch.setattr("mcpgateway.db.SessionLocal", sessionmaker(bind=engine))
    monkeypatch.setattr(transport, "SessionLocal", sessionmaker(bind=engine))
    yield exporter
    provider.shutdown()
    engine.dispose()


async def request(app: Any, path: str = "/servers/a/mcp", headers: Any = ()) -> None:
    """Run an HTTP request through the real tracing middleware."""
    scope = {"type": "http", "path": path, "method": "POST", "headers": list(headers)}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        pass

    async def validated_app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        # First-Party
        from mcpgateway.transports.streamablehttp_transport import SessionManagerWrapper

        await SessionManagerWrapper._validate_server_id(re.search(r"/servers/(?P<server_id>[^/]+)/mcp", path), path, scope, receive, send)
        await app(scope, receive, send)

    await observability.OpenTelemetryRequestMiddleware(validated_app)(scope, receive, send)


@pytest.mark.asyncio
async def test_virtual_server_names_come_from_database(tracing: Any) -> None:
    """Each server supplies its own name without deployment-specific configuration."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        server_id = scope["path"].split("/")[2]
        observability.record_tool_trace_name(server_id, "registered-availability", "get_availability")
        await asyncio.sleep(0)

    await asyncio.gather(request(app), request(app, "/servers/b/mcp"))
    assert {span.name for span in tracing.get_finished_spans()} == {"Clinic Alpha / get_availability", "Clinic Beta / get_availability"}
    for span in tracing.get_finished_spans():
        assert span.attributes is not None
        assert span.attributes["tool.name"] == "registered-availability"
        assert span.attributes["http.request.method"] == "POST"
        assert span.attributes["contextforge.virtual_server.name"] in ("Clinic Alpha", "Clinic Beta")


@pytest.mark.asyncio
async def test_mcp_task_uses_scope_instead_of_inherited_context(tracing: Any) -> None:
    """A session task can rename the current request without inheriting its ContextVars."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def session_task() -> None:
            context = observability.get_tool_trace_context(scope)
            observability.record_tool_trace_name("a", "registered-search", "search", context)

        await asyncio.create_task(session_task(), context=Context())

    await request(app)
    assert [span.name for span in tracing.get_finished_spans()] == ["Clinic Alpha / search"]


@pytest.mark.asyncio
async def test_remote_parent_is_preserved(tracing: Any) -> None:
    """The gateway names its own span and preserves the caller's trace and parent IDs."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")

    await request(app, headers=[(b"traceparent", b"00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")])
    span = tracing.get_finished_spans()[0]
    assert span.name == "Clinic Alpha / search"
    assert span.context is not None
    assert span.context.trace_id == int("a" * 32, 16)
    assert span.parent is not None
    assert span.parent.span_id == int("b" * 16, 16)


@pytest.mark.asyncio
@pytest.mark.parametrize("server_id, expected", [("a", "Clinic Alpha / multiple tools"), ("b", "Multiple virtual servers / tools/call")])
async def test_multiple_tools_do_not_mislabel_request(tracing: Any, server_id: str, expected: str) -> None:
    """A request containing different tool calls receives an aggregate title."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")
        observability.record_tool_trace_name(server_id, "availability", "availability")

    await request(app)
    assert tracing.get_finished_spans()[0].name == expected


@pytest.mark.asyncio
async def test_failed_tool_retains_readable_name(tracing: Any) -> None:
    """Execution failures keep the resolved tool name and error status."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")
        raise RuntimeError("upstream unavailable")

    with pytest.raises(RuntimeError, match="upstream unavailable"):
        await request(app)
    span = tracing.get_finished_spans()[0]
    assert span.name == "Clinic Alpha / search"
    assert span.status.is_ok is False


@pytest.mark.asyncio
async def test_unresolved_server_keeps_http_name(tracing: Any) -> None:
    """Missing server records do not produce invented names or break requests."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("missing", "search", "search")

    await request(app)
    assert tracing.get_finished_spans()[0].name == "POST /servers/a/mcp"


@pytest.mark.asyncio
async def test_span_naming_failure_does_not_fail_request(tracing: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """A telemetry update failure preserves request execution and its HTTP name."""

    def unavailable(name: str) -> None:
        raise RuntimeError("span update unavailable")

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        context = observability.get_tool_trace_context(scope)
        assert context is not None
        monkeypatch.setattr(context.span, "update_name", unavailable)
        observability.record_tool_trace_name("a", "search", "search", context)
        await send({"type": "http.response.start", "status": 200})

    await request(app)
    assert tracing.get_finished_spans()[0].name == "POST /servers/a/mcp"


@pytest.mark.asyncio
async def test_completed_request_cannot_be_renamed(tracing: Any) -> None:
    """Session tasks cannot reuse a finished request's trace context."""
    contexts = []

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        contexts.append(observability.get_tool_trace_context(scope))

    await request(app)
    observability.record_tool_trace_name("a", "search", "search", contexts[0])
    assert tracing.get_finished_spans()[0].name == "POST /servers/a/mcp"
    assert observability.get_tool_trace_context() is None


@pytest.mark.asyncio
async def test_server_rename_updates_only_future_traces(tracing: Any) -> None:
    """Resolve the current name for each request and preserve completed trace names."""
    # First-Party
    from mcpgateway.db import SessionLocal

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")

    await request(app)
    with cast(Session, SessionLocal()) as db:
        db.execute(text("UPDATE servers SET name = 'Renamed Clinic' WHERE id = 'a'"))
        db.commit()
    await request(app)
    assert [span.name for span in tracing.get_finished_spans()] == ["Clinic Alpha / search", "Renamed Clinic / search"]


@pytest.mark.asyncio
async def test_metadata_failure_does_not_fail_request(tracing: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Naming performs no database lookup after server validation."""

    def unavailable() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("mcpgateway.db.SessionLocal", unavailable)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")
        await send({"type": "http.response.start", "status": 200, "headers": []})

    await request(app)
    span = tracing.get_finished_spans()[0]
    assert span.name == "Clinic Alpha / search"
    assert span.attributes is not None
    assert span.attributes["http.response.status_code"] == 200


@pytest.mark.asyncio
async def test_disabled_tracing_does_not_query_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tool calls incur no naming lookup when telemetry is disabled."""
    monkeypatch.setattr(observability, "_TRACER", None)
    calls = []

    def unexpected_lookup() -> None:
        calls.append(True)
        raise AssertionError("No metadata lookup expected")

    monkeypatch.setattr("mcpgateway.db.SessionLocal", unexpected_lookup)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")

    await request(app, "/mcp")
    assert calls == []


@pytest.mark.asyncio
async def test_real_tool_dispatch_uses_current_request_scope(tracing: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """Reuse an MCP session task without leaking names or naming denied calls."""
    # Standard
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, PropertyMock, patch

    # Third-Party
    import httpx

    # First-Party
    from mcpgateway.db import Base, EmailUser, Server, Tool
    from mcpgateway.services import tool_service as service_module
    from mcpgateway.transports import streamablehttp_transport as transport

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False)
    with sessions() as db:
        user = EmailUser(email="trace@example.com", password_hash="unused", is_admin=True, is_active=True)
        tool = Tool(
            id="tool-a",
            name="registered-search",
            original_name="search",
            integration_type="REST",
            request_type="GET",
            url="https://example.com/search",
            enabled=True,
            reachable=True,
            custom_name="registered-search",
            custom_name_slug="registered-search",
            input_schema={"type": "object"},
            visibility="public",
        )
        db.add_all([user, tool, Server(id="a", name="Clinic Alpha", tools=[tool]), Server(id="b", name="Clinic Beta")])
        db.commit()
    monkeypatch.setattr(transport, "SessionLocal", sessions)
    monkeypatch.setattr("mcpgateway.db.SessionLocal", sessions)
    monkeypatch.setattr(transport.settings, "mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr(transport.settings, "ssrf_protection_enabled", False)
    monkeypatch.setattr(transport.settings, "observability_enabled", False)
    monkeypatch.setattr(service_module.SecurityValidator, "validate_url_for_connection_pinning", AsyncMock(return_value={}))
    cache = SimpleNamespace(enabled=False, set=AsyncMock(), set_negative=AsyncMock())
    monkeypatch.setattr(service_module, "_get_tool_lookup_cache", lambda: cache)
    user_context = {"email": "trace@example.com", "teams": None, "is_admin": True, "is_authenticated": True}
    monkeypatch.setattr(transport, "_get_request_context_or_default", AsyncMock(return_value=("a", {}, user_context)))
    calls = []

    def upstream(req: httpx.Request) -> httpx.Response:
        calls.append(req.url.path)
        return httpx.Response(200, json={"result": "found"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
        monkeypatch.setattr(transport.tool_service, "_http_client", client)
        ctx = SimpleNamespace(meta=None, request=None)
        requests = asyncio.Queue()

        async def session_task() -> None:
            while True:
                scope, done = await requests.get()
                if scope is None:
                    return
                ctx.request = SimpleNamespace(scope=scope)
                try:
                    result = await asyncio.wait_for(transport.call_tool("registered-search", {}), timeout=5)
                    done.set_result(result)
                except Exception as exc:
                    done.set_exception(exc)

        async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
            done = asyncio.get_running_loop().create_future()
            await requests.put((scope, done))
            result = await done
            if scope["path"] == "/servers/b/mcp":
                assert result.is_error
            else:
                assert not getattr(result, "is_error", False), result

        with patch.object(type(transport.mcp_app), "request_context", new_callable=PropertyMock, return_value=ctx):
            task = asyncio.create_task(session_task(), context=Context())
            try:
                await request(app)
                with sessions() as db:
                    db.execute(text("UPDATE servers SET name = 'Renamed Clinic' WHERE id = 'a'"))
                    db.commit()
                await request(app)
                monkeypatch.setattr(transport, "_get_request_context_or_default", AsyncMock(return_value=("b", {}, user_context)))
                await request(app, "/servers/b/mcp")
            finally:
                await requests.put((None, None))
                await task
    roots = [span for span in tracing.get_finished_spans() if span.name != "tool.invoke"]
    names = [span.name for span in roots]
    assert "Clinic Alpha / search" in names
    assert "Renamed Clinic / search" in names
    assert "POST /servers/b/mcp" in names
    assert "Clinic Beta / search" not in names
    assert calls == ["/search", "/search"]
    engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure, expected", [("missing", 404), ("database", 503)])
async def test_traced_server_validation_fails_closed(tracing: Any, monkeypatch: pytest.MonkeyPatch, failure: str, expected: int) -> None:
    """Enabling trace metadata preserves missing-server and database-error denials."""
    # First-Party
    from mcpgateway.transports import streamablehttp_transport as transport

    messages = []

    def unavailable() -> None:
        raise RuntimeError("database unavailable")

    if failure == "database":
        monkeypatch.setattr(transport, "SessionLocal", unavailable)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        result = await transport.SessionManagerWrapper._validate_server_id(re.search(r"/servers/(?P<server_id>[^/]+)/mcp", scope["path"]), scope["path"], scope, receive, send)
        assert result is transport._REJECT

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        messages.append(message)

    scope = {"type": "http", "method": "POST", "path": "/servers/missing/mcp", "headers": []}
    await observability.OpenTelemetryRequestMiddleware(app)(scope, receive, send)
    assert messages[0]["status"] == expected
    assert tracing.get_finished_spans()[0].name == "POST /servers/missing/mcp"
