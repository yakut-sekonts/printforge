"""Static release contract. Не заменяет native E2E и smoke артефакта."""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.contract, pytest.mark.release]


def test_tauri_updater_and_bundle_contract():
    config = json.loads((ROOT / "app/src-tauri/tauri.conf.json").read_text())
    release = json.loads((ROOT / "app/src-tauri/tauri.release.conf.json").read_text())
    updater = config["plugins"]["updater"]

    assert release["bundle"]["createUpdaterArtifacts"] is True
    assert updater["endpoints"] == [
        "https://github.com/yakut-sekonts/printforge/releases/latest/download/latest.json"
    ]
    assert updater["pubkey"]
    assert updater["windows"]["installMode"] == "passive"


def test_release_workflow_declares_all_supported_desktop_targets():
    workflow = (ROOT / ".github/workflows/release.yml").read_text()
    assert "macos-15" in workflow
    assert "macos-15-intel" in workflow
    assert "windows-latest" in workflow
    assert "aarch64-apple-darwin" in workflow
    assert "x86_64-apple-darwin" in workflow
    assert "x86_64-pc-windows-msvc" in workflow
    assert "TAURI_SIGNING_PRIVATE_KEY" in workflow
    assert 'echo "APPLE_SIGNING_IDENTITY=-"' in workflow


def test_repository_license_is_apache_2_0():
    license_text = (ROOT / "LICENSE").read_text()
    assert "Apache License\n" in license_text[:100]
    assert "Version 2.0, January 2004" in license_text[:150]
