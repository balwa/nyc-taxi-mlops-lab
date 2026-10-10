"""v1 baseline and v2 LightGBM, the distance lookup they share, and the evaluation the gate uses.

Inputs follow contracts/features.yaml: pickup_zone_id, dropoff_zone_id, pickup_hour (0-23),
pickup_dow (0 = Sunday, as Redshift's extract(dow)), and est_distance_miles. A trip's real distance is
only known afterwards, so est_distance_miles is the zone pair's median distance over the training
window. Both models carry that lookup and fill the column when a caller leaves it empty, which is
what serving does unless the app passes a routing estimate.
"""

import time
from collections.abc import Callable

import lightgbm as lgb
import mlflow.pyfunc
import numpy as np
import pandas as pd
from mlflow.models import ModelSignature
from mlflow.types import ColSpec, Schema

REQUIRED = ["pickup_zone_id", "dropoff_zone_id", "pickup_hour", "pickup_dow"]
FEATURES = [*REQUIRED, "est_distance_miles"]
LABEL = "duration_min"

AIRPORT_ZONES = {1, 132, 138}  # Newark, JFK, LaGuardia


def _lookup(table: dict, keys: list[np.ndarray]) -> np.ndarray:
    """Dict lookup on one or more key columns; NaN where a key is missing. Plain lookups for a few rows
    (serving's single rows: building an index over ~36k zone pairs costs ~15 ms per call), vectorized
    for batches (evaluation's 500k rows)."""
    if not table:
        return np.full(len(keys[0]), np.nan)
    if len(keys[0]) <= 64:
        rows = keys[0].tolist() if len(keys) == 1 else list(zip(*(k.tolist() for k in keys), strict=True))
        return np.array([table.get(r, np.nan) for r in rows], dtype="float64")
    if len(keys) == 1:
        return pd.Series(table, dtype="float64").reindex(keys[0]).to_numpy()
    index = pd.MultiIndex.from_tuples(list(table), names=range(len(keys)))
    return pd.Series(list(table.values()), index=index, dtype="float64").reindex(pd.MultiIndex.from_arrays(keys)).to_numpy()


def model_signature() -> ModelSignature:
    """The pyfunc signature: the contract's inputs (distance optional), minutes out."""
    cols = [ColSpec("long", c) for c in REQUIRED] + [ColSpec("double", "est_distance_miles", required=False)]
    return ModelSignature(inputs=Schema(cols), outputs=Schema([ColSpec("double")]))


class DistanceLookup:
    """Median trip distance per zone pair, falling back to the pickup zone's median, then the overall one.

    State is plain dicts on purpose: a model pickled by this version must load with the next one
    (serving and eval_report load older versions with the current tripmodel)."""

    def __init__(self, pairs: pd.DataFrame):
        """pairs: pickup_zone_id, dropoff_zone_id, est_distance_miles (one row per pair)."""
        self.pairs = {(int(p), int(d)): float(m) for p, d, m in pairs[["pickup_zone_id", "dropoff_zone_id", "est_distance_miles"]].itertuples(index=False)}
        by_pickup = pairs.groupby("pickup_zone_id")["est_distance_miles"].median()
        self.by_pickup = {int(k): float(v) for k, v in by_pickup.items()}
        self.overall = float(pairs["est_distance_miles"].median()) if len(pairs) else 0.0

    def fill(self, df: pd.DataFrame) -> pd.Series:
        """est_distance_miles where given, the lookup's estimate where missing."""
        given = df["est_distance_miles"] if "est_distance_miles" in df else pd.Series(np.nan, index=df.index)
        p, d = df["pickup_zone_id"].to_numpy("int64"), df["dropoff_zone_id"].to_numpy("int64")
        est = _lookup(self.pairs, [p, d])
        est = np.where(np.isnan(est), _lookup(self.by_pickup, [p]), est)
        est = np.where(np.isnan(est), self.overall, est)
        return given.astype("float64").fillna(pd.Series(est, index=df.index, dtype="float64"))


def _inputs(df: pd.DataFrame, lookup: DistanceLookup) -> pd.DataFrame:
    out = df[REQUIRED].astype("int64").copy()
    out["est_distance_miles"] = lookup.fill(df)
    return out


