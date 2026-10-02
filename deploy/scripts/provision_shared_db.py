"""Provision the gateway's login role and database on a shared PostgreSQL server.

Run by ``01-prepare-azure.sh`` with ``uv run --with psycopg``. Inputs come from
environment variables so that no credential appears on a command line:

    PG_ADMIN_URL              admin connection URL (read from Key Vault by the caller)
    PG_APP_USER               gateway login role
    PG_APP_PASSWORD           new password; empty keeps the existing password
    PG_DATABASE               gateway database
    PG_APP_CONNECTION_LIMIT   CONNECTION LIMIT for the role
    PG_ADOPT_EXISTING_ROLE    optional; exact name of a pre-existing gateway role to adopt

Every safety check runs before the first change. The server connection uses
autocommit (``CREATE DATABASE`` cannot run in a transaction), so a check that
failed after a change could not undo it. The script refuses to touch a role or a
database that it cannot prove belongs to the gateway, because the server is shared
with other applications. Proof is an ownership marker on the role (see
``OWNERSHIP_MARKER``); an interrupted run, where the marked role exists but its
database does not, resumes.
"""

# Standard
import os
import re
from typing import Any, NamedTuple, Optional

try:
    # Third-Party
    import psycopg
    from psycopg import sql
except ImportError:  # 01-prepare-azure.sh runs this file with `uv run --with psycopg`
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]

# Written as the role comment in the same transaction as CREATE ROLE. Its presence is
# the only proof that a role on the shared server belongs to the gateway.
OWNERSHIP_MARKER = "mcp-gateway: managed by deploy/scripts/provision_shared_db.py"

RESERVED_DATABASES = frozenset({"postgres", "template0", "template1", "azure_maintenance", "azure_sys"})


class ProvisioningRefused(SystemExit):
    """Raised when a safety check fails; nothing has been changed on the server."""


def _fetchone(cur: Any, query: str, params: tuple = ()) -> Optional[tuple]:
    """Execute a query and return its first row.

    Args:
        cur: psycopg cursor.
        query: SQL text with ``%s`` placeholders.
        params: Query parameters.

    Returns:
        Optional[tuple]: The first row, or ``None``.
    """
    cur.execute(query, params)
    return cur.fetchone()


class Plan(NamedTuple):
    """What ``provision`` must do after preflight passes."""

    role_exists: bool
    database_exists: bool
    adopt: bool


def preflight(cur: Any, user: str, database: str, adopt_role: str = "") -> Plan:
    """Check that the role and database are free or provably belong to the gateway.

    Ownership is proven by ``OWNERSHIP_MARKER``, the role comment written in the same
    transaction as ``CREATE ROLE``. Catalog shape alone cannot prove it: another
    application's ordinary role that owns only its own database looks identical. A
    role created before the marker existed is accepted only when ``adopt_role`` names
    it exactly, and still has to pass every other check.

    Args:
        cur: psycopg cursor on the admin connection.
        user: Gateway login role name.
        database: Gateway database name.
        adopt_role: Exact role name the operator explicitly adopts (``PG_ADOPT_EXISTING_ROLE``).

    Returns:
        Plan: Whether the role and database exist, and whether the role is being adopted.

    Raises:
        ProvisioningRefused: When the names collide with the administrator, a privileged
            role, a reserved database or a role or database the gateway does not own.
    """
    if database in RESERVED_DATABASES:
        raise ProvisioningRefused(f"refusing: database '{database}' is reserved")
    admin = _fetchone(cur, "SELECT current_user")[0]
    if user == admin:
        raise ProvisioningRefused(f"refusing: PG_APP_USER '{user}' is the administrator role")

    role = _fetchone(cur, "SELECT oid, rolsuper, rolcreaterole, rolcreatedb, rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s", (user,))
    owner_row = _fetchone(cur, "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = %s", (database,))
    db_owner = owner_row[0] if owner_row else None

    if role is None:
        if db_owner is not None:
            raise ProvisioningRefused(f"refusing: database '{database}' already exists and belongs to '{db_owner}', not to new role '{user}'")
        return Plan(role_exists=False, database_exists=False, adopt=False)

    role_oid, *privileges = role
    marked = _fetchone(cur, "SELECT shobj_description(%s, 'pg_authid')", (role_oid,))[0] == OWNERSHIP_MARKER
    adopt = not marked and adopt_role == user
    if not marked and not adopt:
        raise ProvisioningRefused(
            f"refusing: role '{user}' exists but was not created by the gateway (no ownership marker); if it is the gateway's own role, set PG_ADOPT_EXISTING_ROLE={user} once to adopt it"
        )
    if any(privileges):
        raise ProvisioningRefused(f"refusing: role '{user}' is privileged (superuser, CREATEROLE, CREATEDB, REPLICATION or BYPASSRLS)")
    memberships = _fetchone(cur, "SELECT count(*) FROM pg_auth_members WHERE member = %s", (role_oid,))[0]
    if memberships:
        raise ProvisioningRefused(f"refusing: role '{user}' is a member of {memberships} other role(s); the gateway role is a member of none")
    if db_owner is not None and db_owner != user:
        raise ProvisioningRefused(f"refusing: database '{database}' belongs to '{db_owner}', not to the gateway role '{user}'")
    other_dbs = _fetchone(cur, "SELECT count(*) FROM pg_database WHERE datdba = %s AND datname <> %s", (role_oid, database))[0]
    if other_dbs:
        raise ProvisioningRefused(f"refusing: role '{user}' also owns {other_dbs} other database(s)")
    # A marked role without its database is an interrupted earlier run: resume it.
    return Plan(role_exists=True, database_exists=db_owner is not None, adopt=adopt)


