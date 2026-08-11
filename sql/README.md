# Schema

```
postgres/schema.sql            tables, constraints, indexes
postgres/poster_gallery_v.sql  the gallery's only read surface
postgres/roles.sql             the bn_app application role and its grants
postgres/apply.py              applies all three, then proves the privilege boundary
```

Build a database from scratch:

```
.venv/bin/python sql/postgres/apply.py
```

Re-check an existing one (after any grant change, or a view rebuild):

```
.venv/bin/python sql/postgres/apply.py --verify-only
```

**These files are applied, not dumped.** The database is built *from* them, so they cannot drift
the way a generated snapshot can. Edit them; there is nothing to regenerate.

**`apply.py` is deliberately not idempotent.** It fails on the first `CREATE` against a database
that already has these objects, rather than silently reconciling. It runs everything in one
transaction, so a failure part-way leaves nothing behind.

---

## Rebuilding from scratch

`apply.py` refuses to run against a populated database. To start clean you must also remove
`bn_app`, and that takes three statements in this order — the obvious two fail:

```sql
DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
REVOKE ALL ON DATABASE neondb FROM bn_app;   -- a database-level grant blocks DROP ROLE
DROP ROLE bn_app;
```

`DROP ROLE` alone reports *"role cannot be dropped because some objects depend on it"* with
`DETAIL: privileges for database neondb`, and the usual remedy — `DROP OWNED BY bn_app` — is itself
refused, because `neondb_owner` is not a member of `bn_app`. Revoking the database grant directly is
the way through.

`apply.py` generates a fresh password for `bn_app` and rewrites `NEON_APP_URL` in `.env`. **Update
the Railway variable to match**, or the next deploy authenticates with a dead password — and
`start.sh` won't catch it, because the variable is present, just wrong.

## The order in `apply.py` is load-bearing

`roles.sql` grants `SELECT` on `poster_gallery_v`, so the view must exist first: schema → view →
roles. Getting this wrong is how the first run failed.

## Three constraints worth understanding before editing

- **`events` uses `UNIQUE NULLS NOT DISTINCT`.** Most gigs have no event name, and Postgres treats
  `NULL != NULL`, so a plain `UNIQUE` would let every unnamed gig at the same venue and date insert
  as a separate event — splitting one lineup across duplicates, silently.
- **The view's CTE structure is load-bearing.** `credits` and `venues` are pre-aggregated to one row
  per poster before the join, because `bands`/`headliners`/`supports` use non-`DISTINCT` aggregates
  over `band_events`; joining the other two directly fans out and duplicates every band.
- **`array_agg(...) FILTER` returns NULL, not `[]`**, when nothing matches. The view `COALESCE`s to
  an empty array because the Python iterates those columns directly.

## The extraction log

`extractions` records one row per AI scan, written before anything is stored and before the user
reviews. Its purpose is a long-term baseline of where the model goes wrong — something you query
occasionally, not machinery the upload path carries.

**The outcome of a scan is derived, never stored.** It isn't known at insert time, and `bn_app` has
no `UPDATE` to set it later. That constraint produced a better design: a derived value cannot drift
from reality.

```sql
select case when not e.is_valid          then 'rejected'
            when p.poster_id is not null then 'saved'
            else 'abandoned' end as outcome,
       e.model, count(*)
from extractions e left join posters p using (scan_id)
group by 1, 2;
```

Accuracy is a join from `e.raw` to the human-confirmed values in `poster_gallery_v` — the review
step produces a labelled dataset for free. `model` is per-row so a model change doesn't blend two
generations into one meaningless average.

## The privilege boundary is verified by exercise

`apply.py` inserts as `bn_app`, then confirms `UPDATE`, `DELETE` and `CREATE TABLE` are all refused,
rather than trusting the `GRANT` statements to read the way they behave.

That matters more than it sounds. An earlier version of the probe used a plain `INSERT` and passed,
while the app issues `INSERT ... ON CONFLICT` — which requires the `UPDATE` privilege `bn_app`
deliberately lacks, and which Postgres checks against the *statement* rather than the path taken.
The check passed; the app could not run. **A verification that doesn't exercise the statement shapes
the app actually issues will happily bless broken code.**

### The future-grants trap

`ALTER DEFAULT PRIVILEGES` is Postgres's equivalent of Snowflake's future grants, and shares its
worst property: it does not show up in a role's grant listing, so an audit that inspects only current
grants can call a role least-privileged while a standing rule quietly hands it every object created
from then on. We set none.

Check with `\ddp` in psql, or `select * from pg_default_acl`. **Neon ships two platform-level
entries of its own** (`cloud_admin` → `neon_superuser`, for tables and sequences) on every database
— so "expect zero rows" is the wrong assertion and will cry wolf forever. Filter for the role you
care about, as `apply.py` does.

## No orphan cleanup, by design

The Snowflake schema had a `CLEANUP_ORPHANED_STAGE_FILES` task because images had to be staged
*before* `AI_COMPLETE` could read them, so rejected, duplicate and abandoned uploads all left files
behind. The Anthropic API takes bytes, so nothing is stored until a human confirms the poster — the
R2 write happens one statement before the row that points at it, inside the same `try` that deletes
the object if the save fails. There is no orphan window worth a scheduled job.

## What is deliberately not here

- **Credentials, connection strings and account identifiers.** This repository is public. The
  application role's password is generated by `apply.py` and written only to `.env`.
- **Data.** Structure only.

The **grant model** *is* here, in `postgres/roles.sql` — see the note in `CLAUDE.md` under
"Postgres and R2 access for schema work" for why that is a deliberate exception.
