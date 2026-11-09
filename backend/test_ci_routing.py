import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_ci_test_stage  # noqa: E402
import run_test_stage  # noqa: E402

pytestmark = pytest.mark.contract
BASE = "a" * 40
HEAD = "b" * 40


def test_git_diff_preserves_spaces_and_newlines_in_file_names(monkeypatch):
    commands = []

    def git_result(command, **_options):
        commands.append(command)
        return SimpleNamespace(stdout=b"app/ui/a file.ts\0docs/a\nfile.md\0")

    monkeypatch.setattr(run_ci_test_stage.subprocess, "run", git_result)
    assert run_ci_test_stage.git_changed_paths(BASE, HEAD) == [
        "app/ui/a file.ts", "docs/a\nfile.md",
    ]
    assert commands == [
        ["git", "cat-file", "-e", f"{BASE}^{{commit}}"],
        ["git", "diff", "--name-only", "-z", BASE, HEAD, "--"],
    ]


def test_push_uses_prior_commit_and_preserves_changed_path_arguments(monkeypatch):
    requested = []

    def changed_paths(base, head):
        requested.append((base, head))
        return ["app/ui/src/SelectionCoach.tsx", "docs/help/with spaces.md"]

    monkeypatch.setattr(run_ci_test_stage, "git_changed_paths", changed_paths)
    assert run_ci_test_stage.stage_arguments("push", {"before": BASE}, HEAD) == [
        "--scope", "changed", "--paths",
        "app/ui/src/SelectionCoach.tsx", "docs/help/with spaces.md",
    ]
    assert requested == [(BASE, HEAD)]


def test_pull_request_diffs_from_pr_base_instead_of_push_before(monkeypatch):
    requested = []
    monkeypatch.setattr(
        run_ci_test_stage, "git_changed_paths",
        lambda base, head: requested.append((base, head)) or ["backend/test_face_offset.py"],
    )
    event = {"before": "c" * 40, "pull_request": {"base": {"sha": BASE}}}
    assert run_ci_test_stage.stage_arguments("pull_request", event, HEAD)[1] == "changed"
    assert requested == [(BASE, HEAD)]


@pytest.mark.parametrize("event_name, expected", [("schedule", "nightly"), ("workflow_dispatch", "full")])
def test_full_stages_are_explicit_for_schedule_and_manual_runs(event_name, expected, monkeypatch):
    def unexpected_diff(*_arguments):
        raise AssertionError("Explicit full stage must not calculate a component diff")

    monkeypatch.setattr(run_ci_test_stage, "git_changed_paths", unexpected_diff)
    assert run_ci_test_stage.stage_arguments(event_name, {}, HEAD) == ["--scope", expected]


@pytest.mark.parametrize("base", ["", "0" * 40, "missing", None])
def test_initial_or_missing_base_falls_back_to_full(base):
    assert run_ci_test_stage.stage_arguments("push", {"before": base}, HEAD) == ["--scope", "full"]


def test_unavailable_base_object_falls_back_to_full(monkeypatch):
    def missing_object(*_arguments):
        raise subprocess.CalledProcessError(128, ["git", "cat-file"])

    monkeypatch.setattr(run_ci_test_stage, "git_changed_paths", missing_object)
    assert run_ci_test_stage.stage_arguments("push", {"before": BASE}, HEAD) == ["--scope", "full"]


def test_empty_diff_and_docs_only_changes_do_not_trigger_full_regression(monkeypatch):
    monkeypatch.setattr(run_ci_test_stage, "git_changed_paths", lambda _base, _head: [])
    assert run_ci_test_stage.stage_arguments("push", {"before": BASE}, HEAD) == [
        "--scope", "changed", "--paths",
    ]
    assert run_test_stage.changed_paths([]) == []
    assert run_test_stage.impact_groups([]) == []
    assert run_test_stage.impact_groups(["README.md"]) == []


@pytest.mark.parametrize("path", ["backend/test_face_offset.py", "backend/test_split_bodies.py", "backend/test_body_resize.py"])
def test_direct_edit_changes_select_cad_group_and_the_real_kernel_tests(path, tmp_path):
    assert run_test_stage.impact_groups([path]) == ["cad"]
    commands = run_test_stage.groups(tmp_path)["cad"]
    assert path in commands[0]["command"]


def test_document_shim_checks_cad_connections_and_manifest_checks_release_version():
    assert run_test_stage.impact_groups(["scripts/dev_shim.py"]) == ["ai", "cad"]
    assert run_test_stage.impact_groups(["app/package.json"]) == ["release"]


@pytest.mark.parametrize("path", ["backend/worker.py", "backend/parameter_expressions.py", "backend/test_full_regressions.py"])
def test_shared_geometry_and_expression_changes_cover_ai_consumers(path):
    assert run_test_stage.impact_groups([path]) == ["ai", "cad"]


def test_focused_cad_stage_includes_full_regression_fixes(tmp_path):
    command = run_test_stage.groups(tmp_path)["cad"][0]["command"]
    assert "backend/test_parameter_expressions.py" in command
    assert "backend/test_full_regressions.py" in command


@pytest.mark.parametrize("path", ["app/ui/src/lessonEngine.ts", "app/ui/src/tooltipController.ts", "app/ui/src/revealCommand.ts"])
def test_lesson_help_components_cover_workflow_and_ui(path):
    assert run_test_stage.impact_groups([path]) == ["help", "ui"]


def test_runner_preserves_utf8_subprocess_output(tmp_path, monkeypatch):
    monkeypatch.setattr(run_test_stage, "ROOT", tmp_path)
    spec = {
        "name": "utf8",
        "command": [sys.executable, "-c", "import sys; sys.stdout.buffer.write(bytes([0xd0, 0x90]))"],
    }
    result = run_test_stage.run_command(spec, tmp_path)
    assert result["status"] == "passed"
    assert (tmp_path / "utf8.log").read_text(encoding="utf-8") == "А"
