"""Документ: сохранение идентичности проекта и новое instance при reopen."""
import json
import math
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dev_shim  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def _stop_worker():
    worker = dev_shim._worker
    if worker is not None and worker.poll() is None:
        worker.terminate()
        worker.wait(timeout=10)
    dev_shim._worker = None


def test_primitive_document_can_add_move_union_and_split(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "box", "params": {}})
        assert created["parts"][0]["name"] == "Параллелепипед"
        assert created["stats"]["bbox"] == pytest.approx([-20, -15, 0, 20, 15, 20])

        added = dev_shim.cmd_doc_add_part({
            "template": "cylinder",
            "params": {"diameter": 10, "height": 20},
        })
        cylinder_id = added["parts"][1]["part_id"]
        moved = dev_shim.cmd_doc_transform({
            "part_id": cylinder_id,
            "translate": [15, 0, 0],
        })
        assert moved["operations"][-1] == {
            "op": "transform", "part_id": cylinder_id, "translate": [15, 0, 0],
        }

        united = dev_shim.cmd_doc_boolean({
            "boolean": "union",
            "target_id": created["parts"][0]["part_id"],
            "tool_id": cylinder_id,
            "keep_tool": False,
        })
        assert united["stats"]["solid_count"] == 1

        split = dev_shim.cmd_doc_split({
            "part_id": created["parts"][0]["part_id"],
            "plane": "YZ",
            "offset": 0,
        })
        assert split["stats"]["solid_count"] == 2
    finally:
        _stop_worker()


@pytest.mark.parametrize("template", ["box", "cylinder", "sphere"])
def test_new_primitive_requires_schema_four_and_reopens(monkeypatch, tmp_path, template):
    _stop_worker()
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": template, "params": {}})
        project = tmp_path / f"{template}.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        with zipfile.ZipFile(project) as archive:
            assert json.loads(archive.read("manifest.json"))["schema_version"] == 4
            assert json.loads(archive.read("document.json"))["schema_version"] == 4
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["error"] is None
        assert reopened["template"] == template
        assert reopened["stats"]["volume"] == pytest.approx(created["stats"]["volume"])
    finally:
        _stop_worker()


def test_face_offset_second_part_is_one_undo_and_survives_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "box", "params": {}})
        added = dev_shim.cmd_doc_add_part({
            "template": "cylinder", "params": {"diameter": 10, "height": 12},
        })
        target_id = added["parts"][1]["part_id"]
        before = json.loads(json.dumps(dev_shim.cmd_doc_transform({
            "part_id": target_id, "translate": [50, 0, 0],
        })))
        mesh = dev_shim.cmd_doc_get_mesh({})
        reference = next(face["face_ref"] for face in mesh["face_ranges"]
                         if face["solid_index"] == 1 and face["face_ref"] is not None
                         and face["face_ref"]["normal"][2] > 0.99)
        assert reference["solid_index"] == 1
        changed = dev_shim.cmd_doc_face_offset({
            "target_id": target_id, "face_ref": reference, "distance": 3,
        })
        assert changed["error"] is None
        assert changed["history_len"] == before["history_len"] + 1
        assert changed["stats"]["volume"] == pytest.approx(
            created["stats"]["volume"] + math.pi * 5 ** 2 * 15)
        assert changed["operations"][-1]["op"] == "face_offset"
        restored = dev_shim.cmd_doc_undo({})
        assert restored["operations"] == before["operations"]
        assert restored["stats"]["volume"] == pytest.approx(before["stats"]["volume"])
        redone = dev_shim.cmd_doc_redo({})
        assert redone["stats"]["volume"] == pytest.approx(changed["stats"]["volume"])

        project = tmp_path / "offset.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        with zipfile.ZipFile(project) as archive:
            assert json.loads(archive.read("manifest.json"))["schema_version"] == 4
            assert json.loads(archive.read("document.json"))["schema_version"] == 4
        reopened = json.loads(json.dumps(dev_shim.cmd_doc_open({"path": str(project)})))
        assert reopened["error"] is None
        assert reopened["operations"] == changed["operations"]
        assert reopened["stats"]["volume"] == pytest.approx(changed["stats"]["volume"])

        failed = dev_shim.cmd_doc_face_offset({
            "target_id": target_id, "face_ref": reference, "distance": 1,
        })
        assert failed["error"]["code"] == "reselect_required"
        assert failed["operations"] == reopened["operations"]
        assert failed["history_len"] == reopened["history_len"]
        assert failed["stats"]["volume"] == pytest.approx(reopened["stats"]["volume"])
    finally:
        _stop_worker()


def _mesh_solid_bbox(mesh, solid_index):
    vertex_indices = {
        mesh["indices"][index]
        for face in mesh["face_ranges"] if face["solid_index"] == solid_index
        for index in range(face["tri_start"] * 3, (face["tri_start"] + face["tri_count"]) * 3)
    }
    points = [mesh["positions"][index * 3:index * 3 + 3] for index in vertex_indices]
    return [min(point[axis] for point in points) for axis in range(3)] + [
        max(point[axis] for point in points) for axis in range(3)]


