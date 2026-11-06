#!/usr/bin/env python3
"""Reproducible test runner with full baseline and impact-based follow-up runs."""
import argparse
import json
import os
import platform
import shlex
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_PYTHON = ROOT / "backend/.venv/bin/python"
PYTHON = str(VENV_PYTHON if VENV_PYTHON.exists() else Path(sys.executable))


def pytest_command(paths, junit):
    return [PYTHON, "-m", "pytest", *paths, "-q", f"--junitxml={junit}"]


def groups(run_dir):
    return {
        "python-full": [{
            "name": "python-full",
            "command": pytest_command(["backend"], run_dir / "pytest.xml"),
            "junit": str(run_dir / "pytest.xml"),
        }],
        "ai": [{
            "name": "ai-deterministic",
            "command": pytest_command([
                "backend/test_ai.py",
                "backend/test_ai_transport.py",
                "backend/test_ai_integration.py",
                "backend/test_live_eval_contract.py",
                "backend/test_native_e2e_contract.py",
            ], run_dir / "pytest-ai.xml"),
            "junit": str(run_dir / "pytest-ai.xml"),
        }],
        "cad": [{
            "name": "cad-document-worker",
            "command": pytest_command([
                "backend/test_worker.py",
                "backend/test_worker_control.py",
                "backend/test_templates.py",
                "backend/test_extended_modeling.py",
                "backend/test_document_integration.py",
                "backend/test_face_offset.py",
                "backend/test_split_bodies.py",
                "backend/test_full_regressions.py",
                "backend/test_body_resize.py",
                "backend/test_designer.py",
                "backend/test_parameter_expressions.py",
            ], run_dir / "pytest-cad.xml"),
            "junit": str(run_dir / "pytest-cad.xml"),
        }],
        "help": [
            {
                "name": "help-tests",
                "command": pytest_command(
                    ["backend/test_help_contract.py"], run_dir / "pytest-help.xml"),
                "junit": str(run_dir / "pytest-help.xml"),
            },
            {
                "name": "help-search-contract",
                "command": ["npm", "run", "test:help", "--prefix", "app/ui"],
            },
            {"name": "help-integrity", "command": [PYTHON, "scripts/check_help.py"]},
        ],
        "release": [
            {
                "name": "release-tests",
                "command": pytest_command(
                    ["backend/test_release_contract.py"], run_dir / "pytest-release.xml"),
                "junit": str(run_dir / "pytest-release.xml"),
            },
            {"name": "release-version", "command": [PYTHON, "scripts/check_release_version.py"]},
        ],
        "traceability": [
            {
                "name": "traceability-tests",
                "command": pytest_command(
                    ["backend/test_traceability.py"], run_dir / "pytest-traceability.xml"),
                "junit": str(run_dir / "pytest-traceability.xml"),
            },
            {"name": "traceability-structure", "command": [PYTHON, "scripts/check_test_manifest.py"]},
        ],
        "perf": [{
            "name": "perf-harness-contract",
            "command": pytest_command(
                ["backend/test_perf_contract.py"], run_dir / "pytest-perf.xml"),
            "junit": str(run_dir / "pytest-perf.xml"),
        }],
        "ci": [{
            "name": "ci-routing-contract",
            "command": pytest_command(
                ["backend/test_ci_routing.py"], run_dir / "pytest-ci.xml"),
            "junit": str(run_dir / "pytest-ci.xml"),
        }],
        "ui": [
            {"name": "native-ipc-argument-contract", "command": ["npm", "run", "test:ipc", "--prefix", "app/ui"]},
            {"name": "geometry-control-contract", "command": ["npm", "run", "test:geometry", "--prefix", "app/ui"]},
            {"name": "scene-selection-contract", "command": ["npm", "run", "test:selection", "--prefix", "app/ui"]},
            {"name": "mesh-binary-contract", "command": ["npm", "run", "test:mesh", "--prefix", "app/ui"]},
            {"name": "ui-build", "command": ["npm", "run", "build", "--prefix", "app/ui"]},
        ],
        "rust": [{
            "name": "rust-tests",
            "command": ["cargo", "test", "--manifest-path", "app/src-tauri/Cargo.toml"],
        }],
    }


