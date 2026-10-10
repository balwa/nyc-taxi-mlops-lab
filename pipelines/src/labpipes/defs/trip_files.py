"""trip_files: a landed file in the data bucket, seen through its Parquet footer only.

Materializing it records the file's columns and row count; nothing is copied yet. That gives the
blocking schema check (schema_check.py) something to look at *before* raw_trips runs COPY, which maps
Parquet columns by position and fails, or worse loads shifted columns, when the schema has moved.
"""

from dataclasses import asdict

import dagster as dg

from ..partitions import trip_months
from ..resources import DataBucket


@dg.asset(partitions_def=trip_months, group_name="ingest", kinds={"s3", "parquet"})
def trip_files(context: dg.AssetExecutionContext, data_bucket: DataBucket) -> dg.MaterializeResult:
    month = context.partition_key
    footer = data_bucket.footer(month)
    return dg.MaterializeResult(
        metadata={
            "uri": data_bucket.trip_uri(month),
            "num_rows": dg.MetadataValue.int(footer.num_rows),
            "num_columns": dg.MetadataValue.int(len(footer.columns)),
            "columns": dg.MetadataValue.json([asdict(c) for c in footer.columns]),
        }
    )
