# -*- coding: utf-8 -*-
"""Exercise safe completion logs through the tool service and JSON formatter."""

# Standard
import asyncio
from contextlib import asynccontextmanager, contextmanager
from itertools import count
import json
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

# Third-Party
import httpx
import pytest

# First-Party
from mcpgateway import observability
from mcpgateway.common.models import TextContent, ToolResult
from mcpgateway.config import settings
from mcpgateway.services import tool_service as tools
from mcpgateway.services.logging_service import json_formatter
from mcpgateway.utils.correlation_id import clear_correlation_id, get_correlation_id, set_correlation_id


@contextmanager
def correlation_id_context(value):
    """Restore request correlation after a test invocation."""
    previous = get_correlation_id()
    set_correlation_id(value)
    try:
        yield
    finally:
        if previous is None:
            clear_correlation_id()
        else:
            set_correlation_id(previous)


@pytest.fixture
def invocation(monkeypatch, caplog):
    """Keep invocation and logging real; replace upstream I/O and persistence."""
    caplog.set_level(logging.INFO)
    monkeypatch.setattr(settings, "log_level", "INFO")
    monkeypatch.setattr(settings, "observability_enabled", False)
    monkeypatch.setattr(settings, "ssrf_allow_localhost", True)
    monkeypatch.setattr(settings, "ssrf_allow_private_networks", True)
    monkeypatch.setattr(settings, "otel_enable_observability", False)
    monkeypatch.setattr(observability, "TRACER", None, raising=False)
    monkeypatch.setattr(tools.structured_logger.router, "database_enabled", False)
    monkeypatch.setattr(tools.structured_logger.router, "external_enabled", False)
    monkeypatch.setattr(tools, "metrics_buffer", MagicMock())
    monkeypatch.setattr(tools.global_config_cache, "get_passthrough_headers", lambda *_: [])
    service = tools.ToolService()
    monkeypatch.setattr(service, "_get_plugin_manager", AsyncMock(return_value=None))
    resolved = tools.ResolvedTool(
        is_direct_proxy=True,
        tool=None,
        gateway=None,
        tool_payload={"id": "synthetic-tool-id", "name": "synthetic-tool", "original_name": "synthetic_tool", "integration_type": "MCP", "request_type": "STREAMABLEHTTP"},
        gateway_payload={"id": "synthetic-gateway-id", "url": "http://127.0.0.1/mcp", "name": "synthetic", "transport": "STREAMABLEHTTP", "passthrough_headers": []},
    )
    monkeypatch.setattr(service, "_resolve_tool_for_invocation", AsyncMock(return_value=resolved))
    responses = {}
    response_ids = count()

    async def dispatch(name, arguments, **kwargs):
        return await responses[arguments["fixture_response_id"]](name, arguments, **kwargs)

    @asynccontextmanager
    async def proxy(**_kwargs):
        yield SimpleNamespace(session=SimpleNamespace(call_tool=dispatch, _x_mcp_header_maps={}))

    monkeypatch.setattr(tools, "mcp_proxy_client", proxy)

    async def invoke(response, headers=None, *, retry_once=False):
        """Invoke a synthetic MCP tool without a real connection."""
        call_count = 0
        timeout_pending = False

        class RetryPlugin:
            """Activate only the timeout hook for this synthetic invocation."""

            def __bool__(self):
                return timeout_pending

        retry_plugin = RetryPlugin()

        async def plugin_manager(*_args):
            return retry_plugin

        async def retry_signal(*_args, **_kwargs):
            nonlocal timeout_pending
            timeout_pending = False
            raise tools.ToolTimeoutError("synthetic timeout", retry_delay_ms=1)

        @contextmanager
        def retry_db():
            yield MagicMock()

        if retry_once:
            monkeypatch.setattr(service, "_get_plugin_manager", plugin_manager)
            monkeypatch.setattr(service, "_run_timeout_post_invoke", retry_signal)
            monkeypatch.setattr(tools, "fresh_db_session", retry_db)

        async def call_tool(*_args, **_kwargs):
            nonlocal call_count, timeout_pending
            call_count += 1
            await asyncio.sleep(0)
            if retry_once and call_count == 1:
                timeout_pending = True
                raise httpx.ReadTimeout("synthetic retry")
            if isinstance(response, BaseException):
                raise response
            return response

        response_id = next(response_ids)
        responses[response_id] = call_tool
        try:
            return await service.invoke_tool(MagicMock(), "synthetic-tool", {"patientName": "SYNTHETIC-PATIENT", "fixture_response_id": response_id}, request_headers=headers)
        finally:
            responses.pop(response_id)

    return invoke