def test_separate_split_parts_can_move_independently_and_reopen(monkeypatch, tmp_path):
    _stop_worker()
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "box", "params": {}})
        parent_id = created["parts"][0]["part_id"]
        split = json.loads(json.dumps(dev_shim.cmd_doc_split({
            "part_id": parent_id, "plane": "YZ", "offset": 0, "separate": True,
        })))
        assert split["error"] is None
        assert split["stats"]["solid_count"] == len(split["stats"]["parts"]) == 2
        child_id = split["stats"]["parts"][1]["part_id"]
        assert child_id == f"{parent_id}-split-1-part-2"
        before_mesh = dev_shim.cmd_doc_get_mesh({})
        parent_bbox = _mesh_solid_bbox(before_mesh, 0)
        child_bbox = _mesh_solid_bbox(before_mesh, 1)
        moved = json.loads(json.dumps(dev_shim.cmd_doc_transform({
            "part_id": child_id, "translate": [15, 0, 0],
        })))
        after_mesh = dev_shim.cmd_doc_get_mesh({})
        assert _mesh_solid_bbox(after_mesh, 0) == pytest.approx(parent_bbox)
        moved_bbox = list(child_bbox)
        moved_bbox[0] += 15
        moved_bbox[3] += 15
        assert _mesh_solid_bbox(after_mesh, 1) == pytest.approx(moved_bbox)
        assert moved["stats"]["volume"] == pytest.approx(created["stats"]["volume"])
        undone = dev_shim.cmd_doc_undo({})
        assert undone["operations"] == split["operations"]
        assert _mesh_solid_bbox(dev_shim.cmd_doc_get_mesh({}), 1) == pytest.approx(child_bbox)
        redone = dev_shim.cmd_doc_redo({})
        assert redone["operations"] == moved["operations"]

        project = tmp_path / "separated.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        with zipfile.ZipFile(project) as archive:
            assert json.loads(archive.read("manifest.json"))["schema_version"] == 4
            assert json.loads(archive.read("document.json"))["schema_version"] == 4
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["error"] is None
        assert reopened["operations"] == moved["operations"]
        assert reopened["stats"]["volume"] == pytest.approx(created["stats"]["volume"])
        assert _mesh_solid_bbox(dev_shim.cmd_doc_get_mesh({}), 0) == pytest.approx(parent_bbox)
        assert _mesh_solid_bbox(dev_shim.cmd_doc_get_mesh({}), 1) == pytest.approx(moved_bbox)
    finally:
        _stop_worker()


@pytest.mark.parametrize("kind", ["face_offset", "split"])
def test_failed_direct_edit_after_undo_preserves_redo_and_saved_state(monkeypatch, tmp_path, kind):
    _stop_worker()
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "washer", "params": {}})
        part_id = created["parts"][0]["part_id"]
        reference = next(face["face_ref"] for face in dev_shim.cmd_doc_get_mesh({})["face_ranges"]
                         if face["face_ref"] and face["face_ref"]["normal"][2] > 0.99)
        if kind == "face_offset":
            changed = dev_shim.cmd_doc_face_offset({
                "target_id": part_id, "face_ref": reference, "distance": 2,
            })
        else:
            changed = dev_shim.cmd_doc_split({
                "part_id": part_id, "plane": "YZ", "offset": 0, "separate": True,
            })
        assert changed["error"] is None
        expected_volume = changed["stats"]["volume"]
        expected_parts = len(changed["stats"]["parts"])
        dev_shim.cmd_doc_undo({})
        project = tmp_path / f"{kind}-saved.printforge"
        before = json.loads(json.dumps(dev_shim.cmd_doc_save({"path": str(project)})))
        saved_bytes = project.read_bytes()
        with zipfile.ZipFile(project) as archive:
            assert json.loads(archive.read("document.json"))["schema_version"] == 3
        before_mesh = json.loads(json.dumps(dev_shim.doc().mesh))
        assert before["can_redo"] is True
        assert before["dirty"] is False
        if kind == "face_offset":
            failed = dev_shim.cmd_doc_face_offset({
                "target_id": part_id, "face_ref": reference, "distance": -100,
            })
        else:
            failed = dev_shim.cmd_doc_split({
                "part_id": part_id, "plane": "YZ", "offset": 1000, "separate": True,
            })
        assert failed["error"]["code"] == f"{kind}_failed"
        for key in ["revision", "history_len", "history_index", "can_redo", "dirty", "parts", "operations", "stats"]:
            assert failed[key] == before[key]
        assert dev_shim.doc().mesh == before_mesh
        assert project.read_bytes() == saved_bytes
        redone = dev_shim.cmd_doc_redo({})
        assert redone["error"] is None
        assert redone["stats"]["volume"] == pytest.approx(expected_volume)
        assert len(redone["stats"]["parts"]) == expected_parts
    finally:
        _stop_worker()


