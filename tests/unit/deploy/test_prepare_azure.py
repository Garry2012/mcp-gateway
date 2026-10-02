# -*- coding: utf-8 -*-
"""Location: ./tests/unit/deploy/test_prepare_azure.py
Copyright contributors to the MCP-CONTEXT-FORGE project
SPDX-License-Identifier: Apache-2.0

Safety tests for the Azure preparation step on shared resources.

``deploy/scripts/01-prepare-azure.sh`` writes Key Vault secrets and provisions a
role and database on a PostgreSQL server shared with other applications. These
tests prove that a transient Key Vault failure never regenerates a secret, and
that a configuration collision never changes another role or database.
"""

# Standard
import importlib.util
from pathlib import Path
import shutil
import subprocess
from unittest.mock import patch

# Third-Party
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PREPARE_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "01-prepare-azure.sh"
PROVISION_SCRIPT = REPO_ROOT / "deploy" / "scripts" / "provision_shared_db.py"


def _load_provision_module():
    spec = importlib.util.spec_from_file_location("provision_shared_db", PROVISION_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


provision_shared_db = _load_provision_module()
requires_psycopg = pytest.mark.skipif(provision_shared_db.psycopg is None, reason="psycopg not installed (postgres extra)")


# --------------------------------------------------------------------------- #
# Key Vault: only a confirmed SecretNotFound creates a secret
# --------------------------------------------------------------------------- #


def _run_secret_helpers(show_behaviour: str) -> subprocess.CompletedProcess:
    """Run the script's Key Vault helpers with a stubbed ``az`` CLI.

    Args:
        show_behaviour: ``present``, ``missing`` or ``transient`` for ``az keyvault secret show``.

    Returns:
        subprocess.CompletedProcess: Result; ``stdout`` records ``SET <name>`` for each write.
    """
    source = PREPARE_SCRIPT.read_text()
    helpers = source[source.index("kv_state() {") : source.index("\nensure_azure_services_firewall()")]
    script = f"""set -euo pipefail
az() {{
  case "$3" in
    show)
      case "{show_behaviour}" in
        present) return 0 ;;
        missing) echo "(SecretNotFound) A secret with (name/id) $7 was not found in this key vault." >&2; return 3 ;;
        *) echo "HTTPSConnectionPool: Read timed out." >&2; return 1 ;;
      esac ;;
    set) echo "SET $7" ;;
  esac
}}
ok() {{ :; }}
die() {{ echo "DIE $*" >&2; exit 1; }}
random_secret() {{ echo generated; }}
KEYVAULT_NAME=test-vault
{helpers}
ensure_secret mcpgw-auth-encryption-secret random_secret 48
echo DONE
"""
    return subprocess.run(["bash"], input=script, text=True, capture_output=True, check=False)


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_transient_key_vault_failure_never_regenerates_secret():
    result = _run_secret_helpers("transient")
    assert result.returncode != 0
    assert "SET" not in result.stdout
    assert "not a SecretNotFound error" in result.stderr


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_missing_secret_is_created():
    result = _run_secret_helpers("missing")
    assert result.returncode == 0, result.stderr
    assert "SET mcpgw-auth-encryption-secret" in result.stdout


@pytest.mark.skipif(shutil.which("bash") is None, reason="bash not available")
def test_existing_secret_is_kept():
    result = _run_secret_helpers("present")
    assert result.returncode == 0, result.stderr
    assert "SET" not in result.stdout
    assert "DONE" in result.stdout


# --------------------------------------------------------------------------- #
# Shared PostgreSQL: refuse collisions before any change
# --------------------------------------------------------------------------- #


class FakeServer:
    """Minimal psycopg stand-in answering the catalog queries the script issues."""

    def __init__(self, admin="serveradmin", roles=None, databases=None, memberships=None):
        self.admin = admin
        self.roles = roles or {}  # name -> (oid, super, createrole, createdb, replication, bypassrls)
        self.databases = databases or {}  # name -> owner name
        self.memberships = memberships or {}  # oid -> count
        self.statements = []
        self._row = None

    # connection protocol
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self

    def fetchone(self):
        return self._row

    def execute(self, statement, params=()):
        text = statement if isinstance(statement, str) else statement.as_string()
        self.statements.append(text)
        self._row = None
        if text == "SELECT current_user":
            self._row = (self.admin,)
        elif "FROM pg_roles" in text:
            role = self.roles.get(params[0])
            self._row = (role[0], *role[1:]) if role else None
        elif "pg_get_userbyid(datdba)" in text:
            owner = self.databases.get(params[0])
            self._row = (owner,) if owner else None
        elif "FROM pg_auth_members" in text:
            self._row = (self.memberships.get(params[0], 0),)
        elif "WHERE datdba" in text:
            oid, name = params
            owner_name = next((n for n, r in self.roles.items() if r[0] == oid), None)
            self._row = (sum(1 for db, owner in self.databases.items() if owner == owner_name and db != name),)
        return self

    @property
    def mutations(self):
        return [s for s in self.statements if not s.startswith("SELECT")]


def _provision(server, user="mcpgateway_app", database="mcpgateway", password="new-password"):  # pragma: allowlist secret
    with patch.object(provision_shared_db.psycopg, "connect", return_value=server):
        provision_shared_db.provision("postgresql://serveradmin:pw@db.example/postgres?sslmode=require", user, password, database, 23)  # pragma: allowlist secret


PLAIN_ROLE = (101, False, False, False, False, False)


@pytest.mark.parametrize(
    ("description", "server", "user", "database", "reason"),
    [
        (
            "administrator as app role",
            FakeServer(roles={"serveradmin": (1, True, True, True, False, False)}, databases={"otherapp": "otherapp_owner"}),
            "serveradmin",
            "otherapp",
            "administrator role",
        ),
        (
            "privileged existing role",
            FakeServer(roles={"mcpgateway_app": (101, False, True, False, False, False)}, databases={"mcpgateway": "mcpgateway_app"}),
            "mcpgateway_app",
            "mcpgateway",
            "privileged",
        ),
        (
            "existing role owning another app's database",
            FakeServer(roles={"frontdesk_app": PLAIN_ROLE}, databases={"frontdesk": "frontdesk_owner"}),
            "frontdesk_app",
            "frontdesk",
            "belongs to 'frontdesk_owner'",
        ),
        ("existing role without the gateway database", FakeServer(roles={"frontdesk_app": PLAIN_ROLE}), "frontdesk_app", "mcpgateway", "does not exist"),
        ("new role but database already owned elsewhere", FakeServer(databases={"voice_agent": "voice_owner"}), "mcpgateway_app", "voice_agent", "already exists and belongs to 'voice_owner'"),
        ("reserved database", FakeServer(), "mcpgateway_app", "postgres", "reserved"),
        (
            "role that is a member of other roles",
            FakeServer(roles={"mcpgateway_app": PLAIN_ROLE}, databases={"mcpgateway": "mcpgateway_app"}, memberships={101: 1}),
            "mcpgateway_app",
            "mcpgateway",
            "member of 1 other role",
        ),
        (
            "role that also owns another database",
            FakeServer(roles={"mcpgateway_app": PLAIN_ROLE}, databases={"mcpgateway": "mcpgateway_app", "other": "mcpgateway_app"}),
            "mcpgateway_app",
            "mcpgateway",
            "owns 1 other database",
        ),
    ],
)
def test_collisions_are_refused_by_preflight(description, server, user, database, reason):
    with pytest.raises(provision_shared_db.ProvisioningRefused, match=reason):
        provision_shared_db.preflight(server, user, database)
    assert server.mutations == [], f"{description}: preflight changed the server: {server.mutations}"


@requires_psycopg
def test_collision_stops_provision_before_any_change():
    """Astra's probe case: PG_APP_USER is the administrator and PG_DATABASE is another app's database."""
    server = FakeServer(roles={"serveradmin": (1, True, True, True, False, False)}, databases={"otherapp": "otherapp_owner"})
    with pytest.raises(provision_shared_db.ProvisioningRefused, match="administrator role"):
        _provision(server, user="serveradmin", database="otherapp")
    assert server.mutations == []


def test_new_role_and_free_database_pass_preflight():
    assert provision_shared_db.preflight(FakeServer(), "mcpgateway_app", "mcpgateway") is False


def test_owned_role_and_database_pass_preflight():
    server = FakeServer(roles={"mcpgateway_app": PLAIN_ROLE}, databases={"mcpgateway": "mcpgateway_app"})
    assert provision_shared_db.preflight(server, "mcpgateway_app", "mcpgateway") is True


@requires_psycopg
def test_new_role_and_database_are_created():
    server = FakeServer()
    _provision(server)
    joined = "\n".join(server.mutations)
    assert 'CREATE ROLE "mcpgateway_app" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 23 PASSWORD' in joined
    assert 'CREATE DATABASE "mcpgateway" OWNER "mcpgateway_app"' in joined
    assert 'REVOKE CONNECT ON DATABASE "mcpgateway" FROM PUBLIC' in joined
    assert 'ALTER SCHEMA public OWNER TO "mcpgateway_app"' in joined


@requires_psycopg
def test_rerun_on_owned_database_keeps_password():
    server = FakeServer(roles={"mcpgateway_app": PLAIN_ROLE}, databases={"mcpgateway": "mcpgateway_app"})
    _provision(server, password="")
    joined = "\n".join(server.mutations)
    assert 'ALTER ROLE "mcpgateway_app" WITH LOGIN CONNECTION LIMIT 23' in joined
    assert "PASSWORD" not in joined
    assert "CREATE DATABASE" not in joined


@requires_psycopg
def test_new_role_without_password_is_refused():
    server = FakeServer()
    with pytest.raises(provision_shared_db.ProvisioningRefused, match="no password"):
        _provision(server, password="")
    assert server.mutations == []
