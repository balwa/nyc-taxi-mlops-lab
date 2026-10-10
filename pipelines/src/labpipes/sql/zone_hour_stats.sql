-- marts.zone_hour_stats, rebuilt in full from every month in staging (one transaction).
-- The DDL is contracts/marts.sql and runs first. Valid trips only: 0 < duration <= 3 h, known zones.
delete from marts.zone_hour_stats;
insert into marts.zone_hour_stats
select s.pickup_zone_id, coalesce(z.zone, 'Unknown'), z.borough, s.pickup_hour,
       count(*),
       percentile_cont(0.5) within group (order by s.duration_min),
       percentile_cont(0.9) within group (order by s.duration_min),
       min(s.trip_month), max(s.trip_month), getdate()
from staging.stg_trips s
left join ingest.taxi_zones z on z.location_id = s.pickup_zone_id
where s.duration_min > 0 and s.duration_min <= 180 and s.pickup_zone_id between 1 and 263
group by s.pickup_zone_id, z.zone, z.borough, s.pickup_hour;
