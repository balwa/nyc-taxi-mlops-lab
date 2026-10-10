"""Read the frozen contracts the pipeline depends on (contracts/ at the repo root, or LAB_CONTRACTS_DIR)."""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import yaml


def contracts_dir() -> Path:
    env = os.environ.get("LAB_CONTRACTS_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[3] / "contracts"


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # Parquet storage type: INT32, INT64, DOUBLE, STRING, TIMESTAMP_MICROS, ...


def trips_schema() -> list[Column]:
    """The expected columns of a landed trip file, in order (contracts/trips.schema.yaml)."""
    doc = yaml.safe_load((contracts_dir() / "trips.schema.yaml").read_text())
    return [Column(c["name"], c["type"]) for c in doc["columns"]]


REDSHIFT_TYPES = {
    "INT32": "INTEGER",
    "INT64": "BIGINT",
    "DOUBLE": "DOUBLE PRECISION",
    "STRING": "VARCHAR(256)",
    "TIMESTAMP_MICROS": "TIMESTAMP",
}


def redshift_columns(columns: list[Column]) -> str:
    """Column definitions for a table that Parquet COPY loads by position, e.g. a landing table."""
    return ", ".join(f"{c.name.lower()} {REDSHIFT_TYPES[c.type]}" for c in columns)


def marts_ddl() -> list[str]:
    """The CREATE TABLE statements of contracts/marts.sql, comments stripped."""
    sql = re.sub(r"--[^\n]*", "", (contracts_dir() / "marts.sql").read_text())
    return [s.strip() for s in sql.split(";") if s.strip()]


def features_contract() -> dict:
    """contracts/features.yaml: inputs, derived inputs, label and forbidden columns."""
    return yaml.safe_load((contracts_dir() / "features.yaml").read_text())


def mlflow_contract() -> dict:
    """contracts/mlflow.yaml: experiment, registered model, aliases, metrics and version tags."""
    return yaml.safe_load((contracts_dir() / "mlflow.yaml").read_text())
