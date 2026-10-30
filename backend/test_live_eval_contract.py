import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

pytestmark = [pytest.mark.contract, pytest.mark.ai]


def test_live_eval_dataset_has_twenty_prompts_and_three_runs():
    data = json.loads((ROOT / "tests/live_eval/prompts.json").read_text())
    assert data["runs_per_prompt"] == 3
    assert len(data["prompts"]) == 20
    assert len({item["id"] for item in data["prompts"]}) == 20
    assert {item["category"] for item in data["prompts"]} >= {
        "build", "edit", "clarify", "help", "refusal", "invalid",
    }
