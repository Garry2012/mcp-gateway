# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/utils/test_trace_redaction.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Tests for trace payload redaction helpers.
"""

# Standard
import json

# Third-Party
from pydantic import BaseModel
import pytest

# First-Party
from mcpgateway.utils.trace_redaction import (
    is_input_capture_enabled,
    is_output_capture_enabled,
    redact_sensitive_fields,
    reload_trace_redaction_config,
    safe_serialize,
    sanitize_trace_attribute_value,
    sanitize_trace_text,
    serialize_trace_payload,
)


class SampleModel(BaseModel):
    password: str
    nested: dict


def teardown_function():
    reload_trace_redaction_config()


def test_redact_sensitive_fields_recurses_through_dicts_lists_and_tuples(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "password,authorization,api-key")
    reload_trace_redaction_config()

    payload = {
        "password": "secret",
        "nested": [
            {"authorization": "Bearer abc"},
            {"ok": "value"},
            ({"api-key": "xyz"},),
        ],
    }

    assert redact_sensitive_fields(payload) == {
        "password": "***",  # pragma: allowlist secret
        "nested": [
            {"authorization": "***"},
            {"ok": "value"},
            ({"api-key": "***"},),  # pragma: allowlist secret
        ],
    }


def test_is_output_capture_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("OTEL_CAPTURE_OUTPUT_SPANS", "llm.proxy,tool.invoke")
    reload_trace_redaction_config()

    assert is_output_capture_enabled("llm.proxy") is True
    assert is_output_capture_enabled("prompt.render") is False


def test_is_input_capture_enabled_reads_env(monkeypatch):
    monkeypatch.setenv("OTEL_CAPTURE_INPUT_SPANS", "tool.invoke,prompt.render")
    reload_trace_redaction_config()

    assert is_input_capture_enabled("tool.invoke") is True
    assert is_input_capture_enabled("llm.chat") is False


def test_safe_serialize_supports_model_dump_and_valid_truncation(monkeypatch):
    monkeypatch.setenv("OTEL_MAX_TRACE_PAYLOAD_SIZE", "256")
    reload_trace_redaction_config()

    rendered = safe_serialize(SampleModel(password="secret", nested={"value": "x" * 400}), max_size=120)
    parsed = json.loads(rendered)

    assert parsed["_truncated"] is True
    assert parsed["_original_size"] > 120
    assert isinstance(parsed["_preview"], str)


def test_safe_serialize_returns_json_for_small_payload(monkeypatch):
    monkeypatch.setenv("OTEL_MAX_TRACE_PAYLOAD_SIZE", "512")
    reload_trace_redaction_config()

    rendered = safe_serialize({"ok": True, "value": "small"})

    assert json.loads(rendered) == {"ok": True, "value": "small"}


def test_redact_sensitive_fields_sanitizes_url_like_fields(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "password")
    reload_trace_redaction_config()

    payload = {
        "uri": "https://example.com/resource?token=secret123&ok=1",
        "nested": {"gateway_url": "https://api.example.com/path?api_key=abc"},
    }

    assert redact_sensitive_fields(payload) == {
        "uri": "https://example.com/resource?token=REDACTED&ok=1",
        "nested": {"gateway_url": "https://api.example.com/path?api_key=REDACTED"},
    }


def test_sanitize_trace_attribute_value_redacts_direct_secret_keys(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "authorization")
    reload_trace_redaction_config()

    assert sanitize_trace_attribute_value("authorization", "Bearer abc") == "***"


def test_serialize_trace_payload_redacts_and_sanitizes(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "authorization")
    reload_trace_redaction_config()

    rendered = serialize_trace_payload(
        {
            "authorization": "Bearer abc",
            "uri": "https://example.com/resource?token=secret123",
        }
    )

    assert json.loads(rendered) == {
        "authorization": "***",
        "uri": "https://example.com/resource?token=REDACTED",
    }


def test_serialize_trace_payload_drops_deep_payload_without_mutating_it(caplog):
    """A redaction recursion error drops telemetry without changing tool data."""
    original = {"password": "private-probe"}  # pragma: allowlist secret
    payload = original
    for _ in range(1200):
        payload = {"nested": payload}

    rendered = serialize_trace_payload(payload)

    assert json.loads(rendered) == {"_error": "trace_payload_unavailable"}
    assert original == {"password": "private-probe"}  # pragma: allowlist secret
    assert "private-probe" not in rendered + caplog.text


def test_serialize_trace_payload_drops_failed_model_conversion(caplog):
    """Model conversion failures cannot escape or disclose exception details."""

    class InvalidPayload:
        def model_dump(self, **kwargs):
            raise ValueError("private-probe")

    rendered = serialize_trace_payload(InvalidPayload())

    assert json.loads(rendered) == {"_error": "trace_payload_unavailable"}
    assert "private-probe" not in rendered + caplog.text


def test_serialize_trace_payload_sanitizes_generic_string_content(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token")
    reload_trace_redaction_config()

    rendered = serialize_trace_payload(
        {
            "message": "call https://example.com/path?token=secret123 using Bearer abc123 and token=inline-secret",
            "content": "Authorization: Basic Zm9vOmJhcg==",
        }
    )

    parsed = json.loads(rendered)
    assert "secret123" not in parsed["message"]
    assert "abc123" not in parsed["message"]
    assert "inline-secret" not in parsed["message"]
    assert "token=REDACTED" in parsed["message"]
    assert "Bearer ***" in parsed["message"]
    assert "Basic ***" in parsed["content"]


def test_serialize_trace_payload_sanitizes_top_level_string_content(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token")
    reload_trace_redaction_config()

    rendered = serialize_trace_payload("Bearer abc123 https://example.com/path?token=secret456")

    assert "abc123" not in rendered
    assert "secret456" not in rendered
    assert "Bearer ***" in rendered
    assert "token=REDACTED" in rendered


def test_redact_sensitive_fields_sanitizes_string_list_and_tuple_items(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token,authorization")
    reload_trace_redaction_config()

    redacted = redact_sensitive_fields(
        {
            "messages": ["Bearer abc123", "token=secret456", "https://x.test?a=1&token=urlsecret"],
            "tuple_values": ("authorization: Basic Zm9vOmJhcg==",),
        }
    )

    assert redacted["messages"] == [
        "Bearer ***",
        "token=***",
        "https://x.test?a=1&token=REDACTED",
    ]
    assert redacted["tuple_values"] == ("authorization: ***",)


def test_sanitize_trace_text_redacts_free_text_assignments(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token,authorization")
    reload_trace_redaction_config()

    sanitized = sanitize_trace_text('boom token=supersecret authorization:"Bearer abc123"')

    assert "supersecret" not in sanitized
    assert "abc123" not in sanitized
    assert "token=***" in sanitized
    assert 'authorization:"***"' in sanitized


def test_sanitize_trace_text_redacts_bearer_credentials_and_urls(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token")
    reload_trace_redaction_config()

    sanitized = sanitize_trace_text("Bearer abc123 https://example.com?token=secret456")

    assert "abc123" not in sanitized
    assert "secret456" not in sanitized
    assert "Bearer ***" in sanitized
    assert "token=REDACTED" in sanitized


def test_sanitize_trace_attribute_value_sanitizes_generic_string_values(monkeypatch):
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token")
    reload_trace_redaction_config()

    sanitized = sanitize_trace_attribute_value("prompt.id", "https://prompt.example.com/item?token=secret123 Bearer abc123")

    assert "secret123" not in sanitized
    assert "abc123" not in sanitized
    assert "token=REDACTED" in sanitized
    assert "Bearer ***" in sanitized


@pytest.mark.parametrize("secret", ["synthetic-output-secret", 'quoted"secret\\tail'])
def test_tool_result_json_text_redacts_secrets_without_changing_response(monkeypatch, secret):
    """MCP text content must redact the same fields as structured content."""
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "access_token")
    reload_trace_redaction_config()
    response = {"appointment_id": "TEST-123", "access_token": secret}
    payload = {"content": [{"type": "text", "text": json.dumps(response)}], "structuredContent": response}

    captured = json.loads(serialize_trace_payload(payload))

    expected = {"appointment_id": "TEST-123", "access_token": "***"}
    assert json.loads(captured["content"][0]["text"]) == expected
    assert captured["structuredContent"] == expected
    assert response["access_token"] == secret
    assert json.loads(payload["content"][0]["text"])["access_token"] == secret


def test_json_text_array_redacts_nested_custom_fields(monkeypatch):
    """Configured redaction fields also apply inside JSON text arrays."""
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "patient_id")
    reload_trace_redaction_config()
    payload = '[{"data":{"patient_id":"PATIENT-TEST","count":2}},{"ok":true}]'

    assert json.loads(sanitize_trace_text(payload)) == [{"data": {"patient_id": "***", "count": 2}}, {"ok": True}]


def test_invalid_json_text_keeps_free_text_redaction(monkeypatch):
    """Invalid JSON must still pass through the existing free-text sanitizer."""
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token")
    reload_trace_redaction_config()

    assert sanitize_trace_text("{status: failed, token=synthetic-secret}") == "{status: failed, token=***"


def test_excessively_nested_json_text_is_not_exported(monkeypatch):
    """Redaction must omit JSON that exceeds the decoder's nesting limit."""
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "token")
    reload_trace_redaction_config()
    payload = "[" * 2000 + '{"token":"synthetic-secret"}' + "]" * 2000

    assert sanitize_trace_text(payload) == '{"_error":"redaction_depth_exceeded"}'


