# S0: security groups and rules.
#
# Decision point: who may reach the app (ingress scope)? Record it in decisions/.
# Traffic between hosts (ports in contracts/runtime.yaml):
#   app -> platform  MLflow
#   app, platform -> llm  chat and embeddings
#   app, platform -> rds  Postgres
# There is no SSH in this lab: use SSM Session Manager for a shell and port forwarding for UIs.
