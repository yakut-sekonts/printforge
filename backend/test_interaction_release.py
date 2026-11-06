import copy
import math
import json
import sys
import zipfile
from pathlib import Path

import pytest

import worker
from interaction_geometry import bind_surface, print_placement_checks, sampled_wall_check, surface_reference

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dev_shim


pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def document(operations=None):
    return {"parts": [{"part_id": "one", "name": "Деталь", "template": "box", "params": {"length": 40, "width": 30, "height": 20}}], "operations": operations or []}


def hole(center=None, bindings=None, diameter=4):
    return {"op": "face_feature", "target_id": "one", "mode": "cut", "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1, "anchor": [0, 0]},
            "profile": {"kind": "circle", "diameter": diameter, "center": center or [0, 0]}, "depth": "through",
            **({"dimension_bindings": bindings} if bindings is not None else {})}


def test_local_hole_face_has_operation_provenance():
    result = worker.handle_build(document([hole()]))
    faces = result["mesh"]["face_ranges"]
    assert any(face["feature_index"] == 0 and face["surface_ref"]["kind"] == "cylinder" for face in faces)
    assert all(face["feature_index"] is None for face in faces if face["surface_ref"] and face["surface_ref"]["kind"] == "plane")


def test_local_fillet_faces_and_transformed_holes_keep_provenance():
    shape, _ = worker.build_any(document())
    operation = {"op": "fillet", "part_id": "one", "edge_ref": worker.list_edges(shape)[0], "radius": 2}
    result = worker.handle_build(document([operation]))
    assert any(face["feature_index"] == 0 for face in result["mesh"]["face_ranges"])
    result = worker.handle_build(document([hole(), {"op": "transform", "part_id": "one", "translate": [20, 0, 0]}]))
    assert any(face["feature_index"] == 0 for face in result["mesh"]["face_ranges"])


def test_offset_binding_survives_parametric_resize_and_updates_center():
    operations = [hole(bindings={"u": {"edge": "min", "offset": 8}}), {"op": "resize_parametric", "target_id": "one", "size": [60, 30, 20], "anchor": [-1, -1, -1]}]
    result = worker.handle_build(document(operations))
    face = next(face for face in result["mesh"]["face_ranges"] if face["feature_index"] == 0 and face["surface_ref"]["kind"] == "cylinder")
    assert face["surface_ref"]["origin"][0] == pytest.approx(-12)
    assert face["surface_ref"]["radius"] == pytest.approx(2)
    assert result["stats"]["volume"] == pytest.approx(60 * 30 * 20 - math.pi * 4 * 20)


def test_equal_hole_diameter_follows_source_edit():
    operations = [hole([-8, 0], diameter=6), hole([8, 0], {"equal_diameter": 0})]
    shape, _ = worker.build_any(document(operations))
    cylinders = [face for face in shape.faces() if face.geom_type.name == "CYLINDER"]
    assert len(cylinders) == 2 and all(face.radius == pytest.approx(3) for face in cylinders)
    operations[0]["profile"]["diameter"] = 8
    shape, _ = worker.build_any(document(operations))
    assert all(face.radius == pytest.approx(4) for face in shape.faces() if face.geom_type.name == "CYLINDER")


@pytest.mark.parametrize("bindings", [{"equal_diameter": 1}, {"equal_diameter": True}, {"u": {"edge": "min", "offset": -1}}, {"unknown": 1}])
def test_invalid_bindings_fail_without_mutating_source(bindings):
    source = document([hole(bindings=bindings)])
    before = copy.deepcopy(source)
    with pytest.raises(worker.GeometryError):
        worker.handle_build(source)
    assert source == before


