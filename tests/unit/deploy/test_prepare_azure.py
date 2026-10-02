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
from contextlib import contextmanager
import importlib.util
from pathlib import Path
import re
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
# Shared PostgreSQL: prove ownership before any change, resume interrupted runs
# --------------------------------------------------------------------------- #

MARK = provision_shared_db.OWNERSHIP_MARKER
PLAIN_ROLE = (101, False, False, False, False, False)


class FakeServer:
    """Stateful psycopg stand-in: answers catalog queries and applies role/database DDL."""

    def __init__(self, admin="serveradmin", roles=None, databases=None, memberships=None, comments=None, fail_create_database=False):
        self.admin = admin
        self.roles = dict(roles or {})  # name -> (oid, super, createrole, createdb, replication, bypassrls)
        self.databases = dict(databases or {})  # name -> owner name
        self.memberships = dict(memberships or {})  # oid -> count
        self.comments = dict(comments or {})  # role oid -> comment
        self.fail_create_database = fail_create_database
        self.statements = []
        self._row = None

    # connection protocol
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def cursor(self):
        return self

    @contextmanager
    def transaction(self):
        self.statements.append("BEGIN")
        yield
        self.statements.append("COMMIT")

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
            self._row = tuple(role) if role else None
        elif "shobj_description" in text:
            self._row = (self.comments.get(params[0]),)
        elif "pg_get_userbyid(datdba)" in text:
            owner = self.databases.get(params[0])
            self._row = (owner,) if owner else None
        elif "FROM pg_auth_members" in text:
            self._row = (self.memberships.get(params[0], 0),)
        elif "WHERE datdba" in text:
            oid, name = params
            owner_name = next((n for n, r in self.roles.items() if r[0] == oid), None)
            self._row = (sum(1 for db, owner in self.databases.items() if owner == owner_name and db != name),)
        elif text.startswith("CREATE ROLE"):
            self.roles[re.search(r'CREATE ROLE "([^"]+)"', text).group(1)] = (200 + len(self.roles), False, False, False, False, False)
        elif text.startswith("COMMENT ON ROLE"):
            name = re.search(r'COMMENT ON ROLE "([^"]+)"', text).group(1)
            self.comments[self.roles[name][0]] = MARK if MARK in text else text
        elif text.startswith("CREATE DATABASE"):
            if self.fail_create_database:
                raise RuntimeError("simulated CREATE DATABASE failure")
            database, owner = re.search(r'CREATE DATABASE "([^"]+)" OWNER "([^"]+)"', text).groups()
            self.databases[database] = owner
        return self

    @property
    def mutations(self):
        return [s for s in self.statements if not s.startswith("SELECT")]


def _gateway_server(**overrides):
    """A server where the gateway's marked role owns its database."""
    kwargs = {"roles": {"mcpgateway_app": PLAIN_ROLE}, "databases": {"mcpgateway": "mcpgateway_app"}, "comments": {101: MARK}}
    kwargs.update(overrides)
    return FakeServer(**kwargs)


def _provision(server, user="mcpgateway_app", database="mcpgateway", password="new-password", adopt_role=""):  # pragma: allowlist secret
    with patch.object(provision_shared_db.psycopg, "connect", return_value=server):
        provision_shared_db.provision("postgresql://serveradmin:pw@db.example/postgres?sslmode=require", user, password, database, 23, adopt_role)  # pragma: allowlist secret


@pytest.mark.parametrize(
    ("description", "server", "user", "database", "adopt_role", "reason"),
    [
        (
            "administrator as app role",
            FakeServer(roles={"serveradmin": (1, True, True, True, False, False)}, databases={"otherapp": "otherapp_owner"}),
            "serveradmin",
            "otherapp",
            "",
            "administrator role",
        ),
        (
            "another app's ordinary role owning only its database",
            FakeServer(roles={"frontdesk_app": PLAIN_ROLE}, databases={"frontdesk": "frontdesk_app"}),
            "frontdesk_app",
            "frontdesk",
            "",
            "not created by the gateway",
        ),
        ("unmarked role without the gateway database", FakeServer(roles={"frontdesk_app": PLAIN_ROLE}), "frontdesk_app", "mcpgateway", "", "not created by the gateway"),
        (
            "adoption naming a different role",
            FakeServer(roles={"frontdesk_app": PLAIN_ROLE}, databases={"frontdesk": "frontdesk_app"}),
            "frontdesk_app",
            "frontdesk",
            "mcpgateway_app",
            "not created by the gateway",
        ),
        ("adoption of a privileged role", FakeServer(roles={"ops": (101, False, True, False, False, False)}, databases={"ops": "ops"}), "ops", "ops", "ops", "privileged"),
        ("new role but database already owned elsewhere", FakeServer(databases={"voice_agent": "voice_owner"}), "mcpgateway_app", "voice_agent", "", "already exists and belongs to 'voice_owner'"),
        ("reserved database", FakeServer(), "mcpgateway_app", "postgres", "", "reserved"),
        ("marked role that is privileged", _gateway_server(roles={"mcpgateway_app": (101, False, True, False, False, False)}), "mcpgateway_app", "mcpgateway", "", "privileged"),
        ("marked role that is a member of other roles", _gateway_server(memberships={101: 1}), "mcpgateway_app", "mcpgateway", "", "member of 1 other role"),
        (
            "marked role that also owns another database",
            _gateway_server(databases={"mcpgateway": "mcpgateway_app", "other": "mcpgateway_app"}),
            "mcpgateway_app",
            "mcpgateway",
            "",
            "owns 1 other database",
        ),
        ("marked role but database owned by another role", _gateway_server(databases={"mcpgateway": "someone_else"}), "mcpgateway_app", "mcpgateway", "", "belongs to 'someone_else'"),
    ],
)
def test_collisions_are_refused_by_preflight(description, server, user, database, adopt_role, reason):
    with pytest.raises(provision_shared_db.ProvisioningRefused, match=reason):
        provision_shared_db.preflight(server, user, database, adopt_role)
    assert server.mutations == [], f"{description}: preflight changed the server: {server.mutations}"


