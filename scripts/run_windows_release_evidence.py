#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import struct
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TARGET = "x86_64-pc-windows-msvc"
DEFAULT_INSTALLER_DIR = (
    ROOT / "app" / "src-tauri" / "target" / TARGET / "release" / "bundle" / "nsis"
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def find_installer(directory: Path) -> Path:
    candidates = sorted(
        directory.glob("*-setup.exe"),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )
    if not candidates:
        raise FileNotFoundError(f"NSIS installer не найден в {directory}")
    return candidates[0].resolve()


def executable_from_command(value: str | None) -> Path | None:
    if not value:
        return None
    command = os.path.expandvars(value.strip())
    if command.startswith('"'):
        closing_quote = command.find('"', 1)
        if closing_quote > 1:
            return Path(command[1:closing_quote])
    match = re.match(r"(?i)(.*?\.exe)(?:\s|,|$)", command)
    return Path(match.group(1).strip()) if match else None


def registry_installations() -> list[dict[str, str]]:
    if platform.system() != "Windows":
        return []
    import winreg

    uninstall_key = r"Software\Microsoft\Windows\CurrentVersion\Uninstall"
    roots = [(winreg.HKEY_CURRENT_USER, "HKCU"), (winreg.HKEY_LOCAL_MACHINE, "HKLM")]
    views = [winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY]
    records = []
    seen = set()
    for root, root_name in roots:
        for view in views:
            try:
                parent = winreg.OpenKey(root, uninstall_key, 0, winreg.KEY_READ | view)
            except OSError:
                continue
            with parent:
                index = 0
                while True:
                    try:
                        subkey_name = winreg.EnumKey(parent, index)
                    except OSError:
                        break
                    index += 1
                    try:
                        subkey = winreg.OpenKey(parent, subkey_name)
                    except OSError:
                        continue
                    with subkey:
                        values = {"registry_root": root_name, "registry_key": subkey_name}
                        for name in (
                            "DisplayName", "DisplayVersion", "InstallLocation",
                            "DisplayIcon", "UninstallString",
                        ):
                            try:
                                values[name] = str(winreg.QueryValueEx(subkey, name)[0])
                            except OSError:
                                pass
                    if values.get("DisplayName", "").casefold() != "printforge":
                        continue
                    identity = (values.get("registry_root"), values.get("registry_key"))
                    if identity not in seen:
                        seen.add(identity)
                        records.append(values)
    return records


def installed_executable(record: dict[str, str]) -> Path | None:
    candidates = []
    install_location = record.get("InstallLocation")
    if install_location:
        candidates.append(Path(os.path.expandvars(install_location)) / "printforge.exe")
    display_icon = executable_from_command(record.get("DisplayIcon"))
    if display_icon:
        candidates.extend([display_icon, display_icon.parent / "printforge.exe"])
    uninstaller = executable_from_command(record.get("UninstallString"))
    if uninstaller:
        candidates.append(uninstaller.parent / "printforge.exe")
    for candidate in candidates:
        if candidate.is_file() and candidate.name.casefold() == "printforge.exe":
            return candidate.resolve()
    return None


def wait_for_installation(timeout: float) -> tuple[dict[str, str], Path]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for record in registry_installations():
            executable = installed_executable(record)
            if executable:
                return record, executable
        time.sleep(0.5)
    raise TimeoutError("PrintForge не найден в Windows uninstall registry после установки")


def authenticode_status(path: Path) -> dict[str, object]:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        raise RuntimeError("Installer не является PE-файлом: DOS header отсутствует")

    pe_offset = struct.unpack_from("<I", data, 0x3C)[0]
    if pe_offset + 24 > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        raise RuntimeError("Installer не является PE-файлом: PE header отсутствует")

    optional_header_size = struct.unpack_from("<H", data, pe_offset + 20)[0]
    optional_header_offset = pe_offset + 24
    if optional_header_offset + optional_header_size > len(data):
        raise RuntimeError("Installer содержит усечённый PE optional header")

    magic = struct.unpack_from("<H", data, optional_header_offset)[0]
    if magic == 0x10B:
        directory_count_offset = 92
        directory_offset = 96
    elif magic == 0x20B:
        directory_count_offset = 108
        directory_offset = 112
    else:
        raise RuntimeError(f"Неподдерживаемый PE optional header magic: 0x{magic:04x}")

    required_size = directory_offset + 5 * 8
    if optional_header_size < required_size:
        raise RuntimeError("PE optional header не содержит security data directory")
    directory_count = struct.unpack_from(
        "<I", data, optional_header_offset + directory_count_offset,
    )[0]
    if directory_count < 5:
        return {
            "Status": "NotSigned",
            "StatusMessage": "PE image has no Authenticode security directory.",
            "SignerSubject": None,
        }

    certificate_offset, certificate_size = struct.unpack_from(
        "<II", data, optional_header_offset + directory_offset + 4 * 8,
    )
    if certificate_offset == 0 or certificate_size == 0:
        return {
            "Status": "NotSigned",
            "StatusMessage": "PE image has no embedded Authenticode certificate table.",
            "SignerSubject": None,
        }
    if certificate_offset + certificate_size > len(data):
        raise RuntimeError("PE Authenticode certificate table выходит за границы installer")
    return {
        "Status": "SignaturePresent",
        "StatusMessage": "PE image contains an embedded Authenticode certificate table.",
        "SignerSubject": None,
        "CertificateTableOffset": certificate_offset,
        "CertificateTableSize": certificate_size,
    }


def sidecar_paths(executable: Path) -> list[Path]:
    return sorted(executable.parent.glob("printforge-geo*.exe"))


def uninstall(record: dict[str, str]) -> dict[str, object]:
    executable = executable_from_command(record.get("UninstallString"))
    if not executable or not executable.is_file():
        return {"status": "not_run", "reason": "uninstaller не найден"}
    result = subprocess.run(
        [str(executable), "/S"],
        check=False,
        capture_output=True,
        text=True,
        timeout=180,
    )
    return {
        "status": "passed" if result.returncode == 0 else "failed",
        "return_code": result.returncode,
        "executable": str(executable),
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def evidence_status(gates: dict[str, dict[str, object]], has_error: bool) -> str:
    if has_error or len(gates) != 3:
        return "failed"
    if any(
        gate.get("blocking", True) and gate.get("status") != "passed"
        for gate in gates.values()
    ):
        return "failed"
    if any(gate.get("status") != "passed" for gate in gates.values()):
        return "passed_with_observations"
    return "passed"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installer", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--startup-runs", type=int, default=7)
    parser.add_argument("--workload-runs", type=int, default=3)
    parser.add_argument("--duration-ms", type=int, default=3000)
    parser.add_argument("--timeout", type=float, default=45)
    parser.add_argument(
        "--performance-policy",
        choices=("enforce", "record"),
        default="enforce",
        help="enforce блокирует выпуск по performance thresholds; record сохраняет их как отдельную оценку",
    )
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().casefold() not in {"amd64", "x86_64"}:
        parser.error("Windows release evidence требует Windows x64 runner")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = (args.output_dir or ROOT / "artifacts" / "windows-release" / timestamp).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "windows-release-evidence.json"
    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip(),
        "environment": {
            "platform": platform.platform(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "configuration": {
            "performance_policy": args.performance_policy,
        },
        "gates": {},
    }
    record = None
    try:
        installer = args.installer.resolve() if args.installer else find_installer(DEFAULT_INSTALLER_DIR)
        report["installer"] = {
            "path": str(installer),
            "size_bytes": installer.stat().st_size,
            "sha256": sha256(installer),
        }
        installer_signature = authenticode_status(installer)
        report["installer"]["authenticode"] = installer_signature
        report["gates"]["installer_authenticode_policy"] = {
            "target": "unsigned NSIS installer for the open-source release profile",
            "actual": installer_signature,
            "status": "passed" if installer_signature.get("Status") == "NotSigned" else "failed",
        }
        install_result = subprocess.run(
            [str(installer), "/S"],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        report["installation"] = {
            "return_code": install_result.returncode,
            "stdout": install_result.stdout.strip(),
            "stderr": install_result.stderr.strip(),
        }
        if install_result.returncode != 0:
            raise RuntimeError(f"NSIS installer завершился с кодом {install_result.returncode}")
        record, executable = wait_for_installation(args.timeout)
        sidecars = sidecar_paths(executable)
        report["installation"].update({
            "registry": record,
            "executable": str(executable),
            "executable_sha256": sha256(executable),
            "sidecars": [str(path) for path in sidecars],
        })
        report["gates"]["installed_nsis_payload"] = {
            "target": "installed printforge.exe and native geometry sidecar exist",
            "actual": {"executable": str(executable), "sidecars": [str(path) for path in sidecars]},
            "status": "passed" if sidecars else "failed",
        }
        perf_dir = output_dir / "performance"
        perf_command = [
            sys.executable,
            str(ROOT / "scripts" / "run_native_perf.py"),
            "--app", str(executable),
            "--output-dir", str(perf_dir),
            "--startup-runs", str(args.startup_runs),
            "--workload-runs", str(args.workload_runs),
            "--duration-ms", str(args.duration_ms),
            "--timeout", str(args.timeout),
        ]
        perf_result = subprocess.run(
            perf_command,
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        native_report_path = perf_dir / "native-perf-report.json"
        report["native_performance"] = {
            "command": perf_command,
            "return_code": perf_result.returncode,
            "stdout": perf_result.stdout.strip(),
            "stderr": perf_result.stderr.strip(),
            "report": str(native_report_path),
            "overall_status": "report_missing",
        }
        if not native_report_path.is_file():
            raise RuntimeError(
                "Native performance report не создан; "
                f"exit={perf_result.returncode}, stderr={perf_result.stderr.strip()}"
            )
        native_report = json.loads(native_report_path.read_text(encoding="utf-8"))
        report["native_performance"]["overall_status"] = native_report.get("overall_status")
        report["gates"]["installed_native_performance"] = {
            "target": "installed NSIS payload passes native startup, FPS, memory and control-scene gates",
            "actual": native_report.get("gates"),
            "status": "passed" if perf_result.returncode == 0 else "failed",
            "blocking": args.performance_policy == "enforce",
        }
    except Exception as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if record:
            try:
                report["uninstall"] = uninstall(record)
            except Exception as error:
                report["uninstall"] = {
                    "status": "failed", "type": type(error).__name__, "message": str(error),
                }

    gates = report["gates"]
    report["overall_status"] = evidence_status(gates, bool(report.get("error")))
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Windows release evidence: {report_path.relative_to(ROOT)}")
    for name, gate in gates.items():
        print(f" - {name}: {gate['status']}")
    if report.get("error"):
        print(f" - error: {report['error']['message']}", file=sys.stderr)
    return 0 if report["overall_status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
