# observability/

Given in S5. Metrics only: LLM tracing (Langfuse) arrives with the assistant in S6.

- `alloy/`: Grafana Alloy's config. `app.alloy` and `platform.alloy` pick what each host scrapes; `common.alloy` has the parts every host shares (the host via node_exporter, every container via cAdvisor, the lab's services, remote write to Grafana Cloud). Everything passes through `budget.alloy`, **yours**: the relabelling that keeps you under the series budget (decision 014). Format with `docker run --rm -v $PWD/observability/alloy:/c grafana/alloy:v1.19.2 fmt -w /c/<file>`; `make check` fails on an unformatted file.
- `rules/`: Prometheus recording and alerting rules, **yours**, and their promtool unit tests (`*.test.yaml`). `make check` runs promtool; the observability workflow loads them into your Grafana Cloud stack's ruler, one namespace per file (`lab-<file>`).
- `slo.yaml`: **yours**: each SLO's SLI, objective and reason (decision 013).
- `dashboards/ride-app.json`: import it in Grafana (Dashboards → New → Import); the SLO row is yours. Export it back over this file when you change it.
- `push-rules.sh`: promtool check and test, then load the rules (needs `lab/grafana` in Secrets Manager).
- `alloy-stats.sh`: what Alloy on this host has sent and had refused, and its active series. The status workflow adds it to both status artifacts.

Deployment: `deploy/compose.observability.yaml` (Alloy plus a one-shot container that copies `lab/grafana` from Secrets Manager), by `.github/workflows/observability.yaml` once `LAB_OBSERVABILITY=on`.

The cost of container metrics: cAdvisor needs the Docker socket, which gives Alloy root-equivalent access to the host. Traefik deliberately has none.
