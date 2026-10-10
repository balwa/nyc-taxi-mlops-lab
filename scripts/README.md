# scripts/

- `register-runner.sh [app|platform|llm]`: register a host as a self-hosted runner over SSM (S0 builds this).
- `gh-secrets.sh`: copy session credentials into GitHub secrets, only for workflows that call AWS from GitHub-hosted runners (S10's destroy). CI and CD don't need it.
- `catch-up.sh N`: rebuild infrastructure and pipeline state for `stage-N`.
- `health.sh` (S4, given): read-only, one line per piece of the lab, exit 0 only when all are OK. Start every morning and every incident with it.
- `verify-teardown.sh` (S10, given): every billable thing left in us-east-1 and us-west-2, one line each; you're done when it prints nothing.
- `restore.sh` (your S4 automation, in the reference): bring the lab back after a session end.
