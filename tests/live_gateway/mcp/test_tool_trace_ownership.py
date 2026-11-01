# -*- coding: utf-8 -*-
"""Check tool tracing against an isolated gateway and synthetic MCP upstream.

Set TRACE_TEST_GATEWAY_URL, TRACE_TEST_TOKEN, TRACE_TEST_TOOL and
TRACE_TEST_COLLECTOR_URL for a local gateway with tool payload capture enabled.
The collector exposes GET /evidence containing spans and synthetic upstream calls.
This suite refuses remote targets and never calls hospital tools.
"""

import asyncio
import json
import os
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage
from opentelemetry.instrumentation.httpx import HTTPX2ClientInstrumentor, HTTPXClientInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.sdk.trace.sampling import ALWAYS_ON

from mcpgateway import observability
from mcpgateway.services import mcp_client_chat_service as chat

URL = os.getenv("TRACE_TEST_GATEWAY_URL", "")
COLLECTOR = os.getenv("TRACE_TEST_COLLECTOR_URL", "")
pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not URL, reason="Isolated tracing gateway not configured")]


@pytest.fixture
def client_tracing(monkeypatch):
    """Capture the real playground client and HTTPX spans in memory."""
    assert urlparse(URL).hostname in {"localhost", "127.0.0.1"}
    assert urlparse(COLLECTOR).hostname in {"localhost", "127.0.0.1"}
    provider = TracerProvider(sampler=observability.RequestRootSampler(ALWAYS_ON))
    exporter = InMemorySpanExporter()
    provider.add_span_processor(observability.RequestRootFilteringSpanProcessor(SimpleSpanProcessor(exporter)))
    provider.add_span_processor(observability.CallSessionSpanProcessor())
    monkeypatch.setattr(observability, "_TRACER", provider.get_tracer("mcp-gateway"))
    monkeypatch.setattr(observability, "_should_emit_langfuse_attributes", lambda: True)
    instruments = [HTTPXClientInstrumentor(), HTTPX2ClientInstrumentor()]
    for instrument in instruments:
        instrument.instrument(tracer_provider=provider)
    yield exporter
    for instrument in instruments:
        instrument.uninstrument()
    provider.shutdown()


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("parallel", [False, True])
async def test_playground_tools_reach_gateway_with_complete_traces(client_tracing, streaming, parallel, monkeypatch):
    """Use real chat orchestration, adapted MCP tools, HTTPX and gateway execution."""
    call_id = "synthetic-" + uuid4().hex
    nonces = [uuid4().hex for _ in range(2 if parallel else 1)]
    service = chat.MCPChatService(
        chat.MCPClientConfig(
            mcp_server=chat.MCPServerConfig(
                url=URL,
                transport="streamable_http",
                auth_token=os.environ["TRACE_TEST_TOKEN"],
                headers={"X-Call-Id": call_id, "X-Operation-Id": "synthetic-operation"},
            ),
            llm=chat.LLMConfig(provider="openai", config=chat.OpenAIConfig(api_key="synthetic-test-only", model="synthetic")),  # pragma: allowlist secret
        )
    )
    await service.mcp_client.connect()
    await service.mcp_client.get_tools()
    tools = await service.mcp_client.get_tools(force_reload=True)
    tool = next(tool for tool in tools if tool is not None and tool.name == os.environ["TRACE_TEST_TOOL"])
    assert tool is not None
    results = []

    async def agent(_messages: Any) -> dict[str, Any]:
        results.extend(await asyncio.gather(*(tool.ainvoke({"nonce": nonce}) for nonce in nonces)))
        return {"messages": [AIMessage(content="synthetic complete")]}

    async def streaming_agent(messages, version):
        assert version == "v2"
        await agent(messages)
        yield {"event": "on_chat_model_stream", "data": {"chunk": SimpleNamespace(content="synthetic complete")}}

    monkeypatch.setattr(service, "_agent", SimpleNamespace(ainvoke=agent, astream_events=streaming_agent))
    service._initialized = True
    try:
        if streaming:
            assert [event async for event in service.chat_stream("Use the synthetic echo")]
        else:
            assert await service.chat("Use the synthetic echo") == "synthetic complete"
    finally:
        await service.mcp_client.disconnect()
    assert all(nonce in str(results) for nonce in nonces)
    roots = [span for span in client_tracing.get_finished_spans() if span.name == "llmchat.tool.call"]
    assert len(roots) == len(nonces)
    assert len({span.context.trace_id for span in roots}) == len(nonces)
    seen = set()
    for root in roots:
        assert root.parent is None
        assert root.attributes["langfuse.session.id"] == call_id
        trace_id = format(root.context.trace_id, "032x")
        async with httpx.AsyncClient() as client:
            for _ in range(50):
                evidence = (await client.get(COLLECTOR + "/evidence")).json()
                spans = [span for span in evidence["spans"] if span["trace_id"] == trace_id]
                if any(span["name"] == "tool.invoke" for span in spans):
                    break
                await asyncio.sleep(0.1)
        tool_spans = [span for span in spans if span["name"] == "tool.invoke"]
        assert len(tool_spans) == 1
        attributes = tool_spans[0]["attributes"]
        assert attributes["langfuse.session.id"] == call_id
        inputs = attributes["langfuse.observation.input"]
        inputs = json.loads(inputs) if isinstance(inputs, str) else inputs
        nonce = inputs["nonce"]
        seen.add(nonce)
        assert nonce in nonces
        assert nonce in str(attributes["langfuse.observation.output"])
        upstream = [call for call in evidence["calls"] if call["method"] == "tools/call" and call["nonce"] == nonce]
        assert len(upstream) == 1
        assert upstream[0]["headers"]["x-call-id"] == call_id
        assert upstream[0]["headers"]["x-operation-id"] == "synthetic-operation"
        assert upstream[0]["headers"]["traceparent"].split("-")[1] == trace_id
        assert all(span.get("scope") != "fastapi" for span in evidence["spans"])
        assert not any(span.name == "llm.chat" for span in client_tracing.get_finished_spans())
        parents = {span["span_id"]: span["parent_id"] for span in spans}
        parents.update({format(span.context.span_id, "016x"): format(span.parent.span_id, "016x") if span.parent else "" for span in client_tracing.get_finished_spans()})
        cursor = tool_spans[0]["span_id"]
        ancestors = set()
        while cursor and cursor not in ancestors:
            ancestors.add(cursor)
            cursor = parents.get(cursor, "")
        assert format(root.context.span_id, "016x") in ancestors
    assert seen == set(nonces)
