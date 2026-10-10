#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3", "jsonschema==4.26.0"]
# ///
"""Validate contracts/: structure, internal references, and that nothing frozen has changed.

  tools/check_contracts.py              exit 1 on any problem
  tools/check_contracts.py --write-sums instructor only: refresh contracts/SHA256SUMS

Full OpenAPI validation runs separately (openapi-spec-validator, see the Makefile).
A changed checksum means a frozen contract was edited: stop and explain instead (AGENTS.md rule 3).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError

CONTRACTS = Path(__file__).resolve().parents[1] / "contracts"
SUMS = CONTRACTS / "SHA256SUMS"
NOT_CONTRACTS = {"README.md", "SHA256SUMS"}
SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")
KEBAB = re.compile(r"^[a-z][a-z0-9-]*$")


def contract_files() -> list[Path]:
    return sorted(p for p in CONTRACTS.iterdir() if p.is_file() and p.name not in NOT_CONTRACTS)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def check_sums(errors: list[str]) -> None:
    if not SUMS.exists():
        errors.append("contracts/SHA256SUMS is missing")
        return
    listed = {}
    for line in SUMS.read_text().splitlines():
        if line.strip():
            digest, name = line.split(maxsplit=1)
            listed[name.strip()] = digest
    for p in contract_files():
        if p.name not in listed:
            errors.append(f"{p.name}: not in SHA256SUMS (new contracts are added by the instructor)")
        elif listed[p.name] != sha(p):
            errors.append(f"{p.name}: changed since it was frozen. Don't edit contracts to make checks pass; explain the conflict instead")
    for name in listed:
        if not (CONTRACTS / name).exists():
            errors.append(f"{name}: listed in SHA256SUMS but missing")


def check_schema(schema: dict, where: str, errors: list[str]) -> None:
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as e:
        errors.append(f"{where}: invalid JSON Schema: {e.message}")


OPENAPI_FILES = ("openapi.yaml", "serving-openapi.yaml", "assistant-openapi.yaml")


def check_openapi(errors: list[str]) -> None:
    for f in OPENAPI_FILES:
        if not (CONTRACTS / f).exists():
            continue
        doc = yaml.safe_load((CONTRACTS / f).read_text())
        if not str(doc.get("openapi", "")).startswith("3.1"):
            errors.append(f"{f}: must be OpenAPI 3.1")
        schemas = doc.get("components", {}).get("schemas", {})
        for name, schema in schemas.items():
            check_schema(schema, f"{f} components.schemas.{name}", errors)
        for ref in re.findall(r"#/components/schemas/([A-Za-z0-9_]+)", (CONTRACTS / f).read_text()):
            if ref not in schemas:
                errors.append(f"{f}: $ref to undefined schema {ref}")
        for path, ops in doc.get("paths", {}).items():
            for method, op in ops.items():
                if "operationId" not in op:
                    errors.append(f"{f}: {method.upper()} {path} has no operationId")


def check_serving_matches_features(errors: list[str]) -> None:
    """The serving API takes exactly the model's inputs (features.yaml), with the same ranges."""
    serving = yaml.safe_load((CONTRACTS / "serving-openapi.yaml").read_text())["components"]["schemas"]["PredictRequest"]
    features = yaml.safe_load((CONTRACTS / "features.yaml").read_text())
    want = [c["name"] for c in features["inputs"] + features["derived"]]
    if list(serving["properties"]) != want:
        errors.append(f"serving-openapi.yaml: PredictRequest properties {list(serving['properties'])} aren't features.yaml's inputs {want}")
    for c in features["inputs"]:
        prop = serving["properties"].get(c["name"], {})
        if "range" in c and [prop.get("minimum"), prop.get("maximum")] != c["range"]:
            errors.append(f"serving-openapi.yaml: {c['name']} range differs from features.yaml {c['range']}")


def check_mcp(errors: list[str]) -> None:
    doc = json.loads((CONTRACTS / "mcp-tools.json").read_text())
    names = [t.get("name") for t in doc.get("tools", [])]
    if len(names) != len(set(names)):
        errors.append("mcp-tools.json: duplicate tool names")
    for tool in doc.get("tools", []):
        name = tool.get("name", "?")
        if not SNAKE.match(name or ""):
            errors.append(f"mcp-tools.json: tool name {name!r} is not snake_case")
        if not tool.get("description"):
            errors.append(f"mcp-tools.json: {name} has no description")
        schema = tool.get("inputSchema", {})
        if schema.get("type") != "object":
            errors.append(f"mcp-tools.json: {name}.inputSchema must be an object schema")
        check_schema(schema, f"mcp-tools.json {name}.inputSchema", errors)
        missing = set(schema.get("required", [])) - set(schema.get("properties", {}))
        if missing:
            errors.append(f"mcp-tools.json: {name} requires undefined properties {sorted(missing)}")


