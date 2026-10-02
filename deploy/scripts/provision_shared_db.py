"""Provision the gateway's login role and database on a shared PostgreSQL server.

Run by ``01-prepare-azure.sh`` with ``uv run --with psycopg``. Inputs come from
environment variables so that no credential appears on a command line:

    PG_ADMIN_URL              admin connection URL (read from Key Vault by the caller)
    PG_APP_USER               gateway login role
    PG_APP_PASSWORD           new password; empty keeps the existing password
    PG_DATABASE               gateway database
    PG_APP_CONNECTION_LIMIT   CONNECTION LIMIT for the role

Every safety check runs before the first change. The server connection uses
autocommit (``CREATE DATABASE`` cannot run in a transaction), so a check that
failed after a change could not undo it. The script refuses to touch a role or a
database that it cannot prove belongs to the gateway, because the server is shared
with other applications.
"""

# Standard
import os
import re
from typing import Any, Optional

try:
    # Third-Party
    import psycopg
    from psycopg import sql
except ImportError:  # 01-prepare-azure.sh runs this file with `uv run --with psycopg`
    psycopg = None  # type: ignore[assignment]
    sql = None  # type: ignore[assignment]

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


def preflight(cur: Any, user: str, database: str) -> bool:
    """Check that the role and database are free or already belong to the gateway.

    Args:
        cur: psycopg cursor on the admin connection.
        user: Gateway login role name.
        database: Gateway database name.

    Returns:
        bool: ``True`` when the role already exists.

    Raises:
        ProvisioningRefused: When the names collide with the administrator, a privileged
            role, a reserved database or another application's role or database.
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
        return False

    role_oid, *privileges = role
    if any(privileges):
        raise ProvisioningRefused(f"refusing: role '{user}' is privileged (superuser, CREATEROLE, CREATEDB, REPLICATION or BYPASSRLS)")
    memberships = _fetchone(cur, "SELECT count(*) FROM pg_auth_members WHERE member = %s", (role_oid,))[0]
    if memberships:
        raise ProvisioningRefused(f"refusing: role '{user}' is a member of {memberships} other role(s); the gateway role is a member of none")
    if db_owner != user:
        found = f"belongs to '{db_owner}'" if db_owner else "does not exist"
        raise ProvisioningRefused(f"refusing: role '{user}' already exists but database '{database}' {found}; it may belong to another application")
    other_dbs = _fetchone(cur, "SELECT count(*) FROM pg_database WHERE datdba = %s AND datname <> %s", (role_oid, database))[0]
    if other_dbs:
        raise ProvisioningRefused(f"refusing: role '{user}' also owns {other_dbs} other database(s)")
    return True


def provision(admin_url: str, user: str, password: str, database: str, limit: int) -> None:
    """Create or update the gateway role and database after the safety checks pass.

    Args:
        admin_url: Admin connection URL.
        user: Gateway login role name.
        password: New password, or empty to keep the existing one.
        database: Gateway database name.
        limit: CONNECTION LIMIT for the role.

    Raises:
        ProvisioningRefused: When a safety check fails, or a new role has no password.
    """
    admin_url = re.sub(r"^postgres(ql)?(\+\w+)?://", "postgresql://", admin_url)
    server_url = admin_url.split("?", 1)[0].rpartition("/")[0]
    query = admin_url.partition("?")[2]

    with psycopg.connect(admin_url, autocommit=True, connect_timeout=15) as conn:
        cur = conn.cursor()
        role_exists = preflight(cur, user, database)
        if not role_exists and not password:
            raise ProvisioningRefused(f"refusing: role '{user}' does not exist and no password was supplied")

        # Privilege flags are set on CREATE only: restating NOSUPERUSER in ALTER ROLE needs superuser.
        verb, attributes = ("ALTER", "LOGIN") if role_exists else ("CREATE", "LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE")
        statement = sql.SQL("{} ROLE {} WITH {} CONNECTION LIMIT {}").format(sql.SQL(verb), sql.Identifier(user), sql.SQL(attributes), sql.Literal(limit))
        if password:
            statement = sql.SQL("{} PASSWORD {}").format(statement, sql.Literal(password))
        cur.execute(statement)
        print(f"  role {user}: {'altered' if role_exists else 'created'}, connection limit {limit}" + ("" if password else ", password unchanged"))

        cur.execute(sql.SQL("GRANT {} TO CURRENT_USER").format(sql.Identifier(user)))
        if role_exists:
            print(f"  database {database}: already exists")
        else:
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
    )
