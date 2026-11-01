# -*- coding: utf-8 -*-
"""Regression tests for gateway-owned request and playground tool tracing."""

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import httpx
import pytest
from opentelemetry import context as otel_context, trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON
from opentelemetry.trace import NonRecordingSpan, SpanContext, SpanKind, TraceFlags
from starlette.middleware import Middleware

from mcpgateway import observability


@pytest.fixture
def recorded_spans(monkeypatch):
    """Use real sampling and export without an external collector."""
    exporter = InMemorySpanExporter()
    provider = TracerProvider(sampler=observability.RequestRootSampler(ALWAYS_ON))
    provider.add_span_processor(observability.RequestRootFilteringSpanProcessor(SimpleSpanProcessor(exporter)))
    monkeypatch.setattr(trace, "_TRACER_PROVIDER", provider)
    monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("mcp-gateway"))
    yield provider, exporter
    provider.shutdown()


@pytest.fixture
def gateway_app(recorded_spans, monkeypatch):
    """Exercise the real application with request tracing enabled at startup."""
    from mcpgateway.main import app

    middleware = list(app.user_middleware)
    if not any(cast(Any, item.cls) is observability.OpenTelemetryRequestMiddleware for item in middleware):
        middleware.insert(0, Middleware(observability.OpenTelemetryRequestMiddleware))
    monkeypatch.setattr(app, "user_middleware", middleware)
    monkeypatch.setattr(app, "middleware_stack", None)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/health", "/static/missing.svg", "/admin/login", "/llmchat/connect"])
async def test_non_tool_routes_do_not_export_native_spans(recorded_spans, gateway_app, path):
    """Catch native framework tracing that bypasses the gateway path filter."""
    _, exporter = recorded_spans
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway_app, raise_app_exceptions=False), base_url="http://testserver") as client:
        await client.get(path)
    assert exporter.get_finished_spans() == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("parent", [None, "00-11111111111111111111111111111111-2222222222222222-01"])
@pytest.mark.parametrize("path", ["/mcp", "/servers/synthetic/mcp", "/sse", "/a2a/synthetic/invoke"])
async def test_mcp_has_one_request_span_with_original_voice_parent(recorded_spans, gateway_app, parent, path):
    """Retain the gateway root or voice parent without a second framework root."""
    _, exporter = recorded_spans
    headers = {"traceparent": parent} if parent else {}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway_app, raise_app_exceptions=False), base_url="http://testserver") as client:
        await client.request("GET" if path == "/sse" else "POST", path, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    server_spans = [span for span in exporter.get_finished_spans() if span.kind == SpanKind.SERVER]
    assert len(server_spans) == 1
    if parent:
        assert server_spans[0].context.trace_id == int("1" * 32, 16)
        assert server_spans[0].parent.span_id == int("2" * 16, 16)
    else:
        assert server_spans[0].parent is None


def test_only_explicit_playground_tool_client_can_start_a_trace(recorded_spans):
    """Permit a logical tool request without exporting arbitrary background clients."""
    provider, exporter = recorded_spans
    tracer = provider.get_tracer("mcp-gateway")
    with tracer.start_as_current_span("llmchat.tool.call", kind=SpanKind.CLIENT):
        with tracer.start_as_current_span("tool.invoke"):
            pass
    with tracer.start_as_current_span("GET", kind=SpanKind.CLIENT):
        pass
    assert [s.name for s in exporter.get_finished_spans()] == ["tool.invoke", "llmchat.tool.call"]


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
async def test_standalone_chat_exports_each_real_tool_and_preserves_result(recorded_spans, monkeypatch, streaming):
    """Exercise chat orchestration and adapted tools without a paid model or upstream."""
    from langchain_core.messages import AIMessage
    from langchain_core.tools import StructuredTool
    from mcpgateway.services import mcp_client_chat_service as chat

    _, exporter = recorded_spans
    config = chat.MCPClientConfig(
        mcp_server=chat.MCPServerConfig(url="https://synthetic.invalid/mcp", headers={"X-Call-Id": "synthetic-chat"}),
        llm=chat.LLMConfig(provider="openai", config=chat.OpenAIConfig(api_key="synthetic-test-only", model="synthetic")),  # pragma: allowlist secret
    )
    service = chat.MCPChatService(config)
    observed = []

    async def upstream(value: str) -> str:
        """Capture the active context at the real tool coroutine boundary."""
        observed.append(trace.get_current_span().get_span_context())
        return value

    original = StructuredTool.from_function(coroutine=upstream, name="synthetic_echo", description="Echo synthetic text.")
    monkeypatch.setattr(service.mcp_client, "_client", SimpleNamespace(list_tools=AsyncMock(return_value=[original])))
    service.mcp_client._connected = True
    tool = (await service.mcp_client.get_tools())[0]
    assert tool is not None
    assert tool.args_schema == original.args_schema
    assert tool.description == original.description

    async def agent(_messages: Any) -> dict[str, Any]:
        assert await tool.ainvoke({"value": "first"}) == "first"
        assert await tool.ainvoke({"value": "second"}) == "second"
        return {"messages": [AIMessage(content="done")]}

    async def stream_agent(messages, version):
        assert version == "v2"
        await agent(messages)
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="done")}}

    monkeypatch.setattr(service, "_agent", SimpleNamespace(ainvoke=agent, astream_events=stream_agent))
    service._initialized = True
    if streaming:
        events = [event async for event in service.chat_stream("Run two synthetic tools")]
        assert events
    else:
        assert await service.chat("Run two synthetic tools") == "done"
    assert len(observed) == 2
    assert all(context.is_valid and context.trace_flags.sampled for context in observed)
    assert observed[0].trace_id != observed[1].trace_id
    spans = exporter.get_finished_spans()
    assert [span.name for span in spans] == ["llmchat.tool.call", "llmchat.tool.call"]


