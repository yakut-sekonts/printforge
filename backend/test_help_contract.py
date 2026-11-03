"""Offline help/lessons contract against shipped registries."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import check_help  # noqa: E402

pytestmark = [pytest.mark.contract, pytest.mark.help]


def test_help_registry_integrity():
    assert check_help.main() == 0


def test_shipped_help_and_lessons_match_authoritative_sources():
    shared_commands = json.loads((ROOT / "app/shared/commands.json").read_text())
    public_commands = json.loads((ROOT / "app/ui/public/commands.json").read_text())
    shared_lessons = json.loads((ROOT / "app/shared/lessons.json").read_text())
    public_lessons = json.loads((ROOT / "app/ui/public/lessons.json").read_text())
    help_index = json.loads((ROOT / "app/ui/public/help/index.json").read_text())

    assert public_commands == shared_commands
    assert public_lessons == shared_lessons
    assert len(public_lessons["lessons"]) == 13
    assert {lesson["lesson_id"] for lesson in public_lessons["lessons"]} >= {
        "navigation", "first-part", "save-export", "ai-assistant", "advanced-bodies",
        "constraint-solver", "mesh-repair", "image-relief",
    }
    help_ids = {article["help_id"] for article in help_index["articles"]}
    assert len(help_ids) == 34
    assert "ai-pomoshchnik" in help_ids
    assert len(public_commands["commands"]) == 58
    assert all(command["help_id"] in help_ids for command in public_commands["commands"])
