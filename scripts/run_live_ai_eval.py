#!/usr/bin/env python3
"""Opt-in live eval: 20 русских запросов × 3, настоящий provider adapter и CAD preview."""
import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_planner  # noqa: E402
import dev_shim  # noqa: E402


def stop_worker():
    worker = dev_shim._worker
    if worker is not None and worker.poll() is None:
        worker.terminate()
        worker.wait(timeout=10)
    dev_shim._worker = None


def prepare_document(setup):
    document = dev_shim.Doc()
    dev_shim.DOCS["main"] = document
    dev_shim.ACTIVE[0] = "main"
    if setup == "plate":
        dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {}})
    elif setup == "bracket":
        dev_shim.cmd_doc_create({"template": "bracket_l", "params": {}})
    return document


def classify(prompt, response, error):
    if prompt.get("must_not_execute"):
        return error is not None or not response or not response["plan"]["operations"]
    if prompt.get("must_not_preview"):
        return error is not None or not response or response.get("preview") is None
    if error is not None or not response:
        return False
    plan = response["plan"]
    operations = plan.get("operations") or []
    if prompt.get("allow_questions") and plan.get("questions"):
        return True
    if prompt.get("allow_assumptions") and plan.get("assumptions"):
        return True
    if not operations:
        return False
    operation = operations[0]
    if prompt.get("expected_command") != operation.get("command_id"):
        return False
    parameters = operation.get("parameters") or {}
    if prompt.get("expected_template") and parameters.get("template") != prompt["expected_template"]:
        return False
    if prompt.get("expected_parameter") and parameters.get("name") != prompt["expected_parameter"]:
        return False
    if "expected_value" in prompt:
        value = parameters.get("value", parameters.get("radius"))
        if value != prompt["expected_value"]:
            return False
    preview = response.get("preview")
    return preview is None or preview.get("error") is None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "tests/live_eval/prompts.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "artifacts/live-ai-eval.json",
    )
    args = parser.parse_args()

    if os.environ.get("PF_LIVE_AI_EVAL") != "1":
        raise SystemExit("Live eval отключён. Для явного запуска задайте PF_LIVE_AI_EVAL=1.")
    provider = ai_planner.provider_info()
    if provider["provider"] not in {"ollama", "openai"}:
        raise SystemExit("Live eval требует PF_AI_PROVIDER=ollama или openai; scripted не считается LLM.")

    dataset = json.loads(args.dataset.read_text())
    results = []
    started = time.time()
    try:
        for prompt in dataset["prompts"]:
            for run_index in range(1, dataset["runs_per_prompt"] + 1):
                prepare_document(prompt.get("setup"))
                run_started = time.perf_counter()
                response = None
                error = None
                try:
                    response = dev_shim.cmd_ai_plan({"text": prompt["prompt"]})
                except Exception as cause:  # noqa: BLE001
                    error = str(cause)
                results.append({
                    "prompt_id": prompt["id"],
                    "category": prompt["category"],
                    "run": run_index,
                    "passed": classify(prompt, response, error),
                    "duration_seconds": round(time.perf_counter() - run_started, 3),
                    "repair_count": response.get("repair_count", 0) if response else 0,
                    "plan_hash": response.get("plan_hash") if response else None,
                    "error": error,
                })
    finally:
        stop_worker()

    categories = {}
    for result in results:
        bucket = categories.setdefault(result["category"], {"passed": 0, "total": 0})
        bucket["total"] += 1
        bucket["passed"] += int(result["passed"])
    for bucket in categories.values():
        bucket["rate"] = bucket["passed"] / bucket["total"]

    report = {
        "schema_version": 1,
        "status": "passed" if all(item["passed"] for item in results) else "failed",
        "provider": provider,
        "model_digest": os.environ.get("PF_AI_MODEL_DIGEST"),
        "quantization": os.environ.get("PF_AI_QUANTIZATION"),
        "runtime": platform.python_version(),
        "platform": platform.platform(),
        "prompt_schema_version": dataset["schema_version"],
        "started_at_unix": started,
        "duration_seconds": round(time.time() - started, 3),
        "categories": categories,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"status": report["status"], "categories": categories}, ensure_ascii=False))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
