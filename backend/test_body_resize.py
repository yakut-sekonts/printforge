import copy
import base64
import hashlib
import math
import sys
from pathlib import Path

import pytest
from build123d import Box, Compound, Cylinder, Pos, export_step

import worker

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dev_shim

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


@pytest.mark.parametrize("anchor", [
    [side_x, side_y, side_z]
    for side_x in (-1, 1) for side_y in (-1, 1) for side_z in (-1, 1)
])
def test_resize_exact_box_with_fixed_opposite_corner(anchor):
    original = Pos(100, 50, 30) * Box(60, 40, 20)
    before = original.bounding_box()
    resized = worker._resize_body(original, {"size": [90, 20, 30], "anchor": anchor})
    after = resized.bounding_box()
    assert resized.is_valid
    assert resized.volume == pytest.approx(90 * 20 * 30, abs=0.001)
    for axis, side, expected in zip(("X", "Y", "Z"), anchor, (90, 20, 30)):
        assert getattr(after.size, axis) == pytest.approx(expected, abs=1e-5)
        assert getattr(after.min if side < 0 else after.max, axis) == pytest.approx(
            getattr(before.min if side < 0 else before.max, axis), abs=1e-5)
    assert original.volume == pytest.approx(60 * 40 * 20)


def test_proportional_resize_preserves_analytic_cylinder_and_volume():
    original = Pos(0, 0, 10) * Cylinder(10, 20)
    resized = worker._resize_body(original, {"size": [40, 40, 40], "anchor": [-1, -1, -1]})
    assert resized.is_valid
    assert resized.volume == pytest.approx(original.volume * 8, abs=0.001)
    assert any(face.geom_type.name == "CYLINDER" for face in resized.faces())


def test_nonuniform_resize_keeps_cylinder_watertight():
    original = Cylinder(10, 20)
    resized = worker._resize_body(original, {"size": [40, 20, 10], "anchor": [-1, -1, -1]})
    assert resized.is_valid and len(resized.solids()) == 1
    assert worker.shape_volume(resized) == pytest.approx(original.volume, abs=0.01)


@pytest.mark.parametrize("template", ["box", "cylinder"])
def test_resized_planar_face_can_be_pulled_again(template):
    original = Box(60, 40, 20) if template == "box" else Cylinder(10, 20)
    resized = worker._resize_body(original, {"size": [90, 20, 30], "anchor": [-1, -1, -1]})
    references = [worker.face_offset_reference(face, 0) for face in resized.faces()]
    reference = next(reference for reference in references if reference is not None and reference["normal"][2] > 0.9)
    pulled = worker._apply_face_offset(resized, {"face_ref": reference, "distance": 2})
    assert pulled.is_valid
    assert worker.shape_volume(pulled) - worker.shape_volume(resized) == pytest.approx(reference["area"] * 2, abs=0.01)


def test_resized_box_can_be_filleted():
    resized = worker._resize_body(Box(60, 40, 20), {"size": [90, 20, 30], "anchor": [-1, -1, -1]})
    result = worker._apply_edge_feature(resized, {"op": "fillet", "radius": 1, "edge_ref": worker.list_edges(resized)[0]})
    assert result.is_valid
    assert 0 < worker.shape_volume(result) < worker.shape_volume(resized)


@pytest.mark.parametrize("size", [None, [], [1, 2], [1, 2, 3, 4], [0, 1, 2], [-1, 2, 3],
                                 [math.nan, 2, 3], [math.inf, 2, 3], [True, 2, 3], ["2", 2, 3]])
def test_resize_rejects_invalid_dimensions(size):
    with pytest.raises(worker.GeometryError, match="три конечных размера"):
        worker._resize_body(Box(1, 2, 3), {"size": size, "anchor": [-1, -1, -1]})


@pytest.mark.parametrize("anchor", [None, [], [0, 1, 1], [True, 1, 1], [1, 1], [2, 1, -1]])
def test_resize_rejects_invalid_anchor(anchor):
    with pytest.raises(worker.GeometryError, match="Неподвижный угол"):
        worker._resize_body(Box(1, 2, 3), {"size": [2, 3, 4], "anchor": anchor})


