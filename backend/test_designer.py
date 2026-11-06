import copy
import math
import sys
from pathlib import Path

import pytest

import worker
from designer_actions import edit_operations

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import dev_shim

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def model(template="box", operations=None):
    return {"parts": [{"part_id": "one", "template": template, "params": {}}], "operations": operations or []}


def preserving(size, anchor=None):
    return {"op": "resize_parametric", "target_id": "one", "size": size, "anchor": anchor or [-1, -1, -1]}


def test_parametric_plate_resize_keeps_four_circular_bores_and_edge_offsets():
    shape, metadata = worker.build_any(model("plate_with_holes", [preserving([100, 50, 6])]))
    assert shape.is_valid
    assert worker.shape_volume(shape) == pytest.approx(100 * 50 * 6 - 4 * math.pi * 2 ** 2 * 6, abs=0.01)
    cylinders = [face for face in shape.faces() if face.geom_type.name == "CYLINDER"]
    assert len(cylinders) == 4
    assert all(face.radius == pytest.approx(2) for face in cylinders)
    assert metadata["parts"][0]["parametric_resize"] is True


def test_parametric_box_resize_replays_fillet_without_scaling_radius():
    original, _ = worker.build_any(model())
    edge = worker.list_edges(original)[0]
    operations = [{"op": "fillet", "part_id": "one", "radius": 2, "edge_ref": edge}, preserving([60, 40, 20])]
    shape, metadata = worker.build_any(model(operations=operations))
    assert shape.is_valid
    radii = [face.radius for face in shape.faces() if face.geom_type.name == "CYLINDER"]
    assert radii and all(radius == pytest.approx(2) for radius in radii)
    assert metadata["parts"][0]["parametric_resize"] is True
    shape_again, _ = worker.build_any(model(operations=operations + [preserving([70, 45, 25], [1, -1, -1])]))
    assert shape_again.is_valid
    assert all(face.radius == pytest.approx(2) for face in shape_again.faces() if face.geom_type.name == "CYLINDER")


def test_parametric_resize_replays_centered_hole_with_constant_diameter():
    operations = [{"op": "face_feature", "target_id": "one", "mode": "cut", "face_ref": {
        "kind": "outer_planar", "axis": "z", "side": 1, "anchor": [0, 0]},
        "profile": {"kind": "circle", "diameter": 4, "center": [0, 0]}, "depth": "through"}, preserving([60, 30, 20])]
    shape, _ = worker.build_any(model(operations=operations))
    assert worker.shape_volume(shape) == pytest.approx(60 * 30 * 20 - math.pi * 2 ** 2 * 20, abs=0.01)


def test_parametric_resize_rejects_mesh_style_stretch_history_and_nonround_cylinder():
    with pytest.raises(worker.GeometryError, match="параметрической истории"):
        worker.build_any(model(operations=[{"op": "resize_body", "target_id": "one", "size": [60, 40, 20], "anchor": [-1, -1, -1]}, preserving([70, 40, 20])]))
    with pytest.raises(worker.GeometryError, match="X и Y"):
        worker.build_any(model("cylinder", [preserving([40, 30, 30])]))


@pytest.mark.parametrize("changes", [{"op": "transform"}, {"target_id": "two"}, {"edge_ref": {}}, {"enabled": "false"}, {}])
def test_history_patch_protects_identity_and_references(changes):
    with pytest.raises(ValueError):
        edit_operations([{"op": "fillet", "radius": 2}], 0, changes)


def test_history_patch_is_immutable_and_validates_index():
    operations = [{"op": "fillet", "radius": 2}]
    assert edit_operations(operations, 0, {"radius": 3})[0]["radius"] == 3
    assert operations[0]["radius"] == 2
    for index in (True, -1, 1, None):
        with pytest.raises(ValueError):
            edit_operations(operations, index, {"radius": 3})


def test_mesh_conversion_is_dense_watertight_and_soft_deformation_keeps_connectivity():
    converted = worker.handle_designer_action({"document": model(), "action": {"type": "convert_mesh"}})
    mesh, before = worker._build_mesh_workflow(converted)
    assert mesh.is_watertight and 12 < len(mesh.faces) <= 200_000
    operation = {"op": "mesh_deform", "center": [20, 0, 10], "delta": [1, 0, 0], "radius": 12}
    deformed = worker._deform_mesh(mesh, operation)
    assert deformed.is_watertight
    assert (deformed.faces == mesh.faces).all()
    assert deformed.vertices[:, 0].max() > mesh.vertices[:, 0].max()
    rebuilt, _ = worker._build_mesh_workflow({**converted, "operations": converted["operations"] + [operation]})
    assert rebuilt.is_watertight and rebuilt.volume == pytest.approx(deformed.volume)


@pytest.mark.parametrize("delta,radius", [([0, 0, 0], 10), ([1, 0, 0], 0), ([math.inf, 0, 0], 10), ([True, 0, 0], 10), ([1, 0, 0], True)])
def test_soft_deform_rejects_invalid_input(delta, radius):
    import trimesh
    with pytest.raises(worker.GeometryError):
        worker._deform_mesh(trimesh.creation.box(), {"center": [0, 0, 0], "delta": delta, "radius": radius})


