"""Документ: сохранение идентичности проекта и новое instance при reopen."""
import math
import sys
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
