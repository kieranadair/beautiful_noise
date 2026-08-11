-- BEAUTIFUL NOISE — poster_gallery_v
--
-- The single read surface for the gallery. get_all_posters() queries this and nothing
-- else, so every column here is part of the app's contract.
--
-- Unlike Snowflake, `CREATE OR REPLACE VIEW` in Postgres replaces the *definition* in
-- place rather than dropping and recreating the object, so grants survive. The warning
-- in CLAUDE.md about re-granting SELECT after a rebuild does not apply here.
--
-- Two translation traps, both silent:
--
--   1. Snowflake's ARRAY_AGG ignores NULLs, so `ARRAY_AGG(CASE WHEN is_headliner THEN
--      band_name END)` yielded just the headliners. Postgres's array_agg KEEPS NULLs, so
--      a literal port would produce [NULL, NULL, 'BAND']. FILTER is the correct form.
--
--   2. array_agg(...) FILTER returns NULL — not an empty array — when nothing matches.
--      get_filtered_posters() iterates HEADLINERS directly, so a NULL would raise
--      TypeError on any poster with no headliners. COALESCE to an empty array keeps the
--      Snowflake behaviour the Python already assumes.
--
-- The CTEs are load-bearing. bands/headliners/supports use non-DISTINCT aggregates over
-- the band_events join, so joining poster_credits or poster_venues directly would
-- multiply those rows and silently duplicate every band. Pre-aggregating to one row per
-- poster first is what prevents the fan-out. This is not hypothetical: posters here
-- reach 12 bands and carry multiple credits and venues.

CREATE OR REPLACE VIEW poster_gallery_v AS
WITH poster_credits_agg AS (
    SELECT pc.poster_id,
           array_agg(cr.credit_name ORDER BY cr.credit_name) AS credits
    FROM poster_credits pc
    JOIN credits cr ON pc.credit_id = cr.credit_id
    GROUP BY pc.poster_id
),
poster_venues_agg AS (
    SELECT pv.poster_id,
           array_agg(vn.venue_name ORDER BY vn.venue_name) AS venues
    FROM poster_venues pv
    JOIN venues vn ON pv.venue_id = vn.venue_id
    GROUP BY pv.poster_id
)
SELECT
    p.poster_id,
    p.file_name,
    e.event_name,
    e.date,
    v.venue_name,
    -- The event's own venue is the fallback for any poster predating poster_venues.
    COALESCE(pva.venues, ARRAY[v.venue_name]) AS venues,
    p.uploaded_at,
    p.md5_hash,
    p.upload_type,
    array_agg(b.band_name ORDER BY b.band_name) AS bands,
    COALESCE(
        array_agg(b.band_name ORDER BY b.band_name) FILTER (WHERE be.is_headliner),
        ARRAY[]::text[]
    ) AS headliners,
    COALESCE(
        array_agg(b.band_name ORDER BY b.band_name) FILTER (WHERE NOT be.is_headliner),
        ARRAY[]::text[]
    ) AS supports,
    COALESCE(pca.credits, ARRAY[]::text[]) AS credits
FROM posters p
JOIN events      e  ON p.event_id = e.event_id
JOIN venues      v  ON e.venue_id = v.venue_id
JOIN band_events be ON e.event_id = be.event_id
JOIN bands       b  ON be.band_id = b.band_id
LEFT JOIN poster_credits_agg pca ON p.poster_id = pca.poster_id
LEFT JOIN poster_venues_agg  pva ON p.poster_id = pva.poster_id
GROUP BY p.poster_id, p.file_name, e.event_name, e.date, v.venue_name,
         p.uploaded_at, p.md5_hash, p.upload_type, pca.credits, pva.venues;
