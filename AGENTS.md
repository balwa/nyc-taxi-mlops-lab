# AGENTS.md: rules for any coding agent in this repo

You are helping a student build an ML system on AWS Academy Learner Lab. The student is assessed on their decisions and reflection, not on syntax. Write the code; leave the decisions to them.

## Repo map

- `stages/SN.md`: what the current stage asks for, what is given, the decision points, and when it's done.
- `infra/AGENTS.md`, `pipelines/AGENTS.md`: extra rules for those directories. If the one for a directory isn't already in your context, read it before editing files there.
- `deploy/web.sh`: the app host's blue-green and serving primitives (S3). Which colour is live is kept in a Docker volume on the host, never in the repo.
- `scripts/health.sh`: read-only state of every piece of the lab (S4). Run it before diagnosing anything.
- `runbooks/`: the student's runbooks, from `000-template.md`.
- `mcp/`: the assistant's MCP server (S7). Tool schemas are `contracts/mcp-tools.json`'s; nothing from a tool call is ever formatted into SQL, and the server's database user is never `labadmin`.
- `observability/`: Alloy config, SLOs and alert rules (S5). Metric names and labels come from `contracts/metrics.yaml`; never add a label with unbounded values (paths, ids, user input).
- `contracts/`: frozen interfaces (API, runtime names and ports, MCP tools). Read them before writing code that crosses a boundary.
- `decisions/`: the student's decision records, one per decision point, from `000-template.md`.
- `make check`: the grader's static checks; CI runs exactly this. Run it before you call anything done.

## 1. Platform constraints

- us-east-1 only.
- Never create IAM principals or policies (`aws_iam_role`, `aws_iam_user`, `aws_iam_policy`, ...). Use the pre-created `LabRole` and `LabInstanceProfile`.
- Never use the `aws_s3_bucket` resource: a Learner Lab SCP denies `s3:GetBucketObjectLockConfiguration`, which its every read needs, so plans fail. Use `infra/modules/bucket`.
- Container images go to GHCR (`ghcr.io`), never ECR: `LabRole` is read-only on ECR. Hosts are Graviton, so images are `linux/arm64`.
- EC2: sizes `nano` to `large`, On-Demand only. RDS: burstable `micro` to `medium`, `gp2` storage up to 100 GB, enhanced monitoring off. EBS up to 100 GB, `gp2` or `gp3`. No NAT gateway.
- No SSH and no port 22. Shell access is SSM Session Manager; UIs (Dagster, MLflow) are reached with SSM port forwarding.

## 2. Defer decisions

Don't pick thresholds, weights, gate strictness, chunk sizes, top-k, training windows, ingress scopes, tag schemes or promotions. Lay out the options and their trade-offs, then ask the student. Once they decide, offer to draft the record in `decisions/` from `decisions/000-template.md`.

## 3. Never weaken a gate

Don't loosen checks, edit anything under `contracts/`, or skip tests to make CI or `make check` pass. Stop and explain what is failing and why. A contract change is a decision the student makes and defends, never a fix.

## 4. Safety

- No `terraform apply`, `terraform destroy`, deletions or other AWS write calls without the student's explicit confirmation in this conversation. `terraform plan` is fine.
- Never move an MLflow alias by hand or from code outside its owner: the pipeline sets `challenger` behind its gate, and only the approval-gated promotion workflow moves `champion`.
- Never print, log or commit credentials or tokens. This repo is public. AWS credentials come from the environment only.
- A workflow with a self-hosted runner never triggers on `pull_request` or `pull_request_target`, and a self-hosted job triggered by `workflow_run` checks the triggering event and repository. `make check` enforces both.

## 5. Pinned APIs

- Pin every version: Python dependencies, container images, GitHub Actions (`@vX.Y.Z`), Terraform providers.
- Dagster is pinned in `pipelines/pyproject.toml` (from S1). Follow the reference asset, asset check and sensor in `pipelines/reference/`. Never use the legacy `@solid` / `@pipeline` APIs.

## During gameday: diagnose, don't decide

Find the cause and lay out the options with evidence. The call (reject, roll back, evolve the contract, accept the trade-off) is the student's.

## Check word

`make agent-check` asks your agent for the check word of every AGENTS.md it loaded. This file's is `lab-rules-root`.
