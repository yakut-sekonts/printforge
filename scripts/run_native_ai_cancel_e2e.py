#!/usr/bin/env python3
import argparse
import json
import os
import platform
import re
import subprocess
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import psutil

import run_native_perf

ROOT = Path(__file__).resolve().parent.parent


def plan_from_request(request_body):
    messages = request_body.get("messages") or []
    context = "\n".join(str(message.get("content", "")) for message in messages)
    def number(name):
        match = re.search(rf'"{name}":(\d+)', context)
        if not match:
            raise ValueError(f"provider request не содержит {name}")
        return int(match.group(1))
    return {
        "schema_version": 1,
        "document_id": number("document_id"),
        "document_instance_id": number("document_instance_id"),
        "base_revision": number("revision"),
        "units": "mm",
        "assumptions": [],
        "questions": [],
        "operations": [{
            "command_id": "part.create.from_template",
            "target_id": None,
            "parameters": {
                "template": "washer",
                "params": {"outer_diameter": 20, "inner_diameter": 6, "height": 4},
            },
        }],
        "summary": "Создать шайбу",
    }


class ProviderServer:
    def __init__(self, mode):
        self.mode = mode
        self.requests = []
        self.request_received = threading.Event()
        self.response_started = threading.Event()
        self.client_disconnected = threading.Event()
        self.stop = threading.Event()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                length = int(self.headers.get("content-length", "0"))
                body = json.loads(self.rfile.read(length))
                owner.requests.append({"path": self.path, "body": body})
                owner.request_received.set()
                if owner.mode == "ai-http-cancel":
                    self.send_response(200)
                    self.send_header("content-type", "application/json")
                    self.end_headers()
                    try:
                        self.wfile.write(b'{"choices":[{"message":{"content":"')
                        self.wfile.flush()
                        owner.response_started.set()
                        while not owner.stop.wait(0.05):
                            self.wfile.write(b" ")
                            self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        owner.client_disconnected.set()
                    return
                content = json.dumps(plan_from_request(body), ensure_ascii=False)
                payload = json.dumps({
                    "choices": [{"message": {"content": content}}],
                }, ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                self.wfile.flush()
                owner.response_started.set()

            def log_message(self, _format, *_args):
                return

        class QuietServer(ThreadingHTTPServer):
            def handle_error(self, _request, _client_address):
                return

        self.server = QuietServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}/v1"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_args):
        self.stop.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def clean_environment(mode, report_path, base_url, cancel_delay_ms):
    environment = os.environ.copy()
    for name in (
        "PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV", "NODE_OPTIONS", "PF_AI_KEY",
        "PF_PERF_MODE", "PF_PERF_REPORT", "PF_PERF_PROJECT", "PF_PERF_DURATION_MS",
    ):
        environment.pop(name, None)
    environment.update({
        "PF_E2E_MODE": mode,
        "PF_E2E_REPORT": str(report_path),
        "PF_E2E_CANCEL_DELAY_MS": str(cancel_delay_ms),
        "PF_AI_PROVIDER": "openai",
        "PF_AI_BASE": base_url,
        "PF_AI_MODEL": "native-e2e-model",
    })
    if platform.system() == "Darwin":
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
    return environment


def run_scenario(executable, mode, output_dir, cancel_delay_ms, timeout):
    report_path = output_dir / f"{mode}.json"
    log_path = output_dir / f"{mode}.log"
    with ProviderServer(mode) as provider:
        environment = clean_environment(mode, report_path, provider.base_url, cancel_delay_ms)
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
            run_native_perf.activate_process(process.pid)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                exit_code = process.poll()
                if exit_code is not None:
                    raise RuntimeError(f"PrintForge завершился с кодом {exit_code}; лог: {log_path}")
                if report_path.exists():
                    report = json.loads(report_path.read_text())
                    if report.get("pid") != process.pid:
                        raise RuntimeError("Native E2E report относится к другому процессу")
                    if mode == "ai-http-cancel":
                        provider.client_disconnected.wait(timeout=5)
                    return {
                        "mode": mode,
                        "duration_ms": (time.perf_counter() - started_at) * 1000,
                        "frontend": report["payload"],
                        "provider": {
                            "request_count": len(provider.requests),
                            "request_received": provider.request_received.is_set(),
                            "response_started": provider.response_started.is_set(),
                            "client_disconnected": provider.client_disconnected.is_set(),
                        },
                        "process_tree_rss_bytes": run_native_perf.process_tree_rss(process.pid),
                        "log": str(log_path.relative_to(ROOT)),
                    }
                time.sleep(0.01)
            raise TimeoutError(f"Native {mode} не завершился за {timeout} с")
        finally:
            run_native_perf.terminate_process_tree(process.pid)


