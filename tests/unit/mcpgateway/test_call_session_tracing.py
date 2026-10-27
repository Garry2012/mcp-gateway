# -*- coding: utf-8 -*-
"""Verify voice call identifiers group gateway spans without changing MCP sessions."""

# Standard
import asyncio

# Third-Party
import pytest
from starlette.types import ASGIApp, Scope

# First-Party
from mcpgateway import observability
from mcpgateway.config import get_settings
from mcpgateway.utils.trace_context import clear_trace_context, set_trace_session_id


@pytest.fixture
def call_tracer(monkeypatch):
    """Initialize real tracing with an isolated provider and memory exporter."""
    sdk = pytest.importorskip("opentelemetry.sdk.trace")
    trace_api = pytest.importorskip("opentelemetry.trace")
    memory = pytest.importorskip("opentelemetry.sdk.trace.export.in_memory_span_exporter")
    exporter = memory.InMemorySpanExporter()
    provider = sdk.TracerProvider()
    monkeypatch.setenv("OTEL_ENABLE_OBSERVABILITY", "true")
    monkeypatch.setenv("OTEL_SYSTEM_TRACES_ENABLED", "false")
    monkeypatch.setenv("DEPLOYMENT_ENV", "staging")
    monkeypatch.setenv("OTEL_TRACES_EXPORTER", "console")
    monkeypatch.setenv("OTEL_EMIT_LANGFUSE_ATTRIBUTES", "true")
    monkeypatch.setenv("OTEL_HTTPX_INSTRUMENTATION_ENABLED", "false")
    monkeypatch.setenv("OTEL_REDIS_INSTRUMENTATION_ENABLED", "false")
    monkeypatch.setattr(observability, "TracerProvider", lambda **_kwargs: provider)
    monkeypatch.setattr(observability, "ConsoleSpanExporter", lambda: exporter)
    monkeypatch.setattr(trace_api, "set_tracer_provider", lambda _provider: None)
    monkeypatch.setattr(trace_api, "get_tracer", provider.get_tracer)
    monkeypatch.setattr(observability, "_TRACER", None)
    get_settings.cache_clear()
    assert observability.init_telemetry() is not None
    yield exporter, provider.get_tracer("automatic-child")
    clear_trace_context()
    get_settings.cache_clear()
    provider.shutdown()


async def send_request(app: ASGIApp, headers: list[tuple[bytes, bytes]], status: int = 200) -> Scope:
    """Execute an MCP HTTP request through the production tracing middleware.

    Args:
        app: Downstream ASGI application.
        headers: Incoming HTTP headers.
        status: Expected response status.

    Returns:
        The request scope for header-preservation assertions.
    """
    messages = []
    scope: Scope = {"type": "http", "method": "POST", "path": "/servers/test/mcp", "headers": headers}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await observability.OpenTelemetryRequestMiddleware(app)(scope, receive, send)
    assert messages[0]["status"] == status
    return scope


