#!/usr/bin/env bash
# Check observability/rules/*.yaml with promtool (and their *.test.yaml unit tests), then load them into
# your Grafana Cloud stack's ruler, one namespace per file (lab-<file>). Namespaces starting with lab-
# that no longer have a file are deleted. (S5, given.)
#
#   observability/push-rules.sh [--check-only]
#
# Credentials come from Secrets Manager (lab/grafana: url, user, token), so it runs on the app host's
# runner (LabRole) or on a laptop with session credentials. The token needs metrics:write and
# rules:write (and rules:read for the sync to compare).
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
cd "$(dirname "$0")/rules"

PROMTOOL=(docker run --rm -v "$PWD:/r:ro" -w /r --entrypoint promtool prom/prometheus:v3.14.0)
MIMIRTOOL_IMAGE=grafana/mimirtool:3.2.1

shopt -s nullglob
rules=() tests=()
for f in *.yaml; do
  if [[ $f == *.test.yaml ]]; then tests+=("$f"); else rules+=("$f"); fi
done
(( ${#rules[@]} )) || { echo "no rule files in observability/rules" >&2; exit 1; }
"${PROMTOOL[@]}" check rules "${rules[@]}"
(( ${#tests[@]} == 0 )) || "${PROMTOOL[@]}" test rules "${tests[@]}"
[[ ${1:-} == --check-only ]] && exit 0

secret=$(aws secretsmanager get-secret-value --secret-id lab/grafana --query SecretString --output text)
address=$(jq -r '.url | sub("/api/prom/push$"; "")' <<<"$secret")
out=$(mktemp -d)
trap 'rm -rf "$out"' EXIT
for f in "${rules[@]}"; do
  { echo "namespace: lab-${f%.yaml}"; cat "$f"; } > "$out/$f"
done
# Passed by name, not value, so the token never appears in a process list.
MIMIR_ADDRESS=$address MIMIR_TENANT_ID=$(jq -r .user <<<"$secret") MIMIR_API_KEY=$(jq -r .token <<<"$secret")
export MIMIR_ADDRESS MIMIR_TENANT_ID MIMIR_API_KEY
docker run --rm -v "$out:/rules:ro" -e MIMIR_ADDRESS -e MIMIR_TENANT_ID -e MIMIR_API_KEY \
  "$MIMIRTOOL_IMAGE" rules sync --namespaces-regex '^lab-' "${rules[@]/#//rules/}"
echo "rules loaded into $address (namespaces lab-*)"
