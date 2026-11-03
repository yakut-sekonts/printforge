"""Static release contract. Не заменяет native E2E и smoke артефакта."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_windows_release_evidence  # noqa: E402

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
    assert config["bundle"]["macOS"]["signingIdentity"] == "-"


def test_geometry_sidecar_bundles_fixed_text_font():
    font = (
        ROOT / "design-sources/impeccable/ui/component-review/fonts/jetbrainsmono.ttf")
    license_path = font.with_name("jetbrainsmono-OFL.txt")
    build_script = (ROOT / "scripts/build_sidecar.py").read_text()
    worker = (ROOT / "backend/worker.py").read_text()

    digest = hashlib.sha256(font.read_bytes()).hexdigest()
    assert digest == "48715a42ec242c21e9f02692891e147d022299a52e48d5e413e1a942193ffeda"
    assert digest in worker
    assert '"--add-data"' in build_script
    assert "jetbrainsmono.ttf" in build_script
    assert "assets" in build_script
    assert "SIL Open Font License, Version 1.1" in license_path.read_text()


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
    assert "python scripts/run_windows_release_evidence.py" in workflow
    assert "windows-release-evidence-${{ github.run_id }}" in workflow
    assert "if: always() && runner.os == 'Windows'" in workflow
    assert "publish-release:" in workflow
    assert "needs: publish" in workflow
    assert "Publish draft after every installer passes" in workflow
    assert "-F draft=false" in workflow


def test_windows_release_evidence_selects_latest_nsis_installer(tmp_path):
    older = tmp_path / "PrintForge_0.1.0_x64-setup.exe"
    newer = tmp_path / "PrintForge_0.2.0_x64-setup.exe"
    older.write_bytes(b"older")
    newer.write_bytes(b"newer")
    older.touch()
    newer.touch()
    older_mtime = older.stat().st_mtime_ns - 1_000_000
    import os
    os.utime(older, ns=(older_mtime, older_mtime))

    assert run_windows_release_evidence.find_installer(tmp_path) == newer.resolve()


def test_windows_release_evidence_extracts_executable_paths():
    assert run_windows_release_evidence.executable_from_command(
        '"C:\\Users\\runner admin\\AppData\\Local\\PrintForge\\uninstall.exe" /S'
    ) == Path("C:\\Users\\runner admin\\AppData\\Local\\PrintForge\\uninstall.exe")
    assert run_windows_release_evidence.executable_from_command(
        "C:\\PrintForge\\printforge.exe,0"
    ) == Path("C:\\PrintForge\\printforge.exe")


def test_windows_authenticode_uses_windows_powershell_and_environment(monkeypatch, tmp_path):
    installer = tmp_path / "PrintForge_0.3.0_x64-setup.exe"
    installer.write_bytes(b"installer")
    captured = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({
                "Status": "NotSigned",
                "StatusMessage": "The file is not digitally signed.",
                "SignerSubject": None,
            }),
            stderr="",
        )

    monkeypatch.setattr(run_windows_release_evidence, "windows_powershell", lambda: "powershell.exe")
    monkeypatch.setattr(run_windows_release_evidence.subprocess, "run", fake_run)

    result = run_windows_release_evidence.authenticode_status(installer)

    assert result["Status"] == "NotSigned"
    assert captured["command"][:6] == [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
    ]
    assert "$env:PRINTFORGE_AUTHENTICODE_PATH" in captured["command"][-1]
    assert str(installer) not in captured["command"][-1]
    assert captured["kwargs"]["env"]["PRINTFORGE_AUTHENTICODE_PATH"] == str(installer)


def test_repository_license_is_apache_2_0():
    license_text = (ROOT / "LICENSE").read_text()
    assert "Apache License\n" in license_text[:100]
    assert "Version 2.0, January 2004" in license_text[:150]
