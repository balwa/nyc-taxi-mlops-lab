#!/usr/bin/env bash
# Rebuild infrastructure and pipeline state for a stage tag, after you've caught up on code.
#
#   git fetch upstream --tags
#   git checkout -B main stage-N && git push --force-with-lease origin main   (your call: replaces your main)
#   scripts/catch-up.sh N
#
# stage-N means "ready to start SN": S0..S(N-1) are done. Every step is idempotent, and anything
# that creates AWS resources asks first (terraform apply prompts).
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""

n=${1:?usage: scripts/catch-up.sh N}
root="$(cd "$(dirname "$0")/.." && pwd)"
repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)

after_s0() {
  echo "== S0: state bucket, infrastructure, runner, first deploy"
  "$root/infra/bootstrap/state-bucket.sh"
  terraform -chdir="$root/infra/live" init -input=false -backend-config=backend.hcl
  [[ -f "$root/infra/live/terraform.tfvars" ]] ||
    { echo "create infra/live/terraform.tfvars from terraform.tfvars.example first" >&2; exit 1; }
  terraform -chdir="$root/infra/live" apply
  echo "waiting for the app host to finish bootstrapping"
  sleep 90
  "$root/scripts/register-runner.sh" app
  gh workflow run ci.yaml --repo "$repo" --ref main
  echo "CI started on main; CD deploys when it succeeds. Watch: gh run watch --repo $repo"
}

# S1's infrastructure (warehouse.tf) is already in the apply above.
after_s1() {
  echo "== S1: platform runner, Dagster deploy; the sensor then loads every month under trips/"
  "$root/scripts/register-runner.sh" platform
  gh variable set LAB_PLATFORM --repo "$repo" --body on
  gh variable set LAB_DATA_BUCKET --repo "$repo" --body "$LAB_DATA_BUCKET"
  gh variable set LAB_ARTIFACT_BUCKET --repo "$repo" --body "$(terraform -chdir="$root/infra/live" output -raw artifact_bucket)"
  gh workflow run platform.yaml --repo "$repo" --ref main
  echo "platform deploy started. Watch: gh run watch --repo $repo; then open Dagster (deploy/compose.platform.yaml)"
}

# Fail before any apply, not after it.
if ((n >= 2)); then : "${LAB_DATA_BUCKET:?export LAB_DATA_BUCKET=<the data bucket from the instructor> first}"; fi

# S2's notebook is in the same apply; then features for every month, and a first challenger.
after_s2() {
  echo "== S2: re-run each month's ingest (idempotent) so trip_features exists for all of them, then train"
  local m
  for m in $(aws s3 ls "s3://$LAB_DATA_BUCKET/trips/" | grep -o 'yellow_tripdata_[0-9-]*\.parquet' | grep -o '[0-9]\{4\}-[0-9]\{2\}'); do
    "$root/scripts/dagster-run.sh" ingest_month --partition "$m" --wait
  done
  "$root/scripts/dagster-run.sh" train_model --wait
}

# Fail before any apply, not after it.
if ((n >= 3)); then
  grep -q '^github_repo' "$root/infra/live/terraform.tfvars" 2>/dev/null ||
    { echo "set github_repo = \"<owner>/<repo>\" in infra/live/terraform.tfvars first (the S2 notebook clones it)" >&2; exit 1; }
fi

# S3's output (platform_private_ip) is in the same apply. Serving, the blue-green web stack, the
# production environment, then a promotion that waits for your approval.
after_s3() {
  echo "== S3: serving, blue-green app, production environment, promotion"
  gh variable set MLFLOW_TRACKING_URI --repo "$repo" --body "http://$(terraform -chdir="$root/infra/live" output -raw platform_private_ip):5000"
  gh variable set LAB_SERVING --repo "$repo" --body on
  gh api -X PUT "repos/$repo/environments/production" --input - >/dev/null \
    <<<"{\"reviewers\": [{\"type\": \"User\", \"id\": $(gh api user -q .id)}], \"prevent_self_review\": false}"
  gh workflow run serving.yaml --repo "$repo" --ref main
  gh workflow run ci.yaml --repo "$repo" --ref main  # CD then deploys with the blue-green stack
  gh workflow run promote.yaml --repo "$repo" --ref main
  echo "approve the promote run (Actions > promote > Review deployments) to make the challenger champion"
}

