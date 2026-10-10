"""Drift (S8, given): how far each month's trips are from what the champion was trained on.

drift_report[month]     population stability index (PSI) of pickup hour, day of week, pickup zone and
                        duration, between the month and the champion's training window (its MLflow tag;
                        before there is a champion, the TRAIN_MONTHS months before)
drift_within_threshold  warns when the largest PSI is over DRIFT_THRESHOLD (default 0.2)
check_drift             runs drift_report for each new trip_features partition (drift_sensor)

PSI = sum((cur - ref) * ln(cur / ref)) over a feature's bins. Rule of thumb: under 0.1 stable, 0.1-0.2
moderate, over 0.2 a real shift. Whether a shift means "retrain", "reject the month" or "fine" is the
judgment call (gameday E4b).
"""

import math
import os

import dagster as dg

from ..contracts import mlflow_contract
from ..partitions import check_month, trip_months
from ..resources import MlflowTracking, RedshiftData

DRIFT_THRESHOLD = float(os.environ.get("DRIFT_THRESHOLD", "0.2"))
TRAIN_MONTHS = 3  # the fallback reference before there's a champion (training.py's default window)
TOP_ZONES = 30
DURATION_EDGES = [5, 10, 15, 20, 30, 45, 60, 90]  # minutes; the last bin is 90-180


def psi(ref: dict, cur: dict, eps: float = 1e-4) -> float:
    bins = set(ref) | set(cur)
    rt, ct = sum(ref.values()) or 1, sum(cur.values()) or 1
    total = 0.0
    for b in bins:
        r, c = max(ref.get(b, 0) / rt, eps), max(cur.get(b, 0) / ct, eps)
        total += (c - r) * math.log(c / r)
    return total


def months_between(window: str) -> list[str]:
    """'2024-01..2024-03' -> ['2024-01', '2024-02', '2024-03']."""
    first, last = window.split("..")
    y, m = map(int, first.split("-"))
    out = []
    while f"{y:04d}-{m:02d}" <= last:
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def reference_window(month: str, tracking: MlflowTracking, redshift: RedshiftData) -> tuple[list[str], str]:
    try:
        mv = tracking.client().get_model_version_by_alias(mlflow_contract()["registered_model"], "champion")
        return months_between(mv.tags["training_window"]), f"champion v{mv.version}"
    except Exception:  # no champion yet, or MLflow unreachable: the months before this one
        months = [r["trip_month"] for r in redshift.query(f"select distinct trip_month from staging.trip_features where trip_month < '{month}' order by 1")]
        return months[-TRAIN_MONTHS:], "the months before (no champion yet)"


@dg.asset(partitions_def=trip_months, deps=["trip_features"], group_name="model", kinds={"redshift"}, pool="redshift")
def drift_report(context: dg.AssetExecutionContext, redshift: RedshiftData, tracking: MlflowTracking) -> dg.MaterializeResult:
    month = check_month(context.partition_key)
    window, source = reference_window(month, tracking, redshift)
    window = [check_month(m) for m in window if m != month]
    if not window:
        return dg.MaterializeResult(metadata={"reference": "none: no earlier months", "max_psi": 0.0})
    months_sql = ", ".join(f"'{m}'" for m in window)
    top = [r["pickup_zone_id"] for r in redshift.query(
        f"select pickup_zone_id from staging.trip_features where trip_month in ({months_sql}) group by 1 order by count(*) desc limit {TOP_ZONES}")]
    duration_bin = "case " + " ".join(f"when duration_min < {e} then {i}" for i, e in enumerate(DURATION_EDGES)) + f" else {len(DURATION_EDGES)} end"
    features = {
        "pickup_hour": "pickup_hour",
        "pickup_dow": "pickup_dow",
        "pickup_zone": f"case when pickup_zone_id in ({', '.join(map(str, top)) or '0'}) then pickup_zone_id else 0 end",
        "duration": duration_bin,
    }
    scores = {}
    for name, expr in features.items():
        rows = redshift.query(
            f"select {expr} as bin, sum(case when trip_month = '{month}' then 1 else 0 end) as cur, "
            f"sum(case when trip_month <> '{month}' then 1 else 0 end) as ref "
            f"from staging.trip_features where trip_month in ({months_sql}, '{month}') group by 1")
        scores[name] = round(psi({r["bin"]: int(r["ref"]) for r in rows}, {r["bin"]: int(r["cur"]) for r in rows}), 4)
    worst = max(scores, key=scores.get)
    context.log.info(f"{month} vs {window[0]}..{window[-1]} ({source}): " + ", ".join(f"{k} {v}" for k, v in scores.items()))
    return dg.MaterializeResult(metadata={"reference": f"{window[0]}..{window[-1]} ({source})", "max_psi": scores[worst],
                                          "max_feature": worst, **{f"psi_{k}": v for k, v in scores.items()}})


@dg.asset_check(asset=drift_report, description=f"Largest PSI at most DRIFT_THRESHOLD ({DRIFT_THRESHOLD})")
def drift_within_threshold(context: dg.AssetCheckExecutionContext) -> dg.AssetCheckResult:
    event = context.instance.get_latest_materialization_event(dg.AssetKey("drift_report"))
    md = event.asset_materialization.metadata if event and event.asset_materialization else {}
    worst = md["max_psi"].value if "max_psi" in md else 0.0
    return dg.AssetCheckResult(passed=worst <= DRIFT_THRESHOLD, severity=dg.AssetCheckSeverity.WARN,
                               metadata={"max_psi": worst, "threshold": DRIFT_THRESHOLD})


check_drift = dg.define_asset_job("check_drift", selection=dg.AssetSelection.assets(drift_report).without_checks() | dg.AssetSelection.checks(drift_within_threshold),
                                  partitions_def=trip_months)


@dg.asset_sensor(asset_key=dg.AssetKey("trip_features"), job=check_drift, default_status=dg.DefaultSensorStatus.RUNNING)
def drift_sensor(context: dg.SensorEvaluationContext, asset_event: dg.EventLogEntry):
    partition = asset_event.dagster_event.partition if asset_event.dagster_event else None
    if partition:
        yield dg.RunRequest(partition_key=partition, run_key=f"drift:{partition}:{asset_event.run_id}:{asset_event.timestamp}")
