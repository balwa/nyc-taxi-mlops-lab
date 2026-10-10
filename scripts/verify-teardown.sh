#!/usr/bin/env bash
# Everything that still costs money in this Learner Lab account, in both regions it allows. Read-only
# (S10, given). Prints one line per leftover and exits 1; prints nothing and exits 0 when the account is
# clean. You're done when it prints nothing.
#
#   scripts/verify-teardown.sh
#
# Needs this session's AWS credentials in the environment (the destroy workflow runs it too).
set -uo pipefail
export AWS_PAGER=""
left=0

say() { # REGION KIND ID [DETAIL]
  printf '%s\t%s\t%s%s\n' "$1" "$2" "$3" "${4:+	$4}"
  left=1
}

list() { # REGION KIND -- aws command with --query returning one id (and detail) per line
  local region=$1 kind=$2
  shift 3
  while IFS=$'\t' read -r id detail; do
    [[ -n $id && $id != None ]] && say "$region" "$kind" "$id" "${detail:-}"
  done < <(AWS_REGION=${region/global/us-east-1} "$@" --output text 2>/dev/null)
}

aws sts get-caller-identity >/dev/null 2>&1 || { echo "AWS credentials missing or expired: export this session's" >&2; exit 2; }

for r in us-east-1 us-west-2; do
  list "$r" ec2-instance -- aws ec2 describe-instances --filters Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].[InstanceId, join(`/`, [InstanceType, State.Name])]'
  list "$r" elastic-ip -- aws ec2 describe-addresses --query 'Addresses[].[AllocationId, PublicIp]'
  list "$r" ebs-volume -- aws ec2 describe-volumes --query 'Volumes[].[VolumeId, join(`/`, [State, to_string(Size)])]'
  list "$r" ebs-snapshot -- aws ec2 describe-snapshots --owner-ids self --query 'Snapshots[].[SnapshotId, to_string(VolumeSize)]'
  list "$r" nat-gateway -- aws ec2 describe-nat-gateways --filter Name=state,Values=pending,available --query 'NatGateways[].[NatGatewayId, State]'
  list "$r" load-balancer -- aws elbv2 describe-load-balancers --query 'LoadBalancers[].[LoadBalancerName, Type]'
  list "$r" rds-instance -- aws rds describe-db-instances --query 'DBInstances[].[DBInstanceIdentifier, DBInstanceStatus]'
  list "$r" rds-snapshot -- aws rds describe-db-snapshots --snapshot-type manual --query 'DBSnapshots[].[DBSnapshotIdentifier, Status]'
  list "$r" redshift-cluster -- aws redshift describe-clusters --query 'Clusters[].[ClusterIdentifier, ClusterStatus]'
  list "$r" redshift-snapshot -- aws redshift describe-cluster-snapshots --snapshot-type manual --query 'Snapshots[].[SnapshotIdentifier, Status]'
  list "$r" sagemaker-notebook -- aws sagemaker list-notebook-instances --query 'NotebookInstances[].[NotebookInstanceName, NotebookInstanceStatus]'
  list "$r" secret -- aws secretsmanager list-secrets --query 'SecretList[].[Name, to_string(DeletedDate)]'
done
# Buckets are global; Learner Lab's own buckets (if any) don't start with lab-.
list global s3-bucket -- aws s3api list-buckets --query 'Buckets[?starts_with(Name, `lab-`)].[Name, CreationDate]'
exit $left