def test_oversized_json_integer_does_not_interrupt_capture_or_expose_secrets(monkeypatch):
    """Omit JSON text when integer decoding fails before sensitive fields can be masked."""
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "access_token")
    reload_trace_redaction_config()
    payload = '{"number":' + "1" * 5000 + ',"access_token":"synthetic-secret"}'

    captured = json.loads(serialize_trace_payload({"note": payload}))

    assert captured["note"] == '{"_error":"redaction_value_exceeded"}'
    assert "synthetic-secret" not in json.dumps(captured)


@pytest.mark.parametrize("shape", ["structuredContent", "structured_content", "text"])
def test_result_metadata_uses_captured_redacted_fields(monkeypatch, shape):
    """Expose selected result codes without re-reading unredacted tool output."""
    from mcpgateway.utils import trace_redaction

    monkeypatch.setenv("OTEL_CAPTURE_OUTPUT_SPANS", "tool.invoke")
    monkeypatch.setenv("OTEL_TOOL_RESULT_METADATA_FIELDS", "outcome,nextStep,patientName")
    monkeypatch.setenv("OTEL_REDACT_FIELDS", "password,nextStep")
    reload_trace_redaction_config()
    body = {"outcome": "BOOKED", "nextStep": "DONE", "patientName": "Synthetic Person"}
    result = {"content": [{"type": "text", "text": json.dumps(body)}]} if shape == "text" else {shape: body}
    captured = serialize_trace_payload(result)
    assert trace_redaction.extract_tool_result_metadata(captured) == {"outcome": "BOOKED"}


