import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_perf_smoke  # noqa: E402
import run_native_perf  # noqa: E402

pytestmark = pytest.mark.contract


def test_control_workload_has_required_scale_and_deterministic_operations():
    workload = run_perf_smoke.build_control_workload()
    assert len(workload["parts"]) == 20
    assert len(workload["operations"]) == 100
    assert {operation["op"] for operation in workload["operations"]} == {"transform"}
    assert {operation["part_id"] for operation in workload["operations"]} == {
        part["part_id"] for part in workload["parts"]
    }


def test_worker_uses_current_interpreter_for_cross_platform_venv(monkeypatch):
    captured = {}

    class ProcessStub:
        stdin = None
        stdout = None

    def popen(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return ProcessStub()

    monkeypatch.setattr(run_perf_smoke.subprocess, "Popen", popen)
    run_perf_smoke.WorkerClient()
    assert captured["command"] == [sys.executable, str(ROOT / "backend" / "worker.py")]


def test_gate_evaluation_keeps_native_only_targets_not_run():
    metrics = {
        "warm_simple_build": {"p95_ms": 500},
        "control_workload": {"worker_rss_bytes": 512 * 1024**2},
        "ui": {
            "triangle_count": 200_000,
            "help_search_ms": {"p95": 10},
        },
    }
    gates = run_perf_smoke.evaluate_report(metrics)
    assert gates["help_search_loaded_index"]["status"] == "passed"
    assert gates["simple_worker_build"]["status"] == "passed"
    assert gates["cold_desktop_ready"]["status"] == "not_run"
    assert gates["viewport_navigation_fps"]["status"] == "not_run"
    assert gates["full_desktop_memory"]["status"] == "not_run"


def test_ui_perf_runner_uses_production_decoder_and_help_search():
    result = subprocess.run(
        [
            "node", "--expose-gc", "--experimental-strip-types",
            "scripts/run_ui_perf.ts", "--triangles", "2000", "--runs", "3",
        ],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    report = json.loads(result.stdout)
    assert report["triangle_count"] == 2000
    assert report["vertex_count"] == 6000
    assert report["help_search_ms"]["samples"] == 1000
    assert report["binary_decode_ms"]["samples"] == 3


def test_native_control_project_has_twenty_bodies_and_one_hundred_operations(tmp_path):
    project = tmp_path / "control.printforge"
    definition = run_native_perf.build_control_project(project)
    assert definition == {"body_count": 20, "operation_count": 100}
    import zipfile
    with zipfile.ZipFile(project) as archive:
        document = json.loads(archive.read("document.json"))
    assert len(document["parts"]) == 20
    assert len(document["operations"]) == 100
    assert {operation["op"] for operation in document["operations"]} == {"transform"}


def test_native_perf_gates_require_every_fps_run_and_full_process_tree_memory():
    metrics = {
        "startup": {"latency": {"p95_ms": 700}},
        "workload": {
            "navigation_fps": {"min": 59.0},
            "process_tree_rss_bytes": {"max": 700 * 1024**2},
            "scene": {
                "body_count": 20,
                "operation_count": 100,
                "solid_count": 20,
                "triangle_count": 40_000,
            },
        },
    }
    signature = {"checked": True, "valid": True, "detail": ""}
    gates = run_native_perf.evaluate_report(metrics, signature)
    assert all(gate["status"] == "passed" for gate in gates.values())
    metrics["workload"]["navigation_fps"]["min"] = 29.9
    assert run_native_perf.evaluate_report(metrics, signature)["viewport_navigation_fps"]["status"] == "failed"
    signature["valid"] = False
    assert run_native_perf.evaluate_report(metrics, signature)["bundle_signature"]["status"] == "failed"
