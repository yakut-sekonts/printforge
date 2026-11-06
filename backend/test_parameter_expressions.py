import copy
import json
from pathlib import Path

import pytest

from parameter_expressions import MINIMUMS, Parser, resolve_parts
from worker import TEMPLATES, handle_resolve_parameters

pytestmark = pytest.mark.unit
DEFAULTS = {name: item[1] for name, item in TEMPLATES.items()}


def box(identifier="part-1", **params):
    return {"part_id": identifier, "template": "box", "params": params}


def test_minimums_match_published_catalog():
    catalog = json.loads((Path(__file__).resolve().parent.parent / "app/shared/templates.json").read_text(encoding="utf-8"))
    assert MINIMUMS == {template["template_id"]: {parameter["name"]: parameter["min"] for parameter in template["params"]} for template in catalog["templates"]}


@pytest.mark.parametrize("source,expected", [("2+3*4", 14), ("(2+3)*4", 20), ("-(-2)+3,5", 5.5), ("длина / 2", 20), ("Длина/2", 20), ("length / 2", 20)])
def test_parser_uses_explicit_grammar_and_russian_aliases(source, expected):
    assert Parser(source, {"length": 40}.__getitem__).evaluate() == expected


@pytest.mark.parametrize("source", ["", "abc", "1/0", "2**3", "(20+5", "1e2", "__import__('os')", "1..2"])
def test_invalid_expressions_are_not_executed(source):
    def lookup(name):
        raise ValueError(f"Неизвестный параметр «{name}»")

    with pytest.raises(ValueError):
        Parser(source, lookup).evaluate()


def test_resolver_uses_defaults_transitive_dependencies_and_part_scoping():
    parts = [box(length=60), box("part-2", length=100)]
    result = resolve_parts(parts, {"part-1.width": "длина / 2", "part-1.height": "width / 2 + 1", "part-2.width": "length / 4"}, DEFAULTS)
    assert result["parts"][0]["params"] == {"length": 60, "width": 30, "height": 16}
    assert result["parts"][1]["params"] == {"length": 100, "width": 25, "height": 20}
    assert parts == [box(length=60), box("part-2", length=100)]
    partial = handle_resolve_parameters({"parts": [box()], "expressions": {"part-1.width": "length / 2"}})
    assert partial["parts"][0]["params"]["width"] == 20


@pytest.mark.parametrize("expressions", [
    {"part-1.width": "width / 2"},
    {"part-1.width": "height / 2", "part-1.height": "width / 2"},
    {"part-1.width": "unknown / 2"},
    {"part-1.width": "1 / 0"},
    {"part-1.width": "-1"},
    {"part-1.width": "0"},
    {"missing.width": "20"},
])
def test_resolution_failure_never_mutates_input(expressions):
    parts = [box(length=60)]
    original = copy.deepcopy(parts)
    with pytest.raises(ValueError):
        resolve_parts(parts, expressions, DEFAULTS)
    assert parts == original


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf"), True, None, "20"])
def test_numeric_values_must_be_finite_numbers(value):
    with pytest.raises(ValueError):
        resolve_parts([box(width=value)], {}, DEFAULTS)


def test_catalog_zero_is_allowed_for_holes_gap_and_rim():
    result = resolve_parts([
        {"part_id": "plate", "template": "plate_with_holes", "params": {"hole_diameter": 0}},
        {"part_id": "case", "template": "case_with_lid", "params": {"gap": 0, "lip_height": 0}},
    ], {}, DEFAULTS)
    assert result["parts"][0]["params"]["hole_diameter"] == 0
    assert result["parts"][1]["params"]["gap"] == 0


@pytest.mark.parametrize("expressions", [
    {"part-1.width": "length / 4", "width": "length / 2"},
    {"width": "length / 2", "part-1.width": "length / 4"},
])
def test_legacy_unqualified_expression_uses_first_part_and_scoped_wins(expressions):
    result = resolve_parts([box(length=80), box("part-2", length=100)], expressions, DEFAULTS)
    assert result["parts"][0]["params"]["width"] == 20
    assert result["parts"][1]["params"]["width"] == 30
    assert result["expressions"] == {"part-1.width": "length / 4"}
    legacy_only = resolve_parts([box(length=80), box("part-2", length=100)], {"width": "length / 2"}, DEFAULTS)
    assert legacy_only["parts"][0]["params"]["width"] == 40
    assert legacy_only["parts"][1]["params"]["width"] == 30
