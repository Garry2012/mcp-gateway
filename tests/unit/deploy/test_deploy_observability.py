# -*- coding: utf-8 -*-
"""Location: ./tests/unit/deploy/test_deploy_observability.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Verify Azure deployment forwards complete, opt-in OpenTelemetry configuration.
"""

# Standard
import json
import os
from pathlib import Path
import subprocess
import sys

# Third-Party
import pytest

ROOT = Path(__file__).resolve().parents[3]


def run_deploy(tmp_path: Path, **settings: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Execute deployment with an isolated Azure CLI boundary.

    Args:
        tmp_path: Temporary directory for the CLI and recorded calls.
        settings: Environment overrides for the deployment.

    Returns:
        The script result and recorded Azure CLI calls.
    """
    calls_path = tmp_path / "calls.jsonl"
    fake_az = tmp_path / "az"
    fake_az.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "args = sys.argv[1:]\n"
        "with open(os.environ['AZ_CALLS'], 'a') as out:\n"
        "    out.write(json.dumps(args) + '\\n')\n"
        "if args[:2] == ['identity', 'show']:\n"
        "    print('/subscriptions/test/resourceGroups/test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gateway')\n"
        "elif args[:3] == ['acr', 'repository', 'show-tags']:\n"
        "    print('test-image')\n"
        "elif args[:2] == ['containerapp', 'show'] and '--query' in args:\n"
        "    query = args[args.index('--query') + 1]\n"
        "    print('https://gateway.example' if 'APP_DOMAIN' in query else 'gateway.example')\n"
    )
    fake_az.chmod(0o755)
    env = {key: value for key, value in os.environ.items() if not key.startswith(("OTEL_", "LANGFUSE_", "DEPLOY_PROFILE", "MCP_CLIENT_CONNECT_MODE", "MCP_INBOUND_PROTOCOL_MODE"))}
    env.update(PATH=f"{tmp_path}:{env['PATH']}", AZ_CALLS=str(calls_path), IMAGE_TAG="test-image", APP_DOMAIN="https://gateway.example")
    env.update(settings)
    result = subprocess.run(["bash", str(ROOT / "deploy/scripts/03-deploy-gateway.sh")], env=env, text=True, capture_output=True, check=False)
    calls = [json.loads(line) for line in calls_path.read_text().splitlines()] if calls_path.exists() else []
    return result, calls


def test_enabled_export_forwards_payload_capture_and_collector_settings(tmp_path):
    """A redeployment must retain the settings needed to export payloads to Jaeger."""
    result, calls = run_deploy(
        tmp_path,
        OTEL_ENABLE_OBSERVABILITY="true",
        OTEL_EXPORTER_OTLP_ENDPOINT="http://jaeger:4317",
        OTEL_EXPORTER_OTLP_PROTOCOL="grpc",
        OTEL_EXPORTER_OTLP_INSECURE="true",
        OTEL_EMIT_LANGFUSE_ATTRIBUTES="true",
        OTEL_CAPTURE_IDENTITY_ATTRIBUTES="false",
        OTEL_REDACT_FIELDS="password,secret,token,api_key,patient_id",
    )
    assert result.returncode == 0, result.stderr
    update = next(call for call in calls if call[:2] == ["containerapp", "update"])
    for setting in (
        "OTEL_ENABLE_OBSERVABILITY=true",
        "OTEL_TRACES_EXPORTER=otlp",
        "OTEL_EXPORTER_OTLP_ENDPOINT=http://jaeger:4317",
        "OTEL_EXPORTER_OTLP_PROTOCOL=grpc",
        "OTEL_EXPORTER_OTLP_INSECURE=true",
        "OTEL_EMIT_LANGFUSE_ATTRIBUTES=true",
        "OTEL_CAPTURE_IDENTITY_ATTRIBUTES=false",
        "OTEL_CAPTURE_INPUT_SPANS=tool.invoke",
        "OTEL_CAPTURE_OUTPUT_SPANS=tool.invoke",
        "OTEL_REDACT_FIELDS=password,secret,token,api_key,patient_id",
    ):
        assert setting in update


def test_disabled_export_does_not_enable_network_export(tmp_path):
    """Ordinary gateway deployments must keep external telemetry disabled."""
    result, calls = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    update = next(call for call in calls if call[:2] == ["containerapp", "update"])
    assert "OTEL_ENABLE_OBSERVABILITY=false" in update


def test_healthcare_deployment_preserves_protocol_and_session_behavior(tmp_path):
    """Keep existing MCP handshakes and eight-hour sessions during upstream updates."""
    result, calls = run_deploy(tmp_path, DEPLOY_PROFILE="profiles/healthcare-rg.env")
    assert result.returncode == 0, result.stderr
    update = next(call for call in calls if call[:2] == ["containerapp", "update"])
    for setting in ("MCP_CLIENT_CONNECT_MODE=legacy", "MCP_INBOUND_PROTOCOL_MODE=legacy", "TOKEN_EXPIRY=480", "TOKEN_IDLE_TIMEOUT=480"):
        assert setting in update


def test_default_deployment_uses_upstream_protocol_defaults(tmp_path):
    """Keep automatic negotiation available outside the healthcare profile."""
    result, calls = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    update = next(call for call in calls if call[:2] == ["containerapp", "update"])
    assert "MCP_CLIENT_CONNECT_MODE=auto" in update
    assert "MCP_INBOUND_PROTOCOL_MODE=auto" in update


@pytest.mark.parametrize("endpoint,protocol", [("", "grpc"), ("http://jaeger:4317", "invalid")])
def test_invalid_export_configuration_stops_before_azure_mutations(tmp_path, endpoint, protocol):
    """Reject configurations that would deploy without a working exporter."""
    result, calls = run_deploy(tmp_path, OTEL_ENABLE_OBSERVABILITY="true", OTEL_EXPORTER_OTLP_ENDPOINT=endpoint, OTEL_EXPORTER_OTLP_PROTOCOL=protocol)
    assert result.returncode != 0
    assert not any(call[:2] == ["containerapp", "update"] or call[:3] == ["containerapp", "secret", "set"] for call in calls)
