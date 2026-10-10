# Model serving: one MLflow alias per container (MODEL_ALIAS). arm64, like every lab host.
FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm
# libgomp1: LightGBM's OpenMP runtime. OMP_WAIT_POLICY=PASSIVE: idle threads sleep instead of spinning.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 serving
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH OMP_WAIT_POLICY=PASSIVE MLFLOW_DISABLE_AGENT_HINT=1
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
USER serving
EXPOSE 8001
HEALTHCHECK --interval=10s --timeout=3s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8001/healthz', timeout=2)"]
CMD ["uvicorn", "servingapp.main:app", "--host", "0.0.0.0", "--port", "8001"]
