#!/usr/bin/env python3
import argparse
import json
import math
import os
import platform
import statistics
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parent.parent


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def latency_summary(values):
    return {
        "samples": len(values),
        "p50_ms": percentile(values, 0.5),
        "p95_ms": percentile(values, 0.95),
        "max_ms": max(values),
        "mean_ms": statistics.fmean(values),
    }


def build_control_project(path):
    parts = []
    operations = []
    for index in range(20):
        part_id = f"native-perf-part-{index + 1}"
        parts.append({
            "part_id": part_id,
            "name": f"Native perf body {index + 1}",
            "template": "plate_with_holes",
            "params": {
                "length": 30,
                "width": 20,
                "height": 4,
                "hole_diameter": 2,
                "hole_offset": 5,
            },
        })
        target_x = (index % 5) * 40
        target_y = (index // 5) * 30
        for _step in range(5):
            operations.append({
                "op": "transform",
                "part_id": part_id,
                "translate": [target_x / 5, target_y / 5, 0],
            })
    manifest = {
        "schema_version": 3,
        "app": "PrintForge",
        "app_version": "0.2.0",
        "units": "mm",
        "kernel": "build123d/OCP",
    }
    document = {
        "schema_version": 3,
        "units": "mm",
        "document_id": 9_000_003,
        "template": "plate_with_holes",
        "parts": parts,
        "parameters": parts[0]["params"],
        "expressions": {},
        "operations": operations,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
        archive.writestr("document.json", json.dumps(document, ensure_ascii=False))
    return {"body_count": len(parts), "operation_count": len(operations)}


def default_app_path():
    if platform.system() == "Darwin":
        return ROOT / "app" / "src-tauri" / "target" / "release" / "bundle" / "macos" / "PrintForge.app"
    if platform.system() == "Windows":
        return ROOT / "app" / "src-tauri" / "target" / "release" / "printforge.exe"
    raise RuntimeError("Native performance runner поддерживает macOS и Windows")


def app_executable(app_path):
    if app_path.suffix.lower() == ".app":
        return app_path / "Contents" / "MacOS" / "printforge"
    return app_path


def app_size_bytes(app_path):
    if app_path.is_file():
        return app_path.stat().st_size
    return sum(path.stat().st_size for path in app_path.rglob("*") if path.is_file())


def process_tree_rss(pid):
    try:
        process = psutil.Process(pid)
        processes = [process, *process.children(recursive=True)]
        return sum(item.memory_info().rss for item in processes if item.is_running())
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def terminate_process_tree(pid):
    try:
        process = psutil.Process(pid)
    except psutil.NoSuchProcess:
        return
    children = process.children(recursive=True)
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.NoSuchProcess:
            pass
    try:
        process.terminate()
    except psutil.NoSuchProcess:
        pass
    _, alive = psutil.wait_procs([*children, process], timeout=5)
    for item in alive:
        try:
            item.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(alive, timeout=5)


def activate_process(pid):
    if platform.system() != "Darwin":
        return
    script = (
        'tell application "System Events" to set frontmost of '
        f'first application process whose unix id is {pid} to true'
    )
    for _attempt in range(20):
        result = subprocess.run(
            ["osascript", "-e", script],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return
        time.sleep(0.05)


def clean_environment(mode, report_path, project_path, duration_ms):
    environment = os.environ.copy()
    for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "NODE_OPTIONS"):
        environment.pop(name, None)
    environment.update({
        "PF_PERF_MODE": mode,
        "PF_PERF_REPORT": str(report_path),
        "PF_PERF_DURATION_MS": str(duration_ms),
    })
    if project_path is not None:
        environment["PF_PERF_PROJECT"] = str(project_path)
    else:
        environment.pop("PF_PERF_PROJECT", None)
    if platform.system() == "Darwin":
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    return environment


def run_native_sample(executable, mode, run_dir, run_number, project_path, duration_ms, timeout):
    report_path = run_dir / f"{mode}-{run_number}.json"
    log_path = run_dir / f"{mode}-{run_number}.log"
    environment = clean_environment(mode, report_path, project_path, duration_ms)
    started_at = time.perf_counter()
    with log_path.open("w", encoding="utf-8") as log:
        process = subprocess.Popen(
            [str(executable)],
            cwd=ROOT,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
    try:
        activate_process(process.pid)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            exit_code = process.poll()
            if exit_code is not None:
                raise RuntimeError(f"PrintForge завершился с кодом {exit_code}; лог: {log_path}")
            if report_path.exists():
                report = json.loads(report_path.read_text())
                ready_ms = (time.perf_counter() - started_at) * 1000
                if report.get("pid") != process.pid:
                    raise RuntimeError("Native report относится к другому процессу")
                rss_samples = []
                for _index in range(5):
                    rss = process_tree_rss(process.pid)
                    if rss is not None:
                        rss_samples.append(rss)
                    time.sleep(0.1)
                return {
                    "run": run_number,
                    "ready_ms": ready_ms,
                    "process_tree_rss_bytes": max(rss_samples) if rss_samples else None,
                    "frontend": report["payload"],
                    "log": str(log_path.relative_to(ROOT)),
                }
            time.sleep(0.01)
        raise TimeoutError(f"PrintForge не создал native perf report за {timeout} с")
    finally:
        terminate_process_tree(process.pid)


def evaluate_report(metrics, signature=None):
    startup_p95 = metrics["startup"]["latency"]["p95_ms"]
    fps_min = metrics["workload"]["navigation_fps"]["min"]
    rss_max = metrics["workload"]["process_tree_rss_bytes"]["max"]
    scene = metrics["workload"]["scene"]
    gates = {
        "cold_desktop_ready": {
            "target": "process-cold frontend ready p95 <= 8000 ms",
            "actual_ms": startup_p95,
            "status": "passed" if startup_p95 <= 8000 else "failed",
        },
        "viewport_navigation_fps": {
            "target": "every native run >= 30 FPS",
            "actual_min_fps": fps_min,
            "status": "passed" if fps_min >= 30 else "failed",
        },
        "full_desktop_memory": {
            "target": "maximum app process tree RSS < 2 GiB",
            "actual_bytes": rss_max,
            "status": "passed" if rss_max < 2 * 1024**3 else "failed",
        },
        "native_control_scene": {
            "target": "20 bodies, 100 operations, 1..200000 displayed triangles",
            "actual": scene,
            "status": "passed" if (
                scene["solid_count"] == 20
                and scene["operation_count"] == 100
                and 0 < scene["triangle_count"] <= 200_000
            ) else "failed",
        },
    }
    if signature and signature.get("checked"):
        gates["bundle_signature"] = {
            "target": "codesign --verify --deep --strict succeeds",
            "actual": signature,
            "status": "passed" if signature.get("valid") else "failed",
        }
    return gates


def collect_metrics(startup_samples, workload_samples, workload_definition):
    startup_latencies = [sample["ready_ms"] for sample in startup_samples]
    workload_latencies = [sample["ready_ms"] for sample in workload_samples]
    fps_values = [sample["frontend"]["navigation"]["fps"] for sample in workload_samples]
    rss_values = [sample["process_tree_rss_bytes"] for sample in workload_samples]
    first_frontend = workload_samples[0]["frontend"]
    return {
        "startup": {
            "latency": latency_summary(startup_latencies),
            "runs": startup_samples,
        },
        "workload": {
            "launch_to_report": latency_summary(workload_latencies),
            "navigation_fps": {
                "samples": len(fps_values),
                "min": min(fps_values),
                "p50": percentile(fps_values, 0.5),
                "max": max(fps_values),
            },
            "process_tree_rss_bytes": {
                "samples": len(rss_values),
                "min": min(rss_values),
                "p50": percentile(rss_values, 0.5),
                "max": max(rss_values),
            },
            "scene": {
                **workload_definition,
                "solid_count": first_frontend["solid_count"],
                "triangle_count": first_frontend["triangle_count"],
                "vertex_count": first_frontend["vertex_count"],
            },
            "runs": workload_samples,
        },
    }


def codesign_status(app_path):
    if platform.system() != "Darwin" or app_path.suffix.lower() != ".app":
        return {"checked": False}
    result = subprocess.run(
        ["codesign", "--verify", "--deep", "--strict", str(app_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    return {
        "checked": True,
        "valid": result.returncode == 0,
        "detail": (result.stderr or result.stdout).strip(),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=default_app_path())
    parser.add_argument("--startup-runs", type=int, default=7)
    parser.add_argument("--workload-runs", type=int, default=3)
    parser.add_argument("--duration-ms", type=int, default=3000)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.startup_runs < 3 or args.workload_runs < 3 or args.duration_ms < 1000:
        parser.error("нужно >= 3 startup/workload runs и duration >= 1000 ms")
    app_path = args.app.resolve()
    executable = app_executable(app_path)
    if not executable.is_file():
        parser.error(f"native executable не найден: {executable}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or ROOT / "artifacts" / "perf" / timestamp
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    project_path = output_dir / "native-control.printforge"
    workload_definition = build_control_project(project_path)
    startup_samples = [
        run_native_sample(
            executable, "startup", output_dir, index + 1, None,
            args.duration_ms, args.timeout,
        )
        for index in range(args.startup_runs)
    ]
    workload_samples = [
        run_native_sample(
            executable, "workload", output_dir, index + 1, project_path,
            args.duration_ms, args.timeout,
        )
        for index in range(args.workload_runs)
    ]
    metrics = collect_metrics(startup_samples, workload_samples, workload_definition)
    signature = codesign_status(app_path)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "cpu_count": os.cpu_count(),
            "memory_bytes": psutil.virtual_memory().total,
        },
        "app": {
            "path": str(app_path),
            "executable": str(executable),
            "size_bytes": app_size_bytes(app_path),
            "codesign": signature,
        },
        "configuration": {
            "startup_runs": args.startup_runs,
            "workload_runs": args.workload_runs,
            "navigation_duration_ms": args.duration_ms,
            "timeout_seconds": args.timeout,
        },
        "methodology": {
            "startup": "Bundle executable launched as a new process; readiness reported after registries, WebView and two animation frames. OS caches are not purged.",
            "workload": "Native app opens a generated .printforge project through production doc_open and binary mesh IPC before measurement.",
            "navigation": "Production Three.js camera orbits the loaded scene on requestAnimationFrame for the configured duration.",
            "memory": "Maximum RSS across the main app process and all descendants, sampled five times after the navigation probe.",
        },
        "metrics": metrics,
    }
    report["gates"] = evaluate_report(metrics, signature)
    report["overall_status"] = (
        "passed" if all(gate["status"] == "passed" for gate in report["gates"].values())
        else "failed"
    )
    report_path = output_dir / "native-perf-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Native performance report: {report_path.relative_to(ROOT)}")
    for name, gate in report["gates"].items():
        print(f" - {name}: {gate['status']}")
    return 0 if report["overall_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
