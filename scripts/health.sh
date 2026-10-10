#!/usr/bin/env bash
# One line per piece of the lab: what state it's in, and whether that's what a working lab needs.
# Read-only (S4, given): it changes nothing, so it's safe to run at any time.
#
#   scripts/health.sh
#
# Needs this session's AWS credentials in the environment, gh logged in, and infra/live initialised.
# Exit status: 0 when every line is OK, 1 otherwise.
set -uo pipefail
export AWS_REGION=us-east-1 AWS_DEFAULT_REGION=us-east-1 AWS_PAGER=""
root="$(cd "$(dirname "$0")/.." && pwd)"
bad=0

line() { # STATUS NAME DETAIL
  printf '%-4s  %-12s %s\n' "$1" "$2" "$3"
  [[ $1 == OK ]] || bad=1
}

if ! who=$(aws sts get-caller-identity --query Arn --output text 2>&1); then
  line FAIL session "AWS credentials don't work: export this session's from Learner Lab ($(tail -1 <<<"$who" | cut -c1-80))"
  exit 1
fi
line OK session "${who##*/}"

tfvars="$root/infra/live/terraform.tfvars"
if ip=$(curl -fsS -m 5 https://checkip.amazonaws.com); then
  if grep -q "\"$ip/32\"" "$tfvars" 2>/dev/null; then
    line OK laptop-ip "$ip is in ingress_cidrs"
  else
    line WARN laptop-ip "$ip is not in ingress_cidrs ($tfvars): the app will refuse you"
  fi
fi

repo=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null) || repo=""
runners=$( [[ -n $repo ]] && gh api "repos/$repo/actions/runners" -q '.runners[] | "\(.name)=\(.status)"' 2>/dev/null)
while read -r role state ip; do
  [[ -n $role ]] || continue
  [[ $ip == None ]] && ip=""
  runner=$(grep -o "lab-$role=[a-z]*" <<<"$runners" | cut -d= -f2)
  detail="$state${ip:+, $ip}, runner ${runner:-not registered}"
  # The LLM host gets its runner in S6; until then an unregistered one is fine.
  if [[ $state == running && ( $runner == online || -z $runners || ( -z $runner && $role == llm ) ) ]]; then
    line OK "$role" "$detail"
  else
    line FAIL "$role" "$detail"
  fi
done < <(aws ec2 describe-instances \
  --filters Name=tag:project,Values=mlops-lab Name=instance-state-name,Values=pending,running,stopping,stopped \
  --query 'Reservations[].Instances[].[Tags[?Key==`role`]|[0].Value, State.Name, PublicIpAddress]' --output text 2>/dev/null)

state() { # NAME STATE WANTED HINT
  if [[ $2 == "$3" ]]; then line OK "$1" "$2"; elif [[ $2 == absent ]]; then line WARN "$1" "absent"; else line FAIL "$1" "$2: $4"; fi
}
rds=$(aws rds describe-db-instances --db-instance-identifier lab --query 'DBInstances[0].DBInstanceStatus' --output text 2>/dev/null || echo absent)
state rds "$rds" available "Dagster and MLflow need it (aws rds start-db-instance, ~7 min)"
rs=$(aws redshift describe-clusters --cluster-identifier lab --query 'Clusters[0].ClusterStatus' --output text 2>/dev/null || echo absent)
state redshift "$rs" available "ingestion and the marts need it (aws redshift resume-cluster, ~3 min)"
nb=$(aws sagemaker describe-notebook-instance --notebook-instance-name lab --query NotebookInstanceStatus --output text 2>/dev/null || echo absent)
# Nothing but exploration needs the notebook, so stopped is a working lab (and cheaper).
if [[ $nb == Stopped ]]; then
  line OK notebook "Stopped (when you need it: aws sagemaker start-notebook-instance --notebook-instance-name lab, ~6 min)"
else
  state notebook "$nb" InService "aws sagemaker start-notebook-instance, ~6 min"
fi

if app=$(terraform -chdir="$root/infra/live" output -raw app_public_ip 2>/dev/null); then
  if r=$(curl -fsS -m 10 "http://$app/predict" -H 'Content-Type: application/json' \
      -d '{"pickup_zone_id": 132, "dropoff_zone_id": 230, "pickup_datetime": "2024-03-08T17:05:00"}' 2>&1); then
    who=$(jq -r '.model | "\(.name) \(.alias // "") \(.version)"' <<<"$r")
    if jq -e '.model.alias == "champion"' <<<"$r" >/dev/null; then line OK predict "$who"; else line WARN predict "answering, but from $who (fallback)"; fi
  else
    line FAIL predict "no answer from $app ($(tail -1 <<<"$r" | cut -c1-60))"
  fi
fi

if [[ -n $repo ]]; then
  read -r result age < <(gh api "repos/$repo/actions/workflows/status.yaml/runs?per_page=1" \
    -q '.workflow_runs[0] | "\(.conclusion // .status) \((now - (.created_at | fromdateiso8601)) / 60 | floor)"' 2>/dev/null)
  if [[ $result == success && ${age:-999} -le 40 ]]; then
    line OK status "Dagster answered the status run ${age} min ago"
  elif [[ $result == success ]]; then
    line WARN status "last good status run ${age} min ago: run it now (gh workflow run status.yaml)"
  else
    line FAIL status "last status run: ${result:-none}${age:+ ${age} min ago}: run it now (gh workflow run status.yaml), then read its log"
  fi
fi
exit $bad
