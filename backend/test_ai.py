"""AC-11: невалидные и устаревшие AI-планы не меняют документ (уровень валидации)."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ai_planner  # noqa: E402
import dev_shim  # noqa: E402

pytestmark = [pytest.mark.unit, pytest.mark.contract, pytest.mark.ai]


class FakeDoc:
    def __init__(self):
        self.doc_id = "doc-test"
        self.document_instance_id = "instance-test"
        self.revision = 7
        self.parts = [{"part_id": "part-1",
                       "template": "plate_with_holes",
                       "params": {"length": 80, "hole_diameter": 4}}]


def base_plan(**kw):
    p = {
        "schema_version": 1,
        "document_id": "doc-test",
        "document_instance_id": "instance-test",
        "base_revision": 7,
        "units": "mm",
        "assumptions": [],
        "questions": [],
        "operations": [],
        "summary": "test",
    }
    p.update(kw)
    return p


def test_negative_diameter_rejected():
    doc = FakeDoc()
    plan = base_plan(operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "hole_diameter", "value": -4}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_invalid"
    assert "положительным" in err["message"]


def test_unknown_command_rejected():
    doc = FakeDoc()
    plan = base_plan(operations=[{
        "command_id": "doc.delete_everything", "target_id": None,
        "parameters": {}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_forbidden"


def test_arbitrary_code_rejected():
    doc = FakeDoc()
    plan = base_plan(operations=[{
        "command_id": "python.exec", "target_id": None,
        "parameters": {"code": "import os; os.system('rm -rf /')"}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_forbidden"


def test_missing_object_rejected():
    doc = FakeDoc()
    plan = base_plan(operations=[{
        "command_id": "parameter.set", "target_id": "part-999",
        "parameters": {"name": "length", "value": 10}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_invalid"
    assert "не существует" in err["message"]


def test_stale_revision_rejected():
    doc = FakeDoc()
    plan = base_plan(base_revision=3, operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "length", "value": 10}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_stale"


def test_wrong_document_rejected():
    doc = FakeDoc()
    plan = base_plan(document_id="doc-other", operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "length", "value": 10}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_stale"


def test_too_many_ops_rejected():
    doc = FakeDoc()
    ops = [{"command_id": "parameter.set", "target_id": "part-1",
            "parameters": {"name": "length", "value": i + 1}} for i in range(21)]
    err = ai_planner.validate_plan(base_plan(operations=ops), doc)
    assert err and err["code"] == "plan_invalid"


def test_non_finite_rejected():
    doc = FakeDoc()
    plan = base_plan(operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "length", "value": float("inf")}}])
    err = ai_planner.validate_plan(plan, doc)
    assert err and err["code"] == "plan_invalid"


@pytest.mark.parametrize("plan", [
    base_plan(unexpected=True, operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "length", "value": 10},
    }]),
    base_plan(operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "length", "value": 10}, "unexpected": True,
    }]),
    base_plan(operations=[{
        "command_id": "part.create.from_template", "target_id": None,
        "parameters": {"template": "washer", "params": {}, "unexpected": True},
    }]),
])
def test_unknown_schema_fields_rejected(plan):
    err = ai_planner.validate_plan(plan, FakeDoc())
    assert err and err["code"] == "plan_invalid"


def test_non_string_target_and_non_mm_units_rejected():
    wrong_target = base_plan(operations=[{
        "command_id": "parameter.set", "target_id": 1,
        "parameters": {"name": "length", "value": 10},
    }])
    target_error = ai_planner.validate_plan(wrong_target, FakeDoc())
    assert target_error and "target_id" in target_error["message"]

    wrong_units = base_plan(units="inch", operations=[{
        "command_id": "parameter.set", "target_id": "part-1",
        "parameters": {"name": "length", "value": 10},
    }])
    units_error = ai_planner.validate_plan(wrong_units, FakeDoc())
    assert units_error and "миллиметрах" in units_error["message"]


def test_clarification_without_ops_is_legal():
    doc = FakeDoc()
    plan = base_plan(questions=["Уточните диаметр?"])
    assert ai_planner.validate_plan(plan, doc) is None


def test_valid_washer_plan_accepted():
    doc = FakeDoc()
    plan = base_plan(operations=[{
        "command_id": "part.create.from_template", "target_id": None,
        "parameters": {"template": "washer",
                       "params": {"outer_diameter": 20, "inner_diameter": 6,
                                  "height": 4}}}])
    assert ai_planner.validate_plan(plan, doc) is None


def test_scripted_planner_ac10():
    doc = FakeDoc()
    plan = ai_planner.scripted_plan(
        "Создай шайбу: наружный диаметр 20 мм, внутренний 6 мм, высота 4 мм", doc)
    op = plan["operations"][0]
    assert op["command_id"] == "part.create.from_template"
    assert op["parameters"]["params"] == {
        "outer_diameter": 20, "inner_diameter": 6, "height": 4}
    assert ai_planner.validate_plan(plan, doc) is None


def test_scripted_planner_builds_ac10_plate_fixture():
    doc = FakeDoc()
    plan = ai_planner.scripted_plan(
        "Создай пластину 80 на 40 толщиной 6 с четырьмя отверстиями 4 мм", doc)
    operation = plan["operations"][0]
    assert operation["command_id"] == "part.create.from_template"
    assert operation["parameters"] == {
        "template": "plate_with_holes",
        "params": {
            "length": 80,
            "width": 40,
            "height": 6,
            "hole_diameter": 4,
        },
    }
    assert ai_planner.validate_plan(plan, doc) is None


def test_scripted_ambiguous_marks_assumption():
    doc = FakeDoc()
    plan = ai_planner.scripted_plan("сделай отверстие побольше", doc)
    assert plan["assumptions"], "ожидалось явное редактируемое предположение"
    assert plan["operations"][0]["parameters"]["value"] > 4


def test_clarification_does_not_start_empty_preview(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "scripted", "base_url": "", "model": "scripted-v1",
        "api_key": "",
    })
    preview_calls = []
    result = ai_planner.ai_plan(
        "непонятный запрос", FakeDoc(),
        lambda *_args: preview_calls.append(True),
    )
    assert result["plan"]["questions"]
    assert result["preview"] is None
    assert preview_calls == []


def test_provider_configuration_never_returns_api_key(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "disabled", "base_url": "", "model": "", "api_key": ""})
    info = ai_planner.configure_provider(
        "openai", "http://127.0.0.1:3001/v1/", "test-model", "secret-value")
    assert info["provider"] == "openai"
    assert info["base_url"] == "http://127.0.0.1:3001/v1"
    assert info["has_api_key"] is True
    assert "secret-value" not in json.dumps(info)


def test_ollama_profile_rejects_remote_endpoint(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "disabled", "base_url": "", "model": "", "api_key": ""})
    try:
        ai_planner.configure_provider(
            "ollama", "https://example.com/v1", "qwen3:4b")
    except ValueError as error:
        assert "локального endpoint" in str(error)
    else:
        raise AssertionError("удалённый endpoint не должен приниматься как локальный Ollama")


def test_disabling_provider_does_not_require_network_settings(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "openai", "base_url": "http://localhost:3001/v1",
        "model": "test-model", "api_key": "secret-value"})
    info = ai_planner.configure_provider(
        "disabled", "", "", clear_api_key=True)
    assert info["available"] is False
    assert info["has_api_key"] is False


def test_ollama_plan_request_includes_json_schema(monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "ollama", "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen3:4b", "api_key": ""})
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return json.dumps({
                "choices": [{"message": {"content": "{}"}}]}).encode()

    def fake_urlopen(request, timeout):
        captured["body"] = json.loads(request.data)
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(ai_planner.urllib.request, "urlopen", fake_urlopen)
    schema = {"type": "object", "properties": {}}
    ai_planner.http_chat(
        [{"role": "user", "content": "test"}], True, json_schema=schema)

    response_format = captured["body"]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["schema"] == schema
    assert captured["body"]["reasoning_effort"] == "none"
    assert captured["timeout"] == ai_planner.AI_TIMEOUT_S


def test_system_prompt_exposes_exact_semantic_contract():
    doc = FakeDoc()
    prompt = ai_planner.system_prompt(doc)

    assert "washer {outer_diameter, inner_diameter, height}" in prompt
    assert "plate_with_holes {length, width, height, hole_diameter, hole_offset}" in prompt
    assert "Если пользователь меняет существующую деталь, используй parameter.set" in prompt
    assert "Не выдумывай template, parameter name, part_id или edge_ref" in prompt
    assert "backend применит defaults" in prompt
    assert doc.document_instance_id in prompt


def test_plan_schema_binds_templates_and_existing_parameters():
    schema = ai_planner.plan_json_schema(FakeDoc())
    variants = schema["properties"]["operations"]["items"]["oneOf"]

    washer = next(
        variant for variant in variants
        if variant["properties"]["parameters"]["properties"]
        .get("template", {}).get("const") == "washer")
    washer_params = washer["properties"]["parameters"]["properties"]["params"]
    assert set(washer_params["properties"]) == {
        "outer_diameter", "inner_diameter", "height"}
    assert washer_params["additionalProperties"] is False

    length_edit = next(
        variant for variant in variants
        if variant["properties"]["command_id"]["const"] == "parameter.set"
        and variant["properties"]["parameters"]["properties"]["name"]["const"]
        == "length")
    assert length_edit["properties"]["target_id"]["const"] == "part-1"

    edit_schema = ai_planner.plan_json_schema(
        FakeDoc(), "Измени длину детали на 100 мм")
    edit_variants = edit_schema["properties"]["operations"]["items"]["oneOf"]
    assert len(edit_variants) == 1
    assert (edit_variants[0]["properties"]["parameters"]["properties"]
            ["name"]["const"] == "length")

    clarification_schema = ai_planner.plan_json_schema(
        type("EmptyDoc", (), {"doc_id": "doc", "document_instance_id": "instance",
                              "revision": 0, "parts": []})(),
        "Сделай деталь покрепче")
    assert clarification_schema["properties"]["operations"]["maxItems"] == 0
    assert clarification_schema["properties"]["questions"]["minItems"] == 1


def test_ai_transaction_single_undo_clears_derived_geometry(monkeypatch):
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    monkeypatch.setitem(dev_shim.DOCS, "tutorial", dev_shim.Doc())
    dev_shim.ACTIVE[0] = "main"

    def fake_worker_call(method, params, revision=0):
        assert method == "build"
        return {
            "stats": {
                "volume": 1143.5,
                "solid_count": 1,
                "bbox": [-10, -10, 0, 10, 10, 4],
                "is_valid": True,
            },
            "mesh": {"path": "/tmp/preview.mesh"},
        }

    monkeypatch.setattr(dev_shim, "worker_call", fake_worker_call)
    operation = {
        "command_id": "part.create.from_template",
        "target_id": None,
        "parameters": {
            "template": "washer",
            "params": {"outer_diameter": 20, "inner_diameter": 6, "height": 4},
        },
    }

    applied = dev_shim.cmd_doc_transaction({
        "operations": [operation],
        "base_revision": 0,
        "mode": "apply",
    })
    assert applied["stats"]["volume"] == 1143.5
    assert applied["can_undo"] is True

    undone = dev_shim.cmd_doc_undo({})
    assert undone["parts"] == []
    assert undone["stats"] is None
    assert undone["can_undo"] is False
    assert undone["can_redo"] is True
    assert undone["revision"] == 2