def provision(admin_url: str, user: str, password: str, database: str, limit: int, adopt_role: str = "") -> None:
    """Create or update the gateway role and database after the safety checks pass.

    Args:
        admin_url: Admin connection URL.
        user: Gateway login role name.
        password: New password, or empty to keep the existing one.
        database: Gateway database name.
        limit: CONNECTION LIMIT for the role.
        adopt_role: Exact role name to adopt when it predates the ownership marker.

    Raises:
        ProvisioningRefused: When a safety check fails, or a new role has no password.
    """
    admin_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql://", admin_url)
    server_url = admin_url.split("?", 1)[0].rpartition("/")[0]
    query = admin_url.partition("?")[2]

    with psycopg.connect(admin_url, autocommit=True, connect_timeout=15) as conn:
        cur = conn.cursor()
        plan = preflight(cur, user, database, adopt_role)
        if not plan.role_exists and not password:
            raise ProvisioningRefused(f"refusing: role '{user}' does not exist and no password was supplied")

        # Role changes and the ownership marker commit together, so a role never exists
        # without the marker that later runs rely on to recognise it.
        with conn.transaction():
            # Privilege flags are set on CREATE only: restating NOSUPERUSER in ALTER ROLE needs superuser.
            verb, attributes = ("ALTER", "LOGIN") if plan.role_exists else ("CREATE", "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
            statement = sql.SQL("{} ROLE {} WITH {} CONNECTION LIMIT {}").format(sql.SQL(verb), sql.Identifier(user), sql.SQL(attributes), sql.Literal(limit))
            if password:
                statement = sql.SQL("{} PASSWORD {}").format(statement, sql.Literal(password))
            cur.execute(statement)
            cur.execute(sql.SQL("COMMENT ON ROLE {} IS {}").format(sql.Identifier(user), sql.Literal(OWNERSHIP_MARKER)))
            cur.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(sql.Identifier(user)))
        action = "adopted" if plan.adopt else ("altered" if plan.role_exists else "created")
        print(f"  role {user}: {action}, connection limit {limit}" + ("" if password else ", password unchanged"))

        if plan.database_exists:
            print(f"  database {database}: already exists")
        else:
            # CREATE DATABASE cannot run inside a transaction block.
            cur.execute(sql.SQL("CREATE DATABASE {} OWNER {}").format(sql.Identifier(database), sql.Identifier(user)))
            print(f"  database {database}: created")
        cur.execute(sql.SQL("REVOKE CONNECT ON DATABASE {} FROM PUBLIC").format(sql.Identifier(database)))
        cur.execute(sql.SQL("GRANT CONNECT ON DATABASE {} TO {}").format(sql.Identifier(database), sql.Identifier(user)))

    # Azure's template database leaves schema public owned by azure_pg_admin, so the
    # database owner cannot create tables there until it owns the schema.
    database_url = f"{server_url}/{database}" + (f"?{query}" if query else "")
    with psycopg.connect(database_url, autocommit=True, connect_timeout=15) as conn:
        conn.execute(sql.SQL("ALTER SCHEMA public OWNER TO {}").format(sql.Identifier(user)))
        print(f"  schema public: owned by {user}")


if __name__ == "__main__":
    provision(
        admin_url=os.environ["PG_ADMIN_URL"],
        user=os.environ["PG_APP_USER"],
        password=os.environ.get("PG_APP_PASSWORD", ""),
        database=os.environ["PG_DATABASE"],
        limit=int(os.environ["PG_APP_CONNECTION_LIMIT"]),
        adopt_role=os.environ.get("PG_ADOPT_EXISTING_ROLE", ""),
    )
