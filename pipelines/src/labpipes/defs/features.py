"""trip_features: one month of model inputs and labels, valid trips only (contracts/features.yaml).

The feature contract check attaches here (feature_check.py): a column that isn't in the contract,
like gameday E1's fare_amount, stops training before it starts.
"""

import dagster as dg

from ..partitions import trip_months
from ..resources import RedshiftData
from ..sql import statements


@dg.asset(partitions_def=trip_months, deps=["stg_trips"], group_name="model", kinds={"redshift"}, pool="redshift")
def trip_features(context: dg.AssetExecutionContext, redshift: RedshiftData) -> dg.MaterializeResult:
    month = context.partition_key
    redshift.execute(*statements("trip_features", month=month))
    rows = redshift.scalar(f"select count(*) from staging.trip_features where trip_month = '{month}'")
    return dg.MaterializeResult(metadata={"rows": dg.MetadataValue.int(int(rows))})