def check_runtime(errors: list[str]) -> None:
    doc = yaml.safe_load((CONTRACTS / "runtime.yaml").read_text())
    hosts, services = doc.get("hosts", {}), doc.get("services", {})
    labels = [h.get("runner_label") for h in hosts.values()]
    if len(labels) != len(set(labels)):
        errors.append("runtime.yaml: runner labels must be unique")
    seen: dict[tuple[str, int], str] = {}
    for name, svc in services.items():
        if not KEBAB.match(name):
            errors.append(f"runtime.yaml: service name {name!r} is not kebab-case")
        if svc.get("host") not in hosts:
            errors.append(f"runtime.yaml: service {name} is on unknown host {svc.get('host')!r}")
        key = (svc.get("host"), svc.get("port"))
        if key in seen:
            errors.append(f"runtime.yaml: {name} and {seen[key]} share port {key[1]} on {key[0]}")
        seen[key] = name
        if "image" in svc and not KEBAB.match(svc["image"]):
            errors.append(f"runtime.yaml: image name {svc['image']!r} is not lowercase kebab-case")
    for host, spec in hosts.items():
        for svc in spec.get("runs", []):
            if svc not in services:
                errors.append(f"runtime.yaml: host {host} runs unknown service {svc}")
            elif services[svc]["host"] != host:
                errors.append(f"runtime.yaml: {svc} is listed on {host} but declared on {services[svc]['host']}")
    outs = doc.get("terraform_outputs", [])
    if len(outs) != len(set(outs)) or not all(SNAKE.match(o) for o in outs):
        errors.append("runtime.yaml: terraform_outputs must be unique snake_case names")
    for var in doc.get("env", {}):
        if not re.match(r"^[A-Z][A-Z0-9_]*$", var):
            errors.append(f"runtime.yaml: env var {var} is not UPPER_SNAKE")


PARQUET_TYPES = {"INT32", "INT64", "DOUBLE", "STRING", "TIMESTAMP_MICROS"}


def check_trips_schema(errors: list[str]) -> None:
    doc = yaml.safe_load((CONTRACTS / "trips.schema.yaml").read_text())
    cols = doc.get("columns") or []
    if not cols:
        errors.append("trips.schema.yaml: no columns")
    names = [str(c.get("name", "")).lower() for c in cols]
    if len(names) != len(set(names)):
        errors.append("trips.schema.yaml: duplicate column names (they compare case-insensitively)")
    for c in cols:
        if c.get("type") not in PARQUET_TYPES:
            errors.append(f"trips.schema.yaml: {c.get('name')} has type {c.get('type')!r}, want one of {sorted(PARQUET_TYPES)}")


def mart_columns() -> dict[str, list[str]]:
    """Table name -> column names, from the CREATE TABLE statements in marts.sql."""
    sql = re.sub(r"--[^\n]*", "", (CONTRACTS / "marts.sql").read_text())
    tables = {}
    for name, body in re.findall(r"CREATE TABLE IF NOT EXISTS\s+([a-z_.]+)\s*\((.*?)\);", sql, re.S | re.I):
        tables[name] = [line.split()[0] for line in body.split(",") if line.strip()]
    return tables


def check_platform(errors: list[str]) -> None:
    doc = yaml.safe_load((CONTRACTS / "platform.yaml").read_text())
    wh = doc.get("warehouse", {})
    schemas = set(wh.get("schemas", []))
    if "raw" in schemas:
        errors.append("platform.yaml: 'raw' is a Redshift reserved word and can't name a schema")
    for key, table in wh.get("tables", {}).items():
        if table.split(".")[0] not in schemas:
            errors.append(f"platform.yaml: table {key} ({table}) is not in a listed schema")
    marts = mart_columns()
    for table in wh.get("tables", {}).values():
        if table.startswith("marts.") and table not in marts:
            errors.append(f"platform.yaml: {table} has no CREATE TABLE in marts.sql")
    outs = doc.get("terraform_outputs", [])
    runtime_outs = yaml.safe_load((CONTRACTS / "runtime.yaml").read_text()).get("terraform_outputs", [])
    if set(outs) & set(runtime_outs) or not all(SNAKE.match(o) for o in outs):
        errors.append("platform.yaml: terraform_outputs must be new snake_case names (not repeats of runtime.yaml's)")
    for var in doc.get("env", {}):
        if not re.match(r"^[A-Z][A-Z0-9_]*$", var):
            errors.append(f"platform.yaml: env var {var} is not UPPER_SNAKE")
    # The MCP tool can only offer metrics the mart has.
    tools = {t["name"]: t for t in json.loads((CONTRACTS / "mcp-tools.json").read_text()).get("tools", [])}
    metrics = tools.get("query_zone_stats", {}).get("inputSchema", {}).get("properties", {}).get("metric", {}).get("enum", [])
    missing = set(metrics) - set(marts.get(wh.get("tables", {}).get("zone_hour_stats", ""), []))
    if missing:
        errors.append(f"marts.sql: zone_hour_stats lacks columns for query_zone_stats metrics {sorted(missing)}")