def evaluate_report(scenarios, signature=None):
    http = scenarios["ai-http-cancel"]
    cad = scenarios["ai-cad-cancel"]
    http_frontend = http["frontend"]
    cad_frontend = cad["frontend"]
    gates = {
        "provider_http_cancel": {
            "status": "passed" if (
                http["provider"]["request_count"] == 1
                and http["provider"]["response_started"]
                and http["provider"]["client_disconnected"]
                and http_frontend.get("cancellation", {}).get("cancelled") is True
                and http_frontend.get("cancellation", {}).get("geometry_cancelled") is False
                and http_frontend.get("outcome", {}).get("ok") is False
                and http_frontend.get("outcome", {}).get("error", {}).get("code") == "ai_cancelled"
                and http_frontend.get("state_unchanged") is True
            ) else "failed",
        },
        "cad_preview_cancel_and_recovery": {
            "status": "passed" if (
                cad["provider"]["request_count"] == 1
                and cad["provider"]["response_started"]
                and cad_frontend.get("cancellation", {}).get("cancelled") is True
                and cad_frontend.get("cancellation", {}).get("geometry_cancelled") is True
                and cad_frontend.get("outcome", {}).get("ok") is False
                and cad_frontend.get("outcome", {}).get("error", {}).get("code") == "ai_cancelled"
                and cad_frontend.get("state_unchanged") is True
                and cad_frontend.get("recovery", {}).get("is_valid") is True
                and cad_frontend.get("recovery", {}).get("solid_count") == 1
            ) else "failed",
        },
    }
    if signature and signature.get("checked"):
        gates["bundle_signature"] = {
            "status": "passed" if signature.get("valid") else "failed",
        }
    return gates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", type=Path, default=run_native_perf.default_app_path())
    parser.add_argument("--cancel-delay-ms", type=int, default=800)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.cancel_delay_ms < 100:
        parser.error("--cancel-delay-ms должен быть >= 100")
    app_path = args.app.resolve()
    executable = run_native_perf.app_executable(app_path)
    if not executable.is_file():
        parser.error(f"native executable не найден: {executable}")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or ROOT / "artifacts" / "native-e2e" / timestamp
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    scenarios = {
        mode: run_scenario(executable, mode, output_dir, args.cancel_delay_ms, args.timeout)
        for mode in ("ai-http-cancel", "ai-cad-cancel")
    }
    signature = run_native_perf.codesign_status(app_path)
    report = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "dirty": bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip()),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
            "memory_bytes": psutil.virtual_memory().total,
        },
        "app": {
            "path": str(app_path),
            "size_bytes": run_native_perf.app_size_bytes(app_path),
            "codesign": signature,
        },
        "configuration": {
            "cancel_delay_ms": args.cancel_delay_ms,
            "timeout_seconds": args.timeout,
            "provider": "loopback OpenAI-compatible HTTP/1.1",
        },
        "methodology": {
            "provider_cancel": "Loopback response starts an incomplete JSON body; native ai_cancel must drop reqwest and close the server connection.",
            "cad_cancel": "Loopback provider returns a valid bound plan; cancel occurs during native preview build, must kill sidecar, preserve document and allow a fresh CAD build.",
            "isolation": "Provider settings come only from child-process environment; user config and Keychain are not modified.",
        },
        "scenarios": scenarios,
    }
    report["gates"] = evaluate_report(scenarios, signature)
    report["overall_status"] = (
        "passed" if all(gate["status"] == "passed" for gate in report["gates"].values())
        else "failed"
    )
    report_path = output_dir / "native-ai-cancel-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Native AI cancellation report: {report_path.relative_to(ROOT)}")
    for name, gate in report["gates"].items():
        print(f" - {name}: {gate['status']}")
    return 0 if report["overall_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
