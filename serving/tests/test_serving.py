"""Serving against a local MLflow registry: load by alias, swap on /reload, 503 before an alias
exists, and every response checked against contracts/serving-openapi.yaml."""

import importlib
from pathlib import Path

import mlflow
import numpy as np
import pandas as pd
import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
from mlflow import MlflowClient

import tripmodel
from tripmodel import LightGBMModel, model_signature

CONTRACT = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts" / "serving-openapi.yaml").read_text())


def assert_matches(name: str, body) -> None:
    defs = yaml.safe_load(yaml.safe_dump(CONTRACT["components"]["schemas"]).replace("#/components/schemas/", "#/$defs/"))
    errors = [e.message for e in Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": defs}).iter_errors(body)]
    assert not errors, errors


def trips(n=3000, seed=0, scale=3.0):
    rng = np.random.default_rng(seed)
    p, d = rng.integers(1, 30, n), rng.integers(1, 30, n)
    dist = 0.5 * np.abs(p - d) + 1
    return (pd.DataFrame({"pickup_zone_id": p, "dropoff_zone_id": d, "pickup_hour": rng.integers(0, 24, n),
                          "pickup_dow": rng.integers(0, 7, n), "duration_min": scale * dist + rng.normal(0, 1, n).clip(-2, 2) + 3}),
            pd.DataFrame({"pickup_zone_id": p, "dropoff_zone_id": d, "est_distance_miles": dist}).drop_duplicates(["pickup_zone_id", "dropoff_zone_id"]))


def register(scale: float) -> str:
    train, dist = trips(scale=scale)
    with mlflow.start_run():
        info = mlflow.pyfunc.log_model(name="model", python_model=LightGBMModel().fit(train, dist, num_rounds=30),
                                       signature=model_signature(), code_paths=[str(Path(tripmodel.__file__).parent)],
                                       registered_model_name="trip-duration")
    v = str(info.registered_model_version)
    MlflowClient().set_model_version_tag("trip-duration", v, "training_window", "2024-01..2024-03")
    return v


@pytest.fixture
def registry(tmp_path, monkeypatch):
    uri = f"sqlite:///{tmp_path}/mlflow.db"
    monkeypatch.setenv("MLFLOW_TRACKING_URI", uri)
    mlflow.set_tracking_uri(uri)
    mlflow.create_experiment("t", artifact_location=str(tmp_path / "artifacts"))
    mlflow.set_experiment("t")
    return MlflowClient(uri)


def serving(monkeypatch, alias="champion"):
    monkeypatch.setenv("MODEL_ALIAS", alias)
    monkeypatch.setenv("LOAD_RETRY_SECONDS", "0.2")
    import servingapp.main as m

    return importlib.reload(m)


REQ = {"pickup_zone_id": 3, "dropoff_zone_id": 20, "pickup_hour": 17, "pickup_dow": 5}


def test_serves_the_alias_and_swaps_only_on_reload(registry, monkeypatch):
    v1, v2 = register(3.0), register(6.0)
    registry.set_registered_model_alias("trip-duration", "champion", v1)
    m = serving(monkeypatch)
    with TestClient(m.app) as c:
        m.server.load_until_available()
        info = c.get("/model").json()
        assert_matches("LoadedModel", info)
        assert info["version"] == v1 and info["tags"]["training_window"] == "2024-01..2024-03"
        first = c.post("/predict", json=REQ).json()
        assert_matches("PredictResponse", first)
        assert first["model"] == {"name": "trip-duration", "version": v1, "alias": "champion"}

        registry.set_registered_model_alias("trip-duration", "champion", v2)  # promotion
        assert c.post("/predict", json=REQ).json()["model"]["version"] == v1  # nothing changes on its own
        r = c.post("/reload").json()
        assert_matches("ReloadResponse", r)
        assert r == {"alias": "champion", "version": v2, "previous_version": v1, "changed": True}
        second = c.post("/predict", json=REQ).json()
        assert second["model"]["version"] == v2 and second["duration_minutes"] > first["duration_minutes"]
        assert c.post("/reload").json()["changed"] is False


def test_given_distance_is_used(registry, monkeypatch):
    registry.set_registered_model_alias("trip-duration", "champion", register(3.0))
    m = serving(monkeypatch)
    with TestClient(m.app) as c:
        m.server.load_until_available()
        near = c.post("/predict", json=REQ | {"est_distance_miles": 1.0}).json()["duration_minutes"]
        far = c.post("/predict", json=REQ | {"est_distance_miles": 14.0}).json()["duration_minutes"]
        assert far > near


def test_no_alias_yet_is_503_and_bad_input_422(registry, monkeypatch):
    register(3.0)  # a version exists, but no challenger alias
    m = serving(monkeypatch, alias="challenger")
    with TestClient(m.app) as c:
        assert c.get("/healthz").json() == {"status": "ok"}
        for r in (c.get("/model"), c.post("/predict", json=REQ), c.post("/reload")):
            assert r.status_code == 503
            assert_matches("Error", r.json())
        assert c.post("/predict", json=REQ | {"pickup_zone_id": 264}).status_code == 422
        assert c.post("/predict", json=REQ | {"fare_amount": 30}).status_code == 422  # not a model input


def test_metrics_follow_the_contract_and_the_loaded_version(registry, monkeypatch):
    from prometheus_client.parser import text_string_to_metric_families

    spec = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts" / "metrics.yaml").read_text())["services"]["serving"]
    v1, v2 = register(3.0), register(6.0)
    registry.set_registered_model_alias("trip-duration", "champion", v1)
    m = serving(monkeypatch)
    with TestClient(m.app) as c:
        m.server.load_until_available()
        c.post("/predict", json=REQ)
        registry.set_registered_model_alias("trip-duration", "champion", v2)
        c.post("/reload")
        c.post("/reload")
        c.post("/predict", json=REQ)
        families = {f.name: f for f in text_string_to_metric_families(c.get("/metrics").text)}
    for name, s in spec["metrics"].items():
        f = families[name.removesuffix("_total")]
        assert f.type == s["type"], name
        samples = [x for x in f.samples if not x.name.endswith(("_created", "_count", "_sum"))]
        assert samples and set(samples[0].labels) - {"le"} == set(s["labels"]), name
        if s["type"] == "histogram":
            assert sorted({float(x.labels["le"]) for x in samples if x.labels["le"] != "+Inf"}) == s["buckets"], name
    assert [(x.labels["version"], x.value) for x in families["lab_model_info"].samples] == [(v2, 1.0)]  # v1's series is gone
    reloads = {x.labels["outcome"]: x.value for x in families["lab_model_reloads"].samples if x.name.endswith("_total")}
    # Start-up load and the promotion's reload change it; the repeat (and the test's own start-up call,
    # racing the lifespan thread) don't.
    assert reloads["changed"] == 2.0 and reloads["unchanged"] >= 1.0 and "failed" not in reloads
    versions = {x.labels["version"] for x in families["lab_model_predict_duration_seconds"].samples if x.name.endswith("_count")}
    assert versions == {v1, v2}
