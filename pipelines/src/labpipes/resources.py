"""Given resources: Redshift through the Data API, and the trip files in the instructor's data bucket.

Both authenticate with whatever the AWS SDK finds: the platform host's instance profile (LabRole)
in production, your exported Learner Lab credentials on a laptop. Neither needs a password.
"""

import json
import re
import time
from dataclasses import dataclass

import boto3
import dagster as dg
import pandas as pd
import pyarrow.dataset as pads
import pyarrow.parquet as pq
from pyarrow import fs

from .contracts import Column
from .partitions import check_month


class RedshiftError(RuntimeError):
    pass


class RedshiftData(dg.ConfigurableResource):
    """Redshift via the Data API, as a named database user with temporary credentials (--db-user).

    execute() with several statements runs them as one transaction in one session
    (batch-execute-statement): a temp table lives across them, and a failure rolls all of them back.
    Batch statements take no bind parameters, so validate anything you format into SQL.
    """

    cluster_id: str
    database: str
    db_user: str
    region: str = "us-east-1"
    poll_seconds: float = 1.0
    timeout_seconds: int = 1800

    def _client(self):
        return boto3.client("redshift-data", region_name=self.region)

    def _target(self) -> dict:
        return {"ClusterIdentifier": self.cluster_id, "Database": self.database, "DbUser": self.db_user}

    def execute(self, *sqls: str) -> str:
        """Run one statement, or several as a single transaction. Returns the statement id."""
        client = self._client()
        if len(sqls) == 1:
            sid = client.execute_statement(Sql=sqls[0], **self._target())["Id"]
        else:
            sid = client.batch_execute_statement(Sqls=list(sqls), **self._target())["Id"]
        self._wait(client, sid)
        return sid

    def query(self, sql: str) -> list[dict]:
        """Run a SELECT and return every row as a dict."""
        client = self._client()
        sid = client.execute_statement(Sql=sql, **self._target())["Id"]
        self._wait(client, sid)
        rows: list[dict] = []
        token = None
        while True:
            page = client.get_statement_result(Id=sid, **({"NextToken": token} if token else {}))
            names = [c["name"] for c in page["ColumnMetadata"]]
            rows += [{n: _field(f) for n, f in zip(names, rec, strict=True)} for rec in page["Records"]]
            token = page.get("NextToken")
            if not token:
                return rows

    def scalar(self, sql: str):
        """First column of the first row, or None."""
        rows = self.query(sql)
        return next(iter(rows[0].values())) if rows else None

    def _wait(self, client, sid: str) -> None:
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            d = client.describe_statement(Id=sid)
            if d["Status"] == "FINISHED":
                return
            if d["Status"] in ("FAILED", "ABORTED"):
                subs = [s["Error"] for s in d.get("SubStatements", []) if s.get("Error")]
                raise RedshiftError(d.get("Error") or (subs[0] if subs else d["Status"]))
            if time.monotonic() > deadline:
                client.cancel_statement(Id=sid)
                raise RedshiftError(f"statement {sid} timed out after {self.timeout_seconds}s")
            time.sleep(self.poll_seconds)


def _field(f: dict):
    """A Data API field ({"longValue": 3}, {"isNull": True}, ...) as a Python value."""
    if f.get("isNull"):
        return None
    return next(iter(f.values()))


TRIP_FILE = re.compile(r"yellow_tripdata_(?P<month>\d{4}-\d{2})\.parquet")


@dataclass(frozen=True)
class TripFile:
    month: str
    key: str
    etag: str
    size: int


@dataclass(frozen=True)
class Footer:
    columns: list[Column]
    num_rows: int


class DataBucket(dg.ConfigurableResource):
    """The instructor's data bucket (runtime.yaml: data). Lists trips/ and reads Parquet footers
    with ranged GETs, so checking a file's schema never downloads the file."""

    bucket: str
    trips_prefix: str = "trips/"
    zones_key: str = "reference/taxi_zone_lookup.csv"
    region: str = "us-east-1"

    def trip_files(self) -> list[TripFile]:
        """Every trip file under trips/, oldest month first."""
        s3 = boto3.client("s3", region_name=self.region)
        found = []
        for page in s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket, Prefix=self.trips_prefix):
            for o in page.get("Contents", []):
                m = TRIP_FILE.fullmatch(o["Key"][len(self.trips_prefix) :])
                if m:
                    found.append(TripFile(m["month"], o["Key"], o["ETag"].strip('"'), o["Size"]))
        return sorted(found, key=lambda f: f.month)

    def trip_uri(self, month: str) -> str:
        return f"s3://{self.bucket}/{self.trips_prefix}yellow_tripdata_{check_month(month)}.parquet"

    def zones_uri(self) -> str:
        return f"s3://{self.bucket}/{self.zones_key}"

    def footer(self, month: str) -> Footer:
        """The Parquet schema and row count of a month's file, from its footer only."""
        s3 = fs.S3FileSystem(region=self.region)
        with s3.open_input_file(self.trip_uri(month).removeprefix("s3://")) as f:
            return read_footer(f)