def test_new_role_and_free_database_pass_preflight():
    assert provision_shared_db.preflight(FakeServer(), "mcpgateway_app", "mcpgateway") == (False, False, False)


def test_marked_role_with_its_database_passes_preflight():
    assert provision_shared_db.preflight(_gateway_server(), "mcpgateway_app", "mcpgateway") == (True, True, False)


def test_marked_role_without_database_resumes():
    """An interrupted run left the marked role but no database: preflight allows resuming."""
    server = _gateway_server(databases={})
    assert provision_shared_db.preflight(server, "mcpgateway_app", "mcpgateway") == (True, False, False)


def test_explicit_adoption_of_unmarked_gateway_role():
    server = FakeServer(roles={"mcpgateway_app": PLAIN_ROLE}, databases={"mcpgateway": "mcpgateway_app"})
    assert provision_shared_db.preflight(server, "mcpgateway_app", "mcpgateway", adopt_role="mcpgateway_app") == (True, True, True)


@requires_psycopg
def test_collision_stops_provision_before_any_change():
    """Review case: another application's ordinary role that owns only its own database."""
    server = FakeServer(roles={"frontdesk_app": PLAIN_ROLE}, databases={"frontdesk": "frontdesk_app"})
    with pytest.raises(provision_shared_db.ProvisioningRefused, match="not created by the gateway"):
        _provision(server, user="frontdesk_app", database="frontdesk")
    assert server.mutations == []


@requires_psycopg
def test_new_role_is_created_with_marker_in_one_transaction():
    server = FakeServer()
    _provision(server)
    begin, commit = server.statements.index("BEGIN"), server.statements.index("COMMIT")
    in_tx = server.statements[begin:commit]
    assert any(s.startswith('CREATE ROLE "mcpgateway_app" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE CONNECTION LIMIT 23 PASSWORD') for s in in_tx)
    assert any(s.startswith('COMMENT ON ROLE "mcpgateway_app" IS') and MARK in s for s in in_tx)
    after = server.statements[commit:]
    assert 'CREATE DATABASE "mcpgateway" OWNER "mcpgateway_app"' in after
    assert 'REVOKE CONNECT ON DATABASE "mcpgateway" FROM PUBLIC' in after
    assert 'ALTER SCHEMA public OWNER TO "mcpgateway_app"' in after


@requires_psycopg
def test_interrupted_run_resumes_on_next_run():
    """CREATE DATABASE fails after the role commits; the next run finishes the job."""
    server = FakeServer(fail_create_database=True)
    with pytest.raises(RuntimeError, match="simulated CREATE DATABASE failure"):
        _provision(server)
    assert "mcpgateway_app" in server.roles and server.comments[server.roles["mcpgateway_app"][0]] == MARK
    assert "mcpgateway" not in server.databases

    server.fail_create_database = False
    _provision(server)
    assert server.databases["mcpgateway"] == "mcpgateway_app"


@requires_psycopg
def test_rerun_on_marked_role_keeps_password():
    server = _gateway_server()
    _provision(server, password="")
    joined = "\n".join(server.mutations)
    assert 'ALTER ROLE "mcpgateway_app" WITH LOGIN CONNECTION LIMIT 23' in joined
    assert "PASSWORD" not in joined
    assert "CREATE DATABASE" not in joined


@requires_psycopg
def test_adoption_writes_the_marker():
    server = FakeServer(roles={"mcpgateway_app": PLAIN_ROLE}, databases={"mcpgateway": "mcpgateway_app"})
    _provision(server, password="", adopt_role="mcpgateway_app")
    assert server.comments[101] == MARK


@requires_psycopg
def test_new_role_without_password_is_refused():
    server = FakeServer()
    with pytest.raises(provision_shared_db.ProvisioningRefused, match="no password"):
        _provision(server, password="")
    assert server.mutations == []
