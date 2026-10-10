"""Pipeline status as JSON: what's loaded, what the checks say, whether the sensor runs.

  python -m labpipes.status [--url http://127.0.0.1:3000]

Read-only: one GraphQL query against the webserver. .github/workflows/status.yaml runs it on the
platform host and uploads the result, which is how the grader sees a pipeline it can't reach.
"""

import argparse
import json
import os
import sys
import time
import urllib.request

QUERY = """{
  assetNodes {
    assetKey { path }
    isPartitioned
    partitionStats { numMaterialized numPartitions numFailed numMaterializing }
    assetMaterializations(limit: 1) { timestamp metadataEntries { label ... on IntMetadataEntry { intValue } ... on FloatMetadataEntry { floatValue } } }
    assetChecksOrError { ... on AssetChecks { checks {
      name blocking
      executionForLatestMaterialization { status evaluation { severity } }
    } } }
  }
  repositoriesOrError { ... on RepositoryConnection { nodes { sensors { name sensorState { status } } } } }
  runsOrError(limit: 200) { ... on Runs { results { status } } }
}"""


def fetch(url: str) -> dict:
    req = urllib.request.Request(f"{url}/graphql", data=json.dumps({"query": QUERY}).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if body.get("errors"):
        raise SystemExit(f"graphql errors: {body['errors']}")
    if not (body["data"].get("repositoriesOrError") or {}).get("nodes"):
        # Right after a host start the webserver answers before the code location has loaded; an
        # empty status would overwrite the last good one, so report nothing instead.
        raise SystemExit("code location not loaded yet")
    return body["data"]


def summarize(data: dict) -> dict:
    assets = {}
    for n in data["assetNodes"]:
        stats = n.get("partitionStats") or {}
        mats = n.get("assetMaterializations") or []
        assets["/".join(n["assetKey"]["path"])] = {
            "partitioned": n["isPartitioned"],
            "materialized_partitions": stats.get("numMaterialized"),
            "partitions": stats.get("numPartitions"),
            "failed_partitions": stats.get("numFailed"),
            "last_materialized": float(mats[0]["timestamp"]) / 1000 if mats else None,
            # Numbers from the last materialization's metadata (S6: did the second wiki run fetch nothing?).
            "last_metadata": {m["label"]: m.get("intValue", m.get("floatValue")) for m in (mats[0].get("metadataEntries") or [])
                              if "intValue" in m or "floatValue" in m} if mats else {},
            "checks": {
                c["name"]: {
                    "blocking": c["blocking"],
                    "status": (c.get("executionForLatestMaterialization") or {}).get("status"),
                    "severity": ((c.get("executionForLatestMaterialization") or {}).get("evaluation") or {}).get("severity"),
                }
                for c in (n.get("assetChecksOrError") or {}).get("checks", [])
            },
        }
    runs: dict[str, int] = {}
    for r in data["runsOrError"]["results"]:
        runs[r["status"]] = runs.get(r["status"], 0) + 1
    sensors = {s["name"]: s["sensorState"]["status"] for repo in data["repositoriesOrError"]["nodes"] for s in repo["sensors"]}
    return {"generated_at": time.time(), "git_sha": os.environ.get("GIT_SHA"), "assets": assets, "sensors": sensors, "runs": runs,
            "mlflow": mlflow_status(), "infra": infra_status()}


def infra_status() -> dict:
    """RDS and Redshift states as LabRole sees them (S4: did the morning restore happen?)."""
    cluster = os.environ.get("REDSHIFT_CLUSTER_ID")
    if not cluster:
        return {"error": "REDSHIFT_CLUSTER_ID not set (not on the platform host)"}
    out = {}
    try:
        import boto3

        rds = boto3.client("rds", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        out["rds"] = rds.describe_db_instances(DBInstanceIdentifier="lab")["DBInstances"][0]["DBInstanceStatus"]
        redshift = boto3.client("redshift", region_name=os.environ.get("AWS_REGION", "us-east-1"))
        out["redshift"] = redshift.describe_clusters(ClusterIdentifier=cluster)["Clusters"][0]["ClusterStatus"]
    except Exception as e:  # status must still report Dagster
        out["error"] = f"{type(e).__name__}: {e}"[:300]
    return out


def mlflow_status() -> dict:
    """The registered model's versions, aliases and the tags contracts/mlflow.yaml requires (S2 on)."""
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        return {"error": "MLFLOW_TRACKING_URI not set"}
    try:
        from mlflow import MlflowClient
        from mlflow.exceptions import MlflowException

        from .contracts import mlflow_contract

        name = mlflow_contract()["registered_model"]
        client = MlflowClient(uri)
        try:
            model = client.get_registered_model(name)
        except MlflowException:
            return {"registered_model": None}
        versions = client.search_model_versions(f"name = '{name}'")
        return {
            "registered_model": name,
            "versions": len(versions),
            "aliases": {alias: str(v) for alias, v in (model.aliases or {}).items()},
            "tags": {str(v.version): dict(v.tags) for v in versions},
        }
    except Exception as e:  # status must still report Dagster if MLflow is down
        return {"error": f"{type(e).__name__}: {e}"[:300]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default="http://127.0.0.1:3000")
    json.dump(summarize(fetch(ap.parse_args().url)), sys.stdout, indent=2, sort_keys=True)
    print()


if __name__ == "__main__":
    main()