@pytest.fixture
def document(monkeypatch):
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    monkeypatch.setattr(dev_shim, "ACTIVE", ["main"])
    yield
    process = dev_shim._worker
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    dev_shim._worker = None


def action(value, preview=False, **overrides):
    document = dev_shim.doc()
    return dev_shim.cmd_doc_designer_action({"action": value, "preview": preview,
        "expected_revision": document.revision, "expected_instance": document.document_instance_id, **overrides})


def test_preview_and_history_edit_are_atomic_undoable_and_persistent(document, tmp_path):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    part_id = dev_shim.doc().parts[0]["part_id"]
    arguments = {"type": "append", "operation": {"op": "resize_parametric", "target_id": part_id, "size": [60, 30, 20], "anchor": [-1, -1, -1]}}
    before = copy.deepcopy(dev_shim.doc().__dict__)
    preview = action(arguments, preview=True)
    assert preview["stats"]["volume"] == pytest.approx(36000)
    assert dev_shim.doc().__dict__ == before
    committed = action(arguments)
    assert committed["stats"]["volume"] == pytest.approx(36000)
    edited = action({"type": "edit", "index": 0, "changes": {"size": [70, 30, 20]}})
    assert edited["stats"]["volume"] == pytest.approx(42000)
    assert dev_shim.cmd_doc_undo({})["stats"]["volume"] == pytest.approx(36000)
    snapshot = copy.deepcopy(dev_shim.doc().__dict__)
    failed = action({"type": "edit", "index": 0, "changes": {"size": [0, 30, 20]}})
    assert failed["error"]
    for key in ("operations", "history", "index", "mesh", "stats", "revision"):
        assert dev_shim.doc().__dict__[key] == snapshot[key]
    assert dev_shim.cmd_doc_redo({})["stats"]["volume"] == pytest.approx(42000)
    destination = tmp_path / "designer.printforge"
    dev_shim.cmd_doc_save({"path": str(destination)})
    import json
    import zipfile
    with zipfile.ZipFile(destination) as archive:
        assert json.loads(archive.read("document.json"))["schema_version"] == 6
    reopened = dev_shim.cmd_doc_open({"path": str(destination)})
    assert reopened["stats"]["volume"] == pytest.approx(42000)
    with pytest.raises(RuntimeError, match="document_changed"):
        action(arguments, expected_revision=0)


def test_mesh_conversion_is_undoable_and_cannot_export_step(document, tmp_path):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    converted = action({"type": "convert_mesh"})
    assert converted["stats"]["mesh_mode"] is True
    with pytest.raises(RuntimeError, match="STEP"):
        dev_shim.cmd_doc_export({"format": "step", "path": str(tmp_path / "mesh.step")})
    restored = dev_shim.cmd_doc_undo({})
    assert not restored["stats"].get("mesh_mode")
    assert restored["stats"]["volume"] == pytest.approx(24000)


def test_disabled_history_and_rotation_rebuild_consistently():
    import numpy as np
    source = model(operations=[{"op": "transform", "part_id": "one", "translate": [10, 0, 0], "enabled": False}])
    shape, _ = worker.build_any(source)
    assert shape.bounding_box().min.X == pytest.approx(-20)
    source["operations"] = [{"op": "transform", "part_id": "one", "translate": [10, 0, 0], "rotate_deg": [0, 0, 90], "pivot": [0, 0, 10]}]
    shape, _ = worker.build_any(source)
    assert shape.bounding_box().size.X == pytest.approx(30)
    assert shape.bounding_box().size.Y == pytest.approx(40)
    converted = worker.handle_designer_action({"document": model(), "action": {"type": "convert_mesh"}})
    mesh, _ = worker._build_mesh_workflow(converted)
    transformed, _ = worker._build_mesh_workflow({**converted, "operations": converted["operations"] + [{"op": "mesh_transform", "rotate_deg": [0, 0, 90], "translate": [10, 0, 0], "pivot": [0, 0, 10]}]})
    assert np.allclose(transformed.extents, [30, 40, 20])
    assert np.allclose(transformed.bounds.mean(axis=0), [10, 0, 10])


@pytest.mark.parametrize("template", ["box", "plate_with_holes", "cylinder", "washer", "sphere"])
def test_mesh_conversion_preserves_closed_surface_for_every_supported_primitive(template):
    converted = worker.handle_designer_action({"document": model(template), "action": {"type": "convert_mesh"}})
    mesh, stats = worker._build_mesh_workflow(converted)
    assert mesh.is_watertight and mesh.is_winding_consistent
    assert len(mesh.faces) <= 200_000
    assert stats["is_valid"]


def test_mesh_deform_rejects_triangle_foldover():
    import trimesh
    with pytest.raises(worker.GeometryError) as failure:
        worker._deform_mesh(trimesh.creation.box(), {"center": [0.5, 0, 0], "delta": [-10, 0, 0], "radius": 1.1})
    assert failure.value.code == "deform_foldover"
