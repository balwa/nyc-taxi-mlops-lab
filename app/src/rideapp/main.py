"""Ride-hailing app backend. Contract: contracts/openapi.yaml.

S0 quotes every trip with a static median, which is the behaviour the backstory starts from.
From S3, with SERVING_URL set, the quote comes from the serving service (contracts/serving-openapi.yaml)
through Traefik, which routes to the champion. If serving is slow, down, or has no champion yet, the app
falls back to the static median, and the response's `model` says which one answered.
From S5, /metrics serves contracts/metrics.yaml's app metrics (Docker network only: Traefik doesn't route it).
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx2
from fastapi import FastAPI, Request, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest
from pydantic import BaseModel, ConfigDict, Field

from .assistant import router as assistant_router

# Median duration of 13,056,791 yellow-taxi trips, 2024-01..2024-04, keeping 0 < duration <= 180 min.
STATIC_MEDIAN_MINUTES = 12.25
NEW_YORK = ZoneInfo("America/New_York")


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_zone_id: int = Field(ge=1, le=263)
    dropoff_zone_id: int = Field(ge=1, le=263)
    pickup_datetime: datetime
    trip_distance_miles: float | None = Field(default=None, gt=0, le=100)


class ModelInfo(BaseModel):
    name: str
    version: str
    alias: str | None = None


class PredictResponse(BaseModel):
    duration_minutes: float
    model: ModelInfo


app = FastAPI(title="Ride app", version="1.0.0")
app.include_router(assistant_router)  # POST /assist (S6): contracts/assistant-openapi.yaml

# contracts/metrics.yaml (S5). Labels are bounded: route templates, never raw paths.
REQUESTS = Counter("lab_http_requests_total", "HTTP requests the app answered.", ["route", "method", "code"])
LATENCY = Histogram("lab_http_request_duration_seconds", "Time from request to response, inside the app.",
                    ["route", "method"], buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5])
PREDICTIONS = Counter("lab_predictions_total", "Quotes given, by who produced them.", ["source", "alias", "version"])
SERVING_CALLS = Histogram("lab_serving_request_duration_seconds", "The app's call to serving, through Traefik.",
                          ["outcome"], buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5])


@app.middleware("http")
async def measure(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    route = getattr(request.scope.get("route"), "path", "other")
    if route != "/metrics":
        LATENCY.labels(route, request.method).observe(time.perf_counter() - start)
        REQUESTS.labels(route, request.method, str(response.status_code)).inc()
    return response


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@app.get("/version")
async def version() -> dict:
    return {
        "service": "app",
        "git_sha": os.environ.get("GIT_SHA", "unknown"),
        "image_tag": os.environ.get("IMAGE_TAG", "dev"),
    }


STATIC = PredictResponse(
    duration_minutes=STATIC_MEDIAN_MINUTES,
    model=ModelInfo(name="static-median", version="2024-01..2024-04", alias=None),
)


def features(req: PredictRequest) -> dict:
    """The serving request (contracts/features.yaml): New York local hour and day, 0 = Sunday."""
    t = req.pickup_datetime.astimezone(NEW_YORK) if req.pickup_datetime.tzinfo else req.pickup_datetime
    body = {
        "pickup_zone_id": req.pickup_zone_id,
        "dropoff_zone_id": req.dropoff_zone_id,
        "pickup_hour": t.hour,
        "pickup_dow": (t.weekday() + 1) % 7,
    }
    if req.trip_distance_miles is not None:
        body["est_distance_miles"] = req.trip_distance_miles
    return body


_client: httpx2.AsyncClient | None = None


def serving_client() -> httpx2.AsyncClient:
    global _client
    if _client is None:
        _client = httpx2.AsyncClient(timeout=float(os.environ.get("SERVING_TIMEOUT_SECONDS", "0.3")))
    return _client


@app.post("/predict")
async def predict(req: PredictRequest) -> PredictResponse:
    url = os.environ.get("SERVING_URL")
    if not url:
        PREDICTIONS.labels("fallback", "", "").inc()
        return STATIC
    start, outcome = time.perf_counter(), "error"
    try:
        r = await serving_client().post(f"{url.rstrip('/')}/predict", json=features(req))
        if r.status_code == 200:
            body = r.json()
            answer = PredictResponse(duration_minutes=body["duration_minutes"], model=ModelInfo(**body["model"]))
            outcome = "ok"
            PREDICTIONS.labels("model", answer.model.alias or "", answer.model.version).inc()
            return answer
        outcome = "unavailable" if r.status_code == 503 else "error"
    except httpx2.TimeoutException:
        outcome = "timeout"
    except (httpx2.HTTPError, ValueError, KeyError):
        pass
    finally:
        SERVING_CALLS.labels(outcome).observe(time.perf_counter() - start)
    PREDICTIONS.labels("fallback", "", "").inc()
    return STATIC
