"""Tests for the given parts of the pipeline. They pass at every stage."""

import importlib
import pkgutil

import dagster as dg
import pyarrow as pa
import pytest
from fakes import parquet_bytes

import labpipes.defs
from labpipes import resources
from labpipes.contracts import marts_ddl, redshift_columns, trips_schema
from labpipes.partitions import check_month, source_file
from labpipes.resources import RedshiftData, RedshiftError, read_footer
from labpipes.sql import statements


def test_definitions_load_with_whatever_this_stage_has(monkeypatch):
    for k in ("REDSHIFT_CLUSTER_ID", "REDSHIFT_DATABASE", "REDSHIFT_DB_USER", "LAB_DATA_BUCKET", "LAB_ARTIFACT_BUCKET", "MLFLOW_TRACKING_URI", "LLM_HOST"):
        monkeypatch.setenv(k, "x")
    for m in pkgutil.iter_modules(labpipes.defs.__path__):
        importlib.import_module(f"labpipes.defs.{m.name}")
    from labpipes.definitions import defs

    dg.Definitions.validate_loadable(defs)
    keys = {k.to_user_string() for k in defs.resolve_asset_graph().get_all_asset_keys()}
    assert {"taxi_zones", "trip_files", "stg_trips", "zone_hour_stats", "trip_features"} <= keys


def test_footer_reads_the_contract_types_back():
    footer = read_footer(pa.BufferReader(parquet_bytes(trips_schema(), rows=5)))
    assert footer.columns == trips_schema()
    assert footer.num_rows == 5


def test_landing_columns_follow_the_contract_in_order():
    cols = redshift_columns(trips_schema())
    assert cols.startswith("vendorid INTEGER, tpep_pickup_datetime TIMESTAMP")
    assert cols.count(",") == len(trips_schema()) - 1


def test_marts_ddl_is_the_contract():
    (ddl,) = marts_ddl()
    assert ddl.startswith("CREATE TABLE IF NOT EXISTS marts.zone_hour_stats")


def test_sql_files_fill_validated_month():
    sqls = statements("stg_trips", month="2024-03", file=source_file("2024-03"))
    assert any("where source_file = 'yellow_tripdata_2024-03.parquet'" in s for s in sqls)
    assert not any("{" in s for s in sqls)
    with pytest.raises(ValueError):
        check_month("2024-03'; drop table x; --")


class StubClient:
    def __init__(self, status="FINISHED", error=None):
        self.status, self.error, self.calls = status, error, []

    def execute_statement(self, **kw):
        self.calls.append(("execute", kw))
        return {"Id": "1"}

    def batch_execute_statement(self, **kw):
        self.calls.append(("batch", kw))
        return {"Id": "2"}

    def describe_statement(self, Id):
        return {"Status": self.status, "Error": self.error}

    def get_statement_result(self, Id, **kw):
        return {"ColumnMetadata": [{"name": "n"}, {"name": "z"}], "Records": [[{"longValue": 7}, {"isNull": True}]]}


def test_redshift_resource_batches_and_reads(monkeypatch):
    client = StubClient()
    monkeypatch.setattr(resources.boto3, "client", lambda *a, **k: client)
    rs = RedshiftData(cluster_id="lab", database="lab", db_user="labadmin", poll_seconds=0)
    rs.execute("select 1")
    rs.execute("begin work", "select 2")
    assert [c[0] for c in client.calls] == ["execute", "batch"]
    assert client.calls[1][1]["DbUser"] == "labadmin" and "SecretArn" not in client.calls[1][1]
    assert rs.query("select 7 as n, null as z") == [{"n": 7, "z": None}]


def test_redshift_resource_raises_the_server_error(monkeypatch):
    monkeypatch.setattr(resources.boto3, "client", lambda *a, **k: StubClient("FAILED", "syntax error at or near raw"))
    rs = RedshiftData(cluster_id="lab", database="lab", db_user="labadmin", poll_seconds=0)
    with pytest.raises(RedshiftError, match="syntax error"):
        rs.execute("create schema raw")


def test_reference_patterns_build():
    import importlib.util
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "reference" / "patterns.py"
    spec = importlib.util.spec_from_file_location("patterns", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    dg.Definitions.validate_loadable(mod.defs)


def test_status_summary_shape():
    from labpipes.status import summarize

    data = {
        "assetNodes": [
            {"assetKey": {"path": ["trip_files"]}, "isPartitioned": True,
             "partitionStats": {"numMaterialized": 4, "numPartitions": 4, "numFailed": 0, "numMaterializing": 0},
             "assetMaterializations": [{"timestamp": "1760000000000", "metadataEntries": [{"label": "rows", "intValue": 7}, {"label": "path"}]}],
             "assetChecksOrError": {"checks": [{"name": "schema_contract", "blocking": True,
                                                "executionForLatestMaterialization": {"status": "SUCCEEDED", "evaluation": {"severity": "ERROR"}}}]}},
            {"assetKey": {"path": ["zone_hour_stats"]}, "isPartitioned": False, "partitionStats": None,
             "assetMaterializations": [], "assetChecksOrError": {"checks": []}},
        ],
        "repositoriesOrError": {"nodes": [{"sensors": [{"name": "trip_files_sensor", "sensorState": {"status": "RUNNING"}}]}]},
        "runsOrError": {"results": [{"status": "SUCCESS"}, {"status": "SUCCESS"}, {"status": "FAILURE"}]},
    }
    s = summarize(data)
    assert s["assets"]["trip_files"]["materialized_partitions"] == 4
    assert s["assets"]["trip_files"]["checks"]["schema_contract"] == {"blocking": True, "status": "SUCCEEDED", "severity": "ERROR"}
    assert s["assets"]["zone_hour_stats"]["last_materialized"] is None
    assert s["assets"]["trip_files"]["last_metadata"] == {"rows": 7}
    assert s["sensors"] == {"trip_files_sensor": "RUNNING"} and s["runs"] == {"SUCCESS": 2, "FAILURE": 1}
    assert "error" in s["infra"]  # off the platform host: no cluster id, no AWS call


def test_status_refuses_an_unloaded_code_location(monkeypatch):
    import io
    import json as _json

    from labpipes import status

    body = {"data": {"assetNodes": [], "repositoriesOrError": {"nodes": []}, "runsOrError": {"results": []}}}
    monkeypatch.setattr(status.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(_json.dumps(body).encode()))
    with pytest.raises(SystemExit, match="not loaded"):
        status.fetch("http://x")