def test_resize_changes_only_target_body_and_replays_in_sequence():
    original = {"one": {"shape": Box(60, 40, 20)}, "two": {"shape": Pos(200, 0, 0) * Box(10, 10, 10)}}
    result = worker.apply_part_operations(original, [
        {"op": "resize_body", "target_id": "one", "size": [90, 20, 30], "anchor": [-1, -1, -1]},
        {"op": "resize_body", "target_id": "one", "size": [45, 40, 30], "anchor": [1, 1, 1]},
    ])
    assert worker.shape_volume(result["one"]["shape"]) == pytest.approx(45 * 40 * 30, abs=0.01)
    assert result["two"]["shape"].volume == pytest.approx(1000)
    with pytest.raises(worker.GeometryError, match="не найдено"):
        worker.apply_part_operations(original, [{"op": "resize_body", "target_id": "missing"}])


def test_resize_keeps_all_solids_in_a_compound_body():
    original = Compound(children=[Pos(-10, 0, 0) * Box(5, 5, 5), Pos(10, 0, 0) * Box(5, 5, 5)])
    resized = worker._resize_body(original, {"size": [50, 5, 5], "anchor": [-1, -1, -1]})
    assert resized.is_valid and len(resized.solids()) == 2
    assert worker.shape_volume(resized) == pytest.approx(500, abs=0.001)
    assert resized.bounding_box().min.X == pytest.approx(-12.5, abs=1e-5)


def test_resize_supports_embedded_step_and_publishes_exact_part_bounds(tmp_path):
    source = tmp_path / "source.step"
    export_step(Box(10, 20, 30), str(source))
    data = source.read_bytes()
    shape, metadata = worker.build_any({"parts": [], "operations": [
        {"op": "step_source", "source_name": source.name, "source_base64": base64.b64encode(data).decode("ascii"), "source_sha256": hashlib.sha256(data).hexdigest()},
        {"op": "resize_body", "target_id": "part-step-1", "size": [20, 30, 40], "anchor": [1, -1, -1]},
    ]})
    assert shape.is_valid
    assert worker.shape_volume(shape) == pytest.approx(24000, abs=0.01)
    bounds = metadata["parts"][0]["bbox"]
    assert [bounds[axis + 3] - bounds[axis] for axis in range(3)] == pytest.approx([20, 30, 40], abs=1e-5)


def test_resize_document_undo_redo_save_and_failed_candidate(monkeypatch, tmp_path):
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    monkeypatch.setattr(dev_shim, "ACTIVE", ["main"])
    try:
        created = dev_shim.cmd_doc_create({"template": "box", "params": {"length": 60, "width": 40, "height": 20}})
        arguments = {"target_id": created["parts"][0]["part_id"], "size": [90, 20, 30], "anchor": [-1, -1, -1]}
        resized = dev_shim.cmd_doc_resize_body(arguments)
        assert resized["error"] is None
        assert resized["stats"]["volume"] == pytest.approx(54000, abs=0.001)
        assert len(resized["operations"]) == 1
        assert dev_shim.cmd_doc_undo({})["stats"]["volume"] == pytest.approx(48000)
        snapshot = copy.deepcopy(dev_shim.doc().__dict__)
        invalid = dev_shim.cmd_doc_resize_body({**arguments, "size": [0, 20, 30]})
        assert invalid["error"] is not None
        for key in ("parts", "operations", "history", "index", "mesh", "stats"):
            assert dev_shim.doc().__dict__[key] == snapshot[key]
        assert dev_shim.cmd_doc_redo({})["stats"]["volume"] == pytest.approx(54000, abs=0.001)
        destination = tmp_path / "resized.printforge"
        dev_shim.cmd_doc_save({"path": str(destination)})
        reopened = dev_shim.cmd_doc_open({"path": str(destination)})
        assert reopened["error"] is None
        assert reopened["stats"]["volume"] == pytest.approx(54000, abs=0.001)
        assert reopened["operations"][0]["size"] == [90, 20, 30]
    finally:
        process = dev_shim._worker
        if process is not None and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        dev_shim._worker = None