def check_features(errors: list[str]) -> None:
    doc = yaml.safe_load((CONTRACTS / "features.yaml").read_text())
    inputs = [c["name"] for c in doc.get("inputs", [])]
    columns = [c["name"] for c in doc.get("keys", [])] + inputs + [doc.get("label", {}).get("name")]
    if len(columns) != len(set(columns)):
        errors.append("features.yaml: duplicate column names")
    leaked = set(columns) & set(doc.get("forbidden", []))
    if leaked:
        errors.append(f"features.yaml: forbidden (post-trip) columns used: {sorted(leaked)}")
    schema = doc.get("table", "").split(".")[0]
    schemas = yaml.safe_load((CONTRACTS / "platform.yaml").read_text()).get("warehouse", {}).get("schemas", [])
    if schema not in schemas:
        errors.append(f"features.yaml: table {doc.get('table')} is not in a platform.yaml schema")


def check_mlflow(errors: list[str]) -> None:
    doc = yaml.safe_load((CONTRACTS / "mlflow.yaml").read_text())
    if set(doc.get("aliases", {})) != {"champion", "challenger"}:
        errors.append("mlflow.yaml: aliases must be exactly champion and challenger")
    metrics, tags = set(doc.get("metrics", [])), set(doc.get("version_tags", []))
    for required in ("mae_min", "p95_latency_ms", "champion_mae_min"):
        if required not in metrics or required not in tags:
            errors.append(f"mlflow.yaml: {required} must be both a metric and a version tag")
    if not {"training_window", "holdout_month", "features_version"} <= tags:
        errors.append("mlflow.yaml: version_tags must include training_window, holdout_month, features_version (get_model_info reads them)")
    gated = doc.get("pipeline", {}).get("blocking_checks", {})
    if "feature_contract" not in gated.get("trip_features", []) or "beats_champion" not in gated.get("eval_report", []):
        errors.append("mlflow.yaml: feature_contract and beats_champion must be listed as blocking checks")


def check_metrics(errors: list[str]) -> None:
    doc = yaml.safe_load((CONTRACTS / "metrics.yaml").read_text())
    services = yaml.safe_load((CONTRACTS / "runtime.yaml").read_text())["services"]
    for name, svc in doc.get("services", {}).items():
        # The lab's services serve /metrics on their own port; Traefik's metrics have an entrypoint of their own.
        if "metrics" in svc and name in services and svc.get("port") != services[name]["port"]:
            errors.append(f"metrics.yaml: {name} port {svc.get('port')} isn't runtime.yaml's {services[name]['port']}")
        for metric, spec in (svc.get("metrics") or {}).items():
            where = f"metrics.yaml: {name}.{metric}"
            if not metric.startswith("lab_"):
                errors.append(f"{where}: the lab's own metrics are named lab_*")
            if spec.get("type") not in ("counter", "gauge", "histogram"):
                errors.append(f"{where}: type must be counter, gauge or histogram")
            if spec.get("type") == "counter" and not metric.endswith("_total"):
                errors.append(f"{where}: counters end in _total")
            if not isinstance(spec.get("labels"), dict) or not spec["labels"]:
                errors.append(f"{where}: labels must map each label to what its values are")
            buckets = spec.get("buckets")
            if (spec.get("type") == "histogram") != (buckets is not None) or (buckets and buckets != sorted(set(buckets))):
                errors.append(f"{where}: histograms (only) list strictly increasing buckets")
    if not isinstance(doc.get("budget", {}).get("active_series"), int):
        errors.append("metrics.yaml: budget.active_series must be an integer")


def main() -> int:
    if "--write-sums" in sys.argv:
        SUMS.write_text("".join(f"{sha(p)}  {p.name}\n" for p in contract_files()))
        print(f"wrote {SUMS.relative_to(CONTRACTS.parent)}")
        return 0
    errors: list[str] = []
    for fn in (check_sums, check_openapi, check_mcp, check_runtime, check_trips_schema, check_platform, check_features, check_mlflow, check_serving_matches_features, check_metrics):
        try:
            fn(errors)
        except (OSError, ValueError, yaml.YAMLError) as e:
            errors.append(f"{fn.__name__}: {e}")
    for e in errors:
        print(f"contract error: {e}", file=sys.stderr)
    if not errors:
        print(f"contracts ok: {', '.join(p.name for p in contract_files())}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
