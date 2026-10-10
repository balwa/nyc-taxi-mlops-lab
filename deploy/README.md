# deploy/

- `compose.app.yaml`: the app host's stack: Traefik on port 80 in front of `app`. `serving` and `mcp` join in S3 and S7. CD runs it with `IMAGE_PREFIX` and `IMAGE_TAG` set; containers restart with Docker after a session refresh.
- `traefik/traefik.yaml`: static config. File provider only, with no Docker socket mounted, so Traefik has no root-equivalent access to the host.
- `traefik/dynamic/`: routing, watched live. S3's blue-green and canary weights go here.
- `compose.platform.yaml` (S1): the platform host's stack: Dagster's code server, webserver (loopback only, reach it with SSM port forwarding) and daemon on the `pipelines` image, plus a one-shot `db-init` that creates the `dagster` database on RDS. The RDS password is read from Secrets Manager when each container starts. MLflow runs from the same image (port 5000, open to the app host and the S2 notebook only): runs in the `mlflow` database, artifacts in your bucket under `mlflow/`. Deployed by `.github/workflows/platform.yaml`.

- `compose.web.yaml` (S3): the app host's stack from S3 on, with the same project name as `compose.app.yaml`, so the first deploy with it replaces S0's containers. Traefik on port 80 and on the internal serving entrypoint (8001, loopback only on the host), and two app colours. Traefik's routes come from `traefik/web/routes.yaml`; the live weights are written into the `lab-traefik` volume by `web.sh`, so a checkout never resets them.
- `compose.serving.yaml` (S3): `serving-champion` and `serving-challenger`, deployed by `.github/workflows/serving.yaml`, on the shared `lab` network.
- The platform stack gains your S4 automation, if you choose to put it there: anything that should run when the host boots (Start Lab) can be a service with `restart: unless-stopped`.
- `compose.llm.yaml` (S6): the LLM host's llama.cpp servers, chat on 8080 and embeddings on 8081, with a one-shot that downloads the pinned models into a volume. Deployed by `.github/workflows/llm.yaml` through the `lab-llm` runner.
- `compose.web.yaml`'s `app-secrets` (S6): a one-shot that `web.sh prepare` runs before every deploy, copying `lab/rds` and `lab/langfuse` into a volume the app reads (`/secrets`).
- `compose.mcp.yaml` (S7): the MCP server on the `lab` network, never published. Deployed by `.github/workflows/mcp.yaml`.
- `compose.observability.yaml` (S5): Alloy on any host (`LAB_HOST=app|platform`), plus a one-shot container that copies `lab/grafana` from Secrets Manager. Deployed by `.github/workflows/observability.yaml`; config in `observability/`.
- `web.sh`: the app host's primitives (`prepare`, `live`, `tag`, `smoke`, `switch`, `serving-weights`, `reload`, `status`). Your CD and promotion workflow call them; they decide when.

Local run: `docker build -t local/app:dev app && IMAGE_PREFIX=local IMAGE_TAG=dev HTTP_PORT=8080 docker compose -f deploy/compose.app.yaml up -d --wait`
