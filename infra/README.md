# infra/

Given: `modules/` (host, rds, bucket, secret), `live/versions.tf` and `variables.tf`, `bootstrap/state-bucket.sh`.
S0 builds: `live/main.tf` (wiring), `live/security.tf` (security groups), `live/outputs.tf` (names from `contracts/runtime.yaml`).
Decisions: runner credentials; ingress scope.

```bash
infra/bootstrap/state-bucket.sh
cp infra/live/terraform.tfvars.example infra/live/terraform.tfvars   # then edit
terraform -chdir=infra/live init -backend-config=backend.hcl
terraform -chdir=infra/live plan
```