def test_worker_restarts_once_after_transport_death():
    _stop_worker()
    params = {
        "template": "plate_with_holes",
        "params": {"length": 80, "width": 40, "height": 6,
                   "hole_diameter": 4, "hole_offset": 10},
    }
    try:
        confirmed = dev_shim.worker_call("build", params, revision=1)
        failed_worker = dev_shim._worker
        failed_pid = failed_worker.pid

        class KillBeforeRead:
            def readline(self):
                failed_worker.kill()
                failed_worker.wait(timeout=10)
                return ""

        failed_worker.stdout = KillBeforeRead()
        recovered = dev_shim.worker_call("build", params, revision=1)

        assert dev_shim._worker.pid != failed_pid
        assert recovered["stats"]["volume"] == pytest.approx(
            confirmed["stats"]["volume"], rel=1e-9)
        assert recovered["stats"]["bbox"] == pytest.approx(
            confirmed["stats"]["bbox"], abs=1e-9)
    finally:
        _stop_worker()


def test_save_reopen_preserves_document_id_and_replaces_instance(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"length": 100},
        })
        project = tmp_path / "identity.printforge"
        saved = dev_shim.cmd_doc_save({"path": str(project)})
        assert saved["dirty"] is False

        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["doc_id"] == created["doc_id"]
        assert reopened["document_instance_id"] != created["document_instance_id"]
        assert reopened["params"]["length"] == 100
        assert reopened["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
        assert reopened["dirty"] is False
    finally:
        _stop_worker()


def test_future_project_version_has_explicit_update_error(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    project = tmp_path / "future.printforge"
    with zipfile.ZipFile(project, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("document.json", json.dumps({
            "schema_version": 999,
            "document_id": 1,
            "parts": [],
            "operations": [],
        }))

    with pytest.raises(RuntimeError) as error:
        dev_shim.cmd_doc_open({"path": str(project)})
    assert "unsupported_project_version" in str(error.value)
    assert "Обновите PrintForge" in str(error.value)


def test_operation_only_sketch_is_one_transaction_and_survives_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    sketch = {
        "regions": [{
            "outer": {"kind": "polygon", "points": [[0, 0], [40, 0], [40, 20], [0, 20]]},
            "holes": [{"kind": "circle", "center": [20, 10], "radius": 5}],
        }],
    }
    try:
        changed = dev_shim.cmd_doc_sketch_extrude({
            "profile": sketch,
            "plane": "XY",
            "depth": 5,
            "name": "Тестовый эскиз",
        })
        assert changed["parts"] == []
        assert changed["operations"][-1]["op"] == "sketch_extrude"
        assert changed["history_len"] == 2
        assert changed["stats"]["volume"] == pytest.approx((800 - 25 * math.pi) * 5, abs=1e-6)

        project = tmp_path / "operation-only.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["parts"] == []
        assert reopened["operations"] == changed["operations"]
        assert reopened["stats"]["volume"] == pytest.approx(changed["stats"]["volume"], abs=1e-6)

        restored = dev_shim.cmd_doc_undo({})
        assert restored["operations"] == []
        assert restored["stats"] is None
    finally:
        _stop_worker()


def test_shell_draft_and_rib_are_independent_transactions(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        shell = dev_shim.cmd_doc_shell({
            "outer_radius": 10, "height": 20, "wall": 2, "bottom": 3,
        })
        drafted = dev_shim.cmd_doc_draft_prism({
            "width": 20, "depth": 12, "height": 10, "angle": 5,
        })
        ribbed = dev_shim.cmd_doc_rib({
            "base_length": 40, "base_width": 20, "base_thickness": 4,
            "rib_length": 15, "rib_height": 12, "rib_width": 3, "overlap": 1,
        })

        assert [operation["op"] for operation in ribbed["operations"]] == [
            "shell", "draft_prism", "rib"]
        assert shell["history_len"] == 2
        assert drafted["history_len"] == 3
        assert ribbed["history_len"] == 4
        assert ribbed["stats"]["solid_count"] == 3

        without_rib = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in without_rib["operations"]] == [
            "shell", "draft_prism"]
        restored = dev_shim.cmd_doc_redo({})
        assert restored["stats"]["volume"] == pytest.approx(
            ribbed["stats"]["volume"], abs=1e-6)

        project = tmp_path / "shell-draft-rib.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"] == ribbed["operations"]
        assert reopened["stats"]["volume"] == pytest.approx(
            ribbed["stats"]["volume"], abs=1e-6)
    finally:
        _stop_worker()


def test_fit_pocket_clearance_semantics_survive_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        changed = dev_shim.cmd_doc_fit_pocket({
            "fixture_id": "bearing_608", "fixture_version": "1",
            "body_length": 32, "body_width": 32, "body_height": 12,
            "clearance": 0.4, "clearance_mode": "radial",
        })
        assert changed["operations"][-1]["clearance_mode"] == "radial"
        assert changed["stats"]["parts"][0]["metadata"]["effective_size"] == pytest.approx(22.8)

        undone = dev_shim.cmd_doc_undo({})
        assert undone["operations"] == []
        restored = dev_shim.cmd_doc_redo({})
        assert restored["stats"]["volume"] == pytest.approx(
            changed["stats"]["volume"], abs=1e-6)

        project = tmp_path / "fit-pocket.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"] == changed["operations"]
        assert reopened["stats"]["parts"][0]["metadata"]["fixture_id"] == "bearing_608"
    finally:
        _stop_worker()


def test_vector_source_and_text_font_identity_survive_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    svg_path = tmp_path / "profile.svg"
    svg_path.write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" '
        'viewBox="0 0 200 100"><rect width="200" height="100"/></svg>')
    try:
        vector = dev_shim.cmd_doc_vector_extrude({
            "path": str(svg_path), "format": "svg", "height": 5,
        })
        text = dev_shim.cmd_doc_text_relief({
            "text": "О", "font_size": 10, "relief_height": 1,
            "body_length": 30, "body_width": 20, "body_height": 4, "mode": "add",
        })
        assert vector["history_len"] == 2
        assert text["history_len"] == 3
        assert text["operations"][0]["source_text"].startswith("<svg")
        assert text["stats"]["parts"][1]["metadata"]["font"] == "JetBrains Mono 2.211"

        project = tmp_path / "portable-vector-text.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        svg_path.unlink()
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"] == text["operations"]
        assert reopened["stats"]["volume"] == pytest.approx(text["stats"]["volume"], abs=1e-6)
    finally:
        _stop_worker()


