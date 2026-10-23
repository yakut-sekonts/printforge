"""AC-11: невалидные и устаревшие AI-планы не меняют документ (уровень валидации)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import ai_planner  # noqa: E402


class FakeDoc:
    def __init__(self):
        self.doc_id = "doc-test"
        self.revision = 7
        self.parts = [{"part_id": "part-1",
                       "template": "plate_with_holes",
                       "params": {"length": 80, "hole_diameter": 4}}]


def base_plan(**kw):
    p = {
        "schema_version": 1,
        "document_id": "doc-test",
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


def test_scripted_ambiguous_marks_assumption():
    doc = FakeDoc()
    plan = ai_planner.scripted_plan("сделай отверстие побольше", doc)
    assert plan["assumptions"], "ожидалось явное редактируемое предположение"
    assert plan["operations"][0]["parameters"]["value"] > 4
