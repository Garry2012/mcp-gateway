# -*- coding: utf-8 -*-
"""Location: ./tests/integration/test_jaeger_dashboard_auth.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Exercise the Jaeger dashboard access boundary with real containers.
"""

# Standard
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

# Third-Party
import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
PROXY_IMAGE = "contextforge-jaeger-proxy:test"
JAEGER_IMAGE = "cr.jaegertracing.io/jaegertracing/jaeger:2.21.0@sha256:3d0ac795ff98aa04d1be04311d2dac6c25b4bfc8322dc02e53bc5b170c5018c3"
pytestmark = pytest.mark.skipif(os.environ.get("RUN_JAEGER_DOCKER_TESTS") != "1", reason="Set RUN_JAEGER_DOCKER_TESTS=1; requires Docker and htpasswd")


def docker(*args: str, cwd: Path | None = None, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Run Docker and return captured output.

    Args:
        args: Docker command arguments.
        cwd: Working directory for Docker.
        env: Environment variables for Docker.

    Returns:
        Completed subprocess result.
    """
    return subprocess.run(["docker", *args], cwd=cwd, env=env, capture_output=True, text=True, check=True)


@pytest.fixture(scope="module")
def dashboard():
    """Start Jaeger and its dashboard proxy with isolated test credentials.

    Yields:
        Dashboard URL and temporary password.
    """
    docker("build", "-f", "Containerfile.proxy", "-t", PROXY_IMAGE, ".", cwd=ROOT / "deploy/jaeger")
    password = secrets.token_urlsafe(32)
    hashed = subprocess.check_output(["htpasswd", "-niB", "-C", "4", "garima"], input=password + "\n", text=True).strip()
    containers = []
    try:
        jaeger = docker(
            "run",
            "-d",
            "--memory",
            "512m",
            "-p",
            "127.0.0.1::8080",
            "-e",
            "GOMEMLIMIT=384MiB",
            "-v",
            f"{ROOT / 'deploy/jaeger/config-memory.yaml'}:/etc/jaeger/config.yaml:ro",
            JAEGER_IMAGE,
            "--config",
            "/etc/jaeger/config.yaml",
        ).stdout.strip()
        containers.append(jaeger)
        proxy = docker("run", "-d", "--network", f"container:{jaeger}", "-e", "JAEGER_HTPASSWD", PROXY_IMAGE, env={**os.environ, "JAEGER_HTPASSWD": hashed}).stdout.strip()
        containers.append(proxy)
        info = json.loads(docker("inspect", jaeger).stdout)[0]
        port = info["NetworkSettings"]["Ports"]["8080/tcp"][0]["HostPort"]
        url = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            try:
                if httpx.get(url, auth=("garima", password)).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        else:
            pytest.fail("Jaeger dashboard did not start")
        yield url, password
        assert password not in docker("logs", proxy).stdout
    finally:
        for container in reversed(containers):
            docker("rm", "-f", container)


@pytest.mark.parametrize("path", ["/", "/api/v3/services", "/api/v3/traces"])
@pytest.mark.parametrize("identity", ["anonymous", "wrong_password", "wrong_user"])
def test_dashboard_rejects_invalid_identity(dashboard, path, identity):
    """Reject access to the UI and trace API without valid credentials."""
    url, password = dashboard
    auth = None if identity == "anonymous" else ("garima", "invalid") if identity == "wrong_password" else ("other", password)
    response = httpx.get(url + path, auth=auth)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Basic")
    assert response.headers["cache-control"] == "no-store"


def test_dashboard_allows_valid_identity(dashboard):
    """Serve the dashboard and query API after password authentication."""
    url, password = dashboard
    assert httpx.get(url, auth=("garima", password)).status_code == 200
    response = httpx.get(url + "/api/v3/services", auth=("garima", password))
    assert response.status_code == 200
    assert "services" in response.json()


def test_dashboard_refuses_start_without_secret(dashboard):
    """Fail closed when the dashboard secret is absent."""
    with pytest.raises(subprocess.CalledProcessError) as error:
        docker("run", "--rm", PROXY_IMAGE)
    assert "Set JAEGER_HTPASSWD" in error.value.stderr