@pytest.mark.parametrize("capture,fields", [("", "outcome"), ("llm.chat", "outcome"), ("tool.invoke", "")])
def test_result_metadata_requires_capture_and_explicit_fields(monkeypatch, capture, fields):
    """Metadata cannot bypass disabled output capture or its own opt-in setting."""
    from mcpgateway.utils import trace_redaction

    monkeypatch.setenv("OTEL_CAPTURE_OUTPUT_SPANS", capture)
    monkeypatch.setenv("OTEL_TOOL_RESULT_METADATA_FIELDS", fields)
    reload_trace_redaction_config()
    assert trace_redaction.extract_tool_result_metadata('{"structuredContent":{"outcome":"BOOKED"}}') == {}


@pytest.mark.parametrize(
    "result",
    [
        {"structuredContent": {"outcome": ["BOOKED"]}},
        {"structuredContent": {"outcome": "a" * 65}},
        {"structuredContent": {"outcome": "free form patient text"}},
        {"structuredContent": {"outcome": "***"}},
        {"_truncated": True, "_preview": '{"outcome":"BOOKED"}'},
        {"content": [{"type": "text", "text": '{"outcome":"BOOKED"}'}, {"type": "text", "text": '{"outcome":"FAILED"}'}]},
        {"structuredContent": {}, "content": [{"type": "text", "text": '{"outcome":"BOOKED"}'}]},
        {"content": [{"type": "text", "text": "not JSON"}]},
    ],
)
def test_result_metadata_omits_ambiguous_or_unsafe_values(monkeypatch, result):
    """Malformed, ambiguous, redacted and oversized results produce no searchable codes."""
    from mcpgateway.utils import trace_redaction

    monkeypatch.setenv("OTEL_CAPTURE_OUTPUT_SPANS", "tool.invoke")
    monkeypatch.setenv("OTEL_TOOL_RESULT_METADATA_FIELDS", "outcome,nextStep")
    reload_trace_redaction_config()
    assert trace_redaction.extract_tool_result_metadata(json.dumps(result)) == {}


def test_result_metadata_respects_whole_output_redaction(monkeypatch):
    """Masking the output attribute must also suppress derived result metadata."""
    from mcpgateway.utils import trace_redaction

    with monkeypatch.context() as patch:
        patch.setenv("OTEL_CAPTURE_OUTPUT_SPANS", "tool.invoke")
        patch.setenv("OTEL_TOOL_RESULT_METADATA_FIELDS", "outcome,nextStep")
        patch.setenv("OTEL_REDACT_FIELDS", "langfuse.observation.output")
        reload_trace_redaction_config()
        captured = serialize_trace_payload({"structuredContent": {"outcome": "BOOKED"}})
        assert sanitize_trace_attribute_value("langfuse.observation.output", captured) == "***"
        assert trace_redaction.extract_tool_result_metadata(captured) == {}
