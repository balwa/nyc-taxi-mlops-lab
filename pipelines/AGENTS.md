# AGENTS.md: pipelines/

The root AGENTS.md applies here too.

- Dagster is pinned to 1.13.25 in `pyproject.toml`. Use assets, asset checks, sensors and dynamic partitions. Never `@solid`, `@pipeline`, `@op`/`@job` graphs, or code copied from older Dagster docs; copy shapes from `reference/patterns.py`.
- Every module in `src/labpipes/defs/` is loaded automatically. Put new definitions there; don't edit `definitions.py` to register them.
- Redshift goes through the `RedshiftData` resource (Data API, `--db-user`). Never add a password, a connection string, a secret or `psycopg2`/`redshift_connector` for Redshift. Several statements in one `execute()` call run as one transaction.
- Batch statements take no bind parameters. Anything formatted into SQL must be validated first (`partitions.check_month`, `source_file`).
- Schema names come from `contracts/platform.yaml`: `ingest`, `staging`, `marts`. `raw` is a Redshift reserved word.
- Checks that `contracts/platform.yaml` lists as blocking stay blocking. Which other checks block, and every threshold, are the student's decisions: show the options with real numbers (query Redshift) and ask.
- Assets that write to Redshift use `pool="redshift"`, so concurrent runs don't abort each other with serializable isolation errors.
- Models live in `src/tripmodel/` (no Dagster, no AWS imports: serving loads them too). Inputs are exactly `contracts/features.yaml`; nothing known only after a trip (actual distance, fare, dropoff time) is ever an input.
- MLflow names come from `contracts/mlflow.yaml`. Only the pipeline registers versions and sets `challenger`, and only behind the blocking gate. Never set `champion` (S3's approval-gated workflow does), and never register from a notebook.
- The wiki branch (S6) uses the given `wiki`, `embed` and `rag` resources. Embed documents with the `search_document: ` prefix (the resource adds it) and never change the embedding model without re-embedding everything: vectors from two models aren't comparable. The wiki token lives in Secrets Manager (`lab/wiki`); never put it in code, config or logs.
- Tests use the fakes in `tests/fakes.py` and a local MLflow (SQLite); they never call AWS. Run `make test-pipelines`.
- Check word for `make agent-check`: `lab-rules-pipelines`.
