"""Fakes for the two resources, so tests run without AWS: a Redshift that records SQL and answers
canned queries, and a data bucket backed by local Parquet files."""

import io
import re
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from labpipes.contracts import Column, trips_schema
from labpipes.resources import ArtifactBucket, DataBucket, Footer, RedshiftData, TripFile, read_footer

ARROW = {
    "INT32": pa.int32(),
    "INT64": pa.int64(),
    "DOUBLE": pa.float64(),
    "STRING": pa.string(),
    "TIMESTAMP_MICROS": pa.timestamp("us"),
}


def parquet_bytes(columns: list[Column], rows: int = 3) -> bytes:
    """A small Parquet file with exactly these column names and storage types."""
    arrays = [pa.array([None] * rows, type=ARROW[c.type]) for c in columns]
    buf = io.BytesIO()
    pq.write_table(pa.table(arrays, names=[c.name for c in columns]), buf)
    return buf.getvalue()


def schema_2025() -> list[Column]:
    """2025-01 onwards: cbd_congestion_fee appended (E4a)."""
    return trips_schema() + [Column("cbd_congestion_fee", "DOUBLE")]


def schema_2023() -> list[Column]:
    """2023-01: types the contract doesn't allow (E8), and the old airport_fee casing."""
    changed = {"VendorID": "INT64", "passenger_count": "DOUBLE", "RatecodeID": "DOUBLE",
               "PULocationID": "INT64", "DOLocationID": "INT64", "Airport_fee": "DOUBLE"}
    return [Column("airport_fee" if c.name == "Airport_fee" else c.name, changed.get(c.name, c.type)) for c in trips_schema()]


class FakeBucket(DataBucket):
    """files: month -> [etag, [[name, type], ...]] (plain JSON: Dagster serializes resource config)."""

    files: dict = {}

    def trip_files(self) -> list[TripFile]:
        return [TripFile(m, f"trips/yellow_tripdata_{m}.parquet", f[0], 1) for m, f in sorted(self.files.items())]

    def footer(self, month: str) -> Footer:
        cols = [Column(n, t) for n, t in self.files[month][1]]
        return read_footer(pa.BufferReader(parquet_bytes(cols)))


LOG: list[str] = []  # every statement any FakeRedshift ran (runs rebuild resources from config)


class FakeRedshift(RedshiftData):
    """Records every statement in LOG; answers counts with `rows` and rate queries with zeros."""

    rows: int = 3

    def execute(self, *sqls: str) -> str:
        LOG.extend(sqls)
        return "fake"

    def query(self, sql: str) -> list[dict]:
        LOG.append(sql)
        if "group by trip_month" in sql:
            return [{"trip_month": "2024-01", "n": self.rows}]
        if "nonpositive_duration" in sql:
            return [{"rows": self.rows, "nonpositive_duration": 0, "over_3h": 0, "null_passengers": 0, "unknown_zone": 0}]
        if "as extra" in sql:
            return [{"rows": self.rows, "extra": 0}]
        if "from marts.zone_hour_stats" in sql:
            return [{"rows": 1, "zones": 1, "first_month": "2024-01", "last_month": "2024-01"}]
        if re.search(r"select count\(\*\)", sql):
            return [{"count": self.rows}]
        return []


def fake_redshift(**kw) -> FakeRedshift:
    LOG.clear()
    return FakeRedshift(cluster_id="lab", database="lab", db_user="labadmin", **kw)


def fake_bucket(files: dict) -> FakeBucket:
    """files: month -> (etag, list of Column)."""
    plain = {m: [etag, [[c.name, c.type] for c in cols]] for m, (etag, cols) in files.items()}
    return FakeBucket(bucket="data", files=plain)


class LocalArtifacts(ArtifactBucket):
    """The artifact bucket as a local directory: `bucket` is a folder under `root`."""

    root: str

    def filesystem(self):
        from pyarrow import fs

        return fs.SubTreeFileSystem(self.root, fs.LocalFileSystem())


def synthetic_trips(months: list[str], rows_per_month: int = 4000, seed: int = 0):
    """Trips whose duration depends on distance and on weekday rush hours, which the v1 baseline
    (zone pair x hour medians) can't see but LightGBM can."""
    import numpy as np
    import pandas as pd

    rng = np.random.default_rng(seed)
    frames = []
    for m in months:
        n = rows_per_month
        pick, drop = rng.integers(1, 21, n), rng.integers(1, 21, n)
        hour, dow = rng.integers(0, 24, n), rng.integers(0, 7, n)
        dist = 0.6 * np.abs(pick - drop) + 1 + rng.random(n)
        rush = ((dow >= 1) & (dow <= 5) & np.isin(hour, [7, 8, 9, 16, 17, 18])).astype(float)
        dur = 3 * dist + 12 * rush + rng.normal(0, 1.5, n)
        frames.append(pd.DataFrame({"trip_month": m, "pickup_zone_id": pick, "dropoff_zone_id": drop, "pickup_hour": hour,
                                    "pickup_dow": dow, "duration_min": np.clip(dur, 0.5, 170), "trip_distance": dist}))
    return pd.concat(frames, ignore_index=True)


class UnloadingRedshift(FakeRedshift):
    """A fake Redshift whose UNLOADs write synthetic trips into a LocalArtifacts root."""

    root: str
    months: list = ["2024-01", "2024-02", "2024-03", "2024-04"]

    def execute(self, *sqls: str) -> str:
        import pyarrow as pa
        import pyarrow.parquet as pq

        LOG.extend(sqls)
        for sql in sqls:
            m = re.search(r"to 's3://([^']+)'", sql)
            if not sql.startswith("unload") or not m:
                continue
            trips = synthetic_trips(self.months)
            window = re.findall(r"''(\d{4}-\d{2})''", sql)
            df = trips[trips.trip_month.isin(window)]
            if "median(trip_distance)" in sql:
                df = df.groupby(["pickup_zone_id", "dropoff_zone_id"])["trip_distance"].median().rename("est_distance_miles").reset_index()
            else:
                df = df[["pickup_zone_id", "dropoff_zone_id", "pickup_hour", "pickup_dow", "duration_min"]]
            out = Path(self.root) / m.group(1)
            out.mkdir(parents=True, exist_ok=True)
            pq.write_table(pa.Table.from_pandas(df, preserve_index=False), out / "part_0000_part_00.parquet")
        return "fake"

    def query(self, sql: str) -> list[dict]:
        LOG.append(sql)
        if "select distinct trip_month" in sql:
            return [{"trip_month": m} for m in self.months]
        if "as train" in sql:
            return [{"train": 12000, "holdout": 4000}]
        if "from ingest.taxi_zones" in sql:
            return [{"location_id": z, "borough": "Manhattan" if z <= 10 else "Queens"} for z in range(1, 21)]
        return super().query(sql)


def unloading_redshift(root: str) -> UnloadingRedshift:
    LOG.clear()
    return UnloadingRedshift(cluster_id="lab", database="lab", db_user="labadmin", root=root)
