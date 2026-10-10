#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# ///
"""Models are pickles: serving must unpickle them with the libraries the pipeline trained them with.
Fails if serving/uv.lock and pipelines/uv.lock disagree on any of them."""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHARED = ["lightgbm", "pandas", "numpy", "mlflow-skinny", "cloudpickle", "scikit-learn"]


def locked(lock: Path) -> dict[str, str]:
    return dict(re.findall(r'\[\[package\]\]\nname = "([^"]+)"\nversion = "([^"]+)"', lock.read_text()))


def main() -> int:
    if not (ROOT / "serving" / "uv.lock").exists():
        return 0
    pipe, serve = locked(ROOT / "pipelines" / "uv.lock"), locked(ROOT / "serving" / "uv.lock")
    bad = [f"{p}: pipelines {pipe[p]}, serving {serve[p]}" for p in SHARED if p in pipe and p in serve and pipe[p] != serve[p]]
    for b in bad:
        print(f"pin mismatch: {b} (models trained by one can't be trusted to load in the other)", file=sys.stderr)
    if not bad:
        print(f"pins ok: {', '.join(f'{p} {serve[p]}' for p in SHARED if p in serve)}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