class BaselineModel(mlflow.pyfunc.PythonModel):
    """v1: median duration per (pickup zone, dropoff zone, hour), falling back to the pair, the pickup
    zone, then every trip. What a careful analyst would ship before any ML."""

    def fit(self, train: pd.DataFrame, distances: pd.DataFrame) -> "BaselineModel":
        self.lookup = DistanceLookup(distances)
        self.by_pair_hour = train.groupby(["pickup_zone_id", "dropoff_zone_id", "pickup_hour"])[LABEL].median().to_dict()
        self.by_pair = train.groupby(["pickup_zone_id", "dropoff_zone_id"])[LABEL].median().to_dict()
        self.by_pickup = train.groupby("pickup_zone_id")[LABEL].median().to_dict()
        self.overall = float(train[LABEL].median())
        return self

    def predict(self, context, model_input: pd.DataFrame, params=None) -> np.ndarray:
        x = model_input[REQUIRED].astype("int64")
        p, d, h = x["pickup_zone_id"].to_numpy(), x["dropoff_zone_id"].to_numpy(), x["pickup_hour"].to_numpy()
        out = _lookup(self.by_pair_hour, [p, d, h])
        out = np.where(np.isnan(out), _lookup(self.by_pair, [p, d]), out)
        out = np.where(np.isnan(out), _lookup(self.by_pickup, [p]), out)
        return np.where(np.isnan(out), self.overall, out)


class LightGBMModel(mlflow.pyfunc.PythonModel):
    """v2: LightGBM on the contract's features, zone ids as categoricals, trained on absolute error."""

    DEFAULT_PARAMS = {
        "objective": "l1",
        "learning_rate": 0.1,
        "num_leaves": 127,
        "min_child_samples": 200,
        "max_cat_to_onehot": 4,
        "cat_smooth": 20,
        "verbose": -1,
    }

    def fit(self, train: pd.DataFrame, distances: pd.DataFrame, num_rounds: int = 300, params: dict | None = None) -> "LightGBMModel":
        self.lookup = DistanceLookup(distances)
        self.params = {**self.DEFAULT_PARAMS, **(params or {})}
        data = lgb.Dataset(_inputs(train, self.lookup), label=train[LABEL], categorical_feature=["pickup_zone_id", "dropoff_zone_id"], free_raw_data=True)
        self.booster = lgb.train(self.params, data, num_boost_round=num_rounds)
        return self

    def predict(self, context, model_input: pd.DataFrame, params=None) -> np.ndarray:
        # One thread for serving's single rows (no OpenMP start-up per call); every core for batches,
        # where one thread takes ~90 s on a 3.5M-row holdout month.
        threads = 1 if len(model_input) <= 64 else 0
        return np.clip(self.booster.predict(_inputs(model_input, self.lookup), num_threads=threads), 0.5, None)


def evaluate(predict: Callable[[pd.DataFrame], np.ndarray], holdout: pd.DataFrame, boroughs: dict[int, str],
             latency_samples: int = 200) -> dict[str, float]:
    """MAE overall and on slices, plus p95 latency of single-row predictions (what serving does).

    predict: a loaded pyfunc's .predict, or `lambda df: model.predict(None, df)` for a model object.
    The holdout's est_distance_miles is left empty, so the model estimates it as it would in serving."""
    x = holdout[REQUIRED].astype("int64")
    # Latency first: a big batch leaves threads and caches behind that would skew single-row timings.
    times = []
    for i in range(latency_samples):
        row = x.iloc[[i % len(x)]]
        t0 = time.perf_counter()
        predict(row)
        times.append(time.perf_counter() - t0)
    err = np.abs(np.asarray(predict(x), dtype="float64") - holdout[LABEL].to_numpy())
    pick, drop, hour = holdout["pickup_zone_id"], holdout["dropoff_zone_id"], holdout["pickup_hour"]
    manhattan = {z for z, b in boroughs.items() if b == "Manhattan"}
    slices = {
        "airport": pick.isin(AIRPORT_ZONES) | drop.isin(AIRPORT_ZONES),
        "manhattan": pick.isin(manhattan) & drop.isin(manhattan),
        "outer": ~pick.isin(manhattan) & ~pick.isin(AIRPORT_ZONES),
        "night": hour.between(0, 5),
    }
    metrics = {"mae_min": float(err.mean()), "holdout_rows": float(len(holdout))}
    for name, mask in slices.items():
        if mask.any():
            metrics[f"mae_min.{name}"] = float(err[mask.to_numpy()].mean())
    metrics["p95_latency_ms"] = float(np.percentile(times, 95) * 1000)
    return metrics
