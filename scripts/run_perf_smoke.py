#!/usr/bin/env python3
import argparse
import json
import math
import os
import platform
import queue
import statistics
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "backend" / "worker.py"


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def latency_summary(values):
    return {
        "samples": len(values),
        "p50_ms": percentile(values, 0.5) * 1000,
        "p95_ms": percentile(values, 0.95) * 1000,
        "max_ms": max(values) * 1000,
        "mean_ms": statistics.fmean(values) * 1000,
    }


def build_control_workload():
    parts = []
    operations = []
    for index in range(20):
        part_id = f"perf-part-{index + 1}"
        parts.append({
            "part_id": part_id,
            "name": f"Perf body {index + 1}",
            "template": "plate_with_holes",
            "params": {
                "length": 30,
                "width": 20,
                "height": 4,
                "hole_diameter": 0,
                "hole_offset": 5,
            },
        })
        target_x = (index % 5) * 45
        target_y = (index // 5) * 35
        for _step in range(5):
            operations.append({
                "op": "transform",
                "part_id": part_id,
                "translate": [target_x / 5, target_y / 5, 0],
            })
    return {"parts": parts, "operations": operations}


def current_rss_bytes(pid):
    try:
        return psutil.Process(pid).memory_info().rss
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


class WorkerClient:
    def __init__(self):
        self.started_at = time.perf_counter()
        self.process = subprocess.Popen(
            [sys.executable, str(WORKER)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.request_number = 0

    def request(self, method, params=None, timeout=600):
        self.request_number += 1
        request_id = f"perf-{self.request_number}"
        request = {
            "request_id": request_id,
            "schema_version": 1,
            "document_id": "perf-document",
            "revision": self.request_number,
            "method": method,
            "params": params or {},
        }
        started_at = time.perf_counter()
        self.process.stdin.write(json.dumps(request) + "\n")
        self.process.stdin.flush()
        responses = queue.Queue()

        def read_response():
            try:
                while True:
                    line = self.process.stdout.readline()
                    if not line:
                        raise RuntimeError("geometry worker завершился без ответа")
                    response = json.loads(line)
                    if response.get("request_id") == request_id:
                        responses.put((response, None))
                        return
            except BaseException as error:  # noqa: BLE001
                responses.put((None, error))

        threading.Thread(target=read_response, daemon=True).start()
        try:
            response, error = responses.get(timeout=timeout)
        except queue.Empty as error:
            self.process.kill()
            raise TimeoutError(f"{method} превысил {timeout} с") from error
        duration = time.perf_counter() - started_at
        if error is not None:
            raise error
        if not response.get("ok"):
            raise RuntimeError(json.dumps(response.get("error") or {}, ensure_ascii=False))
        return response.get("result") or {}, duration

    def close(self):
        if self.process.poll() is None:
            try:
                self.request("shutdown", timeout=10)
            except Exception:  # noqa: BLE001
                self.process.kill()
        self.process.wait(timeout=10)


def environment_metadata():
    metadata = {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "node": subprocess.check_output(["node", "--version"], text=True).strip(),
        "cpu_count": os.cpu_count(),
    }
    if platform.system() == "Darwin":
        metadata["macos"] = subprocess.check_output(["sw_vers", "-productVersion"], text=True).strip()
        metadata["cpu"] = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        metadata["memory_bytes"] = int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True))
    return metadata


def evaluate_report(metrics):
    worker_memory = metrics["control_workload"]["worker_rss_bytes"]
    return {
        "help_search_loaded_index": {
            "target": "p95 <= 200 ms",
            "actual_ms": metrics["ui"]["help_search_ms"]["p95"],
            "status": "passed" if metrics["ui"]["help_search_ms"]["p95"] <= 200 else "failed",
        },
        "simple_worker_build": {
            "target": "p95 <= 1000 ms",
            "actual_ms": metrics["warm_simple_build"]["p95_ms"],
            "status": "passed" if metrics["warm_simple_build"]["p95_ms"] <= 1000 else "failed",
        },
        "worker_memory_20_bodies_100_operations": {
            "target": "worker RSS < 2 GiB",
            "actual_bytes": worker_memory,
            "status": "passed" if worker_memory is not None and worker_memory < 2 * 1024**3 else "failed",
        },
        "binary_path_200k_triangles": {
            "target": "exactly 200000 triangles decoded and mapped",
            "actual_triangles": metrics["ui"]["triangle_count"],
            "status": "passed" if metrics["ui"]["triangle_count"] == 200_000 else "failed",
        },
        "cold_desktop_ready": {"target": "<= 8 s", "status": "not_run"},
        "viewport_navigation_fps": {"target": ">= 30 FPS", "status": "not_run"},
        "full_desktop_memory": {"target": "< 2 GiB", "status": "not_run"},
    }


def run_benchmark(runs, triangles):
    worker = WorkerClient()
    try:
        ping, ping_duration = worker.request("ping")
        worker_start_ping_duration = time.perf_counter() - worker.started_at
        simple_params = {
            "template": "plate_with_holes",
            "params": {"length": 80, "width": 40, "height": 6,
                       "hole_diameter": 4, "hole_offset": 10},
        }
        cold_result, cold_duration = worker.request("build", simple_params)
        warm_durations = []
        for _index in range(runs):
            _result, duration = worker.request("build", simple_params)
            warm_durations.append(duration)
        workload = build_control_workload()
        workload_result, workload_duration = worker.request("build", workload)
        worker_rss = current_rss_bytes(worker.process.pid)
        ui_process = subprocess.run(
            [
                "node", "--expose-gc", "--experimental-strip-types",
                str(ROOT / "scripts" / "run_ui_perf.ts"),
                "--triangles", str(triangles), "--runs", str(runs),
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        ui_metrics = json.loads(ui_process.stdout)
        return {
            "worker_start_ping_ms": worker_start_ping_duration * 1000,
            "ping_pid": ping.get("pid"),
            "cold_simple_build_ms": cold_duration * 1000,
            "cold_simple_mesh": cold_result.get("mesh"),
            "warm_simple_build": latency_summary(warm_durations),
            "control_workload": {
                "body_count": len(workload["parts"]),
                "operation_count": len(workload["operations"]),
                "duration_ms": workload_duration * 1000,
                "solid_count": workload_result.get("stats", {}).get("solid_count"),
                "triangle_count": workload_result.get("mesh", {}).get("triangle_count"),
                "mesh_bytes": workload_result.get("mesh", {}).get("bytes"),
                "worker_rss_bytes": worker_rss,
            },
            "ui": ui_metrics,
            "ping_duration_ms": ping_duration * 1000,
        }
    finally:
        worker.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=7)
    parser.add_argument("--triangles", type=int, default=200_000)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.runs < 3 or args.triangles <= 0:
        parser.error("--runs должен быть >= 3, --triangles — положительным")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or ROOT / "artifacts" / "perf" / timestamp
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    metrics = run_benchmark(args.runs, args.triangles)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "environment": environment_metadata(),
        "configuration": {"runs": args.runs, "synthetic_triangles": args.triangles},
        "methodology": {
            "worker": "Persistent backend/worker.py JSONL process; one cold build followed by repeated warm builds.",
            "control_workload": "One build of 20 independent bodies with 5 transforms per body (100 operations total).",
            "help_search": "1000 queries against the already loaded production help index and production search function.",
            "mesh_pipeline": "Synthetic binary mesh decoded and coordinate-mapped by production UI functions; no WebGL rendering.",
            "native_exclusions": [
                "Current-source desktop cold start was not measured.",
                "Viewport FPS was not measured because this harness does not drive native WebView/WebGL.",
                "Full desktop RSS was not measured; only geometry worker and Node harness RSS are recorded.",
            ],
        },
        "metrics": metrics,
    }
    report["gates"] = evaluate_report(metrics)
    report["overall_status"] = (
        "failed" if any(gate["status"] == "failed" for gate in report["gates"].values())
        else "partial"
    )
    report_path = output_dir / "perf-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Performance report: {report_path.relative_to(ROOT)}")
    for name, gate in report["gates"].items():
        print(f" - {name}: {gate['status']}")
    return 1 if report["overall_status"] == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
