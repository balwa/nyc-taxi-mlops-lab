"""The app asks serving (S3) and falls back to the static median when it can't."""

import httpx2
import pytest
from fastapi.testclient import TestClient

import rideapp.main as m

REQ = {"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-10T17:05:00"}  # a Sunday


@pytest.fixture
def serving(monkeypatch):
    seen = []

    def use(handler):
        def recording(request):
            seen.append(request)
            return handler(request)

        monkeypatch.setenv("SERVING_URL", "http://traefik:8001")
        monkeypatch.setattr(m, "_client", httpx2.AsyncClient(transport=httpx2.MockTransport(recording)))
        return seen

    return use


def test_champion_answers(serving):
    seen = serving(lambda r: httpx2.Response(200, json={"duration_minutes": 31.4, "model": {"name": "trip-duration", "version": "7", "alias": "champion"}}))
    body = TestClient(m.app).post("/predict", json=REQ).json()
    assert body == {"duration_minutes": 31.4, "model": {"name": "trip-duration", "version": "7", "alias": "champion"}}
    sent = __import__("json").loads(seen[0].content)
    assert sent == {"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_hour": 17, "pickup_dow": 0}  # 0 = Sunday


def test_offsets_convert_to_new_york_and_distance_passes_through(serving):
    seen = serving(lambda r: httpx2.Response(200, json={"duration_minutes": 9.0, "model": {"name": "trip-duration", "version": "7", "alias": "champion"}}))
    TestClient(m.app).post("/predict", json=REQ | {"pickup_datetime": "2024-03-11T02:30:00Z", "trip_distance_miles": 3.2})
    sent = __import__("json").loads(seen[0].content)
    assert (sent["pickup_hour"], sent["pickup_dow"]) == (22, 0)  # 02:30 UTC Monday = 22:30 Sunday in New York (EDT)
    assert sent["est_distance_miles"] == 3.2


@pytest.mark.parametrize("handler", [
    lambda r: httpx2.Response(503, json={"detail": "no champion model loaded yet"}),
    lambda r: (_ for _ in ()).throw(httpx2.ConnectTimeout("slow")),
    lambda r: httpx2.Response(200, json={"unexpected": True}),
])
def test_falls_back_to_the_static_median(serving, handler):
    serving(handler)
    body = TestClient(m.app).post("/predict", json=REQ).json()
    assert body["model"]["name"] == "static-median" and body["duration_minutes"] == m.STATIC_MEDIAN_MINUTES