def completions(caplog):
    """Decode actual emitted JSON records for the final completion event."""
    return [json.loads(json_formatter.format(record)) for record in caplog.records if getattr(record, "event", None) == "tool_invocation_completed"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure,code",
    [
        (None, "TOOL_ERROR"),
        (httpx.ConnectError("SYNTHETIC-PATIENT"), "CONNECTION_ERROR"),
        (httpx.ReadTimeout("SYNTHETIC-PATIENT"), "TIMEOUT"),
        (None, "SUCCESS"),
        (None, "RECOVERED"),
        (asyncio.CancelledError(), "CANCELLED"),
        (BaseExceptionGroup("synthetic group", [asyncio.CancelledError()]), "UNEXPECTED_ERROR"),
    ],
)
async def test_completion_fields(invocation, caplog, failure, code):
    """Completion records preserve identifiers and distinguish failures from control flow."""
    success = code in {"SUCCESS", "RECOVERED"}
    response = failure or ToolResult(content=[TextContent(type="text", text="SYNTHETIC-PATIENT")], is_error=not success)
    with correlation_id_context("gateway-request-1"):
        headers = {"x-CaLl-Id": "call-1", "X-Operation-ID": "operation-1"}
        if code == "TIMEOUT":
            with pytest.raises(tools.ToolTimeoutError):
                await invocation(response, headers)
        elif code == "CANCELLED":
            with pytest.raises(asyncio.CancelledError):
                await invocation(response, headers)
        else:
            result = await invocation(response, headers, retry_once=code == "RECOVERED")
            assert result.is_error is not success
    records = completions(caplog)
    assert len(records) == 1
    entry = records[0]
    assert entry["levelname"] == ("INFO" if success or code == "CANCELLED" else "ERROR")
    assert entry["callId"] == "call-1"
    assert entry["operationId"] == "operation-1"
    assert entry["toolName"] == "synthetic-tool"
    assert entry["toolId"] == "synthetic-tool-id"
    assert entry["integrationType"] == "MCP"
    assert entry["gatewayCorrelationId"] == "gateway-request-1"
    assert entry["success"] is success
    assert entry.get("errorCode") == (None if success else code)
    assert entry["durationMs"] >= 0
    assert entry["duration_ms"] == entry["durationMs"]
    assert entry["resource_id"] == entry["toolId"]
    assert entry["@timestamp"].endswith("Z")
    assert "SYNTHETIC-PATIENT" not in json.dumps(entry)
    assert "SYNTHETIC-PATIENT" not in "\n".join(json_formatter.format(record) for record in caplog.records)


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", [None, "bad\nidentifier", "x" * 129, "has space", ""])
async def test_completion_rejects_unsafe_data(invocation, caplog, identifier):
    """Missing or unsafe identifiers and arbitrary response fields stay out of logs."""
    response = ToolResult(
        content=[TextContent(type="text", text="SYNTHETIC-PATIENT SYNTHETIC-SECRET")],
        structured_content={"patientMobile": "SYNTHETIC-MOBILE", "outcome": "SYNTHETIC-PATIENT", "nextStep": "SYNTHETIC-SECRET"},
        is_error=True,
    )
    headers = None if identifier is None else {"X-Call-Id": identifier, "X-Operation-Id": identifier, "Authorization": "SYNTHETIC-SECRET"}
    result = await invocation(response, headers)
    assert result == response
    records = completions(caplog)
    assert len(records) == 1
    assert "callId" not in records[0] and "operationId" not in records[0]
    assert not any(value in json.dumps(records) for value in ("SYNTHETIC-PATIENT", "SYNTHETIC-SECRET", "SYNTHETIC-MOBILE", "bad\\nidentifier"))


@pytest.mark.asyncio
async def test_completion_keeps_concurrent_identifiers_separate(invocation, caplog):
    """Concurrent requests keep their call, operation and gateway correlation IDs."""

    async def call(number):
        with correlation_id_context(f"request-{number}"):
            response = ToolResult(content=[TextContent(type="text", text=f"response-{number}")], is_error=True)
            assert await invocation(response, {"X-Call-Id": f"call-{number}", "X-Operation-Id": f"operation-{number}"}) == response

    await asyncio.gather(call(1), call(2))
    records = completions(caplog)
    assert len(records) == 2
    assert {(r["callId"], r["operationId"], r["gatewayCorrelationId"]) for r in records} == {("call-1", "operation-1", "request-1"), ("call-2", "operation-2", "request-2")}


@pytest.mark.asyncio
async def test_error_level_skips_enrichment_without_otel(invocation, monkeypatch, caplog):
    """Suppressed success logs do not prepare fields; failures work without tracing."""
    monkeypatch.setattr(settings, "log_level", "ERROR")
    response = ToolResult(content=[TextContent(type="text", text="unchanged")])
    original = tools._log_tool_completion

    def unexpected_enrichment(**_kwargs):
        pytest.fail(f"Suppressed completion log performed enrichment: {_kwargs.get('error_code')}")

    monkeypatch.setattr(tools, "_log_tool_completion", unexpected_enrichment)
    assert await invocation(response) == response
    assert await invocation(response, retry_once=True) == response
    assert completions(caplog) == []
    monkeypatch.setattr(tools, "_log_tool_completion", original)
    await invocation(ToolResult(content=[], is_error=True), {"X-Call-Id": "call-no-otel", "X-Operation-Id": "operation-no-otel"})
    assert completions(caplog)[0]["callId"] == "call-no-otel"


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [ToolResult(content=[], is_error=True), asyncio.CancelledError(), httpx.ReadTimeout("synthetic timeout")])
async def test_logging_failure_preserves_tool_behavior(invocation, monkeypatch, response):
    """A broken completion sink cannot change results, timeout or cancellation."""
    original = tools.structured_logger.log
    failures = []

    def failing_sink(*args, **kwargs):
        if kwargs.get("event") == "tool_invocation_completed":
            failures.append(kwargs["event"])
            raise RuntimeError("synthetic logging failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(tools.structured_logger, "log", failing_sink)
    if isinstance(response, BaseException):
        with pytest.raises(tools.ToolTimeoutError if isinstance(response, httpx.ReadTimeout) else type(response)):
            await invocation(response, retry_once=True)
    else:
        assert await invocation(response, retry_once=True) == response
    assert failures == ["tool_invocation_completed"]
