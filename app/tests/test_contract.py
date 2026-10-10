"""The app must match contracts/openapi.yaml: responses are validated against the contract's schemas."""

from pathlib import Path

import pytest
import yaml
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from rideapp.main import STATIC_MEDIAN_MINUTES, app

CONTRACT = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts" / "openapi.yaml").read_text())
DEFS = CONTRACT["components"]["schemas"]
client = TestClient(app)


def validator(name: str) -> Draft202012Validator:
    # Point OpenAPI component refs at $defs so plain JSON Schema can resolve them.
    text = yaml.safe_dump(DEFS).replace("#/components/schemas/", "#/$defs/")
    return Draft202012Validator({"$ref": f"#/$defs/{name}", "$defs": yaml.safe_load(text)})


def assert_matches(name: str, body) -> None:
    errors = list(validator(name).iter_errors(body))
    assert not errors, [e.message for e in errors]


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    assert_matches("Health", r.json())


def test_version_defaults_and_env(monkeypatch):
    assert_matches("Version", client.get("/version").json())
    monkeypatch.setenv("GIT_SHA", "0123abc")
    monkeypatch.setenv("IMAGE_TAG", "sha-0123abc")
    body = client.get("/version").json()
    assert body == {"service": "app", "git_sha": "0123abc", "image_tag": "sha-0123abc"}
    assert_matches("Version", body)


GOOD = {"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-08T17:05:00"}


@pytest.mark.parametrize("body", [
    GOOD,
    GOOD | {"pickup_datetime": "2024-03-08T17:05:00-05:00"},
    GOOD | {"trip_distance_miles": 17.4},
])
def test_predict_static_median(body):
    assert_matches("PredictRequest", body)
    r = client.post("/predict", json=body)
    assert r.status_code == 200
    out = r.json()
    assert_matches("PredictResponse", out)
    assert out["duration_minutes"] == STATIC_MEDIAN_MINUTES
    assert out["model"] == {"name": "static-median", "version": "2024-01..2024-04", "alias": None}


@pytest.mark.parametrize("body", [
    GOOD | {"pickup_zone_id": 264},              # unknown zone
    GOOD | {"dropoff_zone_id": 0},
    {k: v for k, v in GOOD.items() if k != "pickup_datetime"},
    GOOD | {"trip_distance_miles": 0},
    GOOD | {"surprise": 1},                       # additionalProperties: false
])
def test_predict_rejects_what_the_contract_rejects(body):
    assert list(validator("PredictRequest").iter_errors(body))
    r = client.post("/predict", json=body)
    assert r.status_code == 422
    assert_matches("ValidationError", r.json())


def test_predict_rejects_unparseable_datetime():
    # JSON Schema treats `format: date-time` as an annotation, so only the API side is checked here.
    r = client.post("/predict", json=GOOD | {"pickup_datetime": "next tuesday"})
    assert r.status_code == 422
    assert_matches("ValidationError", r.json())