def test_sketch_arc_solver_and_exact_extrusion():
    sketch = {"entities": [{"id": "arc", "type": "arc", "start": [-5, 0], "mid": [0, 5], "end": [5, 0]},
                            {"id": "base", "type": "line", "start": [5, 0], "end": [-5, 0]}],
              "constraints": [], "regions": [{"outer": ["arc", "base"], "holes": []}]}
    solution = worker.handle_solve_sketch({"sketch": sketch})
    assert solution["degrees_of_freedom"] == 10
    result = worker.handle_build({"parts": [], "operations": [{"op": "constrained_sketch_extrude", "sketch": sketch, "depth": 3}]})
    assert result["stats"]["volume"] == pytest.approx(math.pi * 25 / 2 * 3)


def test_sketch_on_face_cuts_exact_brep():
    sketch = {"entities": [{"id": "circle", "type": "circle", "center": [0, 0], "radius": 3}], "constraints": []}
    operation = {"op": "constrained_sketch_extrude", "target_id": "one", "sketch": sketch, "mode": "cut", "depth": 5,
                 "frame": {"origin": [0, 0, 20], "normal": [0, 0, 1], "x_dir": [1, 0, 0]}}
    result = worker.handle_build(document([operation]))
    assert result["stats"]["volume"] == pytest.approx(24000 - math.pi * 9 * 5)


def test_planar_mate_keeps_separate_parts_and_follows_fixed_translation():
    source = document()
    source["parts"].append({"part_id": "two", "name": "Вторая", "template": "box", "params": {"length": 10, "width": 10, "height": 5}})
    from build123d import Box, Align
    moving = Box(10, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))
    fixed = Box(40, 30, 20, align=(Align.CENTER, Align.CENTER, Align.MIN))
    bottom = next(surface_reference(face) for face in moving.faces() if face.normal_at().Z < -0.99)
    top = next(surface_reference(face) for face in fixed.faces() if face.normal_at().Z > 0.99)
    action = {"type": "append", "operation": {"op": "mate", "kind": "plane", "part_id": "two", "fixed_id": "one", "moving_surface": bottom, "fixed_surface": top, "gap": 2}}
    candidate = worker.handle_designer_action({"document": source, "action": action})
    candidate["operations"].append({"op": "transform", "part_id": "one", "translate": [0, 0, 10]})
    result = worker.handle_build(candidate)
    assert result["stats"]["solid_count"] == 2
    parts = result["stats"]["parts"]
    assert next(part for part in parts if part["part_id"] == "two")["bbox"][2] == pytest.approx(32)


def test_print_position_checks_absolute_bounds_not_only_extents():
    profile = {"x": 200, "y": 200, "z": 200}
    assert print_placement_checks([-10, -10, 0, 10, 10, 20], profile)[0]["status"] == "pass"
    assert print_placement_checks([101, 0, 0, 111, 10, 20], profile)[0]["status"] == "fail"
    assert print_placement_checks([-10, -10, -1, 10, 10, 19], profile)[0]["status"] == "fail"


def test_wall_sampling_detects_thin_plate_without_claiming_universal_pass():
    from build123d import Box
    thin = sampled_wall_check(Box(20, 20, 0.5), 0.8)
    assert thin["status"] == "fail" and thin["issues"]
    assert sampled_wall_check(Box(20, 20, 5), 0.8)["status"] == "unknown"


def test_cylindrical_mate_matches_axes_and_preserves_volume():
    from build123d import Cylinder, Align
    source = {"parts": [{"part_id": name, "name": name, "template": "cylinder", "params": {"diameter": diameter, "height": 10}} for name, diameter in (("one", 20), ("two", 6))], "operations": []}
    surfaces = [next(surface_reference(face) for face in Cylinder(diameter / 2, 10, align=(Align.CENTER, Align.CENTER, Align.MIN)).faces() if face.geom_type.name == "CYLINDER") for diameter in (20, 6)]
    candidate = worker.handle_designer_action({"document": source, "action": {"type": "append", "operation": {
        "op": "mate", "kind": "axis", "part_id": "two", "fixed_id": "one", "moving_surface": surfaces[1], "fixed_surface": surfaces[0], "gap": 12}}})
    candidate["operations"].append({"op": "transform", "part_id": "one", "translate": [30, 4, 0]})
    result = worker.handle_build(candidate)
    assert result["stats"]["solid_count"] == 2
    moving = next(part for part in result["stats"]["parts"] if part["part_id"] == "two")
    assert moving["bbox"] == pytest.approx([27, 1, 12, 33, 7, 22])
    assert result["stats"]["volume"] == pytest.approx(math.pi * 109 * 10)


