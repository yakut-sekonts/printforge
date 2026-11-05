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
    assert len(help_ids) == 35
    assert "ai-pomoshchnik" in help_ids
    assert len(public_commands["commands"]) == 62
    assert all(command["help_id"] in help_ids for command in public_commands["commands"])


def test_lesson_checks_reference_supported_actions_and_parameters():
    lessons = json.loads((ROOT / "app/shared/lessons.json").read_text())["lessons"]
    commands = {
        command["command_id"]
        for command in json.loads((ROOT / "app/shared/commands.json").read_text())["commands"]
    }
    commands.update({"view.fit", "view.top", "view.front", "view.side", "view.iso", "view.proj"})
    templates = {
        template["template_id"]: {parameter["name"] for parameter in template["params"]}
        for template in json.loads((ROOT / "app/shared/templates.json").read_text())["templates"]
    }
    check_types = {
        "camera_rotated", "camera_zoomed", "command", "face_selected", "params",
        "saved", "reopened", "exported", "operation", "error_shown", "imported",
        "check_result",
    }
    operations = {
        "transform", "face_offset", "fillet", "chamfer", "sketch_extrude", "constrained_sketch_extrude",
        "shell", "mesh_source", "mesh_repair", "mesh_decimate", "image_relief_source",
    }
    for lesson in lessons:
        template_id = None
        step_ids = set()
        for step in lesson["steps"]:
            assert step["id"] not in step_ids, lesson["lesson_id"]
            step_ids.add(step["id"])
            check = step["check"]
            assert check["type"] in check_types, step
            if check["type"] == "command":
                assert check["command_id"] in commands, step
            if check["type"] == "operation":
                assert check["op"] in operations, step
            if "template" in check:
                template_id = check["template"]
                assert template_id in templates, step
            if template_id and "params" in check:
                assert set(check["params"]) <= templates[template_id], step


def test_first_lesson_teaches_primitive_selection_and_direct_editing():
    lessons = json.loads((ROOT / "app/shared/lessons.json").read_text())["lessons"]
    lesson = next(item for item in lessons if item["lesson_id"] == "first-part")
    assert lesson["content_version"] >= 2
    creation, selection, dimension, movement, undo = [step["check"] for step in lesson["steps"]]
    assert creation == {
        "type": "params", "template": "box",
        "params": {"length": 40, "width": 30, "height": 20},
    }
    assert selection == {"type": "face_selected"}
    assert dimension == {"type": "operation", "op": "face_offset"}
    assert movement == {"type": "operation", "op": "transform"}
    assert undo == {"type": "command", "command_id": "op.undo"}
