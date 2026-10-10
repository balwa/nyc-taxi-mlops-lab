"""Container entrypoint: put Dagster's storage credentials in the environment, then run the command.

  python -m labpipes.runtime COMMAND...    e.g. dagster-webserver -h 0.0.0.0 -p 3000 -w workspace.yaml
  python -m labpipes.runtime --init-db     create the databases in LAB_DATABASES if missing, then exit
  python -m labpipes.runtime --mlflow-server   MLflow's tracking server on port 5000 (S2)

The RDS credentials come from Secrets Manager (RDS_SECRET_NAME, default lab/rds) at start-up, through
the host's instance profile. They're never in a Compose file, the image or the repo, and a restart
picks up a rotation.
"""

import json
import os
import re
import sys

import boto3


def storage_env() -> dict[str, str]:
    if all(os.environ.get(k) for k in ("DAGSTER_PG_HOST", "DAGSTER_PG_USERNAME", "DAGSTER_PG_PASSWORD")):
        # Local runs (a laptop Postgres): credentials already in the environment, no Secrets Manager.
        return {k: os.environ[k] for k in ("DAGSTER_PG_HOST", "DAGSTER_PG_USERNAME", "DAGSTER_PG_PASSWORD")} | {
            "DAGSTER_PG_DB": os.environ.get("DAGSTER_PG_DB", "dagster"),
            "LAB_PG_ADMIN_DB": os.environ.get("LAB_PG_ADMIN_DB", "postgres"),
        }
    name = os.environ.get("RDS_SECRET_NAME", "lab/rds")
    sm = boto3.client("secretsmanager", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    s = json.loads(sm.get_secret_value(SecretId=name)["SecretString"])
    return {
        "DAGSTER_PG_HOST": s["host"],
        "DAGSTER_PG_USERNAME": s["username"],
        "DAGSTER_PG_PASSWORD": s["password"],
        "DAGSTER_PG_DB": os.environ.get("DAGSTER_PG_DB", "dagster"),
        "LAB_PG_ADMIN_DB": s.get("dbname", "postgres"),
    }


def init_db(env: dict[str, str]) -> None:
    import psycopg2  # from dagster-postgres

    conn = psycopg2.connect(
        host=env["DAGSTER_PG_HOST"], user=env["DAGSTER_PG_USERNAME"], password=env["DAGSTER_PG_PASSWORD"],
        dbname=env["LAB_PG_ADMIN_DB"], connect_timeout=10,
    )
    # CREATE DATABASE can't run in a transaction. Not `with conn:`: since psycopg2 2.9 that opens a
    # transaction even on an autocommit connection.
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            for db in os.environ.get("LAB_DATABASES", env["DAGSTER_PG_DB"]).split(","):
                if not re.fullmatch(r"[a-z_][a-z0-9_]*", db):
                    raise SystemExit(f"bad database name {db!r}")
                cur.execute("select 1 from pg_database where datname = %s", (db,))
                if cur.fetchone():
                    print(f"database {db} exists")
                else:
                    cur.execute(f'create database "{db}"')
                    print(f"created database {db}")
    finally:
        conn.close()


def mlflow_server(env: dict[str, str]) -> None:
    """MLflow's tracking server: runs in the `mlflow` database, artifacts in the student's bucket,
    served through the server (clients need no S3 access). The database URI goes in the
    environment, not the command line."""
    from urllib.parse import quote

    bucket = os.environ["LAB_ARTIFACT_BUCKET"]
    env["MLFLOW_BACKEND_STORE_URI"] = (
        f"postgresql+psycopg2://{quote(env['DAGSTER_PG_USERNAME'])}:{quote(env['DAGSTER_PG_PASSWORD'])}"
        f"@{env['DAGSTER_PG_HOST']}:5432/mlflow"
    )
    # Host headers MLflow accepts (DNS-rebinding guard): the Compose name, loopback, and the default
    # VPC's private range, which is how the app host's serving (S3) reaches it.
    env.setdefault("MLFLOW_SERVER_ALLOWED_HOSTS", "mlflow,mlflow:*,localhost,localhost:*,127.0.0.1,127.0.0.1:*,172.31.*")
    cmd = ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", "--workers", os.environ.get("MLFLOW_WORKERS", "2"),
           "--serve-artifacts", "--artifacts-destination", f"s3://{bucket}/mlflow"]
    os.execvpe(cmd[0], cmd, os.environ | env)


def main(argv: list[str]) -> None:
    env = storage_env()
    if argv == ["--init-db"]:
        init_db(env)
        return
    if argv == ["--mlflow-server"]:
        mlflow_server(env)
        return
    if not argv:
        raise SystemExit("usage: python -m labpipes.runtime COMMAND... | --init-db")
    os.execvpe(argv[0], argv, os.environ | env)


if __name__ == "__main__":
    main(sys.argv[1:])
