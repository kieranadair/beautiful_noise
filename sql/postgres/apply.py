"""Build the Beautiful Noise schema on a fresh Postgres database.

Applies schema.sql -> poster_gallery_v.sql -> roles.sql as the owner (that order matters:
roles.sql grants SELECT on the view, so the view must already exist), generates bn_app's
password, writes the resulting connection URL into .env, then verifies the privilege
boundary empirically rather than trusting the GRANT statements to mean what they read.

Deliberately not idempotent. On a database that already has these objects it fails on the
first CREATE, which is what you want from something that builds a schema: drift should be
visible, not silently reconciled.

    .venv/bin/python sql/postgres/apply.py                # build, then verify
    .venv/bin/python sql/postgres/apply.py --verify-only  # re-check an existing database
"""

import os
import re
import secrets
import sys
from pathlib import Path

import psycopg
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent.parent
ENV = ROOT / ".env"

load_dotenv(ENV)

# The app connects through the pooler; the owner does DDL over a direct connection,
# because Neon's pooler is PgBouncer in transaction mode and session-scoped work
# (roles, grants, some DDL) wants a real session.
POOLER_HOST_SUFFIX = "-pooler"


def run(cur, label: str, sql: str) -> None:
    print(f"  applying {label} ... ", end="", flush=True)
    cur.execute(sql)
    print("ok")


def app_url_from_admin(admin_url: str, password: str) -> str:
    """Derive bn_app's URL from the owner's: swap user, password, and add -pooler."""
    url = re.sub(r"://[^:]+:[^@]+@", f"://bn_app:{password}@", admin_url, count=1)
    host = re.search(r"@([^/?]+)", url).group(1)
    if POOLER_HOST_SUFFIX not in host:
        ep, _, rest = host.partition(".")
        url = url.replace(host, f"{ep}{POOLER_HOST_SUFFIX}.{rest}", 1)
    return url


def write_env_app_url(url: str) -> None:
    text = ENV.read_text()
    line = f"NEON_APP_URL={url}"
    if re.search(r"^NEON_APP_URL=.*$", text, flags=re.M):
        text = re.sub(r"^NEON_APP_URL=.*$", line, text, flags=re.M)
    else:
        text = text.rstrip("\n") + "\n" + line + "\n"
    ENV.write_text(text)


def verify(app_url: str) -> int:
    """Prove the privilege boundary by exercising it, not by reading the GRANTs."""
    print("\nVerifying the privilege boundary as bn_app ...")
    failures: list[str] = []

    with psycopg.connect(app_url, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("select current_user")
        print(f"  connected as     : {cur.fetchone()[0]}")

        cur.execute("select count(*) from poster_gallery_v")
        print(f"  SELECT view      : ok ({cur.fetchone()[0]} rows)")

        # INSERT must work, including claiming an identity value. This is the real test
        # of whether identity columns need the sequence grant; the GRANT in roles.sql is
        # a guess, this is the answer.
        cur.execute(
            "insert into bands (band_name) values ('__PRIVILEGE PROBE__') returning band_id"
        )
        probe_id = cur.fetchone()[0]
        print(f"  INSERT + identity: ok (band_id {probe_id})")

        for label, sql in [
            ("UPDATE", "update bands set band_name = 'x' where band_id = %s"),
            ("DELETE", "delete from bands where band_id = %s"),
        ]:
            try:
                cur.execute(sql, (probe_id,))
            except psycopg.errors.InsufficientPrivilege:
                print(f"  {label} refused    : ok")
            else:
                failures.append(f"{label} SUCCEEDED as bn_app - it must not")

        try:
            cur.execute("create table __should_not_exist (x int)")
        except psycopg.errors.InsufficientPrivilege:
            print("  CREATE refused   : ok")
        else:
            failures.append("CREATE TABLE SUCCEEDED as bn_app - it must not")

    # Clean up the probe row as owner, since bn_app deliberately cannot delete it.
    with psycopg.connect(os.environ["NEON_ADMIN_URL"], autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("delete from bands where band_name = '__PRIVILEGE PROBE__'")

        # Postgres's future-grants equivalent. The check names bn_app rather than
        # asserting the table is empty: Neon ships two platform-level entries of its own
        # (cloud_admin -> neon_superuser, for tables and sequences) on every database. An
        # "expect zero rows" check would flag those forever, and a check that cries wolf
        # is a check people stop reading.
        cur.execute("""
            select count(*) from pg_default_acl
            where array_to_string(defaclacl, ',') like '%bn_app%'
        """)
        n = cur.fetchone()[0]
        print(f"  future grants    : {n} involving bn_app ({'ok' if n == 0 else 'INVESTIGATE'})")
        if n:
            failures.append("ALTER DEFAULT PRIVILEGES grants bn_app access to future objects")

        cur.execute("""
            select string_agg(distinct privilege_type, ', ' order by privilege_type)
            from information_schema.role_table_grants
            where table_schema = 'public' and grantee = 'bn_app'
        """)
        privs = cur.fetchone()[0]
        print(f"  effective privs  : {privs}")
        if privs != "INSERT, SELECT":
            failures.append(f"bn_app holds {privs}; expected exactly INSERT, SELECT")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print("\nAll checks passed.")
    return 0


def main() -> int:
    if "--verify-only" in sys.argv:
        return verify(os.environ["NEON_APP_URL"])

    password = secrets.token_urlsafe(32)

    print("Applying schema as owner ...")
    admin_url = os.environ["NEON_ADMIN_URL"]
    with psycopg.connect(admin_url, autocommit=False) as conn, conn.cursor() as cur:
        run(cur, "schema.sql", (HERE / "schema.sql").read_text())
        run(cur, "poster_gallery_v.sql", (HERE / "poster_gallery_v.sql").read_text())
        run(cur, "roles.sql", (HERE / "roles.sql").read_text().replace("__APP_PASSWORD__", password))
        conn.commit()

    app_url = app_url_from_admin(admin_url, password)
    write_env_app_url(app_url)
    print(f"\nWrote NEON_APP_URL to {ENV} (password generated, never displayed)")

    return verify(app_url)


if __name__ == "__main__":
    sys.exit(main())
