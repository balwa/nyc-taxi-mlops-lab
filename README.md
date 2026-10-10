# NYC taxi trip-duration: from stub to production-shaped ML system

A ride-hailing app quotes trip times with a static median. Product wants predicted durations, plus a support assistant that explains them. Over two days you build the data, model and deploy pipelines, then operate and extend them.

## Get started (before Day 1, 10:30)

1. **Your own copy**, public (GitHub's approval gates, which you need from S3, only work on public repos):

   ```bash
   gh repo create <your-github-user>/nyc-taxi-mlops-lab --public --template balwa/nyc-taxi-mlops-lab --clone
   cd nyc-taxi-mlops-lab && git remote add upstream https://github.com/balwa/nyc-taxi-mlops-lab.git
   ```

2. **Tools on your laptop** (macOS or Linux; on Windows, work inside WSL): `git`, `gh` (logged in), the AWS CLI v2, Terraform 1.11 or later, `uv`, `make`, `jq`, Docker (optional, for the observability checks) and Claude Code.
3. **Check:** `make check` passes, and `make agent-check` shows that Claude Code loads `AGENTS.md` here and in `infra/` and `pipelines/`. Each `CLAUDE.md` is a link to its `AGENTS.md`: keep it that way. If you run `/init` or edit a `CLAUDE.md`, run `make agent-check` again.

## Where things are

- What to do now: [stages/](stages/), one handout per stage
- Rules for your coding agent: [AGENTS.md](AGENTS.md)
- Frozen interfaces: [contracts/](contracts/)
- Your decision records: [decisions/](decisions/); your runbooks (from S4): [runbooks/](runbooks/)
- `make check` runs the same static checks as the grader (needs `uv`, `terraform`, `make`; with Docker running it also checks the observability rules and Alloy configs, which CI always does).
- What state everything is in: `scripts/health.sh` (from S4).

Falling behind is planned for: `git fetch upstream --tags`, put `stage-N` on your `main`, then `scripts/catch-up.sh N`. `stage-N` means "ready to start SN".