def test_real_thread_pair_is_one_transaction_and_survives_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        changed = dev_shim.cmd_doc_thread_pair({
            "profile_version": "metric-60-v1",
            "major_diameter": 10, "pitch": 1.5, "length": 12,
            "hand": "right", "starts": 1, "clearance": 0.3,
            "nut_height": 5, "nut_across_flats": 18,
        })
        assert changed["history_len"] == 2
        assert changed["stats"]["solid_count"] == 2
        assert changed["stats"]["parts"][0]["metadata"]["assembly_intersection_volume"] == 0

        undone = dev_shim.cmd_doc_undo({})
        assert undone["operations"] == []
        restored = dev_shim.cmd_doc_redo({})
        assert restored["stats"]["volume"] == pytest.approx(
            changed["stats"]["volume"], abs=1e-6)

        project = tmp_path / "thread-pair.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"] == changed["operations"]
        assert reopened["stats"]["solid_count"] == 2
    finally:
        _stop_worker()


def test_clearance_calibration_series_is_one_transaction(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        changed = dev_shim.cmd_doc_clearance_calibration({
            "values": [0.1, 0.2, 0.35], "nominal_diameter": 8,
            "coupon_length": 24, "coupon_width": 18, "thickness": 3,
            "spacing": 28, "font_size": 3, "label_height": 0.6,
            "profile_name": "PLA test v1",
        })
        assert changed["history_len"] == 2
        assert changed["stats"]["solid_count"] == 3
        assert [part["metadata"]["label"] for part in changed["stats"]["parts"]] == [
            "0.10", "0.20", "0.35"]

        project = tmp_path / "clearance-calibration.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"] == changed["operations"]
        assert reopened["stats"]["solid_count"] == 3
        assert dev_shim.cmd_doc_undo({})["operations"] == []
    finally:
        _stop_worker()


def test_split_connector_pair_is_one_transaction_and_survives_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        changed = dev_shim.cmd_doc_split_connector_pair({
            "length": 40, "width": 24, "height": 10,
            "pin_radius": 2, "pin_length": 6,
            "radial_clearance": 0.25, "print_separation": 5,
        })
        assert changed["history_len"] == 2
        assert changed["stats"]["solid_count"] == 2
        assert changed["stats"]["parts"][1]["metadata"]["assembly_translation"] == [0, -29, 0]

        project = tmp_path / "split-connector.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"] == changed["operations"]
        assert reopened["stats"]["volume"] == pytest.approx(
            changed["stats"]["volume"], abs=1e-6)
        assert dev_shim.cmd_doc_undo({})["operations"] == []
    finally:
        _stop_worker()


