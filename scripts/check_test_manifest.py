#!/usr/bin/env python3
"""Structural traceability validation; --strict-stage also fails on M0–M3 gaps."""
import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs/testing/requirements.yaml"
CATALOG = ROOT / "tests/test_catalog.json"
SOURCE = ROOT / "REQUIREMENTS.md"
SOURCE_PATTERN = re.compile(
    r"\b(?:HELP|UI|CAD|DOC|IO|PRINT|AI|TECH|BUILD)-\d{3}\b|\bAC-\d{2}\b")
RUN_STATUSES = {"passed", "failed", "not_run", "planned", "blocked", "skipped", "quarantined"}
IMPLEMENTATION_STATUSES = {"implemented", "partial", "planned", "blocked"}
STAGE_ORDER = {"M0": 0, "M1": 1, "M2": 2, "M3": 3, "M4": 4}


def source_ids(root=ROOT):
    product = set(SOURCE_PATTERN.findall((root / "REQUIREMENTS.md").read_text(encoding="utf-8")))
    return product | {f"EXT-{number:03d}" for number in range(1, 13)}


def nodeid_exists(root, nodeid):
    path_text, separator, function_name = nodeid.partition("::")
    path = root / path_text
    if not separator or not path.is_file() or path.suffix != ".py":
        return False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name
        for node in ast.walk(tree)
    )


def validate(manifest, catalog, root=ROOT, strict_stage=False):
    errors = []
    warnings = []
    entries = manifest.get("requirements") or []
    ids = [entry.get("requirement_id") for entry in entries]
    expected = source_ids(root)
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    missing = sorted(expected - set(ids))
    unknown = sorted(set(ids) - expected)
    if duplicates:
        errors.append(f"duplicate requirement IDs: {duplicates}")
    if missing:
        errors.append(f"missing requirement IDs: {missing}")
    if unknown:
        errors.append(f"unknown requirement IDs: {unknown}")

    tests = catalog.get("tests") or []
    test_ids = [test.get("test_id") for test in tests]
    duplicate_tests = sorted({item for item in test_ids if test_ids.count(item) > 1})
    if duplicate_tests:
        errors.append(f"duplicate test IDs: {duplicate_tests}")
    test_map = {test["test_id"]: test for test in tests if test.get("test_id")}
    for test_id, test in test_map.items():
        nodeids = test.get("nodeids") or []
        if not nodeids:
            errors.append(f"{test_id}: no nodeids")
        for nodeid in nodeids:
            if not nodeid_exists(root, nodeid):
                errors.append(f"{test_id}: nonexistent nodeid {nodeid}")

    current_stage = manifest.get("current_stage")
    for entry in entries:
        requirement_id = entry.get("requirement_id", "<missing>")
        if entry.get("implementation_status") not in IMPLEMENTATION_STATUSES:
            errors.append(f"{requirement_id}: invalid implementation_status")
        if entry.get("last_run_status") not in RUN_STATUSES:
            errors.append(f"{requirement_id}: invalid last_run_status")
        for test_id in entry.get("test_ids") or []:
            if test_id not in test_map:
                errors.append(f"{requirement_id}: unknown test ID {test_id}")
        claimed_levels = set(entry.get("levels") or [])
        actual_levels = {
            test_map[test_id]["level"]
            for test_id in entry.get("test_ids") or []
            if test_id in test_map
        }
        if claimed_levels != actual_levels:
            errors.append(
                f"{requirement_id}: levels {sorted(claimed_levels)} != catalog {sorted(actual_levels)}")
        if entry.get("last_run_status") == "passed" and not entry.get("evidence"):
            errors.append(f"{requirement_id}: passed without evidence")
        required_from = entry.get("required_from")
        mandatory_now = (
            required_from in STAGE_ORDER
            and current_stage in STAGE_ORDER
            and STAGE_ORDER[required_from] <= STAGE_ORDER[current_stage]
        )
        has_gap = entry.get("implementation_status") != "implemented" or not entry.get("test_ids")
        if mandatory_now and has_gap:
            warnings.append(f"{requirement_id}: mandatory {required_from}, evidence incomplete")

    if strict_stage and warnings:
        errors.extend(warnings)
    return errors, warnings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict-stage", action="store_true")
    args = parser.parse_args()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    errors, warnings = validate(manifest, catalog, strict_stage=args.strict_stage)
    if errors:
        print("Traceability: errors")
        for error in errors:
            print(" -", error)
        return 1
    print(
        f"Traceability structure valid: {len(manifest['requirements'])} requirements, "
        f"{len(catalog['tests'])} test IDs; current-stage gaps: {len(warnings)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
