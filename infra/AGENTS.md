# AGENTS.md: infra/

The root AGENTS.md applies here too.

- `modules/` is given: `host` (EC2 + Elastic IP + Docker, no SSH), `rds`, `bucket` (CLI-backed, because `aws_s3_bucket` fails in Learner Lab), `secret`, `redshift` (S1), `notebook` (S2: SageMaker, LabRole, in the VPC). Wire them in `live/`. Change a module only if the student asks.
- State lives in S3 with native locking. Run `bootstrap/state-bucket.sh` once per account, then `terraform -chdir=infra/live init -backend-config=backend.hcl`. Never commit `backend.hcl`, `terraform.tfvars` or state.
- Hosts use `LabInstanceProfile`; roles are referenced by ARN (`arn:aws:iam::<account>:role/LabRole`), never created.
- Allowed sizes: EC2 up to `large` (Graviton by default), RDS `db.t4g`/`db.t3` up to `medium` on `gp2`, Redshift `ra3.large` with at most 2 nodes.
- Every resource carries the provider's default tags. Don't remove them; teardown finds resources by tag.
- UIs without opening ports: `aws ssm start-session --target <instance-id> --document-name AWS-StartPortForwardingSession --parameters portNumber=3000,localPortNumber=3000`.
- `terraform plan` is always fine. `apply` and `destroy` need the student's confirmation.
- Check word for `make agent-check`: `lab-rules-infra`.