def test_face_feature_is_one_document_transaction(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        history_before = created["history_len"]
        changed = dev_shim.cmd_doc_face_feature({
            "target_id": created["parts"][0]["part_id"],
            "mode": "cut",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "circle", "diameter": 8, "center": [0, 0]},
            "depth": "through",
        })
        assert changed["error"] is None
        assert changed["history_len"] == history_before + 1
        assert changed["stats"]["volume"] < created["stats"]["volume"]
        assert changed["operations"][-1]["op"] == "face_feature"

        restored = dev_shim.cmd_doc_undo({})
        assert restored["operations"] == []
        assert restored["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_face_dome_is_one_document_transaction(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        changed = dev_shim.cmd_doc_face_dome({
            "target_id": created["parts"][0]["part_id"],
            "mode": "add",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "center": [0, 0],
            "diameter": 20,
            "height": 4,
        })
        assert changed["error"] is None
        assert changed["history_len"] == created["history_len"] + 1
        assert changed["stats"]["volume"] > created["stats"]["volume"]
        assert changed["operations"][-1]["op"] == "face_dome"

        restored = dev_shim.cmd_doc_undo({})
        assert restored["operations"] == []
        assert restored["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_sheet_bend_is_one_document_transaction(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {}})
        changed = dev_shim.cmd_doc_sheet_bend({
            "target_id": created["parts"][0]["part_id"],
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3149.73},
            "bend_axis": "x",
            "position": 0,
            "angle": 90,
            "inside_radius": 5,
            "moving_side": 1,
            "direction": 1,
        })
        assert changed["error"] is None
        assert changed["history_len"] == created["history_len"] + 1
        assert changed["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
        assert changed["stats"]["bbox"][5] > created["stats"]["bbox"][5]
        assert changed["operations"][-1]["op"] == "sheet_bend"

        restored = dev_shim.cmd_doc_undo({})
        assert restored["operations"] == []
        assert restored["stats"]["bbox"] == pytest.approx(created["stats"]["bbox"], abs=1e-6)
    finally:
        _stop_worker()


def test_parallel_sheet_bends_are_independent_document_transactions(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {}})
        target_id = created["parts"][0]["part_id"]
        common = {
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3149.73},
            "bend_axis": "x",
            "angle": 90,
            "inside_radius": 3,
            "direction": 1,
        }
        first = dev_shim.cmd_doc_sheet_bend({
            **common,
            "position": 20,
            "moving_side": 1,
        })
        second = dev_shim.cmd_doc_sheet_bend({
            **common,
            "position": -20,
            "moving_side": -1,
        })
        assert second["error"] is None
        assert second["history_len"] == first["history_len"] + 1
        assert [operation["op"] for operation in second["operations"]] == [
            "sheet_bend", "sheet_bend"]
        assert second["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
        assert second["stats"]["bbox"] == pytest.approx(
            [-24.287611, -20, 0, 24.287611, 20, 24.287611], abs=1e-3)

        undo_second = dev_shim.cmd_doc_undo({})
        assert len(undo_second["operations"]) == 1
        assert undo_second["stats"]["bbox"] == pytest.approx(first["stats"]["bbox"], abs=1e-6)
        undo_first = dev_shim.cmd_doc_undo({})
        assert undo_first["operations"] == []
        assert undo_first["stats"]["bbox"] == pytest.approx(created["stats"]["bbox"], abs=1e-6)
    finally:
        _stop_worker()


def test_perpendicular_flange_bend_is_independent_document_transaction(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {}})
        target_id = created["parts"][0]["part_id"]
        first = dev_shim.cmd_doc_sheet_bend({
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3149.73},
            "bend_axis": "x",
            "position": 0,
            "angle": 90,
            "inside_radius": 3,
            "moving_side": 1,
            "direction": 1,
        })
        second = dev_shim.cmd_doc_sheet_bend({
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "x", "side": 1,
                         "anchor": [0, 0], "selected_area": 1000},
            "bend_axis": "y",
            "position": 0,
            "angle": 90,
            "inside_radius": 2,
            "moving_side": 1,
            "direction": 1,
        })
        assert second["error"] is None
        assert second["history_len"] == first["history_len"] + 1
        assert len(second["operations"]) == 2
        assert second["stats"]["solid_count"] == 1
        assert second["stats"]["volume"] == pytest.approx(
            created["stats"]["volume"], abs=3e-2)

        undo_flange = dev_shim.cmd_doc_undo({})
        assert len(undo_flange["operations"]) == 1
        assert undo_flange["stats"]["bbox"] == pytest.approx(first["stats"]["bbox"], abs=1e-6)
        undo_base = dev_shim.cmd_doc_undo({})
        assert undo_base["operations"] == []
        assert undo_base["stats"]["bbox"] == pytest.approx(created["stats"]["bbox"], abs=1e-6)
    finally:
        _stop_worker()


