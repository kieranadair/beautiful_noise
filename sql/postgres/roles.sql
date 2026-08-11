-- BEAUTIFUL NOISE — application role
--
-- Direct port of the Snowflake privilege model, which is settled and should stay that
-- way: the app accepts anonymous uploads, so its credential is the one most likely to
-- leak. It gets SELECT + INSERT and nothing else.
--
-- What is deliberately absent, and why:
--   UPDATE / DELETE — every write in the app is an insert or an upsert. Corrections and
--                     takedowns are applied by hand, by a human, as the owner role.
--   CREATE          — the app never creates objects. Snowpark's save_as_table() looked
--                     like it might; it emitted a plain INSERT when the table existed.
--                     psycopg does not even blur the line.
--   ownership       — nothing here is owned by bn_app.
--
-- __APP_PASSWORD__ is substituted at apply time by sql/postgres/apply.py, which
-- generates it and writes the resulting URL into .env. The password is never chosen by
-- a human and never transcribed, so it cannot leak through a paste.

-- Belt and braces: Postgres 15+ already stops PUBLIC creating objects in `public`, but
-- say it out loud rather than depending on a version default.
REVOKE CREATE ON SCHEMA public FROM PUBLIC;

CREATE ROLE bn_app LOGIN PASSWORD '__APP_PASSWORD__';

GRANT CONNECT ON DATABASE neondb TO bn_app;
GRANT USAGE   ON SCHEMA   public TO bn_app;

-- Tables the app reads and appends to. Enumerated rather than wildcarded: a new table
-- should have to be granted deliberately, not inherit access by existing.
GRANT SELECT, INSERT ON
    bands,
    venues,
    credits,
    events,
    posters,
    band_events,
    poster_venues,
    poster_credits,
    extractions,
    requests
TO bn_app;

-- The gallery's only read surface.
GRANT SELECT ON poster_gallery_v TO bn_app;

-- Identity columns generally do not need a separate sequence grant, but granting it
-- costs nothing and removes a class of "works for the owner, fails for the app" bug.
-- apply.py verifies the real answer by inserting as bn_app rather than trusting this.
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO bn_app;

-- ---------------------------------------------------------------------------
-- NO default privileges, on purpose.
--
-- ALTER DEFAULT PRIVILEGES is Postgres's equivalent of Snowflake's future grants, and it
-- carries the identical audit trap: it does not appear in a role's grant listing, so an
-- audit that only inspects current grants can conclude a role is least-privileged while
-- a standing rule quietly hands it access to every object created from then on.
--
-- We set none. Verify with `\ddp` in psql, or:
--
--   SELECT * FROM pg_default_acl;   -- expect zero rows
--
-- If that ever returns rows for bn_app, something has granted more than this file did.
-- ---------------------------------------------------------------------------
