#!/usr/bin/env bash
# Copy the current Learner Lab session credentials into this repo's GitHub Actions secrets.
#
#   export AWS_ACCESS_KEY_ID=... AWS_SECRET_ACCESS_KEY=... AWS_SESSION_TOKEN=...   (AWS Details)
#   scripts/gh-secrets.sh
#
# Only workflows that call AWS from a GitHub-hosted runner need these (the S10 destroy workflow).
# CI only builds and pushes images, and CD runs on your app host with its instance profile, so
# neither uses them. Session credentials die with the session: re-run after Start Lab when needed.
# Values go to gh on stdin, never on the command line, and are never printed.
set -euo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""

for v in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN; do
  [[ -n "${!v:-}" ]] || { echo "export $v first (Learner Lab > AWS Details)" >&2; exit 1; }
done
arn=$(aws sts get-caller-identity --query Arn --output text) ||
  { echo "these credentials are rejected (expired session?)" >&2; exit 1; }
[[ "$arn" == *":assumed-role/voclabs/"* ]] ||
  { echo "refusing: $arn is not a Learner Lab identity" >&2; exit 1; }

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner)
for v in AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN; do
  printf '%s' "${!v}" | gh secret set "$v" --repo "$repo"
done
gh variable set AWS_REGION --repo "$repo" --body us-east-1
fp=$(printf '%s' "$AWS_ACCESS_KEY_ID" | { shasum -a 256 2>/dev/null || sha256sum; } | cut -c1-12)
echo "updated AWS_* secrets on $repo (key fingerprint $fp, valid until this session ends)"
