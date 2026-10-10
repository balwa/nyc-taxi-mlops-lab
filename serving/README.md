# serving/

Model serving (given in S3), the contract is `contracts/serving-openapi.yaml`. One container per MLflow alias: `serving-champion` and `serving-challenger` (`deploy/compose.serving.yaml`), behind Traefik's weighted service on port 8001 (100/0 until S8's canary).

- Loads `models:/trip-duration@<MODEL_ALIAS>` at start-up. Until the alias exists, `/predict` and `/model` answer 503 and the container checks again every 30 s.
- After that it never changes on its own. `POST /reload` (internal: port 8001 is never published) moves it to what the alias points at now; the old model answers until the new one has loaded and warmed up. Restarting the container also works, with a gap. Which one promotion uses is decision 010.
- It doesn't install `tripmodel`: every model carries its own copy (MLflow `code_paths`). LightGBM, pandas and NumPy must match the pipeline's pins, because models are pickles; `make check` compares the two lock files (`tools/check_pins.py`).

Tests: `make test-serving` registers real models in a local MLflow (SQLite) and checks every response against the contract.
