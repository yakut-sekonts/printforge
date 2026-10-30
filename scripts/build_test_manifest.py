#!/usr/bin/env python3
"""Генерирует explicit requirements manifest из source IDs и test catalog."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "REQUIREMENTS.md"
CATALOG = ROOT / "tests/test_catalog.json"
OUTPUT = ROOT / "docs/testing/requirements.yaml"

SOURCE_PATTERN = re.compile(
    r"\b(?:HELP|UI|CAD|DOC|IO|PRINT|AI|TECH|BUILD)-\d{3}\b|\bAC-\d{2}\b")

DEFAULT_STAGE = {
    "HELP": "M1", "UI": "M1", "CAD": "M2", "DOC": "M2",
    "IO": "M2", "PRINT": "M2", "AI": "M3", "TECH": "M0",
    "BUILD": "M2", "AC": "M2", "EXT": "M4",
}

AC_STAGE = {
    "AC-01": "M1", "AC-02": "M2", "AC-03": "M2", "AC-04": "M2",
    "AC-05": "M2", "AC-06": "M2", "AC-07": "M1", "AC-08": "M2",
    "AC-09": "M2", "AC-10": "M3", "AC-11": "M3", "AC-12": "M2",
    "AC-13": "M3",
}

COVERAGE = {
    "HELP-001": ["T-HELP-14"], "HELP-002": ["T-HELP-14"],
    "HELP-003": ["T-HELP-14"], "HELP-004": ["T-HELP-13"],
    "HELP-005": ["T-HELP-13"], "HELP-006": ["T-HELP-13"],
    "HELP-007": ["T-HELP-14"], "HELP-008": ["T-HELP-14"],
    "HELP-009": ["T-HELP-14"], "HELP-010": ["T-HELP-14"],
    "HELP-011": ["T-HELP-14"], "HELP-012": ["T-HELP-14"],
    "HELP-013": ["T-HELP-13", "T-HELP-14"],
    "CAD-001": ["T-CAD-01", "T-CAD-02", "T-CAD-03", "T-CAD-04"],
    "CAD-002": ["T-CAD-01", "T-CAD-02"], "CAD-003": ["T-CAD-04", "T-CAD-05"],
    "CAD-004": ["T-CAD-06"], "CAD-005": ["T-CAD-06"],
    "CAD-006": ["T-CAD-06"], "CAD-007": ["T-CAD-06"],
    "CAD-008": ["T-CAD-06"], "CAD-009": ["T-CAD-06"],
    "CAD-010": ["T-CAD-01", "T-CAD-02", "T-CAD-03", "T-CAD-04"],
    "DOC-001": ["T-DOC-01"], "DOC-002": ["T-CAD-01", "T-CAD-02"],
    "DOC-003": ["T-AI-16"], "DOC-004": ["T-AI-13", "T-AI-16", "T-AI-17"],
    "DOC-005": ["T-AI-13", "T-AI-17", "T-AI-26"], "DOC-006": ["T-DOC-01"],
    "DOC-007": ["T-DOC-01"], "DOC-008": ["T-DOC-01"],
    "IO-001": ["T-IO-01", "T-IO-02"], "IO-002": ["T-IO-01"],
    "IO-003": ["T-IO-01", "T-IO-02"], "IO-004": ["T-IO-01"],
    "IO-005": ["T-IO-01"], "IO-006": ["T-DOC-01"],
    "PRINT-001": ["T-PRINT-01"], "PRINT-002": ["T-PRINT-01"],
    "PRINT-003": ["T-PRINT-02"], "PRINT-004": ["T-PRINT-02"],
    "PRINT-005": ["T-PRINT-01", "T-PRINT-02"],
    "AI-001": ["T-AI-01", "T-AI-02"], "AI-002": ["T-AI-02", "T-AI-03"],
    "AI-003": ["T-AI-04", "T-AI-05", "T-AI-06"],
    "AI-004": ["T-AI-07", "T-AI-08"],
    "AI-005": ["T-AI-10", "T-AI-12", "T-AI-13", "T-AI-14", "T-AI-16"],
    "AI-006": ["T-AI-04", "T-AI-05", "T-AI-06"],
    "AI-007": ["T-AI-17", "T-AI-18", "T-AI-19", "T-AI-20", "T-AI-23", "T-AI-24", "T-AI-26"],
    "AI-008": ["T-AI-27-HARNESS"],
    "TECH-001": ["T-TECH-01", "T-TECH-02"],
    "TECH-002": ["T-TECH-03", "T-AI-17", "T-AI-24"],
    "TECH-003": ["T-BUILD-01", "T-BUILD-02"],
    "BUILD-001": ["T-BUILD-01", "T-BUILD-02"],
    "BUILD-002": ["T-BUILD-02"], "BUILD-003": ["T-BUILD-01"],
    "BUILD-004": ["T-BUILD-02", "T-BUILD-03"],
    "AC-01": ["T-CAD-01", "T-DOC-01", "T-IO-01"],
    "AC-02": ["T-CAD-02", "T-IO-01"], "AC-03": ["T-CAD-03", "T-IO-01"],
    "AC-04": ["T-CAD-04", "T-CAD-05"], "AC-05": ["T-IO-01", "T-IO-02"],
    "AC-07": ["T-HELP-13", "T-HELP-14"], "AC-09": ["T-PRINT-01", "T-PRINT-02"],
    "AC-10": ["T-AI-10", "T-AI-12", "T-AI-16"],
    "AC-11": ["T-AI-05", "T-AI-13", "T-AI-17", "T-AI-26"],
    "AC-12": ["T-HELP-14", "T-BUILD-01"], "AC-13": [],
}

BLOCKING_PREFIXES = {"CAD", "DOC", "IO", "PRINT", "AI", "TECH", "BUILD"}


def natural_key(requirement_id):
    prefix, number = requirement_id.split("-")
    return prefix, int(number)


def main():
    source_ids = sorted(set(SOURCE_PATTERN.findall(SOURCE.read_text())), key=natural_key)
    if len(source_ids) != 85:
        raise SystemExit(f"Ожидалось 85 source requirement ID, найдено {len(source_ids)}")
    ext_ids = [f"EXT-{number:03d}" for number in range(1, 13)]
    catalog = json.loads(CATALOG.read_text())
    tests = {item["test_id"]: item for item in catalog["tests"]}
    entries = []
    for requirement_id in source_ids + ext_ids:
        prefix = requirement_id.split("-")[0]
        test_ids = COVERAGE.get(requirement_id, [])
        levels = sorted({tests[test_id]["level"] for test_id in test_ids})
        required_from = AC_STAGE.get(requirement_id, DEFAULT_STAGE[prefix])
        if prefix == "EXT":
            implementation_status = "planned"
            gap = "M4 scope: функция и её доказательства ещё не реализованы."
        elif test_ids:
            implementation_status = "partial"
            gap = "Есть перечисленное automated evidence; оставшиеся clauses и уровни указаны в TEST_GAPS.md."
        else:
            implementation_status = "partial"
            gap = "Нет automated evidence подходящего уровня; требование не считается принятым."
        severity = "B" if prefix in BLOCKING_PREFIXES and requirement_id != "AI-008" else "R"
        if requirement_id == "AI-008":
            severity = "Q"
        entries.append({
            "requirement_id": requirement_id,
            "required_from": required_from,
            "severity": severity,
            "test_ids": test_ids,
            "levels": levels,
            "implementation_status": implementation_status,
            "last_run_status": "not_run",
            "evidence": [],
            "uncovered_clauses": [gap],
        })
    payload = {
        "schema_version": 1,
        "current_stage": "M3",
        "source": {
            "product_requirements": "REQUIREMENTS.md",
            "autotest_requirements": "PrintForge_Codex_Autotest_Requirements.md v1.0",
            "autotest_requirements_sha256": "c1485d569f6b32e25f21b0593f65c21eb4c122f77300ef3af7bde8be43fed09a",
        },
        "note": "JSON is valid YAML 1.2. last_run_status is static and intentionally not_run; actual statuses live in generated test-report.json.",
        "requirements": entries,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"Manifest: {len(source_ids)} source + {len(ext_ids)} EXT = {len(entries)} entries")


if __name__ == "__main__":
    main()
