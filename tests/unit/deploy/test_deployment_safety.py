# -*- coding: utf-8 -*-
"""Exercise Azure deployment safety through the real shell entry point."""

# Third-Party
import pytest

# Local
from .test_deploy_observability import run_deploy


def main_update(calls: list[list[str]]) -> list[str]:
    """Return the update that configures the gateway container."""
    return next(call for call in calls if call[:2] == ["containerapp", "update"] and "--image" in call)


def assert_no_mutations(calls: list[list[str]]) -> None:
    """Reject writes when any deployment prerequisite fails."""
    prefixes = (["containerapp", "create"], ["containerapp", "update"], ["containerapp", "secret", "set"])
    assert not any(call[: len(prefix)] == prefix for call in calls for prefix in prefixes)


def test_explicit_tag_deploys_immutable_digest(tmp_path):
    """A mutable tag must resolve before Azure receives an image update."""
    result, calls = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    assert update[update.index("--image") + 1] == "vcarercacr.azurecr.io/mcp-gateway@sha256:" + "a" * 64


def test_config_only_preserves_live_digest_and_resources(tmp_path):
    """Omitting image and resource selectors must preserve the live deployment."""
    result, calls = run_deploy(tmp_path, IMAGE_TAG="")
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    assert update[update.index("--image") + 1] == "vcarercacr.azurecr.io/mcp-gateway@sha256:" + "b" * 64
    for flag, expected in (("--cpu", "1.5"), ("--memory", "3Gi"), ("--min-replicas", "0"), ("--max-replicas", "3"), ("--container-name", "gateway-container")):
        assert update[update.index(flag) + 1] == expected
    assert not any(call[:3] == ["acr", "repository", "show-tags"] for call in calls)


def test_explicit_resources_are_applied_on_update(tmp_path):
    """Profile resource changes must reach existing Container Apps."""
    result, calls = run_deploy(tmp_path, APP_CPU="2", APP_MEMORY="4Gi", APP_MIN_REPLICAS="2", APP_MAX_REPLICAS="4")
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    for flag, expected in (("--cpu", "2"), ("--memory", "4Gi"), ("--min-replicas", "2"), ("--max-replicas", "4")):
        assert update[update.index(flag) + 1] == expected


def test_only_explicitly_cleared_optional_settings_are_removed(tmp_path):
    """Clear obsolete owned settings without replacing the complete environment."""
    result, calls = run_deploy(tmp_path, KV_OTEL_HEADERS="", OTEL_REDACT_FIELDS="", DCR_ALLOWED_ISSUERS="")
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    start = update.index("--remove-env-vars") + 1
    removed = []
    for value in update[start:]:
        if value.startswith("-"):
            break
        removed.append(value)
    assert set(removed) == {"OTEL_EXPORTER_OTLP_HEADERS", "OTEL_REDACT_FIELDS", "DCR_ALLOWED_ISSUERS"}
    assert "--replace-env-vars" not in update and "--remove-all-env-vars" not in update
    assert not any(call[:3] == ["containerapp", "secret", "remove"] for call in calls)


def test_unspecified_optional_settings_are_preserved(tmp_path):
    """An omitted setting must not disable existing masking or exporter authentication."""
    result, calls = run_deploy(tmp_path)
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    assert "--remove-env-vars" not in update
    assert "--replace-env-vars" not in update and "--remove-all-env-vars" not in update


@pytest.mark.parametrize(
    "settings",
    [
        {"TEST_DIGEST": "not-a-digest"},
        {"TEST_DIGEST_ERROR": "1"},
        {"IMAGE_TAG": "", "TEST_LIVE_IMAGE": "vcarercacr.azurecr.io/mcp-gateway:mutable"},
        {"IMAGE_TAG": "", "IMAGE_DIGEST": "sha256:bad"},
        {"TEST_APP_ERROR": "Forbidden"},
        {"TEST_APP_ERROR": "Connection timeout"},
    ],
)
def test_unsafe_preflight_stops_before_mutation(tmp_path, settings):
    """Failed reads and ambiguous image identity must never change Azure resources."""
    result, calls = run_deploy(tmp_path, **settings)
    assert result.returncode != 0
    assert_no_mutations(calls)


