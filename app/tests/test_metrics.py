"""The app's /metrics must serve contracts/metrics.yaml's app metrics, with exactly its labels and buckets."""

from pathlib import Path

import httpx2
import yaml
from fastapi.testclient import TestClient
from prometheus_client.parser import text_string_to_metric_families

import rideapp.main as m

CONTRACT = yaml.safe_load((Path(__file__).resolve().parents[2] / "contracts" / "metrics.yaml").read_text())["services"]["app"]
REQ = {"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-10T17:05:00"}


def scrape(client) -> dict:
    r = client.get("/metrics")
    assert r.status_code == 200
    return {f.name: f for f in text_string_to_metric_families(r.text)}


def test_every_contract_metric_with_its_labels_and_buckets(monkeypatch):
    monkeypatch.setenv("SERVING_URL", "http://traefik:8001")
    monkeypatch.setattr(m, "_client", httpx2.AsyncClient(transport=httpx2.MockTransport(
        lambda r: httpx2.Response(200, json={"duration_minutes": 9.0, "model": {"name": "trip-duration", "version": "7", "alias": "champion"}}))))
    client = TestClient(m.app)
    client.post("/predict", json=REQ)
    families = scrape(client)
    for name, spec in CONTRACT["metrics"].items():
        family = families[name.removesuffix("_total")]  # the parser names counters without _total
        assert family.type == spec["type"], name
        samples = [s for s in family.samples if not s.name.endswith(("_created", "_count", "_sum"))]
        assert samples, f"{name} has no samples"
        labels = set(samples[0].labels) - {"le"}
        assert labels == set(spec["labels"]), (name, labels)
        if spec["type"] == "histogram":
            les = sorted(float(s.labels["le"]) for s in samples if s.name.endswith("_bucket") and s.labels["le"] != "+Inf")
            assert sorted(set(les)) == spec["buckets"], name


def test_routes_are_templates_and_fallbacks_are_counted(monkeypatch):
    monkeypatch.setenv("SERVING_URL", "http://traefik:8001")
    monkeypatch.setattr(m, "_client", httpx2.AsyncClient(transport=httpx2.MockTransport(lambda r: httpx2.Response(503, json={}))))
    client = TestClient(m.app)
    client.post("/predict", json=REQ)
    client.get("/no/such/path/42")
    families = scrape(client)
    routes = {s.labels["route"] for s in families["lab_http_requests"].samples}
    assert "/predict" in routes and "other" in routes and not any("42" in r for r in routes)
    outcomes = {s.labels["outcome"] for s in families["lab_serving_request_duration_seconds"].samples if "outcome" in s.labels}
    assert "unavailable" in outcomes
    fallback = [s for s in families["lab_predictions"].samples if s.name == "lab_predictions_total" and s.labels["source"] == "fallback"]
    assert fallback and fallback[0].value >= 1
