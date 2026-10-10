"""zone_hour_stats: trip counts and duration percentiles per pickup zone and hour, over every month.

It's unpartitioned and rebuilt in full; include it in the ingest run so a month that fails a blocking
check upstream never reaches the mart. The table's DDL is the frozen contract in contracts/marts.sql.
"""

import dagster as dg

from ..contracts import marts_ddl
from ..resources import RedshiftData
from ..sql import statements


@dg.asset(deps=["stg_trips", "taxi_zones"], group_name="marts", kinds={"redshift"}, pool="redshift")
def zone_hour_stats(redshift: RedshiftData) -> dg.MaterializeResult:
    redshift.execute("create schema if not exists marts", *marts_ddl(), *statements("zone_hour_stats"))
    s = redshift.query(
        "select count(*) as rows, count(distinct pickup_zone_id) as zones, min(first_month) as first_month, "
        "max(last_month) as last_month from marts.zone_hour_stats"
    )[0]
    return dg.MaterializeResult(
        metadata={
            "rows": dg.MetadataValue.int(int(s["rows"])),
            "zones": dg.MetadataValue.int(int(s["zones"])),
            "months": f"{s['first_month']}..{s['last_month']}",
        }
    )
