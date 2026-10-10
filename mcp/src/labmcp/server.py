"""MCP server for the support assistant (S7): contracts/mcp-tools.json's tools over Streamable HTTP
(runtime.yaml: mcp, port 8002, path /mcp). get_model_info is given; predict_duration and
query_zone_stats are yours.

  get_model_info     serving-champion's /model, through Traefik's serving entrypoint
  predict_duration   zone names -> TLC zone ids -> serving-champion's /predict
  query_zone_stats   marts.zone_hour_stats through the Redshift Data API, as a read-only database user

Settings: SERVING_URL (http://traefik:8001), REDSHIFT_CLUSTER_ID, REDSHIFT_DATABASE, MCP_DB_USER (the
read-only user; never labadmin). AWS credentials are the app host's instance profile (LabRole).
A tool that fails raises; the client sees an error result with the message, never a stack trace.
"""

from __future__ import annotations

import csv
import difflib
import os
import time
from functools import cache
from importlib.resources import files
from typing import Annotated, Literal

import boto3
import httpx
from mcp.server.fastmcp import FastMCP
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

SERVING_URL = os.environ.get("SERVING_URL", "http://traefik:8001")
DB_USER = os.environ.get("MCP_DB_USER", "lab_ro")
DAYS = ["sunday", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday"]  # index = pickup_dow (features.yaml)
METRICS = ("trip_count", "median_duration_min", "p90_duration_min")

mcp = FastMCP("lab", host="0.0.0.0", port=8002, stateless_http=True, json_response=True,
              instructions="Tools for a NYC ride-hailing support assistant: the serving model, trip predictions, zone statistics.")


@cache
def zones() -> dict[str, int]:
    """TLC zone name (lower case) -> LocationID, from the bundled taxi_zone_lookup.csv."""
    with files("labmcp").joinpath("taxi_zone_lookup.csv").open() as f:
        return {row["Zone"].strip().lower(): int(row["LocationID"]) for row in csv.DictReader(f) if row["Zone"] not in ("", "N/A")}


def zone_id(name: str) -> int:
    key = name.strip().lower()
    if key in zones():
        return zones()[key]
    close = difflib.get_close_matches(key, zones(), n=3, cutoff=0.6)
    raise ValueError(f"unknown TLC zone {name!r}" + (f"; did you mean {', '.join(repr(c) for c in close)}?" if close else ""))


async def champion(method: str, path: str, body: dict | None = None) -> dict:
    """Call serving-champion through Traefik, pinned by header (so S8's canary weights never pick the model)."""
    async with httpx.AsyncClient(timeout=5) as client:
        r = await client.request(method, f"{SERVING_URL}{path}", json=body, headers={"X-Lab-Alias": "champion"})
    if r.status_code != 200:
        raise ValueError(f"serving answered {r.status_code}: {r.text[:200]}")
    return r.json()


class Warehouse:
    """Redshift through the Data API as DB_USER. Named parameters only: nothing from a tool call is ever
    formatted into SQL."""

    def __init__(self, db_user: str = DB_USER):
        self.client = boto3.client("redshift-data", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        self.target = {"ClusterIdentifier": os.environ.get("REDSHIFT_CLUSTER_ID", "lab"),
                       "Database": os.environ.get("REDSHIFT_DATABASE", "lab"), "DbUser": db_user}

    def query(self, sql: str, params: dict[str, object] | None = None, timeout_s: float = 30) -> list[dict]:
        kwargs = {"Parameters": [{"name": k, "value": str(v)} for k, v in params.items()]} if params else {}
        sid = self.client.execute_statement(Sql=sql, **self.target, **kwargs)["Id"]
        deadline = time.monotonic() + timeout_s
        while (d := self.client.describe_statement(Id=sid))["Status"] not in ("FINISHED", "FAILED", "ABORTED"):
            if time.monotonic() > deadline:
                self.client.cancel_statement(Id=sid)
                raise ValueError("the warehouse took too long")
            time.sleep(0.3)
        if d["Status"] != "FINISHED":
            raise ValueError(f"warehouse query {d['Status'].lower()}: {d.get('Error', '')[:200]}")
        if not d.get("HasResultSet"):
            return []
        res = self.client.get_statement_result(Id=sid)
        cols = [c["name"] for c in res["ColumnMetadata"]]
        return [dict(zip(cols, (next(iter(v.values())) if not v.get("isNull") else None for v in rec), strict=True)) for rec in res["Records"]]


@mcp.tool(description="Version, training window and evaluation metrics of the model currently serving predictions.")
async def get_model_info() -> dict:
    m = await champion("GET", "/model")
    tags = m.get("tags", {})
    return {"name": m["name"], "version": m["version"], "alias": m["alias"], "loaded_at": m["loaded_at"],
            **{k: tags.get(k) for k in ("training_window", "holdout_month", "features_version", "mae_min", "p95_latency_ms")}}


Zone = Annotated[str, Field(description="TLC taxi zone name, e.g. 'JFK Airport' or 'Times Sq/Theatre District'.")]
Hour = Annotated[int, Field(ge=0, le=23, description="Pickup hour, 24h clock, New York local time.")]
Day = Literal["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
Metric = Literal["trip_count", "median_duration_min", "p90_duration_min"]


@mcp.tool(description="Predict the duration in minutes of a yellow-taxi trip between two NYC TLC taxi zones, using the champion model.")
async def predict_duration(pickup_zone: Zone, dropoff_zone: Zone, hour: Hour, day_of_week: Day) -> dict:
    raise NotImplementedError("S7: predict_duration isn't built yet")


@mcp.tool(description="Historical trip statistics for one pickup zone from the zone_hour_stats mart.")
def query_zone_stats(zone: Zone, metric: Metric, hour: Annotated[int | None, Field(ge=0, le=23, description="Optional: restrict to one pickup hour.")] = None) -> dict:
    raise NotImplementedError("S7: query_zone_stats isn't built yet")


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request: Request) -> JSONResponse:
    """Liveness; with ?db=1 also what the database user may do (the status workflow shows it to the grader)."""
    out: dict[str, object] = {"status": "ok", "db_user": DB_USER, "tools": [t.name for t in await mcp.list_tools()]}
    if request.query_params.get("db"):
        try:
            row = Warehouse().query(
                "select has_table_privilege(current_user, 'marts.zone_hour_stats', 'select') as read_marts,"
                " has_table_privilege(current_user, 'marts.zone_hour_stats', 'insert') as write_marts,"
                " has_schema_privilege(current_user, 'ingest', 'usage') as use_ingest,"
                " has_schema_privilege(current_user, 'marts', 'create') as create_in_marts")[0]
            out["db"] = {k: v in (True, "true", "t") for k, v in row.items()}
        except Exception as e:  # noqa: BLE001 - report it, don't fail the health check
            out["db"] = {"error": f"{type(e).__name__}: {e}"[:200]}
    return JSONResponse(out)


def main() -> None:
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