def test_mate_cycles_and_duplicate_bindings_are_rejected():
    from build123d import Box
    shape = Box(10, 10, 10)
    reference = surface_reference(shape.faces()[0])
    binding = bind_surface(shape, reference)
    parts = {name: {"name": name, "shape": shape} for name in ("one", "two")}
    mate = {"op": "mate", "kind": "plane", "part_id": "one", "fixed_id": "two", "moving_surface": binding, "fixed_surface": binding}
    with pytest.raises(worker.GeometryError, match="цикл"):
        worker.apply_part_operations(copy.deepcopy(parts), [mate, {**mate, "part_id": "two", "fixed_id": "one"}])
    with pytest.raises(worker.GeometryError, match="уже есть"):
        worker.apply_part_operations(copy.deepcopy(parts), [mate, mate])


def test_build_and_export_stats_never_leak_ocp_provenance_objects(tmp_path):
    source = document([hole()])
    json.dumps(worker.handle_build(source))
    result = worker.handle_export({**source, "format": "stl", "path": str(tmp_path / "hole.stl")})
    json.dumps(result)
    assert not any(key.startswith("_") for key in result["stats"])


def test_extended_history_preview_undo_redo_and_schema_seven_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    monkeypatch.setattr(dev_shim, "ACTIVE", ["main"])
    try:
        dev_shim.cmd_doc_create({"template": "box", "params": {}})
        part_id = dev_shim.doc().parts[0]["part_id"]
        operation = {**hole(bindings={"u": {"edge": "min", "offset": 10}}), "target_id": part_id}

        def execute(action, preview=False):
            current = dev_shim.doc()
            return dev_shim.cmd_doc_designer_action({"action": action, "expected_revision": current.revision, "expected_instance": current.document_instance_id, "preview": preview})

        before = copy.deepcopy(dev_shim.doc().__dict__)
        execute({"type": "append", "operation": operation}, preview=True)
        assert dev_shim.doc().__dict__ == before
        created = execute({"type": "append", "operation": operation})
        assert not created["error"]
        changed = execute({"type": "edit", "index": 0, "changes": {"profile": {"kind": "circle", "diameter": 6, "center": [0, 0]}}})
        assert changed["stats"]["volume"] < created["stats"]["volume"]
        dev_shim.cmd_doc_undo({})
        confirmed = copy.deepcopy(dev_shim.doc().__dict__)
        failed = execute({"type": "edit", "index": 0, "changes": {"dimension_bindings": {"equal_diameter": 0}}})
        assert failed["error"]
        for key in ("operations", "history", "index", "revision", "stats", "mesh"):
            assert dev_shim.doc().__dict__[key] == confirmed[key]
        assert dev_shim.cmd_doc_redo({})["stats"]["volume"] == pytest.approx(changed["stats"]["volume"])
        path = tmp_path / "bound.printforge"
        dev_shim.cmd_doc_save({"path": str(path)})
        with zipfile.ZipFile(path) as archive:
            assert json.loads(archive.read("document.json"))["schema_version"] == 7
        assert dev_shim.cmd_doc_open({"path": str(path)})["stats"]["volume"] == pytest.approx(changed["stats"]["volume"])
    finally:
        if dev_shim._worker is not None and dev_shim._worker.poll() is None:
            dev_shim._worker.terminate()
            dev_shim._worker.wait(timeout=10)
        dev_shim._worker = None
