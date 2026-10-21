#!/usr/bin/env python3
"""Сборка поискового индекса справки для приложения (HELP-006/HELP-012).

Читает docs/help/articles/*.md и пишет единый JSON
app/ui/public/help/index.json (оглавление + тела статей для локального
поиска). Скрипт сначала запускает check_help.py.

Запуск: backend/.venv/bin/python scripts/build_help_index.py
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from check_help import parse_article  # noqa: E402

ARTICLES = ROOT / "docs" / "help" / "articles"
OUT = ROOT / "app" / "ui" / "public" / "help" / "index.json"


def main() -> int:
    check = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_help.py")],
        capture_output=True, text=True)
    if check.returncode != 0:
        print(check.stdout)
        return 1
    articles = []
    for path in sorted(ARTICLES.glob("*.md")):
        meta, body = parse_article(path)
        articles.append({
            "help_id": meta["help_id"],
            "title": meta.get("title", meta["help_id"]),
            "synonyms": meta.get("synonyms", []),
            "commands": meta.get("commands", []),
            "related": meta.get("related", []),
            "body_markdown": body.strip(),
        })
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"schema_version": 1, "articles": articles},
                              ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"Индекс собран: {OUT} ({len(articles)} статей)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
