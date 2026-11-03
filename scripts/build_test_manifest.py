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
    "AI-005": ["T-AI-10", "T-AI-12", "T-AI-13", "T-AI-14", "T-AI-16", "T-AI-21", "T-AI-22", "T-AI-28-HARNESS"],
    "AI-006": ["T-AI-04", "T-AI-05", "T-AI-06", "T-AI-22", "T-AI-25", "T-AI-28-HARNESS"],
    "AI-007": ["T-AI-17", "T-AI-18", "T-AI-19", "T-AI-20", "T-AI-23", "T-AI-24", "T-AI-26"],
    "AI-008": ["T-AI-27-HARNESS"],
    "TECH-001": ["T-TECH-01", "T-TECH-02"],
    "TECH-002": ["T-TECH-03", "T-TECH-04", "T-AI-17", "T-AI-24", "T-AI-28-HARNESS"],
    "TECH-003": ["T-TECH-05", "T-BUILD-01", "T-BUILD-02"],
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
    "EXT-001": ["T-EXT-01"],
    "EXT-002": ["T-EXT-02"],
    "EXT-003": ["T-EXT-03", "T-EXT-04"],
    "EXT-004": ["T-EXT-05"],
    "EXT-005": ["T-EXT-06", "T-EXT-07"],
    "EXT-006": ["T-EXT-08"],
    "EXT-007": ["T-EXT-09"],
    "EXT-008": ["T-EXT-10"],
    "EXT-009": ["T-EXT-11"],
    "EXT-010": ["T-EXT-12", "T-EXT-13"],
    "EXT-011": ["T-EXT-14"],
    "EXT-012": ["T-EXT-15"],
}

EXT_GAPS = {
    "EXT-001": (
        "partial",
        "Real-kernel regions, line/arc/circle contours, holes, invalid contours, "
        "single transaction, Undo and save/reopen are covered. The interactive arbitrary "
        "Sketcher UI and preview/cancel flow are not implemented yet.",
    ),
    "EXT-002": (
        "partial",
        "A deterministic numerical solver covers coincident/horizontal/vertical/parallel/"
        "perpendicular/tangent/equal/dimension/fix fixtures, residuals, rank/DOF, conflict versus "
        "compatible redundancy, drag stability, preview without commit and document persistence. "
        "Direct canvas editing of arbitrary sketch elements remains open.",
    ),
    "EXT-003": (
        "partial",
        "Real-kernel revolve, circular sweep and ruled loft match independent volume oracles. "
        "The UI currently exposes controlled presets; curved sweep orientation, self-intersection "
        "rejection and arbitrary multi-section editing remain open.",
    ),
    "EXT-004": (
        "partial",
        "Cylindrical shell, signed rectangular draft and triangular rib presets have real-kernel "
        "analytical oracles, invalid-input checks and document transaction evidence. Generic face "
        "shelling, draft on selected faces and ribs from arbitrary sketches remain open.",
    ),
    "EXT-005": (
        "partial",
        "Embedded SVG/DXF extrusion validates physical units, holes and unsafe content; fixed-version "
        "Cyrillic text creates exportable add/cut BRep geometry without silent font fallback. Broader "
        "entity/transform fixtures, arbitrary placement on existing faces and native file-dialog E2E remain open.",
    ),
    "EXT-006": (
        "partial",
        "Versioned explicit fixtures for an M5 nut pocket, 608 bearing pocket and M3 heat insert "
        "have analytical real-kernel oracles and distinct radial/diametral/one-sided clearance "
        "semantics. External dimensional sources, dependent edits on existing bodies and physical "
        "print validation remain open.",
    ),
    "EXT-007": (
        "partial",
        "A versioned metric-60-v1 single-start external/internal pair uses real helical BRep geometry, "
        "supports right/left hand, checks assembly clearance and persists as one document transaction. "
        "Multi-start profiles, standards catalog and physical fastener print validation remain open.",
    ),
    "EXT-008": (
        "partial",
        "Existing arbitrary plane split preserves volume; a rectangular fixture adds two pins and "
        "clearanced sockets, verifies assembly non-intersection and stores reversible print placement. "
        "Connectors on arbitrary selected parts, snap locks and thin-wall warning UI remain open.",
    ),
    "EXT-009": (
        "partial",
        "A single transaction creates 2-10 geometrically distinct coupons with BRep value labels "
        "and an explicit sample-to-clearance mapping; the chosen profile name is stored only in that "
        "operation. Printer/material profile management and physical print measurements remain open.",
    ),
    "EXT-010": (
        "partial",
        "Persistent embedded mesh history covers transforms, a specific supported hole repair with "
        "before/after diagnostics and counterexample, topology-aware decimation range, components, "
        "Euler number, bbox/volume and explicitly sampled shape error. General self-intersection "
        "detection/repair and arbitrary manual vertex editing remain open.",
    ),
    "EXT-011": (
        "partial",
        "An experimental embedded image-to-heightmap mesh workflow enforces limits, provides preview "
        "and explicit hash-bound Apply, stores model/seed/settings, scale/units, supports cancel, "
        "Undo, reopen and mesh export, and labels quality as non-engineering. External generative "
        "providers and perceptual 3D similarity evaluation remain open.",
    ),
    "EXT-012": (
        "partial",
        "Every shipped M4 command is linked to offline help, operation-only projects embed vector "
        "and mesh/image sources, dedicated advanced/constraint/mesh/image lessons are shipped, and "
        "future format versions fail with an explicit update message. Native walkthrough evidence "
        "and examples for every remaining partial clause remain open.",
    ),
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
            implementation_status, gap = EXT_GAPS.get(
                requirement_id,
                ("planned", "M4 scope: функция и её доказательства ещё не реализованы."),
            )
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
        "current_stage": "M4",
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
