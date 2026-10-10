#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pyyaml==6.0.3"]
# ///
"""Repo-specific workflow rules that actionlint doesn't know about. The repo is public, so:

1. A job on a self-hosted runner never runs for pull_request or pull_request_target: a fork's PR
   would execute arbitrary code on your EC2 host with LabRole.
2. pull_request_target is not used at all.
3. Every workflow declares top-level `permissions` (least privilege for GITHUB_TOKEN).
4. Every `uses:` is pinned to a version (no @main, @master or bare action names).
5. A self-hosted job triggered by workflow_run must check both workflow_run.event and
   workflow_run.head_repository: otherwise a fork's PR CI run (even from a branch named main)
   can trigger it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
UNSAFE = {"pull_request", "pull_request_target"}


def triggers(doc: dict) -> set[str]:
    on = doc.get("on", doc.get(True))  # YAML 1.1 parses a bare `on:` key as True
    if isinstance(on, str):
        return {on}
    if isinstance(on, list):
        return set(on)
    if isinstance(on, dict):
        return set(on)
    return set()


def self_hosted(runs_on) -> bool:
    if isinstance(runs_on, str):
        return runs_on == "self-hosted"
    if isinstance(runs_on, list):
        return "self-hosted" in runs_on
    if isinstance(runs_on, dict):  # {group: ..., labels: [...]}
        labels = runs_on.get("labels", [])
        return "group" in runs_on or "self-hosted" in (labels if isinstance(labels, list) else [labels])
    return False


def check(path: Path) -> list[str]:
    doc = yaml.safe_load(path.read_text()) or {}
    errs: list[str] = []
    on = triggers(doc)
    if "pull_request_target" in on:
        errs.append("uses pull_request_target")
    if "permissions" not in doc:
        errs.append("no top-level `permissions:`")
    for name, job in (doc.get("jobs") or {}).items():
        if self_hosted(job.get("runs-on")) and on & UNSAFE:
            errs.append(f"job {name} runs on a self-hosted runner but the workflow triggers on {sorted(on & UNSAFE)}")
        guard = str(job.get("if", ""))
        if self_hosted(job.get("runs-on")) and "workflow_run" in on and not (
            "workflow_run.event" in guard and "workflow_run.head_repository" in guard
        ):
            errs.append(f"job {name}: self-hosted and triggered by workflow_run without checking the triggering event and repository")
        for step in job.get("steps", []) or []:
            uses = step.get("uses")
            if uses and not uses.startswith(("./", "docker://")):
                ref = uses.partition("@")[2]
                if not ref or ref in {"main", "master", "HEAD"}:
                    errs.append(f"job {name}: `{uses}` is not pinned to a version")
    return [f"{path.name}: {e}" for e in errs]


def main() -> int:
    files = sorted(list(WORKFLOWS.glob("*.yml")) + list(WORKFLOWS.glob("*.yaml"))) if WORKFLOWS.exists() else []
    errors = [e for f in files for e in check(f)]
    for e in errors:
        print(f"workflow error: {e}", file=sys.stderr)
    if not errors:
        print(f"workflow rules ok ({len(files)} workflow files)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
