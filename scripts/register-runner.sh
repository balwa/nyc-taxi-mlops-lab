#!/usr/bin/env bash
# S0: register the app host as a self-hosted GitHub Actions runner (label: lab-app, from
# contracts/runtime.yaml), so the CD workflow can deploy with the host's instance profile.
#
# Decision point: instance profile vs static credentials for the runner. Record it in decisions/.
# Constraints: no SSH in this lab (use SSM), never commit or print tokens. The repo is public, so
# set fork-PR workflow approval to all external contributors before the runner exists.
echo "scripts/register-runner.sh is not written yet (S0)" >&2
exit 1
