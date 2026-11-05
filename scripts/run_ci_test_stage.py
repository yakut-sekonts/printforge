#!/usr/bin/env python3
"""Route GitHub events to changed components or an explicit full stage."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMMIT_SHA = re.compile(r"[0-9a-fA-F]{40}")


def git_changed_paths(base: str, head: str) -> list[str]:
    subprocess.run(
        ["git", "cat-file", "-e", f"{base}^{{commit}}"],
        cwd=ROOT, check=True, capture_output=True,
    )
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", base, head, "--"],
        cwd=ROOT, check=True, capture_output=True,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def stage_arguments(event_name: str, event: dict, head: str) -> list[str]:
    if event_name == "schedule":
        return ["--scope", "nightly"]
    if event_name == "pull_request":
        base = event.get("pull_request", {}).get("base", {}).get("sha", "")
    elif event_name == "push":
        base = event.get("before", "")
    else:
        return ["--scope", "full"]
    if (
        not isinstance(base, str)
        or not COMMIT_SHA.fullmatch(base)
        or base == "0" * 40
        or not COMMIT_SHA.fullmatch(head)
    ):
        return ["--scope", "full"]
    try:
        paths = git_changed_paths(base, head)
    except subprocess.CalledProcessError:
        return ["--scope", "full"]
    return ["--scope", "changed", "--paths", *paths]


def main() -> int:
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event = json.loads(Path(event_path).read_text()) if event_path else {}
    arguments = stage_arguments(
        os.environ.get("GITHUB_EVENT_NAME", ""),
        event,
        os.environ.get("GITHUB_SHA", ""),
    )
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts/run_test_stage.py"), *arguments],
        cwd=ROOT, check=False,
    )
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