def test_four_line_sheet_bend_cascade_keeps_each_undo_step(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        target_id = created["parts"][0]["part_id"]
        common = {
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "bend_axis": "x",
            "angle": 45,
            "inside_radius": 1,
            "moving_side": 1,
        }
        states = []
        for position, direction in zip([-30, -10, 10, 30], [1, -1, 1, -1]):
            states.append(dev_shim.cmd_doc_sheet_bend({
                **common,
                "position": position,
                "direction": direction,
            }))

        final = states[-1]
        assert final["error"] is None
        assert [operation["op"] for operation in final["operations"]] == [
            "sheet_bend", "sheet_bend", "sheet_bend", "sheet_bend"]
        assert final["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)

        for expected_count in [3, 2, 1]:
            restored = dev_shim.cmd_doc_undo({})
            assert len(restored["operations"]) == expected_count
            assert restored["stats"]["volume"] == pytest.approx(
                created["stats"]["volume"], rel=1e-6)
        restored = dev_shim.cmd_doc_undo({})
        assert restored["operations"] == []
        assert restored["stats"]["bbox"] == pytest.approx(created["stats"]["bbox"], abs=1e-6)
    finally:
        _stop_worker()


def test_flat_through_cut_survives_sequential_sheet_bends_and_undo(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        target_id = created["parts"][0]["part_id"]
        cut = dev_shim.cmd_doc_face_feature({
            "target_id": target_id,
            "mode": "cut",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "circle", "diameter": 8, "center": [30, 0]},
            "depth": "through",
        })
        common = {
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200 - math.pi * 4**2},
            "bend_axis": "x",
            "angle": 90,
            "inside_radius": 3,
            "direction": 1,
        }
        first = dev_shim.cmd_doc_sheet_bend({
            **common,
            "position": 20,
            "moving_side": 1,
        })
        second = dev_shim.cmd_doc_sheet_bend({
            **common,
            "position": -20,
            "moving_side": -1,
        })

        assert second["error"] is None
        assert [operation["op"] for operation in second["operations"]] == [
            "face_feature", "sheet_bend", "sheet_bend"]
        assert second["stats"]["volume"] == pytest.approx(cut["stats"]["volume"], rel=1e-6)

        undo_second = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_second["operations"]] == [
            "face_feature", "sheet_bend"]
        assert undo_second["stats"]["volume"] == pytest.approx(cut["stats"]["volume"], rel=1e-6)
        undo_first = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_first["operations"]] == ["face_feature"]
        assert undo_first["stats"]["bbox"] == pytest.approx(cut["stats"]["bbox"], abs=1e-6)
        undo_cut = dev_shim.cmd_doc_undo({})
        assert undo_cut["operations"] == []
        assert undo_cut["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_rectangular_through_cut_crosses_bend_zone_as_document_replay(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        target_id = created["parts"][0]["part_id"]
        cut = dev_shim.cmd_doc_face_feature({
            "target_id": target_id,
            "mode": "cut",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "rectangle", "width": 12, "height": 8,
                        "center": [0, 0]},
            "depth": "through",
        })
        bent = dev_shim.cmd_doc_sheet_bend({
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200 - 12 * 8},
            "bend_axis": "x",
            "position": 0,
            "angle": 90,
            "inside_radius": 3,
            "moving_side": 1,
            "direction": 1,
        })

        assert bent["error"] is None
        assert [operation["op"] for operation in bent["operations"]] == [
            "face_feature", "sheet_bend"]
        assert bent["stats"]["volume"] == pytest.approx(cut["stats"]["volume"], rel=1e-6)
        assert bent["stats"]["bbox"][5] > cut["stats"]["bbox"][5]

        undo_bend = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_bend["operations"]] == ["face_feature"]
        assert undo_bend["stats"]["bbox"] == pytest.approx(cut["stats"]["bbox"], abs=1e-6)
        undo_cut = dev_shim.cmd_doc_undo({})
        assert undo_cut["operations"] == []
        assert undo_cut["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_circular_through_cut_crosses_bend_zone_and_undoes(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        target_id = created["parts"][0]["part_id"]
        cut_area = math.pi * 4**2
        cut = dev_shim.cmd_doc_face_feature({
            "target_id": target_id,
            "mode": "cut",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "circle", "diameter": 8, "center": [0, 0]},
            "depth": "through",
        })
        bent = dev_shim.cmd_doc_sheet_bend({
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200 - cut_area},
            "bend_axis": "x",
            "position": 0,
            "angle": 90,
            "inside_radius": 3,
            "moving_side": 1,
            "direction": 1,
        })

        assert bent["error"] is None
        assert [operation["op"] for operation in bent["operations"]] == [
            "face_feature", "sheet_bend"]
        assert bent["stats"]["volume"] == pytest.approx(cut["stats"]["volume"], rel=1e-6)
        assert bent["stats"]["solid_count"] == 1
        assert bent["stats"]["is_valid"] is True

        undo_bend = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_bend["operations"]] == [
            "face_feature"]
        assert undo_bend["stats"]["bbox"] == pytest.approx(
            cut["stats"]["bbox"], abs=1e-6)
        undo_cut = dev_shim.cmd_doc_undo({})
        assert undo_cut["operations"] == []
        assert undo_cut["stats"]["volume"] == pytest.approx(
            created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_slot_through_cut_crosses_bend_zone_and_undoes(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        target_id = created["parts"][0]["part_id"]
        cut_area = (12 - 4) * 4 + math.pi * 2**2
        cut = dev_shim.cmd_doc_face_feature({
            "target_id": target_id,
            "mode": "cut",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "slot", "width": 4, "length": 12,
                        "center": [0, 0]},
            "depth": "through",
        })
        bent = dev_shim.cmd_doc_sheet_bend({
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200 - cut_area},
            "bend_axis": "x",
            "position": 0,
            "angle": 90,
            "inside_radius": 3,
            "moving_side": 1,
            "direction": 1,
        })

        assert bent["error"] is None
        assert [operation["op"] for operation in bent["operations"]] == [
            "face_feature", "sheet_bend"]
        assert bent["stats"]["volume"] == pytest.approx(cut["stats"]["volume"], rel=1e-6)
        assert bent["stats"]["solid_count"] == 1
        assert bent["stats"]["is_valid"] is True

        undo_bend = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_bend["operations"]] == [
            "face_feature"]
        assert undo_bend["stats"]["bbox"] == pytest.approx(
            cut["stats"]["bbox"], abs=1e-6)
        undo_cut = dev_shim.cmd_doc_undo({})
        assert undo_cut["operations"] == []
        assert undo_cut["stats"]["volume"] == pytest.approx(
            created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_ring_through_cut_crosses_bend_zone_and_undoes(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"hole_diameter": 0},
        })
        target_id = created["parts"][0]["part_id"]
        cut_area = math.pi * (5**2 - 3**2)
        cut = dev_shim.cmd_doc_face_feature({
            "target_id": target_id,
            "mode": "cut",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "ring", "outer_diameter": 10,
                        "inner_diameter": 6, "center": [0, 0]},
            "depth": "through",
        })
        bent = dev_shim.cmd_doc_sheet_bend({
            "target_id": target_id,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200 - cut_area},
            "bend_axis": "x",
            "position": 0,
            "angle": 90,
            "inside_radius": 3,
            "moving_side": 1,
            "direction": 1,
        })

        assert bent["error"] is None
        assert [operation["op"] for operation in bent["operations"]] == [
            "face_feature", "sheet_bend"]
        assert bent["stats"]["volume"] == pytest.approx(cut["stats"]["volume"], rel=1e-6)
        assert bent["stats"]["solid_count"] == 2
        assert bent["stats"]["is_valid"] is True

        undo_bend = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_bend["operations"]] == [
            "face_feature"]
        assert undo_bend["stats"]["bbox"] == pytest.approx(
            cut["stats"]["bbox"], abs=1e-6)
        undo_cut = dev_shim.cmd_doc_undo({})
        assert undo_cut["operations"] == []
        assert undo_cut["stats"]["volume"] == pytest.approx(
            created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_edge_features_are_independent_document_transactions(monkeypatch):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({"template": "bracket_l", "params": {}})
        first_edge = next(edge for edge in created["stats"]["edges"]
                          if edge["kind"] == "LINE" and edge["length"] > 29)
        chamfered = dev_shim.cmd_doc_chamfer({
            "edge_ref": first_edge,
            "distance": 1,
            "part_id": created["parts"][0]["part_id"],
        })
        assert chamfered["error"] is None
        assert chamfered["history_len"] == created["history_len"] + 1
        assert [operation["op"] for operation in chamfered["operations"]] == ["chamfer"]

        second_edge = next(edge for edge in chamfered["stats"]["edges"]
                           if edge["kind"] == "LINE" and edge["length"] > 10)
        filleted = dev_shim.cmd_doc_fillet({
            "edge_ref": second_edge,
            "radius": 0.5,
            "part_id": created["parts"][0]["part_id"],
        })
        assert filleted["error"] is None
        assert filleted["history_len"] == chamfered["history_len"] + 1
        assert [operation["op"] for operation in filleted["operations"]] == ["chamfer", "fillet"]

        undo_fillet = dev_shim.cmd_doc_undo({})
        assert [operation["op"] for operation in undo_fillet["operations"]] == ["chamfer"]
        undo_chamfer = dev_shim.cmd_doc_undo({})
        assert undo_chamfer["operations"] == []
        assert undo_chamfer["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
    finally:
        _stop_worker()


def test_constrained_sketch_preview_apply_undo_and_reopen(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    order = ["bottom", "right", "top", "left"]
    sketch = {
        "entities": [
            {"id": "bottom", "type": "line", "start": [0.1, -0.2], "end": [39.8, 0.3]},
            {"id": "right", "type": "line", "start": [40.2, 0.1], "end": [39.7, 19.8]},
            {"id": "top", "type": "line", "start": [40.1, 20.2], "end": [-0.2, 19.7]},
            {"id": "left", "type": "line", "start": [0.2, 20.1], "end": [-0.1, 0.2]},
        ],
        "constraints": [
            *[
                {"type": "coincident", "a": [entity_id, "end"],
                 "b": [order[(index + 1) % 4], "start"]}
                for index, entity_id in enumerate(order)
            ],
            {"type": "horizontal", "entity": "bottom"},
            {"type": "horizontal", "entity": "top"},
            {"type": "vertical", "entity": "right"},
            {"type": "vertical", "entity": "left"},
            {"type": "dimension", "kind": "distance_x", "a": ["bottom", "start"],
             "b": ["bottom", "end"], "value": 40},
            {"type": "dimension", "kind": "distance_y", "a": ["right", "start"],
             "b": ["right", "end"], "value": 20},
            {"type": "fix", "point": ["bottom", "start"], "value": [0, 0]},
        ],
        "regions": [{"outer": order, "holes": []}],
    }
    try:
        before = dev_shim.cmd_doc_get_state({})
        preview = dev_shim.cmd_sketch_solve({"sketch": sketch})
        after_preview = dev_shim.cmd_doc_get_state({})
        assert preview["degrees_of_freedom"] == 0
        assert after_preview["history_len"] == before["history_len"]
        assert after_preview["operations"] == []

        applied = dev_shim.cmd_doc_constrained_sketch_extrude({
            "sketch": sketch, "plane": "XY", "depth": 5,
        })
        assert applied["error"] is None
        assert applied["history_len"] == before["history_len"] + 1
        assert applied["stats"]["volume"] == pytest.approx(4000, abs=1e-5)

        undone = dev_shim.cmd_doc_undo({})
        assert undone["operations"] == []
        redone = dev_shim.cmd_doc_redo({})
        assert redone["stats"]["volume"] == pytest.approx(4000, abs=1e-5)

        project = tmp_path / "constrained-sketch.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["operations"][0]["op"] == "constrained_sketch_extrude"
        assert reopened["stats"]["parts"][0]["metadata"]["degrees_of_freedom"] == 0
    finally:
        _stop_worker()


def test_mesh_source_repair_undo_save_reopen_and_export_policy(monkeypatch, tmp_path):
    import numpy as np
    import trimesh

    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    source = trimesh.creation.box(extents=[10, 10, 10])
    removed = np.where(source.face_normals[:, 2] > 0.9)[0]
    source.update_faces(~np.isin(np.arange(len(source.faces)), removed))
    source.remove_unreferenced_vertices()
    source_path = tmp_path / "mesh with hole.stl"
    source.export(source_path)
    try:
        applied = dev_shim.cmd_doc_mesh_import_apply({
            "path": str(source_path), "format": "stl", "unit_scale": 1,
        })
        assert applied["operations"][0]["op"] == "mesh_source"
        assert applied["stats"]["mesh_mode"] is True
        assert applied["stats"]["mesh_diagnostics"]["boundary_edges"] == 4

        repaired = dev_shim.cmd_doc_mesh_repair({"action": "fill_holes"})
        assert repaired["error"] is None
        assert repaired["stats"]["is_valid"] is True
        assert repaired["stats"]["volume"] == pytest.approx(1000, abs=1e-5)
        assert repaired["history_len"] == applied["history_len"] + 1

        undone = dev_shim.cmd_doc_undo({})
        assert undone["stats"]["mesh_diagnostics"]["boundary_edges"] == 4
        redone = dev_shim.cmd_doc_redo({})
        assert redone["stats"]["mesh_diagnostics"]["boundary_edges"] == 0

        project = tmp_path / "persistent-mesh.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        source_path.unlink()
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["stats"]["is_valid"] is True
        assert reopened["stats"]["volume"] == pytest.approx(1000, abs=1e-5)

        exported = tmp_path / "repaired.stl"
        result = dev_shim.cmd_doc_export({"path": str(exported), "format": "stl"})
        assert result["bytes"] > 0
        assert trimesh.load(exported).is_watertight is True
        exported_3mf = tmp_path / "repaired.3mf"
        result_3mf = dev_shim.cmd_doc_export({"path": str(exported_3mf), "format": "3mf"})
        assert result_3mf["bytes"] > 0
        with zipfile.ZipFile(exported_3mf) as archive:
            assert {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model"} <= set(archive.namelist())
            model_xml = archive.read("3D/3dmodel.model")
            assert model_xml.count(b"<triangle ") == 12
        with pytest.raises(RuntimeError) as step_error:
            dev_shim.cmd_doc_export({"path": str(tmp_path / "fake.step"), "format": "step"})
        assert "mesh_step_unsupported" in str(step_error.value)
    finally:
        _stop_worker()


def test_image_relief_preview_apply_hash_guard_and_reopen(monkeypatch, tmp_path):
    import numpy as np
    from PIL import Image

    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    image_path = tmp_path / "gradient image.png"
    pixels = np.tile(np.linspace(0, 255, 32, dtype=np.uint8), (16, 1))
    Image.fromarray(pixels, mode="L").save(image_path)
    settings = {
        "path": str(image_path), "model": "heightmap-luminance-v1", "seed": 7,
        "width_mm": 40, "relief_height": 4, "base_thickness": 2,
        "samples": 24, "noise_strength": 0.01, "invert": False,
    }
    try:
        before = dev_shim.cmd_doc_get_state({})
        preview = dev_shim.cmd_image_relief_preview(settings)
        after_preview = dev_shim.cmd_doc_get_state({})
        assert preview["stats"]["is_valid"] is True
        assert preview["stats"]["mesh_mode"] is True
        assert after_preview["history_len"] == before["history_len"]
        assert after_preview["operations"] == []

        changed_pixels = np.flip(pixels, axis=1)
        Image.fromarray(changed_pixels, mode="L").save(image_path)
        with pytest.raises(RuntimeError) as changed:
            dev_shim.cmd_doc_image_relief_apply({
                **settings, "expected_sha256": preview["source_sha256"],
            })
        assert "image_changed" in str(changed.value)
        assert dev_shim.cmd_doc_get_state({})["operations"] == []

        Image.fromarray(pixels, mode="L").save(image_path)
        applied = dev_shim.cmd_doc_image_relief_apply({
            **settings, "expected_sha256": preview["source_sha256"],
        })
        assert applied["error"] is None
        assert applied["history_len"] == before["history_len"] + 1
        assert applied["operations"][0]["model"] == "heightmap-luminance-v1"
        assert applied["operations"][0]["seed"] == 7

        project = tmp_path / "image-relief.printforge"
        dev_shim.cmd_doc_save({"path": str(project)})
        image_path.unlink()
        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        metadata = reopened["stats"]["mesh_history"][0]
        assert metadata["seed"] == 7
        assert metadata["settings"]["width_mm"] == 40
        assert metadata["quality"]["engineering_accuracy"] is False

        exported = tmp_path / "image-relief.stl"
        export = dev_shim.cmd_doc_export({"path": str(exported), "format": "stl"})
        assert export["bytes"] > 0
    finally:
        _stop_worker()