after_s4() {
  echo "== S4: restore after a session end (the platform workflow already deployed the wake service)"
  "$root/scripts/restore.sh"
}

after_s5() {
  echo "== S5: Grafana Cloud secret, Alloy on both hosts, SLO rules"
  if ! aws secretsmanager get-secret-value --secret-id lab/grafana --query VersionId --output text >/dev/null 2>&1; then
    echo "lab/grafana has no value yet. From your Grafana Cloud stack (stages/S5.md, step 1):" >&2
    echo "  aws secretsmanager put-secret-value --secret-id lab/grafana --secret-string '{\"url\": ..., \"user\": ..., \"token\": ...}'" >&2
    echo "then run scripts/catch-up.sh $n again." >&2
    exit 1
  fi
  gh variable set LAB_OBSERVABILITY --repo "$repo" --body on
  gh workflow run observability.yaml --repo "$repo" --ref main
}

after_s6() {
  echo "== S6: LLM host, wiki and Langfuse secrets, redeploys, wiki ingestion"
  for secret in lab/wiki lab/langfuse; do
    aws secretsmanager get-secret-value --secret-id "$secret" --query VersionId --output text >/dev/null 2>&1 ||
      { echo "$secret has no value yet: see stages/S6.md (steps 2 and 5), then run scripts/catch-up.sh $n again" >&2; exit 1; }
  done
  "$root/scripts/register-runner.sh" llm
  gh variable set LAB_LLM --repo "$repo" --body on
  gh variable set LLM_HOST --repo "$repo" --body "$(terraform -chdir="$root/infra/live" output -raw llm_private_ip)"
  gh workflow run llm.yaml --repo "$repo" --ref main
  gh workflow run platform.yaml --repo "$repo" --ref main  # LLM_HOST and the rag database
  gh workflow run ci.yaml --repo "$repo" --ref main        # CD redeploys the app with LLM_HOST
  echo "when the llm and platform runs are green: scripts/dagster-run.sh ingest_wiki --wait"
}

after_s7() {
  echo "== S7: the MCP server, its read-only database user"
  gh variable set LAB_MCP --repo "$repo" --body on
  "$root/scripts/dagster-run.sh" mcp_reader_job --wait
  gh workflow run mcp.yaml --repo "$repo" --ref main
  gh workflow run ci.yaml --repo "$repo" --ref main  # CD redeploys the app (MCP_URL, the tool loop)
}

after_s8() {
  echo "== S8: gameday responses are per cohort; redeploy the platform (retrain_on_drift) and put serving back on the champion"
  gh workflow run platform.yaml --repo "$repo" --ref main
  echo "on the app host, if a canary was left half-way: deploy/web.sh serving-weights 100 0"
}

case $n in
  0) echo "stage-0 is the starter: nothing to rebuild" ;;
  1) after_s0 ;;
  2) after_s0; after_s1 ;;
  3) after_s0; after_s1; after_s2 ;;
  4) after_s0; after_s1; after_s2; after_s3 ;;
  5) after_s0; after_s1; after_s2; after_s3; after_s4 ;;
  6) after_s0; after_s1; after_s2; after_s3; after_s4; after_s5 ;;
  7) after_s0; after_s1; after_s2; after_s3; after_s4; after_s5; after_s6 ;;
  8) after_s0; after_s1; after_s2; after_s3; after_s4; after_s5; after_s6; after_s7 ;;
  9 | 10) after_s0; after_s1; after_s2; after_s3; after_s4; after_s5; after_s6; after_s7; after_s8 ;;
  *)
    after_s0; after_s1; after_s2; after_s3; after_s4; after_s5; after_s6; after_s7; after_s8
    echo "catch-up for stages after S9 arrives with those stages" >&2
    exit 2
    ;;
esac
