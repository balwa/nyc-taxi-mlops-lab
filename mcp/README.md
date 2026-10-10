# mcp/

Given in S7: the MCP server for the support assistant, Streamable HTTP on port 8002 at `/mcp` (`contracts/runtime.yaml`), with the tools in `contracts/mcp-tools.json` (frozen since S0).

- `get_model_info` is done: serving-champion's `/model`, through Traefik's serving entrypoint, pinned by header.
- `predict_duration` and `query_zone_stats` are **yours**: zone names resolve with `zone_id` (the bundled TLC zone list, with suggestions for typos); the warehouse is `Warehouse`, which queries through the Redshift Data API as `MCP_DB_USER` with named parameters only.
- `/healthz` lists the tools; `/healthz?db=1` also asks Redshift what the database user may do. The status workflow shows that to the grader.

Run the tests with `make test-mcp` (serving and Redshift faked). Deployed by `.github/workflows/mcp.yaml` with `deploy/compose.mcp.yaml`, on the `lab` network only: the app reaches it as `http://mcp:8002/mcp`, and nothing outside the host can.