def test_explicit_digest_does_not_resolve_mutable_tag(tmp_path):
    """An explicit release digest must remain independent of tag changes."""
    result, calls = run_deploy(tmp_path, IMAGE_TAG="", IMAGE_DIGEST="sha256:" + "c" * 64)
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    assert update[update.index("--image") + 1].endswith("@sha256:" + "c" * 64)
    assert not any(call[:3] == ["acr", "repository", "show"] and "--query" in call for call in calls)


def test_first_deployment_uses_digest_and_resource_defaults(tmp_path):
    """A verified ResourceNotFound permits creation with a fixed image."""
    result, calls = run_deploy(tmp_path, TEST_APP_ERROR="ERROR: (ResourceNotFound) Missing app")
    assert result.returncode == 0, result.stderr
    create = next(call for call in calls if call[:2] == ["containerapp", "create"])
    assert create[create.index("--image") + 1].endswith("@sha256:" + "a" * 64)
    for flag, value in (("--cpu", "1.0"), ("--memory", "2.0Gi"), ("--min-replicas", "1"), ("--max-replicas", "1")):
        assert create[create.index(flag) + 1] == value


def test_missing_app_without_image_selector_never_creates(tmp_path):
    """A configuration-only update must not create an app from local HEAD."""
    result, calls = run_deploy(tmp_path, IMAGE_TAG="", TEST_APP_ERROR="ERROR: (ResourceNotFound) Missing app")
    assert result.returncode != 0
    assert_no_mutations(calls)


@pytest.mark.parametrize("revision,success", [("gateway--old", False), ("gateway--new", True)])
def test_smoke_requires_latest_revision_even_for_same_image(tmp_path, revision, success):
    """An older healthy revision cannot prove a configuration update succeeded."""
    result, _ = run_deploy(tmp_path, entrypoint="04-smoke.sh", TEST_SERVING_REVISION=revision)
    assert (result.returncode == 0) == success, result.stderr


def test_config_only_smoke_uses_current_digest(tmp_path):
    """Standalone verification must use the current pinned image without a tag."""
    result, _ = run_deploy(tmp_path, entrypoint="04-smoke.sh", IMAGE_TAG="", TEST_SERVING_IMAGE="vcarercacr.azurecr.io/mcp-gateway@sha256:" + "b" * 64)
    assert result.returncode == 0, result.stderr


@pytest.fixture
def build_repository(tmp_path):
    """Create a small committed repository for real archive and build-script execution."""
    # Standard
    from pathlib import Path
    import shutil
    import subprocess

    root = Path(__file__).resolve().parents[3]
    repo = tmp_path / "repo"
    shutil.copytree(root / "deploy", repo / "deploy", ignore=shutil.ignore_patterns("__pycache__"))
    (repo / "Containerfile").write_text("ARG UBI_BASE=base\nARG NODEJS_IMAGE=node\nARG UBI_MINIMAL=minimal\nFROM scratch\n")
    for args in (("init", "-q"), ("add", "."), ("-c", "user.name=Test", "-c", "user.email=test@example.com", "-c", "commit.gpgsign=false", "commit", "-qm", "test fixture")):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    return repo


def test_build_defaults_to_unique_tag_and_reports_digest(tmp_path, build_repository):
    """Rebuilding one commit must produce distinct build identities and a pinned result."""
    images = []
    for index in range(2):
        run_path = tmp_path / str(index)
        run_path.mkdir()
        result, calls = run_deploy(run_path, entrypoint="02-build-images.sh", script_root=build_repository, IMAGE_TAG="")
        assert result.returncode == 0, result.stderr
        build = next(call for call in calls if call[:2] == ["acr", "build"])
        images.append(build[build.index("--image") + 1])
        assert "mcp-gateway:latest" not in build
        assert "sha256:" + "a" * 64 in result.stdout
    assert images[0] != images[1]


def test_build_refuses_deployment_digest_selector(tmp_path, build_repository):
    """A stale deployment digest must not override a newly built image."""
    result, calls = run_deploy(tmp_path, entrypoint="02-build-images.sh", script_root=build_repository, IMAGE_TAG="", IMAGE_DIGEST="sha256:" + "c" * 64)
    assert result.returncode != 0
    assert not any(call[:2] == ["acr", "build"] for call in calls)


