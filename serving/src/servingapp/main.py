"""Model serving (contracts/serving-openapi.yaml): one container per MLflow alias.

MODEL_ALIAS (champion or challenger) picks the alias, and the model loads at start-up. Until that alias
exists (there is no champion before the first promotion), /predict answers 503 and the container looks
again every LOAD_RETRY_SECONDS. Once loaded, it never changes on its own: a restart, or POST /reload,
moves it to whatever the alias points at now. Which of the two promotion uses is decision 010.
From S5, /metrics serves contracts/metrics.yaml's serving metrics.
"""

import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime

import mlflow
import pandas as pd
from fastapi import FastAPI, HTTPException, Response
from mlflow import MlflowClient
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, ProcessCollector, generate_latest
from pydantic import BaseModel, ConfigDict, Field

MODEL_NAME = os.environ.get("MODEL_NAME", "trip-duration")
ALIAS = os.environ.get("MODEL_ALIAS", "champion")
LOAD_RETRY_SECONDS = float(os.environ.get("LOAD_RETRY_SECONDS", "30"))
INPUTS = ["pickup_zone_id", "dropoff_zone_id", "pickup_hour", "pickup_dow"]

log = logging.getLogger("serving")

# contracts/metrics.yaml (S5). A registry of our own, so re-importing the module (tests) starts clean.
REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)
PREDICT_SECONDS = Histogram("lab_model_predict_duration_seconds", "One /predict inside serving, model call included.",
                            ["alias", "version"], buckets=[0.001, 0.0025, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25], registry=REGISTRY)
MODEL_INFO = Gauge("lab_model_info", "1 for the version this container serves; absent before its first load.",
                   ["alias", "version"], registry=REGISTRY)
RELOADS = Counter("lab_model_reloads_total", "Reloads asked for (POST /reload and start-up loads).", ["alias", "outcome"], registry=REGISTRY)


@dataclass
class Loaded:
    model: object
    version: str
    tags: dict
    loaded_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class Server:
    """Holds the loaded model. Reloads are serialized; requests keep using the old model until the new
    one is ready, then the reference is swapped."""

    def __init__(self):
        self.current: Loaded | None = None
        self.error: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def reload(self) -> tuple[str | None, str]:
        """Resolve the alias and load that version if it isn't the current one. Returns (previous, now)."""
        with self._lock:
            try:
                mv = MlflowClient().get_model_version_by_alias(MODEL_NAME, ALIAS)
                version = str(mv.version)
                previous = self.current.version if self.current else None
                if previous != version:
                    model = mlflow.pyfunc.load_model(f"models:/{MODEL_NAME}/{version}")
                    model.predict(pd.DataFrame([[132, 230, 17, 5]], columns=INPUTS))  # warm up before taking traffic
                    self.current = Loaded(model, version, dict(mv.tags))
                    MODEL_INFO.clear()
                    MODEL_INFO.labels(ALIAS, version).set(1)
                    log.info("serving %s v%s (was %s)", ALIAS, version, previous)
            except Exception:
                RELOADS.labels(ALIAS, "failed").inc()
                raise
            RELOADS.labels(ALIAS, "changed" if previous != version else "unchanged").inc()
            self.error = None
            return previous, version

    def load_until_available(self) -> None:
        while self.current is None and not self._stop.is_set():
            try:
                self.reload()
            except Exception as e:  # alias missing, MLflow not up yet: try again later
                self.error = f"{type(e).__name__}: {e}"[:300]
                log.warning("no %s model yet: %s", ALIAS, self.error)
                self._stop.wait(LOAD_RETRY_SECONDS)


server = Server()


@asynccontextmanager
async def lifespan(_: FastAPI):
    threading.Thread(target=server.load_until_available, daemon=True).start()
    yield
    server._stop.set()


app = FastAPI(title="Model serving", version="1.0.0", lifespan=lifespan)


class PredictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pickup_zone_id: int = Field(ge=1, le=263)
    dropoff_zone_id: int = Field(ge=1, le=263)
    pickup_hour: int = Field(ge=0, le=23)
    pickup_dow: int = Field(ge=0, le=6)
    est_distance_miles: float | None = Field(default=None, gt=0, le=100)


def _current() -> Loaded:
    if server.current is None:
        raise HTTPException(503, f"no {ALIAS} model loaded yet ({server.error or 'loading'})")
    return server.current


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/metrics", include_in_schema=False)
def metrics() -> Response:
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/model")
def model_info() -> dict:
    m = _current()
    return {"name": MODEL_NAME, "version": m.version, "alias": ALIAS, "tags": m.tags, "loaded_at": m.loaded_at.isoformat()}


@app.post("/predict")
def predict(req: PredictRequest) -> dict:
    m = _current()
    start = time.perf_counter()
    row = pd.DataFrame([[req.pickup_zone_id, req.dropoff_zone_id, req.pickup_hour, req.pickup_dow]], columns=INPUTS)
    if req.est_distance_miles is not None:
        row["est_distance_miles"] = float(req.est_distance_miles)
    minutes = float(m.model.predict(row)[0])
    PREDICT_SECONDS.labels(ALIAS, m.version).observe(time.perf_counter() - start)
    return {"duration_minutes": round(max(minutes, 0.5), 2), "model": {"name": MODEL_NAME, "version": m.version, "alias": ALIAS}}


@app.post("/reload")
def reload() -> dict:
    try:
        previous, version = server.reload()
    except Exception as e:
        raise HTTPException(503, f"can't reload {ALIAS}: {type(e).__name__}: {e}"[:300]) from e
    return {"alias": ALIAS, "version": version, "previous_version": previous, "changed": previous != version}