def read_footer(source) -> Footer:
    """Columns (Parquet storage types, as in contracts/trips.schema.yaml) and row count of a Parquet file."""
    pf = pq.ParquetFile(source)
    schema = pf.schema
    cols = [Column(schema.column(i).name, parquet_type(schema.column(i))) for i in range(len(schema))]
    return Footer(cols, pf.metadata.num_rows)


def parquet_type(col: pq.ColumnSchema) -> str:
    """INT32, INT64, DOUBLE, STRING, TIMESTAMP_MICROS/MILLIS/NANOS, or the bare physical type."""
    logical = str(col.logical_type)
    if col.physical_type == "BYTE_ARRAY" and logical == "String":
        return "STRING"
    if col.physical_type == "INT64" and logical.startswith("Timestamp("):
        unit = re.search(r"timeUnit=(\w+)", logical)
        return {"microseconds": "TIMESTAMP_MICROS", "milliseconds": "TIMESTAMP_MILLIS", "nanoseconds": "TIMESTAMP_NANOS"}.get(
            unit[1] if unit else "", "TIMESTAMP"
        )
    return col.physical_type


class ArtifactBucket(dg.ConfigurableResource):
    """The student's own bucket (runtime.yaml: LAB_ARTIFACT_BUCKET): training sets that Redshift
    UNLOADs, and MLflow's artifacts (under mlflow/, written by the tracking server)."""

    bucket: str
    region: str = "us-east-1"

    def uri(self, key: str) -> str:
        return f"s3://{self.bucket}/{key}"

    def filesystem(self) -> fs.FileSystem:
        return fs.S3FileSystem(region=self.region)

    def read_parquet(self, prefix: str) -> pd.DataFrame:
        """Every Parquet file under a prefix (UNLOAD writes several) as one DataFrame."""
        files = pads.dataset(f"{self.bucket}/{prefix}", filesystem=self.filesystem(), format="parquet")
        return files.to_table().to_pandas()

    def write_json(self, key: str, obj) -> None:
        with self.filesystem().open_output_stream(f"{self.bucket}/{key}") as f:
            f.write(json.dumps(obj, indent=2).encode())

    def read_json(self, key: str):
        with self.filesystem().open_input_stream(f"{self.bucket}/{key}") as f:
            return json.loads(f.read())


class MlflowTracking(dg.ConfigurableResource):
    """The MLflow tracking server (runtime.yaml: MLFLOW_TRACKING_URI). Names come from contracts/mlflow.yaml."""

    tracking_uri: str

    def client(self):
        import mlflow
        from mlflow import MlflowClient

        from .contracts import mlflow_contract

        mlflow.set_tracking_uri(self.tracking_uri)
        mlflow.set_experiment(mlflow_contract()["experiment"])
        return MlflowClient(self.tracking_uri)


# S6: the wiki, the embedding server and the vector store.


class WikiApi(dg.ConfigurableResource):
    """The instructor's ops wiki. Its URL and your token are in Secrets Manager (lab/wiki), read per run."""

    secret_name: str = "lab/wiki"

    def client(self):
        from .wiki import Wiki

        return Wiki.from_secret(self.secret_name)


class LlmEmbed(dg.ConfigurableResource):
    """llama.cpp's embedding server on the LLM host (runtime.yaml: llm-embed, port 8081), OpenAI-style.

    nomic-embed-text-v1.5 expects a task prefix: documents are embedded as "search_document: ...", and the
    app embeds questions as "search_query: ...". Mixing them up quietly ruins retrieval."""

    llm_host: str
    port: int = 8081
    batch: int = 8
    dimensions: int = 768

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        import urllib.request

        out: list[list[float]] = []
        for i in range(0, len(texts), self.batch):
            body = json.dumps({"input": [f"search_document: {t}" for t in texts[i : i + self.batch]], "model": "embed"}).encode()
            req = urllib.request.Request(f"http://{self.llm_host}:{self.port}/v1/embeddings", body, {"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=300) as r:
                data = sorted(json.load(r)["data"], key=lambda d: d["index"])
            out.extend(d["embedding"] for d in data)
        if out and len(out[0]) != self.dimensions:
            raise RuntimeError(f"embedding has {len(out[0])} dimensions, expected {self.dimensions}")
        return out


class RagStore(dg.ConfigurableResource):
    """The `rag` database on RDS (pgvector), as the RDS admin user from Secrets Manager (lab/rds)."""

    database: str = "rag"

    def connect(self):
        import psycopg2  # from dagster-postgres

        from .runtime import storage_env

        env = storage_env()
        conn = psycopg2.connect(host=env["DAGSTER_PG_HOST"], user=env["DAGSTER_PG_USERNAME"], password=env["DAGSTER_PG_PASSWORD"],
                                dbname=self.database, connect_timeout=10)
        return conn