def test_orchestrator_carries_build_digest_to_deploy_and_smoke(tmp_path, build_repository):
    """Build, deploy and verify must agree on one immutable image."""
    # The wrapper retains real orchestration while avoiding unrelated infrastructure provisioning.
    wrapper = build_repository / "deploy/scripts/test-orchestrator.sh"
    wrapper.write_text('#!/usr/bin/env bash\nexec "$(dirname "$0")/deploy.sh" --skip-infra\n')
    result, calls = run_deploy(tmp_path, entrypoint=wrapper.name, script_root=build_repository, IMAGE_TAG="", TEST_CONCURRENT_REVISION="1")
    assert result.returncode == 0, result.stderr
    assert any(call[:2] == ["acr", "build"] for call in calls)
    update = main_update(calls)
    assert update[update.index("--image") + 1].endswith("@sha256:" + "a" * 64)
    assert "All checks passed" in result.stdout


def test_skip_build_preserves_live_digest(tmp_path, build_repository):
    """Skipping the build without selectors must preserve the currently deployed image."""
    wrapper = build_repository / "deploy/scripts/test-orchestrator.sh"
    wrapper.write_text('#!/usr/bin/env bash\nexec "$(dirname "$0")/deploy.sh" --skip-infra --skip-build\n')
    result, calls = run_deploy(tmp_path, entrypoint=wrapper.name, script_root=build_repository, IMAGE_TAG="", TEST_SERVING_IMAGE="vcarercacr.azurecr.io/mcp-gateway@sha256:" + "b" * 64)
    assert result.returncode == 0, result.stderr
    assert not any(call[:2] == ["acr", "build"] for call in calls)
    update = main_update(calls)
    assert update[update.index("--image") + 1].endswith("@sha256:" + "b" * 64)
    assert "All checks passed" in result.stdout


@pytest.mark.parametrize("query", ["length(properties.template.containers)", "properties.template.containers[0].name", "properties.template.containers[0].resources.cpu"])
def test_failed_container_reads_stop_before_mutation(tmp_path, query):
    """Unavailable container metadata must not trigger partial updates."""
    result, calls = run_deploy(tmp_path, TEST_READ_ERROR=query)
    assert result.returncode != 0
    assert_no_mutations(calls)


def test_multi_container_update_requires_separate_review(tmp_path):
    """Never apply gateway settings to an ambiguous container selection."""
    result, calls = run_deploy(tmp_path, TEST_CONTAINER_COUNT="2")
    assert result.returncode != 0
    assert_no_mutations(calls)


def test_unavailable_explicit_digest_never_sets_secrets(tmp_path):
    """Digest availability must be checked before secret references change."""
    result, calls = run_deploy(tmp_path, IMAGE_TAG="", IMAGE_DIGEST="sha256:" + "c" * 64, TEST_DIGEST_ERROR="1")
    assert result.returncode != 0
    assert_no_mutations(calls)


def test_explicit_auth_removal_with_enabled_export(tmp_path):
    """Deliberately switching to an unauthenticated collector removes only its header reference."""
    result, calls = run_deploy(tmp_path, OTEL_ENABLE_OBSERVABILITY="true", OTEL_EXPORTER_OTLP_ENDPOINT="http://collector:4317", KV_OTEL_HEADERS="")
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    assert update[update.index("--remove-env-vars") + 1] == "OTEL_EXPORTER_OTLP_HEADERS"
    assert not any("otel-headers=" in arg for call in calls for arg in call)


def test_update_rolls_revision_and_records_its_identity(tmp_path):
    """Even unchanged templates must reload updated secret references in a fresh revision."""
    result_file = tmp_path / "revision"
    result, calls = run_deploy(tmp_path, DEPLOY_RESULT_FILE=str(result_file))
    assert result.returncode == 0, result.stderr
    update = main_update(calls)
    suffix = update[update.index("--revision-suffix") + 1]
    assert result_file.read_text().strip() == "mcp-gateway--" + suffix


def test_stale_update_result_is_rejected(tmp_path):
    """Azure returning an older revision cannot count as a completed rollout."""
    result, _ = run_deploy(tmp_path, TEST_STALE_UPDATE="1")
    assert result.returncode != 0


def test_smoke_uses_captured_revision_instead_of_concurrent_latest(tmp_path):
    """A newer concurrent deployment must not replace the expected revision identity."""
    result, _ = run_deploy(tmp_path, entrypoint="04-smoke.sh", EXPECTED_REVISION="gateway--intended", TEST_SERVING_REVISION="gateway--new")
    assert result.returncode != 0
