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


def run_deploy(tmp_path: Path, entrypoint: str = "03-deploy-gateway.sh", script_root: Path = ROOT, **settings: str) -> tuple[subprocess.CompletedProcess[str], list[list[str]]]:
    """Execute deployment with an isolated Azure CLI boundary.

    Args:
        tmp_path: Temporary directory for the CLI and recorded calls.
        entrypoint: Script to execute.
        script_root: Repository containing the deployment scripts.
        settings: Environment overrides for the deployment.

    Returns:
        The script result and recorded Azure CLI calls.
    """
    calls_path = tmp_path / "calls.jsonl"
    fake_az = tmp_path / "az"
    fake_az.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
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
        "elif args[:3] == ['acr', 'repository', 'show']:\n"
        "    if os.environ.get('TEST_DIGEST_ERROR'): sys.exit(1)\n"
        "    print(os.environ.get('TEST_DIGEST', 'sha256:' + 'a' * 64))\n"
        "elif args[:2] in (['containerapp', 'create'], ['containerapp', 'update']):\n"
        "    Path(os.environ['AZ_CALLS'] + '.created').touch()\n"
        "    if '--revision-suffix' in args:\n"
        "        revision = args[args.index('--name' if '--name' in args else '-n') + 1] + '--' + args[args.index('--revision-suffix') + 1]\n"
        "    else: revision = 'gateway--new'\n"
        "    if os.environ.get('TEST_STALE_UPDATE'): revision = 'gateway--old'\n"
        "    Path(os.environ['AZ_CALLS'] + '.revision').write_text(revision)\n"
        "    if '--query' in args: print(revision)\n"
        "elif args[:2] == ['containerapp', 'show'] and os.environ.get('TEST_APP_ERROR') and not Path(os.environ['AZ_CALLS'] + '.created').exists():\n"
        "    print(os.environ['TEST_APP_ERROR'], file=sys.stderr)\n"
        "    sys.exit(1)\n"
        "elif args[:3] == ['acr', 'repository', 'show-tags']:\n"
        "    print('test-image')\n"
        "elif args[:2] == ['containerapp', 'show'] and '--query' in args:\n"
        "    query = args[args.index('--query') + 1]\n"
        "    if query == os.environ.get('TEST_READ_ERROR'): sys.exit(1)\n"
        "    revision_file = Path(os.environ['AZ_CALLS'] + '.revision')\n"
        "    if query == 'properties.latestRevisionName' and revision_file.exists():\n"
        "        print('gateway--concurrent' if os.environ.get('TEST_CONCURRENT_REVISION') else revision_file.read_text())\n"
        "        sys.exit(0)\n"
        "    values = {'properties.latestRevisionName': 'gateway--new', 'name': 'mcp-gateway', 'length(properties.template.containers)': os.environ.get('TEST_CONTAINER_COUNT', '1'),\n"
        "        'properties.template.containers[0].name': 'gateway-container',\n"
        "        'properties.template.containers[0].image': os.environ.get('TEST_LIVE_IMAGE', 'vcarercacr.azurecr.io/mcp-gateway@sha256:' + 'b' * 64),\n"
        "        'properties.template.containers[0].resources.cpu': '1.5',\n"
        "        'properties.template.containers[0].resources.memory': '3Gi',\n"
        "        'properties.template.scale.minReplicas': '0', 'properties.template.scale.maxReplicas': '3'}\n"
        "    if 'DEFAULT_USER_PASSWORD' in query: print('default-user-password')\n"
        "    else: print(values.get(query, 'https://gateway.example' if 'APP_DOMAIN' in query else 'gateway.example'))\n"
        "elif args[:3] == ['containerapp', 'revision', 'list']:\n"
        "    import re\n"
        "    query = args[args.index('--query') + 1]\n"
        "    image = os.environ.get('TEST_SERVING_IMAGE', 'vcarercacr.azurecr.io/mcp-gateway@sha256:' + 'a' * 64)\n"
        "    revision_file = Path(os.environ['AZ_CALLS'] + '.revision')\n"
        "    revision = os.environ.get('TEST_SERVING_REVISION', revision_file.read_text() if revision_file.exists() else 'gateway--new')\n"
        "    if '-o' in args and args[args.index('-o') + 1] == 'table': sys.exit(0)\n"
        "    expected_name = re.search(r\"name=='([^']+)'\", query)\n"
        "    expected_image = re.search(r\"image=='([^']+)'\", query)\n"
        "    assert expected_image, 'unexpected revision query'\n"
        "    assert 'properties.active' in query and 'properties.trafficWeight==`100`' in query\n"
        "    assert \"properties.healthState=='Healthy'\" in query and \"starts_with(properties.runningState, 'Running')\" in query\n"
        "    print(revision if expected_image[1] == image and (not expected_name or expected_name[1] == revision) else '')\n"
    )
    fake_az.chmod(0o755)
    fake_curl = tmp_path / "curl"
    fake_curl.write_text(
        '#!/usr/bin/env bash\ncase "$*" in\n  *gateways*) echo 401 ;;\n  *admin/login*) echo "<title>Login</title>" ;;\n  *http_code*) echo 200 ;;\n  *) echo \'{"status":"healthy"}\' ;;\nesac\n'
    )
    fake_curl.chmod(0o755)
    fake_sleep = tmp_path / "sleep"
    fake_sleep.write_text("#!/usr/bin/env bash\nexit 0\n")
    fake_sleep.chmod(0o755)
    excluded = (
        "OTEL_",
        "LANGFUSE_",
        "KV_OTEL_HEADERS",
        "TEST_",
        "IMAGE",
        "EXPECTED_REVISION",
        "DEPLOY_RESULT_FILE",
        "APP_CPU",
        "APP_MEMORY",
        "APP_MIN_REPLICAS",
        "APP_MAX_REPLICAS",
        "DCR_ALLOWED_ISSUERS",
        "DEPLOY_PROFILE",
        "MCPGATEWAY_",
        "MCP_CLIENT_CONNECT_MODE",
        "MCP_INBOUND_PROTOCOL_MODE",
    )
    env = {key: value for key, value in os.environ.items() if not key.startswith(excluded)}
    env.update(PATH=f"{tmp_path}:{env['PATH']}", AZ_CALLS=str(calls_path), IMAGE_TAG="test-image", APP_DOMAIN="https://gateway.example")
    env.update(settings)
    result = subprocess.run(["bash", str(script_root / "deploy/scripts" / entrypoint)], env=env, text=True, capture_output=True, check=False)
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


def test_trace_environment_does_not_change_auth_environment(tmp_path):
    """Custom trace labels must not change token environment validation."""
    result, calls = run_deploy(tmp_path, DEPLOYMENT_ENV="staging", OTEL_TOOL_RESULT_METADATA_FIELDS="outcome,nextStep")
    assert result.returncode == 0, result.stderr
    update = next(call for call in calls if call[:2] == ["containerapp", "update"])
    assert "DEPLOYMENT_ENV=staging" in update
    assert "ENVIRONMENT=production" in update
    assert "OTEL_TOOL_RESULT_METADATA_FIELDS=outcome,nextStep" in update