def changed_paths(explicit_paths):
    if explicit_paths is not None:
        return explicit_paths
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    untracked = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return sorted(set(result.stdout.splitlines()) | set(untracked.stdout.splitlines()))


def impact_groups(paths):
    selected = set()
    for path in paths:
        if path.startswith(("scripts/ai_planner.py", "scripts/dev_shim.py", "backend/test_ai", "tests/live_eval/")):
            selected.add("ai")
        if path.startswith(("scripts/dev_shim.py", "backend/worker.py", "backend/test_worker", "backend/test_templates.py", "backend/test_extended_modeling.py", "backend/test_document", "backend/test_face_offset.py", "backend/test_split_bodies.py", "backend/test_full_regressions.py", "backend/test_parameter_expressions.py", "backend/parameter_expressions.py", "tests/fixtures/")):
            selected.add("cad")
        if path in {"backend/test_body_resize.py", "backend/test_designer.py", "backend/designer_actions.py", "scripts/run_designer_sidecar_smoke.py"}:
            selected.add("cad")
        if path == "scripts/run_designer_sidecar_smoke.py":
            selected.add("release")
        if path in {"backend/worker.py", "backend/parameter_expressions.py", "backend/test_parameter_expressions.py", "backend/test_full_regressions.py"}:
            selected.update({"ai", "cad"})
        if path in {"app/ui/src/documentState.ts", "app/ui/src/parameterEditing.ts", "app/ui/src/expr.ts"}:
            selected.update({"ai", "cad", "ui"})
        if path.startswith(("app/ui/src/lessonEngine", "app/ui/src/tooltipController", "app/ui/src/revealCommand", "app/ui/src/HelpPanel", "app/ui/src/Tooltips", "app/ui/test/lessonEngine", "app/ui/test/tooltipController")):
            selected.update({"help", "ui"})
        if path.startswith(("docs/help/", "app/shared/commands", "app/shared/lessons", "app/ui/public/help", "app/ui/public/lessons", "app/ui/src/helpSearch", "app/ui/test/helpSearch", "backend/test_help")):
            selected.update({"help", "ui"})
        if path.startswith(("app/src-tauri/src/ai.rs",)):
            selected.update({"ai", "rust"})
        if path == "app/src-tauri/src/main.rs":
            selected.update({"ai", "cad", "rust"})
        if path.startswith("app/ui/src/Ai") or path in {"app/ui/src/backend.ts", "app/ui/src/types.ts"}:
            selected.update({"ai", "ui"})
        elif path.startswith("app/ui/"):
            selected.add("ui")
        if path.startswith(("app/src-tauri/tauri", ".github/workflows/release", "scripts/build_sidecar", "scripts/check_release_version", "scripts/run_windows_release_evidence", "backend/test_release", "LICENSE")):
            selected.add("release")
        if path in {"app/package.json", "app/package-lock.json", "app/ui/package.json", "app/ui/package-lock.json", "app/src-tauri/Cargo.toml", "app/src-tauri/Cargo.lock"}:
            selected.add("release")
        if path.startswith(("app/src-tauri/", "app/src-tauri/Cargo")):
            selected.add("rust")
        if path.startswith(("docs/testing/", "tests/test_catalog", "scripts/check_test_manifest", "scripts/build_test_manifest", "backend/test_traceability", "REQUIREMENTS.md")):
            selected.add("traceability")
        if path.startswith(("scripts/run_perf_smoke", "scripts/run_ui_perf", "scripts/run_native_perf", "scripts/run_windows_release_evidence", "backend/test_perf_contract")):
            selected.add("perf")
        if path.startswith(("scripts/run_native_ai_cancel_e2e", "backend/test_native_e2e_contract")):
            selected.update({"ai", "ui", "rust"})
        if path.startswith(("scripts/run_ci_test_stage.py", "backend/test_ci_routing.py", ".github/workflows/ci.yml")):
            selected.add("ci")
        if path.startswith(("pytest.ini", "scripts/run_test_stage.py", ".github/workflows/ci.yml", "backend/requirements.txt")):
            selected.update({"ai", "cad", "help", "release", "traceability", "ui", "rust", "ci"})
    return sorted(selected)


