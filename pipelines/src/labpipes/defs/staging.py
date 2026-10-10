"""stg_trips: one month of raw_trips, typed and with a duration. Data-quality checks attach here."""

import dagster as dg

from ..partitions import source_file, trip_months
from ..resources import RedshiftData
from ..sql import statements


@dg.asset(partitions_def=trip_months, deps=["raw_trips"], group_name="staging", kinds={"redshift"}, pool="redshift")
def stg_trips(context: dg.AssetExecutionContext, redshift: RedshiftData) -> dg.MaterializeResult:
    month = context.partition_key
    redshift.execute(*statements("stg_trips", month=month, file=source_file(month)))
    rows = redshift.scalar(f"select count(*) from staging.stg_trips where trip_month = '{month}'")
    return dg.MaterializeResult(metadata={"rows": dg.MetadataValue.int(int(rows))})
