-- Marts: what the assistant's MCP tools (S7) and the notebook read. Frozen in S1.
-- Built by the zone_hour_stats asset from staging.stg_trips and ingest.taxi_zones.
-- query_zone_stats (mcp-tools.json) selects one of its metric columns for a zone, optionally by hour.

CREATE TABLE IF NOT EXISTS marts.zone_hour_stats (
  pickup_zone_id      INTEGER          NOT NULL,  -- TLC LocationID, 1..263
  zone                VARCHAR(64)      NOT NULL,  -- taxi_zone_lookup Zone: the name tools are called with
  borough             VARCHAR(32),
  pickup_hour         SMALLINT         NOT NULL,  -- 0..23, local time as recorded by TLC
  trip_count          BIGINT           NOT NULL,
  median_duration_min DOUBLE PRECISION,
  p90_duration_min    DOUBLE PRECISION,
  first_month         CHAR(7)          NOT NULL,  -- YYYY-MM: the months the statistics cover
  last_month          CHAR(7)          NOT NULL,
  refreshed_at        TIMESTAMP        NOT NULL
);
