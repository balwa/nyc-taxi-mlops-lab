"""The given models: v1 baseline, v2 LightGBM, the distance lookup, evaluation, and an MLflow round trip."""

from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
from fakes import synthetic_trips

import tripmodel
from tripmodel import FEATURES, BaselineModel, DistanceLookup, LightGBMModel, evaluate, model_signature


def frames():
    trips = synthetic_trips(["2024-01", "2024-02", "2024-03", "2024-04"])
    train, hold = trips[trips.trip_month < "2024-04"], trips[trips.trip_month == "2024-04"]
    dist = train.groupby(["pickup_zone_id", "dropoff_zone_id"])["trip_distance"].median().rename("est_distance_miles").reset_index()
    return train.drop(columns="trip_distance"), hold.drop(columns="trip_distance"), dist


def test_lookup_fills_only_missing_and_falls_back():
    lookup = DistanceLookup(pd.DataFrame({"pickup_zone_id": [1, 1], "dropoff_zone_id": [2, 3], "est_distance_miles": [2.0, 4.0]}))
    df = pd.DataFrame({"pickup_zone_id": [1, 1, 9], "dropoff_zone_id": [2, 7, 9], "est_distance_miles": [np.nan, np.nan, 5.5]})
    assert lookup.fill(df).tolist() == [2.0, 3.0, 5.5]  # pair; pickup-zone median; given value kept


def test_lightgbm_beats_the_baseline_and_the_static_median():
    train, hold, dist = frames()
    zones = {z: "Manhattan" for z in range(1, 11)}
    v1 = evaluate(lambda df: BaselineModel().fit(train, dist).predict(None, df), hold, zones, latency_samples=5)
    v2_model = LightGBMModel().fit(train, dist, num_rounds=100)
    v2 = evaluate(lambda df: v2_model.predict(None, df), hold, zones, latency_samples=5)
    static = float(np.abs(hold["duration_min"] - train["duration_min"].median()).mean())
    assert v2["mae_min"] < v1["mae_min"] < static
    assert {"mae_min.manhattan", "mae_min.night", "p95_latency_ms"} <= set(v2)


def test_mlflow_round_trip_without_the_distance(tmp_path):
    train, hold, dist = frames()
    mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/mlflow.db")
    mlflow.create_experiment("t", artifact_location=str(tmp_path / "artifacts"))
    mlflow.set_experiment("t")

    with mlflow.start_run():
        info = mlflow.pyfunc.log_model(name="model", python_model=LightGBMModel().fit(train, dist, num_rounds=20),
                                       signature=model_signature(), code_paths=[str(Path(tripmodel.__file__).parent)],
                                       registered_model_name="trip-duration")
    loaded = mlflow.pyfunc.load_model(f"models:/trip-duration/{info.registered_model_version}")
    assert loaded.metadata.signature.inputs.input_names() == FEATURES
    pred = loaded.predict(hold[["pickup_zone_id", "dropoff_zone_id", "pickup_hour", "pickup_dow"]].astype("int64").head(3))
    assert len(pred) == 3 and (np.asarray(pred) > 0).all()


def test_vectorized_lookups_match_plain_dict_lookups():
    train, hold, dist = frames()
    v1 = BaselineModel().fit(train, dist)
    lookup = DistanceLookup(dist)
    x = hold.head(500).copy()
    x.loc[x.index[:5], "pickup_zone_id"] = 250  # unseen zones exercise every fallback
    expected_v1 = [v1.by_pair_hour.get((p, d, h), v1.by_pair.get((p, d), v1.by_pickup.get(p, v1.overall)))
                   for p, d, h in zip(x.pickup_zone_id, x.dropoff_zone_id, x.pickup_hour, strict=True)]
    expected_dist = [lookup.pairs.get((p, d), lookup.by_pickup.get(p, lookup.overall))
                     for p, d in zip(x.pickup_zone_id, x.dropoff_zone_id, strict=True)]
    assert np.allclose(v1.predict(None, x), expected_v1)
    assert np.allclose(lookup.fill(x), expected_dist)
