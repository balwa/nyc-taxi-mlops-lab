# Dagster image: code location, webserver and daemon (Compose runs it three ways). arm64, like every
# lab host. Build from the repo root, since the pipeline reads contracts/:
#   docker build -f pipelines/Dockerfile .
FROM ghcr.io/astral-sh/uv:0.12.15 AS uv

FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pipelines/pyproject.toml pipelines/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY pipelines/src ./src
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim-bookworm
# libgomp1: LightGBM's OpenMP runtime (S2), absent from the slim image.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --home-dir /opt/dagster dagster \
 && mkdir -p /opt/dagster/home/storage && chown -R dagster /opt/dagster
COPY --from=build /app/.venv /app/.venv
COPY contracts /app/contracts
COPY pipelines/dagster.yaml pipelines/workspace.yaml /opt/dagster/home/
# OMP_WAIT_POLICY=PASSIVE: LightGBM's OpenMP threads sleep instead of spinning after a batch, which
# otherwise steals the host's two cores from the next single-row prediction (p95 3.9 -> 19.6 ms on AWS).
ENV PATH=/app/.venv/bin:$PATH DAGSTER_HOME=/opt/dagster/home LAB_CONTRACTS_DIR=/app/contracts MLFLOW_DISABLE_AGENT_HINT=1 \
    OMP_WAIT_POLICY=PASSIVE
ARG GIT_SHA=unknown
ENV GIT_SHA=$GIT_SHA
USER dagster
WORKDIR /opt/dagster/home
ENTRYPOINT ["python", "-m", "labpipes.runtime"]
CMD ["dagster", "code-server", "start", "-h", "0.0.0.0", "-p", "4000", "-m", "labpipes.definitions"]
