# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/test_tool_trace_names.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify exported request names and isolation across MCP task boundaries.
"""

# Standard
import asyncio
from contextvars import Context
from typing import Any, cast

# Third-Party
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

# First-Party
from mcpgateway import observability


@pytest.fixture
def tracing(monkeypatch: pytest.MonkeyPatch) -> InMemorySpanExporter:
    """Export real SDK spans and resolve server names from an isolated database."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("trace-name-test"))
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE servers (id TEXT PRIMARY KEY, name TEXT)"))
        connection.execute(text("INSERT INTO servers VALUES ('a', 'Clinic Alpha'), ('b', 'Clinic Beta')"))
    monkeypatch.setattr("mcpgateway.db.SessionLocal", sessionmaker(bind=engine))
    return exporter


async def request(app: Any, path: str = "/servers/a/mcp", headers: Any = ()) -> None:
    """Run an HTTP request through the real tracing middleware."""
    scope = {"type": "http", "path": path, "method": "POST", "headers": list(headers)}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        pass

    await observability.OpenTelemetryRequestMiddleware(app)(scope, receive, send)


@pytest.mark.asyncio
async def test_virtual_server_names_come_from_database(tracing: InMemorySpanExporter) -> None:
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
        assert span.attributes["server.name"] in ("Clinic Alpha", "Clinic Beta")


@pytest.mark.asyncio
async def test_mcp_task_uses_scope_instead_of_inherited_context(tracing: InMemorySpanExporter) -> None:
    """A session task can rename the current request without inheriting its ContextVars."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        async def session_task() -> None:
            context = observability.get_tool_trace_context(scope)
            observability.record_tool_trace_name("a", "registered-search", "search", context)

        await asyncio.create_task(session_task(), context=Context())

    await request(app)
    assert [span.name for span in tracing.get_finished_spans()] == ["Clinic Alpha / search"]


@pytest.mark.asyncio
async def test_remote_parent_is_preserved(tracing: InMemorySpanExporter) -> None:
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
async def test_multiple_tools_do_not_mislabel_request(tracing: InMemorySpanExporter, server_id: str, expected: str) -> None:
    """A request containing different tool calls receives an aggregate title."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")
        observability.record_tool_trace_name(server_id, "availability", "availability")

    await request(app)
    assert tracing.get_finished_spans()[0].name == expected


@pytest.mark.asyncio
async def test_failed_tool_retains_readable_name(tracing: InMemorySpanExporter) -> None:
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
async def test_unresolved_server_keeps_http_name(tracing: InMemorySpanExporter) -> None:
    """Missing server records do not produce invented names or break requests."""

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("missing", "search", "search")

    await request(app)
    assert tracing.get_finished_spans()[0].name == "POST /servers/a/mcp"


@pytest.mark.asyncio
async def test_completed_request_cannot_be_renamed(tracing: InMemorySpanExporter) -> None:
    """Session tasks cannot reuse a finished request's trace context."""
    contexts = []

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        contexts.append(observability.get_tool_trace_context(scope))

    await request(app)
    observability.record_tool_trace_name("a", "search", "search", contexts[0])
    assert tracing.get_finished_spans()[0].name == "POST /servers/a/mcp"
    assert observability.get_tool_trace_context() is None


@pytest.mark.asyncio
async def test_server_rename_updates_only_future_traces(tracing: InMemorySpanExporter) -> None:
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
async def test_metadata_failure_does_not_fail_request(tracing: InMemorySpanExporter, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the HTTP span and response when the metadata database is unavailable."""

    def unavailable() -> None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr("mcpgateway.db.SessionLocal", unavailable)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        observability.record_tool_trace_name("a", "search", "search")
        await send({"type": "http.response.start", "status": 200, "headers": []})

    await request(app)
    span = tracing.get_finished_spans()[0]
    assert span.name == "POST /servers/a/mcp"
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

    await request(app)
    assert calls == []
