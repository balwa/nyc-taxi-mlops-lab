"""Partitions: one per trip file in the data bucket, added by the sensor as files land."""

import re

import dagster as dg

trip_months = dg.DynamicPartitionsDefinition(name="trip_months")

MONTH = re.compile(r"\d{4}-(0[1-9]|1[0-2])")


def check_month(key: str) -> str:
    """Partition keys end up inside SQL text (batch statements take no parameters), so validate them."""
    if not MONTH.fullmatch(key):
        raise ValueError(f"not a YYYY-MM partition key: {key!r}")
    return key


def source_file(month: str) -> str:
    """The file name a month's rows carry in ingest.raw_trips.source_file."""
    return f"yellow_tripdata_{check_month(month)}.parquet"
