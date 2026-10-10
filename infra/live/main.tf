# S0: wire the root module.
#
# Given modules in ../modules:
#   host    one EC2 host per role in contracts/runtime.yaml (platform, app, llm)
#   rds     Postgres for Dagster, MLflow and pgvector
#   bucket  your artifact bucket (never aws_s3_bucket: see AGENTS.md)
#   secret  the lab/wiki secret container
#
# variables.tf has the inputs; outputs.tf must expose what runtime.yaml lists under
# terraform_outputs. Ask your agent to propose the wiring, then check it against those files.
