# contracts/

Everything that crosses a boundary. Frozen once written: `make check` validates each file and compares it to `SHA256SUMS`, and the grader compares them with the upstream tag. A contract change is a decision you defend, never a way to make a check pass.

| File | Fixes | Frozen in |
| --- | --- | --- |
| `openapi.yaml` | The app's public API (`/healthz`, `/version`, `/predict`) | S0 |
| `runtime.yaml` | Hosts, services, ports, env var names, image names, data bucket layout, Terraform output names | S0 |
| `mcp-tools.json` | MCP tool schemas (`get_model_info`, `predict_duration`, `query_zone_stats`) | S0, ahead of S7 so the LLM bench uses the real schemas |
| `trips.schema.yaml` | The raw trip files' Parquet schema, which the pre-COPY check enforces | S1 |
| `marts.sql` | Mart DDL (`zone_hour_stats`), matching `query_zone_stats` | S1 |
| `platform.yaml` | Warehouse names and access mode, Dagster storage, partitions, blocking checks, env names, Terraform outputs | S1 |
| `features.yaml` | The model's inputs, label and forbidden post-trip columns; `staging.trip_features` | S2 |
| `mlflow.yaml` | Experiment and registered model names, `champion` / `challenger` aliases, metrics and version tags | S2 |
| `serving-openapi.yaml` | The serving service's API: `/predict` takes `features.yaml`'s inputs, `/model`, `/reload` | S3 |
| `metrics.yaml` | The app's and serving's metric names, types, labels and buckets; Traefik's service label values; the series budget | S5 |
| `assistant-openapi.yaml` | The app's `POST /assist`: question in; answer, wiki sources, tool calls, timings and trace id out | S6 |
