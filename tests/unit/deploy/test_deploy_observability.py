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
        "if args[:3] == ['keyvault', 'secret', 'show'] and args[args.index('--name') + 1] == os.environ.get('KV_OTEL_HEADERS'):\n"
        "    error = os.environ.get('TEST_OTEL_SECRET_ERROR')\n"
        "    if error:\n"
        "        print(error, file=sys.stderr)\n"
        "        sys.exit(1)\n"
        "if args[:2] == ['identity', 'show']:\n"
        "    print('/subscriptions/test/resourceGroups/test/providers/Microsoft.ManagedIdentity/userAssignedIdentities/gateway')\n"
        "elif args[:3] == ['acr', 'repository', 'show-tags']:\n"
        "    print('test-image')\n"
        "elif args[:2] == ['containerapp', 'show'] and '--query' in args:\n"
        "    query = args[args.index('--query') + 1]\n"
        "    print('https://gateway.example' if 'APP_DOMAIN' in query else 'gateway.example')\n"
    )
    fake_az.chmod(0o755)
    excluded = ("OTEL_", "LANGFUSE_", "KV_OTEL_HEADERS", "TEST_OTEL_", "DEPLOY_PROFILE", "MCP_CLIENT_CONNECT_MODE", "MCP_INBOUND_PROTOCOL_MODE")
    env = {key: value for key, value in os.environ.items() if not key.startswith(excluded)}
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


def test_export_auth_uses_key_vault_reference(tmp_path):
    """Deploy exporter authentication through a secret reference without reading its value."""
    result, calls = run_deploy(tmp_path, KV_OTEL_HEADERS="trace-export-headers")
    assert result.returncode == 0, result.stderr
    update = next(call for call in calls if call[:2] == ["containerapp", "update"])
    secret_set = next(call for call in calls if call[:3] == ["containerapp", "secret", "set"])
    assert "OTEL_EXPORTER_OTLP_HEADERS=secretref:otel-headers" in update
    assert any(arg.startswith("otel-headers=keyvaultref:") and "/trace-export-headers,identityref:" in arg for arg in secret_set)
    secret_reads = [call for call in calls if call[:3] == ["keyvault", "secret", "show"]]
    assert all(call[call.index("-o") + 1] == "none" and "--query" not in call for call in secret_reads)


@pytest.mark.parametrize("error", ["SecretNotFound", "Forbidden"])
def test_unavailable_export_secret_stops_before_app_mutation(tmp_path, error):
    """Reject missing or inaccessible exporter secrets before changing the container app."""
    result, calls = run_deploy(tmp_path, KV_OTEL_HEADERS="trace-export-headers", TEST_OTEL_SECRET_ERROR=error)
    assert result.returncode != 0
    assert "trace-export-headers" in result.stderr
    mutations = (["containerapp", "update"], ["containerapp", "create"], ["containerapp", "secret", "set"])
    assert not any(call[: len(prefix)] == prefix for call in calls for prefix in mutations)


def test_omitted_export_secret_adds_no_auth_reference(tmp_path):
    """Keep exporter credentials optional for deployments without an authenticated collector."""
    result, calls = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    assert not any("otel-headers" in arg or "OTEL_EXPORTER_OTLP_HEADERS=" in arg for call in calls for arg in call)


@pytest.mark.parametrize("secret_name", ["", "trace-export-headers"])
def test_export_secret_grant_is_scoped_to_named_secret(secret_name):
    """Grant exporter access only to the configured secret and gateway identity."""
    source = (ROOT / "deploy/scripts/01-prepare-azure.sh").read_text()
    selection = source[source.index("GATEWAY_SECRETS=(") : source.index("\nrandom_secret()")]
    grants = source[source.index("GRANTED=0") : source.index('\nif [ "$GRANTED"')]
    script = f"""set -euo pipefail
KV_JWT_SECRET=jwt KV_ENC_SECRET=enc KV_DB_URL=db KV_ADMIN_PASSWORD=admin KV_DEFAULT_USER_PASSWORD=user
KV_OTEL_HEADERS={secret_name}
UAMI_PRINCIPAL=gateway-identity KV_ID=/vaults/test-vault ACR_ID=/registries/test-acr
ok() {{ :; }}
az() {{
  if [ "$3" = list ]; then echo 0; else printf '%s\\n' "$*"; fi
}}
{selection}
{grants}
"""
    result = subprocess.run(["bash"], input=script, text=True, capture_output=True, check=False)
    assert result.returncode == 0, result.stderr
    vault_grants = [line for line in result.stdout.splitlines() if "Key Vault Secrets User" in line]
    expected = {"jwt", "enc", "db", "admin", "user"} | ({secret_name} if secret_name else set())
    scopes = {line.split("--scope ", 1)[1].split()[0] for line in vault_grants}
    assert scopes == {f"/vaults/test-vault/secrets/{name}" for name in expected}
    assert all("--assignee-object-id gateway-identity --assignee-principal-type ServicePrincipal" in line for line in vault_grants)


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
