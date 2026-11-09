import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_test_manifest  # noqa: E402

pytestmark = pytest.mark.contract


def _data():
    manifest = json.loads((ROOT / "docs/testing/requirements.yaml").read_text(encoding="utf-8"))
    catalog = json.loads((ROOT / "tests/test_catalog.json").read_text(encoding="utf-8"))
    return manifest, catalog


def test_repository_test_manifest_is_structurally_valid():
    manifest, catalog = _data()
    errors, warnings = check_test_manifest.validate(manifest, catalog)
    assert errors == []
    assert warnings, "M3 product gaps must remain visible until all mandatory evidence exists"


def test_manifest_validator_detects_missing_requirement():
    manifest, catalog = _data()
    broken = copy.deepcopy(manifest)
    broken["requirements"].pop()
    errors, _warnings = check_test_manifest.validate(broken, catalog)
    assert any("missing requirement IDs" in error for error in errors)


def test_manifest_validator_detects_nonexistent_test_name():
    manifest, catalog = _data()
    broken = copy.deepcopy(catalog)
    broken["tests"][0]["nodeids"] = ["backend/test_templates.py::test_does_not_exist"]
    errors, _warnings = check_test_manifest.validate(manifest, broken)
    assert any("nonexistent nodeid" in error for error in errors)
