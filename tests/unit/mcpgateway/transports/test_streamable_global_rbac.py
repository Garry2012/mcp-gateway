# -*- coding: utf-8 -*-
"""Location: ./tests/unit/mcpgateway/transports/test_streamable_global_rbac.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Global ``/mcp`` RBAC with real permission resolution.

The Streamable HTTP handlers run against an in-memory database and the real
``PermissionService``. Only the tool invocation and the logging sink are stubbed,
so these tests prove which team roles a team-scoped API token can use on the
global endpoint, and that public-only, wrong-team and under-privileged tokens are
denied.
"""

# Future
from __future__ import annotations

# Standard
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid

# Third-Party
import mcp_types as types
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

# First-Party
from mcpgateway.db import Base, EmailTeam, EmailUser, Role, UserRole
from mcpgateway.transports import streamablehttp_transport as tr

PASSWORD_HASH = "$argon2id$v=19$m=65536,t=3,p=1$test"  # pragma: allowlist secret


@pytest.fixture
def rbac_db():
    """Two teams; a developer on Team A, a viewer on Team A, an operator with admin.system_config on Team A.

    Yields:
        tuple: (session, team_a_id, team_b_id)
    """
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    db.add(EmailUser(email="admin@test.local", password_hash=PASSWORD_HASH, full_name="Admin", is_admin=False, is_active=True))
    db.flush()
    team_a, team_b = str(uuid.uuid4()), str(uuid.uuid4())
    db.add_all(
        [
            EmailTeam(id=team_a, name="Team A", slug="team-a", created_by="admin@test.local", is_personal=False),
            EmailTeam(id=team_b, name="Team B", slug="team-b", created_by="admin@test.local", is_personal=False),
        ]
    )
    roles = {
        "developer": Role(id=str(uuid.uuid4()), name="developer", scope="team", permissions=["tools.read", "tools.execute"], created_by="admin@test.local", is_system_role=True, is_active=True),
        "viewer": Role(id=str(uuid.uuid4()), name="viewer", scope="team", permissions=["tools.read"], created_by="admin@test.local", is_system_role=True, is_active=True),
        "operator": Role(id=str(uuid.uuid4()), name="operator", scope="team", permissions=["admin.system_config"], created_by="admin@test.local", is_system_role=False, is_active=True),
    }
    db.add_all(roles.values())
    db.flush()
    for email, role in (("dev@test.local", "developer"), ("viewer@test.local", "viewer"), ("operator@test.local", "operator")):
        db.add(EmailUser(email=email, password_hash=PASSWORD_HASH, full_name=email, is_admin=False, is_active=True))
        db.flush()
        db.add(UserRole(user_email=email, role_id=roles[role].id, scope="team", scope_id=team_a, granted_by="admin@test.local", is_active=True))
    db.commit()
    yield db, team_a, team_b
    db.close()
    engine.dispose()


@pytest.fixture
def real_rbac(monkeypatch, rbac_db):
    """Route the transport's permission checks to the in-memory database.

    Yields:
        tuple: (team_a_id, team_b_id, invoke_tool mock, set_level mock)
    """
    db, team_a, team_b = rbac_db

    @asynccontextmanager
    async def fake_get_db():
        yield db

    invoke = AsyncMock(return_value=types.CallToolResult(content=[types.TextContent(type="text", text="ok")]))
    set_level = AsyncMock()
    monkeypatch.setattr(tr, "get_db", fake_get_db)
    monkeypatch.setattr(tr.settings, "mcpgateway_session_affinity_enabled", False)
    monkeypatch.setattr(tr, "extract_gateway_id_from_headers", lambda _headers: None)
    monkeypatch.setattr(tr.tool_service, "invoke_tool", invoke)
    monkeypatch.setattr(tr.logging_service, "set_level", set_level)
    yield team_a, team_b, invoke, set_level


def _api_token_context(monkeypatch, email, teams):
    """Make the next global /mcp request carry a team-scoped API token for ``email``."""
    user = {"email": email, "teams": teams, "token_use": "api", "is_admin": False, "is_authenticated": True}
    monkeypatch.setattr(tr, "_get_request_context_or_default", AsyncMock(return_value=(None, {}, user)))


@pytest.mark.asyncio
async def test_team_token_executes_tool_with_its_team_role(monkeypatch, real_rbac):
    """A developer's Team A token may execute tools on global /mcp."""
    team_a, _, invoke, _ = real_rbac
    _api_token_context(monkeypatch, "dev@test.local", [team_a])
    await tr.call_tool("mytool", {})
    invoke.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("teams", [[], None], ids=["empty-teams", "null-teams"])
async def test_public_only_token_cannot_use_team_role(monkeypatch, real_rbac, teams):
    """Public-only tokens gain no team permissions on global /mcp."""
    _, _, invoke, _ = real_rbac
    _api_token_context(monkeypatch, "dev@test.local", teams)
    with pytest.raises(PermissionError, match="Access denied"):
        await tr.call_tool("mytool", {})
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_token_for_other_team_cannot_use_team_a_role(monkeypatch, real_rbac):
    """A token narrowed to Team B cannot use the user's Team A role."""
    _, team_b, invoke, _ = real_rbac
    _api_token_context(monkeypatch, "dev@test.local", [team_b])
    with pytest.raises(PermissionError, match="Access denied"):
        await tr.call_tool("mytool", {})
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_team_role_without_execute_permission_is_denied(monkeypatch, real_rbac):
    """A Team A viewer (tools.read only) cannot execute tools on global /mcp."""
    team_a, _, invoke, _ = real_rbac
    _api_token_context(monkeypatch, "viewer@test.local", [team_a])
    with pytest.raises(PermissionError, match="Access denied"):
        await tr.call_tool("mytool", {})
    invoke.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_logging_level_requires_admin_system_config(monkeypatch, real_rbac):
    """logging/setLevel on global /mcp is denied for a developer token."""
    team_a, _, _, set_level = real_rbac
    _api_token_context(monkeypatch, "dev@test.local", [team_a])
    with pytest.raises(PermissionError, match="Access denied"):
        await tr.set_logging_level(None, SimpleNamespace(level="debug"))
    set_level.assert_not_awaited()


@pytest.mark.asyncio
async def test_set_logging_level_allowed_by_team_role(monkeypatch, real_rbac):
    """A Team A role granting admin.system_config allows logging/setLevel on global /mcp."""
    team_a, _, _, set_level = real_rbac
    _api_token_context(monkeypatch, "operator@test.local", [team_a])
    await tr.set_logging_level(None, SimpleNamespace(level="debug"))
    set_level.assert_awaited_once()


@pytest.mark.asyncio
async def test_set_logging_level_public_only_token_denied(monkeypatch, real_rbac):
    """A public-only token cannot use the operator's team role for logging/setLevel."""
    _, _, _, set_level = real_rbac
    _api_token_context(monkeypatch, "operator@test.local", [])
    with pytest.raises(PermissionError, match="Access denied"):
        await tr.set_logging_level(None, SimpleNamespace(level="debug"))
    set_level.assert_not_awaited()