def git_commit():
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, check=False,
        capture_output=True, text=True)
    return result.stdout.strip() or None


def run_command(spec, run_dir):
    command = [str(item) for item in spec["command"]]
    log_path = run_dir / f"{spec['name']}.log"
    started = time.time()
    print(f"\n== {spec['name']} ==")
    print("$", shlex.join(command))
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONHASHSEED": "0"},
        )
        assert process.stdout is not None
        for line in process.stdout:
            print(line, end="")
            log.write(line)
        return_code = process.wait()
    return {
        "name": spec["name"],
        "status": "passed" if return_code == 0 else "failed",
        "return_code": return_code,
        "duration_seconds": round(time.time() - started, 3),
        "command": command,
        "log": str(log_path.relative_to(ROOT)),
        "junit": str(Path(spec["junit"]).relative_to(ROOT)) if spec.get("junit") else None,
    }


def declared_gates():
    return [
        {
            "name": "native-e2e",
            "status": "blocked",
            "required_from": "M1",
            "reason": "WebdriverIO/Tauri native harness ещё не внедрён; browser/component test не выдаётся за native evidence.",
        },
        {
            "name": "macos-release-smoke",
            "status": "not_run",
            "required_from": "M2",
            "reason": "Этот runner проверяет source tree; smoke собранного .app выполняется отдельно перед release.",
        },
        {
            "name": "windows-release-smoke",
            "status": "not_run",
            "required_from": "M2",
            "reason": "Требуется Windows runner и собранный NSIS artifact.",
        },
        {
            "name": "live-ai-eval",
            "status": "not_run",
            "required_from": "M3",
            "reason": "Только opt-in: PF_LIVE_AI_EVAL=1; fake provider не считается evidence качества модели.",
        },
        {
            "name": "m4-extended-modeling",
            "status": "partial",
            "required_from": "M4",
            "reason": "Все EXT-001…EXT-012 имеют automated evidence как partial; открытые clauses перечислены в TEST_GAPS.md.",
        },
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--scope",
        choices=["full", "pr", "nightly", "changed", "ai", "cad", "help", "release", "traceability", "perf", "ui", "rust"],
        default="changed",
    )
    parser.add_argument("--paths", nargs="*")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_dir or ROOT / "artifacts/test-runs" / run_id
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir.mkdir(parents=True, exist_ok=True)
    available = groups(run_dir)
    paths = changed_paths(args.paths) if args.scope == "changed" else []
    if args.scope in {"full", "pr", "nightly"}:
        selected = ["python-full", "ui", "rust"]
        extra_commands = [
            {"name": "help-search-contract", "command": ["npm", "run", "test:help", "--prefix", "app/ui"]},
            {"name": "help-integrity", "command": [PYTHON, "scripts/check_help.py"]},
            {"name": "traceability-structure", "command": [PYTHON, "scripts/check_test_manifest.py"]},
            {"name": "release-version", "command": [PYTHON, "scripts/check_release_version.py"]},
        ]
    elif args.scope == "changed":
        selected = impact_groups(paths)
        extra_commands = []
    else:
        selected = [args.scope]
        extra_commands = []

    command_specs = []
    for group in selected:
        command_specs.extend(available[group])
    command_specs.extend(extra_commands)
    seen = set()
    unique_specs = []
    for spec in command_specs:
        if spec["name"] not in seen:
            seen.add(spec["name"])
            unique_specs.append(spec)

    started_at = datetime.now(timezone.utc)
    results = [run_command(spec, run_dir) for spec in unique_specs]
    status = "failed" if any(result["status"] == "failed" for result in results) else "passed"
    report = {
        "schema_version": 1,
        "status": status,
        "scope": args.scope,
        "selected_groups": selected,
        "changed_paths": paths,
        "commit": git_commit(),
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "python": platform.python_version(),
        "results": results,
        "declared_gates": declared_gates(),
    }
    report_path = run_dir / "test-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    latest = ROOT / "artifacts/test-report.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"\nTest stage: {status}; report: {report_path.relative_to(ROOT)}")
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