@pytest.mark.asyncio
async def test_call_id_groups_root_manual_and_automatic_spans(call_tracer):
    """Keep the call ID after authentication clears identity and MCP sets its own session."""
    exporter, tracer = call_tracer

    async def app(_scope, _receive, send):
        clear_trace_context()
        set_trace_session_id("mcp-connection-one")
        with observability.create_span("tool.invoke"):
            with tracer.start_as_current_span("HTTP client"):
                await send({"type": "http.response.start", "status": 200, "headers": []})

    scope = await send_request(app, [(b"X-Call-Id", b"voice-call-one")])
    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    assert {span.attributes.get("langfuse.session.id") for span in spans} == {"voice-call-one"}
    assert (b"X-Call-Id", b"voice-call-one") in scope["headers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("call_id", [None, b"", b"bad\r\nvalue", b"x" * 129, b"call with spaces", b"session-id:42", b"session-id:43", b"token:abc"])
async def test_missing_or_invalid_call_id_preserves_mcp_session(call_tracer, call_id):
    """Invalid trace labels never block requests or replace existing MCP session labels."""
    exporter, _tracer = call_tracer

    async def app(_scope, _receive, send):
        set_trace_session_id("mcp-session-fallback")
        with observability.create_span("tool.invoke"):
            await send({"type": "http.response.start", "status": 200, "headers": []})

    scope = await send_request(app, [] if call_id is None else [(b"x-call-id", call_id)])
    if call_id is not None:
        assert (b"x-call-id", call_id) in scope["headers"]
    spans = {span.name: span for span in exporter.get_finished_spans()}
    assert "langfuse.session.id" not in spans["POST /servers/test/mcp"].attributes
    assert spans["tool.invoke"].attributes["langfuse.session.id"] == "mcp-session-fallback"


@pytest.mark.asyncio
async def test_parallel_requests_keep_distinct_call_sessions(call_tracer):
    """Concurrent requests never share a voice call session attribute."""
    exporter, tracer = call_tracer
    ready = asyncio.Event()
    count = 0

    async def app(scope, _receive, send):
        nonlocal count
        count += 1
        if count == 2:
            ready.set()
        await ready.wait()
        call_id = dict(scope["headers"])[b"x-call-id"].decode()
        with tracer.start_as_current_span(call_id):
            await send({"type": "http.response.start", "status": 200, "headers": []})

    await asyncio.gather(send_request(app, [(b"x-call-id", b"call-a")]), send_request(app, [(b"x-call-id", b"call-b")]))
    children = {s.name: s.attributes.get("langfuse.session.id") for s in exporter.get_finished_spans() if s.name.startswith("call-")}
    assert children == {"call-a": "call-a", "call-b": "call-b"}
    with tracer.start_as_current_span("outside-request") as span:
        assert not span.is_recording()
    assert all(span.name != "outside-request" for span in exporter.get_finished_spans())


@pytest.mark.parametrize("current_id", ["current-call", None])
def test_current_scope_overrides_inherited_mcp_headers(call_tracer, current_id):
    """A reused MCP task uses the current scope, even when the new call omits its header."""
    _exporter, tracer = call_tracer
    with observability.call_trace_session({"X-Call-Id": "previous-call"}), tracer.start_as_current_span("request", kind=observability.SpanKind.SERVER):
        request_trace = observability.ToolTraceContext(None, call_id=current_id)
        with observability.call_trace_session({"X-Call-Id": "stale-header-call"}, request_trace):
            with observability.create_span("tool.invoke") as span:
                assert span.attributes.get("langfuse.session.id") == current_id
            with tracer.start_as_current_span("HTTP client") as span:
                assert span.attributes.get("langfuse.session.id") == current_id
        with tracer.start_as_current_span("restored-parent") as span:
            assert span.attributes["langfuse.session.id"] == "previous-call"


@pytest.mark.parametrize("error", [RuntimeError, asyncio.CancelledError])
def test_error_and_cancellation_restore_call_context(call_tracer, error):
    """Failed and cancelled requests cannot leak their call identifier into later work."""
    _exporter, tracer = call_tracer
    with pytest.raises(error):
        with observability.call_trace_session({"x-call-id": "failed-call"}):
            raise error()
    with tracer.start_as_current_span("next-request", kind=observability.SpanKind.SERVER) as span:
        assert "langfuse.session.id" not in span.attributes


@pytest.mark.asyncio
async def test_disabled_langfuse_attributes_omit_call_id(call_tracer, monkeypatch):
    """The existing Langfuse opt-out suppresses call identifiers on every span."""
    exporter, tracer = call_tracer
    monkeypatch.setenv("OTEL_EMIT_LANGFUSE_ATTRIBUTES", "false")
    get_settings.cache_clear()

    async def app(_scope, _receive, send):
        with observability.create_span("tool.invoke"), tracer.start_as_current_span("HTTP client"):
            await send({"type": "http.response.start", "status": 200, "headers": []})

    await send_request(app, [(b"x-call-id", b"disabled-call")])
    spans = exporter.get_finished_spans()
    assert spans
    assert all("langfuse.session.id" not in s.attributes for s in spans)


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 500])
async def test_call_label_does_not_change_auth_or_error_responses(call_tracer, status):
    """Call metadata preserves denied and failed HTTP responses."""
    exporter, _tracer = call_tracer

    async def app(_scope, _receive, send):
        await send({"type": "http.response.start", "status": status, "headers": []})

    await send_request(app, [(b"x-call-id", b"denied-call")], status=status)
    (span,) = exporter.get_finished_spans()
    assert span.attributes["http.response.status_code"] == status
    assert span.attributes["langfuse.session.id"] == "denied-call"


def test_call_identifier_does_not_enable_background_tracing(call_tracer):
    """A call identifier cannot cause a background trace tree to be exported."""
    exporter, tracer = call_tracer
    with observability.call_trace_session({"X-Call-Id": "background-call"}):
        with tracer.start_as_current_span("background") as root:
            assert not root.is_recording()
            with observability.create_span("tool.invoke") as child:
                assert not child.is_recording()
    assert not exporter.get_finished_spans()


@pytest.mark.asyncio
async def test_environment_labels_request_manual_and_automatic_spans(call_tracer):
    """Every exported span receives the configured environment, including automatic children."""
    exporter, tracer = call_tracer

    async def app(_scope, _receive, send):
        with observability.create_span("tool.invoke"), tracer.start_as_current_span("HTTP client"):
            await send({"type": "http.response.start", "status": 200, "headers": []})

    await send_request(app, [])
    spans = exporter.get_finished_spans()
    assert len(spans) == 3
    assert {span.attributes.get("langfuse.environment") for span in spans} == {"staging"}
