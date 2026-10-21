#!/usr/bin/env python3
"""Проверка целостности справки PrintForge (HELP-013).

- у каждой команды app/shared/commands.json есть статья с её help_id;
- нет дубликатов help_id; ссылки related/commands существуют;
- нет пустых статей, TODO, Lorem ipsum;
- synonyms из HELP-006 ведут на существующие статьи.

Запуск: backend/.venv/bin/python scripts/check_help.py
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARTICLES = ROOT / "docs" / "help" / "articles"
COMMANDS = ROOT / "app" / "shared" / "commands.json"

FRONT = re.compile(r"^---\n(.*?)\n---\n", re.S)
REQUIRED_SYNONYMS = ["дырка", "скос", "закруглить угол", "подготовить к печати",
                     "почему кнопка серая"]


def parse_article(path: Path):
    text = path.read_text(encoding="utf-8")
    m = FRONT.match(text)
    if not m:
        return None, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            v = v.strip()
            if v.startswith("["):
                v = [s.strip().strip('"') for s in v.strip("[]").split(",") if s.strip()]
            meta[k.strip()] = v
    return meta, text[m.end():]


def main() -> int:
    errors = []
    articles = {}
    for path in sorted(ARTICLES.glob("*.md")):
        meta, body = parse_article(path)
        if meta is None:
            errors.append(f"{path.name}: нет YAML-шапки")
            continue
        hid = meta.get("help_id")
        if not hid:
            errors.append(f"{path.name}: нет help_id")
            continue
        if hid in articles:
            errors.append(f"{path.name}: дубликат help_id {hid}")
        meta["body"] = body
        articles[hid] = meta
        if len(body.strip()) < 200:
            errors.append(f"{path.name}: слишком короткая статья")
        for bad in ("TODO", "Lorem ipsum", "TBD"):
            if bad.lower() in body.lower():
                errors.append(f"{path.name}: найден маркер «{bad}»")

    registry = json.loads(COMMANDS.read_text(encoding="utf-8"))
    cmd_ids = set()
    for cmd in registry["commands"]:
        cid = cmd["command_id"]
        cmd_ids.add(cid)
        hid = cmd.get("help_id")
        if not hid or hid not in articles:
            errors.append(f"команда {cid}: нет статьи help_id={hid}")

    for hid, meta in articles.items():
        for rel in meta.get("related", []):
            if rel not in articles:
                errors.append(f"{hid}: related → несуществующая статья {rel}")
        for cid in meta.get("commands", []):
            if cid not in cmd_ids:
                errors.append(f"{hid}: commands → неизвестная команда {cid}")

    all_syn = set()
    for meta in articles.values():
        all_syn.update(meta.get("synonyms", []))
    for s in REQUIRED_SYNONYMS:
        if s not in all_syn:
            errors.append(f"обязательный синоним «{s}» ни к чему не привязан")

    if errors:
        print("Справка: ошибки целостности:")
        for e in errors:
            print(" -", e)
        return 1
    print(f"Справка в порядке: {len(articles)} статей, "
          f"{len(registry['commands'])} команд, все help_id и ссылки валидны.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
