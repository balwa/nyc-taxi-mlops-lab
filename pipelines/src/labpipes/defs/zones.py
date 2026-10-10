"""taxi_zones: the TLC zone lookup, copied whole from the data bucket into ingest.taxi_zones."""

import dagster as dg

from ..resources import DataBucket, RedshiftData


@dg.asset(group_name="ingest", kinds={"redshift"}, pool="redshift")
def taxi_zones(redshift: RedshiftData, data_bucket: DataBucket) -> dg.MaterializeResult:
    """Zone id -> borough and zone name. Static, small, and reloaded in full (one transaction)."""
    redshift.execute(
        "create schema if not exists ingest",
        "create table if not exists ingest.taxi_zones ("
        "location_id integer not null, borough varchar(32), zone varchar(64), service_zone varchar(32))",
        "delete from ingest.taxi_zones",
        f"copy ingest.taxi_zones from '{data_bucket.zones_uri()}' iam_role default format as csv ignoreheader 1",
    )
    rows = redshift.scalar("select count(*) from ingest.taxi_zones")
    return dg.MaterializeResult(metadata={"rows": dg.MetadataValue.int(int(rows)), "source": data_bucket.zones_uri()})
