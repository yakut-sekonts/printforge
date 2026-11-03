#!/usr/bin/env python3
"""Собирает geometry worker для текущей платформы и кладёт его в Tauri binaries."""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
BINARIES = ROOT / "app" / "src-tauri" / "binaries"


def native_target() -> str:
    machine = platform.machine().lower()
    if sys.platform == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "aarch64-apple-darwin"
        if machine in {"x86_64", "amd64"}:
            return "x86_64-apple-darwin"
    if sys.platform == "win32" and machine in {"x86_64", "amd64"}:
        return "x86_64-pc-windows-msvc"
    raise SystemExit(f"Неподдерживаемая платформа sidecar: {sys.platform}/{machine}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", help="Ожидаемый Rust target triple")
    args = parser.parse_args()

    detected_target = native_target()
    target = args.target or detected_target
    if target != detected_target:
        raise SystemExit(
            f"PyInstaller не поддерживает cross-build sidecar: runner={detected_target}, target={target}"
        )

    dist_dir = BACKEND / "dist"
    build_dir = BACKEND / "build"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--onefile",
            "--name",
            "printforge-geo",
            "--collect-all",
            "build123d",
            "--collect-all",
            "OCP",
            "--collect-all",
            "OCP_modules",
            "--collect-all",
            "lib3mf",
            "--collect-all",
            "trimesh",
            "--add-data",
            f"{ROOT / 'design-sources' / 'impeccable' / 'ui' / 'component-review' / 'fonts' / 'jetbrainsmono.ttf'}{os.pathsep}assets",
            "--distpath",
            str(dist_dir),
            "--workpath",
            str(build_dir),
            "--specpath",
            str(BACKEND),
            "--clean",
            "--noconfirm",
            str(BACKEND / "worker.py"),
        ],
        cwd=ROOT,
        check=True,
    )

    suffix = ".exe" if sys.platform == "win32" else ""
    source = dist_dir / f"printforge-geo{suffix}"
    destination = BINARIES / f"printforge-geo-{target}{suffix}"
    BINARIES.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    if sys.platform != "win32":
        destination.chmod(destination.stat().st_mode | 0o111)
    print(f"Sidecar: {destination} ({destination.stat().st_size / 1024 / 1024:.1f} MiB)")


if __name__ == "__main__":
    main()
