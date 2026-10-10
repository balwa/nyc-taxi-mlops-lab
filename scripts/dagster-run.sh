#!/usr/bin/env bash
# Start a Dagster job on the platform host from your laptop, and optionally wait for it.
#
#   scripts/dagster-run.sh JOB [--partition KEY] [--wait]
#   e.g. scripts/dagster-run.sh train_model --wait;  scripts/dagster-run.sh ingest_month --partition 2024-03
#
# Goes through SSM Run Command to the webserver's GraphQL API on the host's loopback: no SSH, no open
# port. Needs AWS credentials in the environment and infra/live applied. The run is queued like one
# started from the UI, so the concurrency limits in pipelines/dagster.yaml apply.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""

job=${1:?usage: scripts/dagster-run.sh JOB [--partition KEY] [--wait]}
shift
partition='' wait=''
while [[ $# -gt 0 ]]; do
  case $1 in
    --partition) partition=$2; shift 2 ;;
    --wait) wait=1; shift ;;
    *) echo "unknown argument $1" >&2; exit 2 ;;
  esac
done
[[ "$job" =~ ^[a-z_][a-z0-9_]*$ ]] || { echo "not a job name: $job" >&2; exit 2; }
[[ -z "$partition" || "$partition" =~ ^[0-9]{4}-[0-9]{2}$ ]] || { echo "not a YYYY-MM partition: $partition" >&2; exit 2; }
tags=''
[[ -n "$partition" ]] && tags=", executionMetadata: {tags: [{key: \"dagster/partition\", value: \"$partition\"}]}"
root="$(cd "$(dirname "$0")/.." && pwd)"
iid=$(terraform -chdir="$root/infra/live" output -raw platform_instance_id)

gql() { # QUERY: run it against Dagster on the platform host, print the JSON response. Fails after ~2 min.
  local body params id status tries=0
  body=$(jq -cn --arg q "$1" '{query: $q}')
  params=$(jq -cn --arg c "curl -sS http://127.0.0.1:3000/graphql -H 'Content-Type: application/json' -d '$body'" '{commands: [$c]}')
  id=$(aws ssm send-command --instance-ids "$iid" --document-name AWS-RunShellScript --parameters "$params" \
    --comment "dagster-run $job" --query Command.CommandId --output text) || return 1
  status=Pending
  while [[ "$status" =~ ^(Pending|InProgress|Delayed)$ ]]; do
    ((++tries <= 60)) || { echo "no answer from the platform host via SSM (is it running?)" >&2; return 1; }
    sleep 2
    status=$(aws ssm get-command-invocation --command-id "$id" --instance-id "$iid" --query Status --output text 2>/dev/null || echo Pending)
  done
  [[ "$status" == Success ]] || { echo "SSM command $status" >&2; return 1; }
  aws ssm get-command-invocation --command-id "$id" --instance-id "$iid" --query StandardOutputContent --output text
}

out=$(gql "mutation { launchRun(executionParams: {selector: {repositoryLocationName: \"labpipes\", repositoryName: \"__repository__\", jobName: \"$job\"}, runConfigData: {}$tags}) { __typename ... on LaunchRunSuccess { run { runId } } ... on Error { message } } }")
run=$(jq -r '.data.launchRun.run.runId // empty' <<<"$out")
[[ -n "$run" ]] || { echo "launch failed: $(jq -c '.data.launchRun // .errors' <<<"$out")" >&2; exit 1; }
echo "started $job${partition:+ [$partition]}: run $run (Dagster UI: Runs)"
[[ -n "$wait" ]] || exit 0

status=QUEUED failures=0 deadline=$(($(date +%s) + 3 * 3600))
while [[ ! "$status" =~ ^(SUCCESS|FAILURE|CANCELED)$ ]]; do
  (($(date +%s) < deadline)) || { echo "gave up waiting after 3 hours; the run continues: Dagster UI, run $run" >&2; exit 1; }
  sleep 20
  if out=$(gql "{ runOrError(runId: \"$run\") { ... on Run { status } } }") && [[ -n "$(jq -r '.data.runOrError.status // empty' <<<"$out")" ]]; then
    status=$(jq -r '.data.runOrError.status' <<<"$out") failures=0
    echo "$(date +%H:%M:%S) $status"
  else
    ((++failures < 5)) || { echo "lost contact with Dagster on the platform host; the run may still be going: run $run" >&2; exit 1; }
  fi
done
gql "{ runOrError(runId: \"$run\") { ... on Run { stepStats { stepKey status } } } }" |
  jq -r '.data.runOrError.stepStats[] | "  \(.stepKey): \(.status)"'
[[ "$status" == SUCCESS ]]
