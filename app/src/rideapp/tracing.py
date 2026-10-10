"""Langfuse tracing for the assistant (S6, given; off until configured).

On when /secrets/langfuse.json exists ({"host": "https://cloud.langfuse.com", "public_key": "pk-lf-...",
"secret_key": "sk-lf-..."}): deploy/web.sh copies it there from Secrets Manager (lab/langfuse) at every
deploy. Each /assist becomes one trace: a root span, a span per step and a generation for each LLM call,
sent as OpenTelemetry (OTLP over HTTP, JSON) to Langfuse's /api/public/otel/v1/traces after the response,
so tracing never slows a rider down and a Langfuse outage never fails a request. (Langfuse's older
/api/public/ingestion is deprecated: new organisations don't see what it accepts.)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx2

log = logging.getLogger("rideapp.tracing")
SECRET = Path(os.environ.get("LANGFUSE_SECRET_FILE", "/secrets/langfuse.json"))


def now() -> int:
    return time.time_ns()


def attr(key: str, value: object) -> dict:
    """One OTLP attribute; anything that isn't a scalar goes as a JSON string, which Langfuse parses."""
    if isinstance(value, bool):
        v = {"boolValue": value}
    elif isinstance(value, int):
        v = {"intValue": str(value)}
    elif isinstance(value, float):
        v = {"doubleValue": value}
    elif isinstance(value, str):
        v = {"stringValue": value}
    else:
        v = {"stringValue": json.dumps(value, default=str)}
    return {"key": key, "value": v}


class Trace:
    """Collects one request's spans; nothing is sent until Tracer.send."""

    def __init__(self, name: str, input: object):
        self.id = secrets.token_hex(16)  # an OTLP trace id: 32 hex characters
        self.root_id = secrets.token_hex(8)
        self.name, self.input, self.start = name, input, now()
        self.spans: list[dict] = []

    def _add(self, kind: str, name: str, start: int, input: object, output: object, attributes: list[dict], metadata: dict,
             span_id: str | None = None, parent: str | None = None) -> None:
        attrs = [attr("langfuse.observation.type", kind)] + attributes
        attrs += [attr("langfuse.observation.input", input)] if input is not None else []
        attrs += [attr("langfuse.observation.output", output)] if output is not None else []
        attrs += [attr(f"langfuse.observation.metadata.{k}", v) for k, v in metadata.items() if v is not None]
        span = {"traceId": self.id, "spanId": span_id or secrets.token_hex(8), "name": name, "kind": 1,
                "startTimeUnixNano": str(start), "endTimeUnixNano": str(now()), "attributes": attrs}
        if parent:
            span["parentSpanId"] = parent
        self.spans.append(span)

    def span(self, name: str, start: int, input: object = None, output: object = None, **metadata) -> None:
        self._add("span", name, start, input, output, [], metadata, parent=self.root_id)

    def generation(self, name: str, start: int, model: str, input: object, output: object, usage: dict | None = None, **metadata) -> None:
        attrs = [attr("langfuse.observation.model.name", model)]
        for key, field in (("gen_ai.usage.input_tokens", "prompt_tokens"), ("gen_ai.usage.output_tokens", "completion_tokens")):
            if (usage or {}).get(field) is not None:
                attrs.append(attr(key, usage[field]))
        self._add("generation", name, start, input, output, attrs, metadata, parent=self.root_id)

    def end(self, output: object) -> None:
        """Closes the root span, which carries the trace's name, input and output."""
        self._add("span", self.name, self.start, self.input, output, [attr("langfuse.trace.name", self.name)], {}, span_id=self.root_id)

    def payload(self) -> dict:
        return {"resourceSpans": [{"resource": {"attributes": [attr("service.name", "rideapp")]},
                                   "scopeSpans": [{"scope": {"name": "rideapp.tracing"}, "spans": self.spans}]}]}


class Tracer:
    def __init__(self, secret: Path = SECRET):
        self.config = json.loads(secret.read_text()) if secret.exists() else None

    @property
    def enabled(self) -> bool:
        return bool(self.config)

    def start(self, name: str, input: object) -> Trace | None:
        return Trace(name, input) if self.enabled else None

    def send(self, trace: Trace | None) -> None:
        """Fire and forget: ships the trace in the background."""
        if trace is None or not self.enabled:
            return
        asyncio.get_running_loop().create_task(self._post(trace.payload()))

    async def _post(self, payload: dict) -> None:
        c = self.config
        try:
            async with httpx2.AsyncClient(timeout=10) as client:
                r = await client.post(f"{c['host'].rstrip('/')}/api/public/otel/v1/traces", json=payload,
                                      auth=(c["public_key"], c["secret_key"]))
            if r.status_code >= 300:
                log.warning("langfuse otel: HTTP %s %s", r.status_code, r.text[:200])
        except httpx2.HTTPError as e:
            log.warning("langfuse otel failed: %s", e)