@pytest.mark.asyncio
@pytest.mark.parametrize("sampled", [False, True])
async def test_playground_tool_honors_existing_parent(recorded_spans, sampled):
    """Keep remote trace identity and sampling choices for explicit tool roots."""
    from langchain_core.tools import StructuredTool
    from mcpgateway.services import mcp_client_chat_service as chat

    _, exporter = recorded_spans
    client = chat.MCPClient(chat.MCPServerConfig(url="https://synthetic.invalid/mcp"))

    async def upstream(value: str) -> str:
        """Return the synthetic input unchanged."""
        return value

    tool = StructuredTool.from_function(coroutine=upstream, name="echo", description="Echo.")
    parent = SpanContext(trace_id=123, span_id=456, is_remote=True, trace_flags=TraceFlags(1 if sampled else 0))
    token = otel_context.attach(trace.set_span_in_context(NonRecordingSpan(parent)))
    try:
        assert await client._trace_tool_call(tool)(value="kept") == "kept"
    finally:
        otel_context.detach(token)
    spans = exporter.get_finished_spans()
    if sampled:
        assert len(spans) == 1
        assert spans[0].context.trace_id == 123
        assert spans[0].parent.span_id == 456
    else:
        assert spans == ()


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [TimeoutError("synthetic"), asyncio.CancelledError()])
async def test_tool_tracing_does_not_retry_errors_or_cancellation(recorded_spans, failure):
    """Propagate the exact failure once, including cancellation."""
    from langchain_core.tools import StructuredTool
    from mcpgateway.services import mcp_client_chat_service as chat

    client = chat.MCPClient(chat.MCPServerConfig(url="https://synthetic.invalid/mcp"))
    calls = []

    async def upstream() -> str:
        """Simulate a failure after one invocation."""
        calls.append(1)
        raise failure

    tool = StructuredTool.from_function(coroutine=upstream, name="echo", description="Echo.")
    with pytest.raises(type(failure)) as caught:
        await client._trace_tool_call(tool)()
    assert caught.value is failure
    assert calls == [1]


@pytest.mark.asyncio
async def test_concurrent_playground_tools_keep_call_sessions_separate(recorded_spans, monkeypatch):
    """Prevent context and call identifiers from leaking between concurrent callers."""
    from langchain_core.tools import StructuredTool
    from mcpgateway.services import mcp_client_chat_service as chat

    _, exporter = recorded_spans
    monkeypatch.setattr(observability, "_should_emit_langfuse_attributes", lambda: True)
    waiting = 0
    ready = asyncio.Event()

    async def upstream(value: str) -> str:
        """Overlap two executions before returning their distinct values."""
        nonlocal waiting
        waiting += 1
        if waiting == 2:
            ready.set()
        await ready.wait()
        return value

    async def call(call_id: str) -> str:
        client = chat.MCPClient(chat.MCPServerConfig(url="https://synthetic.invalid/mcp", headers={"X-Call-Id": call_id}))
        tool = StructuredTool.from_function(coroutine=upstream, name="echo", description="Echo.")
        return cast(str, await client._trace_tool_call(tool)(value=call_id))

    assert tuple(await asyncio.gather(call("synthetic-a"), call("synthetic-b"))) == ("synthetic-a", "synthetic-b")
    spans = exporter.get_finished_spans()
    assert {s.attributes["langfuse.session.id"] for s in spans} == {"synthetic-a", "synthetic-b"}
    assert len({s.context.trace_id for s in spans}) == 2


@pytest.mark.asyncio
async def test_playground_tool_runs_without_optional_otel_sdk(recorded_spans, monkeypatch):
    """Retain tool execution when the optional SDK supplies only its fallback shim."""
    from langchain_core.tools import StructuredTool
    from mcpgateway.services import mcp_client_chat_service as chat

    _, exporter = recorded_spans
    monkeypatch.setattr(observability, "_TRACER", None)
    monkeypatch.setattr(observability, "SpanKind", SimpleNamespace(SERVER="server"))
    client = chat.MCPClient(chat.MCPServerConfig(url="https://synthetic.invalid/mcp"))

    async def upstream(value: str) -> str:
        """Return a result without any tracing dependency."""
        return value

    tool = StructuredTool.from_function(coroutine=upstream, name="echo", description="Echo.")
    assert await client._trace_tool_call(tool)(value="still works") == "still works"
    assert exporter.get_finished_spans() == ()
