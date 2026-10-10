-- staging.stg_trips for one month: typed, named and with a duration, but NOT filtered.
-- Bad rows (negative durations, unknown zones, duplicates) stay here so the data-quality checks
-- can see them; trip_features (S2) decides what training excludes.
-- {month} and {file} are substituted after validation (batch statements take no parameters).
create schema if not exists staging;
create table if not exists staging.stg_trips (
  trip_month      char(7)          not null,
  source_file     varchar(64)      not null,
  vendor_id       integer,
  pickup_at       timestamp,
  dropoff_at      timestamp,
  duration_min    double precision,
  pickup_hour     smallint,
  pickup_dow      smallint,          -- 0 = Sunday
  pickup_zone_id  integer,
  dropoff_zone_id integer,
  passenger_count integer,
  trip_distance   double precision,
  ratecode_id     integer,
  payment_type    integer,
  fare_amount     double precision,
  total_amount    double precision
) sortkey (pickup_at);
delete from staging.stg_trips where trip_month = '{month}';
insert into staging.stg_trips
select '{month}', source_file, vendorid, tpep_pickup_datetime, tpep_dropoff_datetime,
       datediff(second, tpep_pickup_datetime, tpep_dropoff_datetime) / 60.0,
       extract(hour from tpep_pickup_datetime), extract(dow from tpep_pickup_datetime),
       pulocationid, dolocationid, passenger_count, trip_distance, ratecodeid, payment_type,
       fare_amount, total_amount
from ingest.raw_trips
where source_file = '{file}';
