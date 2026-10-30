#!/usr/bin/env python3
"""Проверяет единую SemVer-версию перед desktop release."""

from __future__ import annotations

import json
import os
import re
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?(?:\+[0-9A-Za-z.-]+)?$")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    values = {
        "app/package.json": read_json(ROOT / "app" / "package.json")["version"],
        "app/package-lock.json": read_json(ROOT / "app" / "package-lock.json")["version"],
        "app/ui/package.json": read_json(ROOT / "app" / "ui" / "package.json")["version"],
        "app/ui/package-lock.json": read_json(ROOT / "app" / "ui" / "package-lock.json")["version"],
        "app/src-tauri/Cargo.toml": tomllib.loads(
            (ROOT / "app" / "src-tauri" / "Cargo.toml").read_text(encoding="utf-8")
        )["package"]["version"],
        "app/src-tauri/tauri.conf.json": read_json(
            ROOT / "app" / "src-tauri" / "tauri.conf.json"
        )["version"],
    }
    unique = set(values.values())
    if len(unique) != 1:
        detail = "\n".join(f"- {path}: {version}" for path, version in values.items())
        raise SystemExit(f"Версии desktop release не совпадают:\n{detail}")

    version = unique.pop()
    if not SEMVER.fullmatch(version):
        raise SystemExit(f"Некорректная SemVer-версия: {version}")

    if os.environ.get("GITHUB_REF_TYPE") == "tag":
        expected_tag = f"v{version}"
        actual_tag = os.environ.get("GITHUB_REF_NAME")
        if actual_tag != expected_tag:
            raise SystemExit(f"Тег {actual_tag!r} не совпадает с версией приложения {expected_tag!r}")

    print(f"Desktop release version: {version}")


if __name__ == "__main__":
    main()
