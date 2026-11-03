"""M2: приёмочные проверки AC-01…AC-05 на уровне worker (аналитические допуски)."""
import json
import math
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]

BACKEND = Path(__file__).resolve().parent
FIXTURES = BACKEND.parent / "tests" / "fixtures" / "f05"
WORKER = BACKEND / "worker.py"
PYTHON = BACKEND / ".venv" / "bin" / "python"

TOL_V = lambda v: max(1e-3, 1e-6 * v)


class Worker:
    def __init__(self):
        self.proc = subprocess.Popen(
            [str(PYTHON), str(WORKER)], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._n = 0

    def call(self, method, params=None, timeout=60):
        self._n += 1
        rid = f"t{self._n}"
        self.proc.stdin.write(json.dumps({
            "request_id": rid, "schema_version": 1, "document_id": "t",
            "revision": self._n, "method": method, "params": params or {}}) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("worker завершился")
            resp = json.loads(line)
            if resp.get("request_id") == rid:
                return resp
        raise TimeoutError(method)

    def stop(self):
        if self.proc.poll() is None:
            self.call("shutdown", timeout=5)
        self.proc.wait(timeout=10)


@pytest.fixture(scope="module")
def worker():
    w = Worker()
    yield w
    w.stop()


def build(w, template, params=None, operations=None):
    resp = w.call("build", {"template": template, "params": params or {},
                            "operations": operations or []})
    assert resp["ok"], resp.get("error")
    return resp["result"]


# --- AC-01 (регрессия через новый API) ---

def test_ac01_plate(worker):
    r = build(worker, "plate_with_holes")
    st = r["stats"]
    exp = 80 * 40 * 6 - 4 * math.pi * 4 * 6
    assert abs(st["volume"] - exp) <= TOL_V(exp)
    r2 = build(worker, "plate_with_holes", {"length": 100})
    exp2 = 100 * 40 * 6 - 4 * math.pi * 4 * 6
    assert abs(r2["stats"]["volume"] - exp2) <= TOL_V(exp2)
    for cx, cy in r2["stats"]["hole_centers"]:
        assert (abs(cx), abs(cy)) == (40.0, 10.0)


# --- AC-02. Шайба ---

def test_ac02_washer(worker):
    r = build(worker, "washer")
    st = r["stats"]
    exp = math.pi * (100 - 9) * 4
    assert st["solid_count"] == 1
    assert abs(st["volume"] - exp) <= TOL_V(exp)
    # увеличение наружного диаметра не меняет внутренний
    r2 = build(worker, "washer", {"outer_diameter": 24})
    exp2 = math.pi * (144 - 9) * 4
    assert abs(r2["stats"]["volume"] - exp2) <= TOL_V(exp2)


# --- AC-03. Корпус и крышка ---

def test_ac03_case_with_lid(worker):
    r = build(worker, "case_with_lid")
    st = r["stats"]
    assert st["solid_count"] == 2
    assert abs(st["case_volume"] - 29472) <= 1
    assert abs(st["lid_volume"] - 14355.2) <= 1
    assert abs(st["intersection_volume"]) <= 1e-6
    bb = st["bbox"]
    assert bb[2] == pytest.approx(0, abs=1e-3)
    assert bb[5] == pytest.approx(32, abs=1e-3)
    # изменение длины: зазор остаётся 0,2 на сторону
    r2 = build(worker, "case_with_lid", {"length": 120})
    st2 = r2["stats"]
    # полость 116 × 56; бортик 115,6 × 55,6 → зазор 0,2
    case_vol = 120 * 60 * 30 - 116 * 56 * 28
    assert abs(st2["case_volume"] - case_vol) <= 1
    assert abs(st2["intersection_volume"]) <= 1e-6


# --- AC-04. Кронштейн и ошибочное скругление ---

def test_ac04_bracket_and_fillet(worker):
    r = build(worker, "bracket_l")
    st = r["stats"]
    assert st["solid_count"] == 1
    assert abs(st["volume"] - 11000) <= TOL_V(11000)
    # выбираем длинное вертикальное ребро (у стойки B): LINE длиной 30
    edges = [e for e in st["edges"] if e["kind"] == "LINE" and e["length"] > 29]
    assert edges
    ref = edges[0]
    # допустимое скругление R2
    r2 = build(worker, "bracket_l", operations=[{
        "op": "fillet", "radius": 2.0, "edge_ref": ref}])
    assert r2["stats"]["is_valid"]
    assert r2["stats"]["volume"] < 11000
    # заведомо чрезмерный радиус — понятная ошибка, без подмены значения
    resp = worker.call("build", {"template": "bracket_l", "params": {},
                                 "operations": [{"op": "fillet", "radius": 50.0,
                                                 "edge_ref": ref}]})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "fillet_failed"
    assert "50" in resp["error"]["message"]
    # ссылка живёт после изменения размера (кронштейн длиннее)
    r3 = build(worker, "bracket_l", {"a_length": 50}, operations=[{
        "op": "fillet", "radius": 2.0, "edge_ref": ref}])
    assert r3["stats"]["is_valid"]


def test_bracket_chamfer_and_excessive_distance(worker):
    base = build(worker, "bracket_l")
    edges = [edge for edge in base["stats"]["edges"]
             if edge["kind"] == "LINE" and edge["length"] > 29]
    assert edges
    edge_ref = edges[0]

    chamfered = build(worker, "bracket_l", operations=[{
        "op": "chamfer", "distance": 1.5, "edge_ref": edge_ref,
    }])
    assert chamfered["stats"]["is_valid"]
    assert chamfered["stats"]["volume"] < base["stats"]["volume"]

    failed = worker.call("build", {
        "template": "bracket_l",
        "params": {},
        "operations": [{"op": "chamfer", "distance": 50, "edge_ref": edge_ref}],
    })
    assert failed["ok"] is False
    assert failed["error"]["code"] == "chamfer_failed"
    assert "50" in failed["error"]["message"]


def test_edge_reselect_required(worker):
    resp = worker.call("build", {"template": "bracket_l", "params": {},
                                 "operations": [{"op": "fillet", "radius": 2.0,
                                                 "edge_ref": {"kind": "LINE",
                                                              "length": 3.3,
                                                              "midpoint": [1, 2, 3]}}]})
    assert resp["ok"] is False
    assert resp["error"]["code"] == "reselect_required"


# --- AC-05. Форматы ---

def test_ac05_formats(worker, tmp_path):
    doc = {"template": "plate_with_holes", "params": {}, "operations": []}
    exp = 80 * 40 * 6 - 4 * math.pi * 4 * 6
    # STEP roundtrip
    step = tmp_path / "p.step"
    r = worker.call("export", {**doc, "format": "step", "path": str(step)})
    assert r["ok"]
    ri = worker.call("import", {"format": "step", "path": str(step)})
    assert ri["ok"]
    assert abs(ri["result"]["stats"]["volume"] - exp) <= TOL_V(exp)
    # STL: экспорт и чтение сетки
    stl = tmp_path / "p.stl"
    r = worker.call("export", {**doc, "format": "stl", "path": str(stl)})
    assert r["ok"]
    ri = worker.call("import", {"format": "stl", "path": str(stl), "unit_scale": 1.0})
    st = ri["result"]["stats"]
    assert abs(st["bbox_mesh"][0] - 80) <= 0.05
    assert abs(st["volume"] - exp) / exp <= 0.005
    # STL в дюймах: та же сетка × 25,4
    ri2 = worker.call("import", {"format": "stl", "path": str(stl), "unit_scale": 25.4})
    assert abs(ri2["result"]["stats"]["bbox_mesh"][0] - 80 * 25.4) <= 0.1
    # 3MF
    mf = tmp_path / "p.3mf"
    r = worker.call("export", {**doc, "format": "3mf", "path": str(mf)})
    assert r["ok"] and mf.stat().st_size > 0


# --- Проверки печати ---

def test_print_check(worker):
    r = worker.call("print_check", {"template": "plate_with_holes", "params": {},
                                    "printer": {"x": 220, "y": 220, "z": 250}})
    checks = {c["id"]: c for c in r["result"]["checks"]}
    assert checks["brep_valid"]["status"] == "pass"
    assert checks["bed_fit"]["status"] == "pass"
    assert checks["wall_thickness"]["status"] == "unknown"
    # деталь длиной 230 не влезает в стол 220
    r2 = worker.call("print_check", {"template": "plate_with_holes",
                                     "params": {"length": 230},
                                     "printer": {"x": 220, "y": 220, "z": 250}})
    checks2 = {c["id"]: c for c in r2["result"]["checks"]}
    assert checks2["bed_fit"]["status"] == "fail"
    assert "230" in checks2["bed_fit"]["detail"]


def test_mesh_check_open_edge(worker, tmp_path):
    import trimesh
    from build123d import Box, Pos, export_stl
    closed = tmp_path / "c.stl"
    export_stl(Pos(0, 0, 3) * Box(80, 40, 6), str(closed), tolerance=0.02)
    m = trimesh.load(str(closed))
    open_p = tmp_path / "o.stl"
    trimesh.Trimesh(vertices=m.vertices, faces=m.faces[5:], process=False).export(str(open_p))
    r1 = worker.call("mesh_check", {"path": str(closed)})
    c1 = {c["id"]: c for c in r1["result"]["checks"]}
    assert c1["boundary"]["status"] == "pass"
    assert c1["watertight"]["status"] == "pass"
    assert c1["self_intersection"]["status"] == "unknown"
    r2 = worker.call("mesh_check", {"path": str(open_p)})
    c2 = {c["id"]: c for c in r2["result"]["checks"]}
    assert c2["boundary"]["status"] == "fail"
    assert c2["watertight"]["status"] == "fail"


def test_independent_stl_fixtures(worker):
    closed = FIXTURES / "unit_cube_ascii.stl"
    imported = worker.call("import", {
        "format": "stl",
        "path": str(closed),
        "unit_scale": 25.4,
    })
    assert imported["ok"], imported.get("error")
    stats = imported["result"]["stats"]
    assert stats["bbox_mesh"] == pytest.approx([25.4, 25.4, 25.4], abs=0.001)
    assert stats["volume"] == pytest.approx(25.4 ** 3, rel=1e-6)

    opened = worker.call("mesh_check", {"path": str(FIXTURES / "unit_cube_open_ascii.stl")})
    assert opened["ok"], opened.get("error")
    checks = {item["id"]: item for item in opened["result"]["checks"]}
    assert checks["boundary"]["status"] == "fail"
    assert checks["watertight"]["status"] == "fail"

    damaged = worker.call("import", {
        "format": "stl",
        "path": str(FIXTURES / "truncated.stl"),
        "unit_scale": 1.0,
    })
    assert damaged["ok"] is False


# --- документ v3: несколько деталей и операции ---

def test_v3_boolean_subtract(worker):
    doc = {"parts": [
        {"part_id": "base", "template": "plate_with_holes", "params": {}},
        {"part_id": "tool", "template": "washer", "params": {}}],
        "operations": []}
    r = build(worker, "v3", doc) if False else None
    resp = worker.call("build", doc)
    assert resp["ok"]
    st = resp["result"]["stats"]
    assert len(st["parts"]) == 2 and st["solid_count"] == 2
    doc["operations"] = [{"op": "boolean", "boolean": "subtract",
                          "target_id": "base", "tool_id": "tool"}]
    r2 = worker.call("build", doc)
    st2 = r2["result"]["stats"]
    washer_vol = math.pi * (100 - 9) * 4
    plate_vol = 80 * 40 * 6 - 4 * math.pi * 4 * 6
    # шайба (кольцо Ø20/Ø6, Z 0…4) целиком внутри пластины по X/Y;
    # отверстия пластины на (±30; ±10) с ней не пересекаются
    assert abs(st2["volume"] - (plate_vol - washer_vol)) <= 1
    assert len(st2["parts"]) == 1  # инструмент удалён


def test_v3_array_and_mirror(worker):
    doc = {"parts": [{"part_id": "a", "template": "plate_with_holes",
                      "params": {"length": 20, "width": 20, "hole_diameter": 0}}],
           "operations": [{"op": "array_linear", "part_id": "a",
                           "count": 3, "step": [30, 0, 0]}]}
    r = worker.call("build", doc)
    st = r["result"]["stats"]
    assert st["solid_count"] == 3
    assert st["bbox"][3] - st["bbox"][0] == pytest.approx(80, abs=1e-3)
    doc2 = {"parts": [{"part_id": "a", "template": "bracket_l", "params": {}}],
            "operations": [{"op": "mirror", "part_id": "a", "plane": "YZ"}]}
    r2 = worker.call("build", doc2)
    st2 = r2["result"]["stats"]
    assert abs(st2["volume"] - 11000) <= 1
    assert st2["bbox"][3] == pytest.approx(0, abs=1e-3)
    assert st2["bbox"][0] == pytest.approx(-40, abs=1e-3)


def test_v3_split(worker):
    doc = {"parts": [{"part_id": "a", "template": "bracket_l", "params": {}}],
           "operations": [{"op": "split", "part_id": "a", "plane": "YZ", "offset": 20}]}
    r = worker.call("build", doc)
    st = r["result"]["stats"]
    assert len(st["parts"]) == 2
    assert abs(st["volume"] - 11000) <= 1
    vols = sorted(p["volume"] for p in st["parts"])
    assert vols == pytest.approx([5500, 5500], abs=1)


def test_v3_split_fail_is_managed(worker):
    doc = {"parts": [{"part_id": "a", "template": "bracket_l", "params": {}}],
           "operations": [{"op": "split", "part_id": "a", "plane": "YZ", "offset": 200}]}
    r = worker.call("build", doc)
    assert r["ok"] is False
    assert r["error"]["code"] == "split_failed"


def test_profile_extrude_and_slot(worker):
    doc = {"parts": [{"part_id": "a", "template": "plate_with_holes", "params": {}}],
           "operations": [{"op": "profile_extrude", "mode": "add", "plane": "XY",
                           "depth": 8,
                           "profile": {"kind": "rectangle", "width": 10, "height": 6,
                                       "center": [0, 0]}}]}
    r = worker.call("build", doc)
    vols = sorted(p["volume"] for p in r["result"]["stats"]["parts"])
    assert vols[0] == pytest.approx(480, abs=1e-3)
    doc2 = {"parts": [{"part_id": "a", "template": "plate_with_holes",
                       "params": {"hole_diameter": 0}}],
            "operations": [{"op": "profile_extrude", "mode": "cut", "plane": "XY",
                            "depth": "through", "target_id": "a",
                            "profile": {"kind": "slot", "width": 4, "length": 20,
                                        "center": [0, 0]}}]}
    r2 = worker.call("build", doc2)
    exp = 80 * 40 * 6 - (4 * 16 * 6 + math.pi * 4 * 6)
    assert abs(r2["result"]["stats"]["volume"] - exp) <= 1


def test_face_feature_add_and_cut(worker):
    base = 80 * 40 * 6
    add_doc = {
        "parts": [{"part_id": "a", "template": "plate_with_holes",
                   "params": {"hole_diameter": 0}}],
        "operations": [{
            "op": "face_feature", "target_id": "a", "mode": "add", "depth": 4,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "circle", "diameter": 10, "center": [5, -3]},
        }],
    }
    added = worker.call("build", add_doc)
    assert added["ok"], added.get("error")
    expected_added = base + math.pi * 5**2 * 4
    assert added["result"]["stats"]["volume"] == pytest.approx(expected_added, abs=1e-3)
    assert added["result"]["stats"]["bbox"][5] == pytest.approx(10, abs=1e-3)
    assert added["result"]["stats"]["solid_count"] == 1

    through_doc = {
        "parts": [{"part_id": "a", "template": "plate_with_holes",
                   "params": {"hole_diameter": 0}}],
        "operations": [{
            "op": "face_feature", "target_id": "a", "mode": "cut", "depth": "through",
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "circle", "diameter": 8, "center": [0, 0]},
        }],
    }
    through = worker.call("build", through_doc)
    assert through["ok"], through.get("error")
    expected_through = base - math.pi * 4**2 * 6
    assert through["result"]["stats"]["volume"] == pytest.approx(expected_through, abs=1e-3)


def test_face_feature_side_and_invalid_blind_depth(worker):
    base = 80 * 40 * 6
    side_doc = {
        "parts": [{"part_id": "a", "template": "plate_with_holes",
                   "params": {"hole_diameter": 0}}],
        "operations": [{
            "op": "face_feature", "target_id": "a", "mode": "add", "depth": 5,
            "face_ref": {"kind": "outer_planar", "axis": "x", "side": 1,
                         "anchor": [0, 0], "selected_area": 240},
            "profile": {"kind": "rectangle", "width": 10, "height": 4,
                        "center": [0, 0]},
        }],
    }
    side = worker.call("build", side_doc)
    assert side["ok"], side.get("error")
    assert side["result"]["stats"]["volume"] == pytest.approx(base + 200, abs=1e-3)
    assert side["result"]["stats"]["bbox"][3] == pytest.approx(45, abs=1e-3)

    invalid = {
        "parts": [{"part_id": "a", "template": "plate_with_holes",
                   "params": {"hole_diameter": 0}}],
        "operations": [{
            "op": "face_feature", "target_id": "a", "mode": "cut", "depth": 6,
            "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                         "anchor": [0, 0], "selected_area": 3200},
            "profile": {"kind": "circle", "diameter": 8, "center": [0, 0]},
        }],
    }
    response = worker.call("build", invalid)
    assert response["ok"] is False
    assert response["error"]["code"] == "bad_params"
    assert "сквозной" in response["error"]["message"].lower()


def test_face_dome_add_cut_and_constraints(worker):
    base = 80 * 40 * 6
    diameter = 20
    height = 4
    cap_volume = math.pi * height * (3 * (diameter / 2) ** 2 + height ** 2) / 6
    common = {
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200},
        "center": [0, 0],
        "diameter": diameter,
        "height": height,
    }
    part = [{"part_id": "a", "template": "plate_with_holes",
             "params": {"hole_diameter": 0}}]

    added = worker.call("build", {
        "parts": part,
        "operations": [{"op": "face_dome", "mode": "add", **common}],
    })
    assert added["ok"], added.get("error")
    assert added["result"]["stats"]["volume"] == pytest.approx(base + cap_volume, abs=1e-3)
    assert added["result"]["stats"]["bbox"][5] == pytest.approx(10, abs=1e-3)
    assert added["result"]["stats"]["solid_count"] == 1

    cut = worker.call("build", {
        "parts": part,
        "operations": [{"op": "face_dome", "mode": "cut", **common}],
    })
    assert cut["ok"], cut.get("error")
    assert cut["result"]["stats"]["volume"] == pytest.approx(base - cap_volume, abs=1e-3)

    excessive_height = worker.call("build", {
        "parts": part,
        "operations": [{"op": "face_dome", "mode": "add", **common, "height": 11}],
    })
    assert excessive_height["ok"] is False
    assert excessive_height["error"]["code"] == "bad_params"

    through_dent = worker.call("build", {
        "parts": part,
        "operations": [{"op": "face_dome", "mode": "cut", **common, "height": 6}],
    })
    assert through_dent["ok"] is False
    assert through_dent["error"]["code"] == "bad_params"


def test_sheet_bend_preserves_volume_and_holes(worker):
    base_volume = 80 * 40 * 6 - 4 * math.pi * 2**2 * 6
    common = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - 4 * math.pi * 2**2},
        "position": 0,
        "angle": 90,
        "inside_radius": 5,
        "moving_side": 1,
        "direction": 1,
    }
    parts = [{"part_id": "a", "template": "plate_with_holes", "params": {}}]

    bent_x = worker.call("build", {
        "parts": parts,
        "operations": [{**common, "bend_axis": "x"}],
    })
    assert bent_x["ok"], bent_x.get("error")
    stats_x = bent_x["result"]["stats"]
    assert stats_x["volume"] == pytest.approx(base_volume, abs=1e-3)
    assert stats_x["solid_count"] == 1
    assert stats_x["bbox"][5] == pytest.approx(44.7168, abs=1e-3)
    assert stats_x["bbox"][3] == pytest.approx(4.7168, abs=1e-3)

    bent_y_down = worker.call("build", {
        "parts": parts,
        "operations": [{
            **common,
            "bend_axis": "y",
            "inside_radius": 3,
            "moving_side": -1,
            "direction": -1,
        }],
    })
    assert bent_y_down["ok"], bent_y_down.get("error")
    stats_y = bent_y_down["result"]["stats"]
    assert stats_y["volume"] == pytest.approx(base_volume, abs=1e-3)
    assert stats_y["bbox"][2] < -15
    assert stats_y["bbox"][5] == pytest.approx(6, abs=1e-3)

    crosses_hole = worker.call("build", {
        "parts": parts,
        "operations": [{**common, "bend_axis": "x", "position": -30}],
    })
    assert crosses_hole["ok"] is False
    assert crosses_hole["error"]["code"] == "bend_failed"
    assert "отверст" in crosses_hole["error"]["message"].lower()


def test_parallel_sheet_bends_rebuild_one_parametric_blank(worker):
    base_volume = 80 * 40 * 6 - 4 * math.pi * 2**2 * 6
    common = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - 4 * math.pi * 2**2},
        "bend_axis": "x",
        "angle": 90,
        "inside_radius": 3,
        "direction": 1,
    }
    parts = [{"part_id": "a", "template": "plate_with_holes", "params": {}}]
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": 20, "moving_side": 1},
            {**common, "position": -20, "moving_side": -1},
        ],
    })
    assert response["ok"], response.get("error")
    stats = response["result"]["stats"]
    assert stats["volume"] == pytest.approx(base_volume, abs=1e-3)
    assert stats["solid_count"] == 1
    assert stats["bbox"] == pytest.approx(
        [-24.287611, -20, 0, 24.287611, 20, 24.287611], abs=1e-3)

    wrong_axis = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": 20, "moving_side": 1},
            {**common, "bend_axis": "y", "position": -10, "moving_side": -1},
        ],
    })
    assert wrong_axis["ok"] is False
    assert wrong_axis["error"]["code"] == "bend_failed"
    assert "параллель" in wrong_axis["error"]["message"].lower()

    overlapping = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": 4, "moving_side": 1},
            {**common, "position": -4, "moving_side": -1},
        ],
    })
    assert overlapping["ok"] is False
    assert overlapping["error"]["code"] == "bend_failed"
    assert "пересека" in overlapping["error"]["message"].lower()

    wrong_sides = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": -20, "moving_side": 1},
            {**common, "position": 20, "moving_side": -1},
        ],
    })
    assert wrong_sides["ok"] is False
    assert wrong_sides["error"]["code"] == "bend_failed"
    assert "левая" in wrong_sides["error"]["message"].lower()


def test_parallel_sheet_bend_cascade_supports_four_lines(worker):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    common = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200},
        "bend_axis": "x",
        "angle": 45,
        "inside_radius": 1,
    }
    positions = [-30, -10, 10, 30]
    directions = [1, -1, 1, -1]
    cascade = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": position, "moving_side": 1,
             "direction": direction}
            for position, direction in zip(positions, directions)
        ],
    })
    assert cascade["ok"], cascade.get("error")
    assert cascade["result"]["stats"]["volume"] == pytest.approx(80 * 40 * 6, abs=1e-3)
    assert cascade["result"]["stats"]["solid_count"] == 1
    assert cascade["result"]["stats"]["bbox"][5] > 10

    central_anchor = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": position,
             "moving_side": -1 if position < 0 else 1,
             "direction": 1}
            for position in positions
        ],
    })
    assert central_anchor["ok"], central_anchor.get("error")
    assert central_anchor["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6, abs=1e-3)
    assert central_anchor["result"]["stats"]["solid_count"] == 1

    conflicting_anchor = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": -20, "moving_side": 1, "direction": 1},
            {**common, "position": 20, "moving_side": -1, "direction": 1},
        ],
    })
    assert conflicting_anchor["ok"] is False
    assert conflicting_anchor["error"]["code"] == "bend_failed"
    assert "левая группа" in conflicting_anchor["error"]["message"].lower()

    too_many = worker.call("build", {
        "parts": parts,
        "operations": [
            {**common, "position": position, "moving_side": 1, "direction": 1,
             "angle": 20}
            for position in [-32, -16, 0, 16, 32]
        ],
    })
    assert too_many["ok"] is False
    assert too_many["error"]["code"] == "bend_failed"
    assert "четырёх" in too_many["error"]["message"].lower()


@pytest.mark.parametrize(("base_axis", "base_side", "base_direction"), [
    ("x", 1, 1),
    ("x", -1, -1),
    ("y", 1, -1),
    ("y", -1, 1),
])
def test_perpendicular_flange_bend_preserves_body_and_stock_holes(
        worker, base_axis, base_side, base_direction):
    parts = [{"part_id": "a", "template": "plate_with_holes", "params": {}}]
    base = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - 4 * math.pi * 2**2},
        "bend_axis": base_axis,
        "position": 0,
        "angle": 90,
        "inside_radius": 3,
        "moving_side": base_side,
        "direction": base_direction,
    }
    flange_axis = "y" if base_axis == "x" else "x"
    flange = {
        **base,
        "face_ref": {"kind": "outer_planar", "axis": base_axis, "side": base_side,
                     "anchor": [0, 0], "selected_area": 1000},
        "bend_axis": flange_axis,
        "position": 0,
        "inside_radius": 2,
        "moving_side": 1,
        "direction": 1,
    }
    response = worker.call("build", {
        "parts": parts,
        "operations": [base, flange],
    })
    assert response["ok"], response.get("error")
    stats = response["result"]["stats"]
    base_volume = 80 * 40 * 6 - 4 * math.pi * 2**2 * 6
    assert stats["volume"] == pytest.approx(base_volume, abs=3e-2)
    assert stats["solid_count"] == 1
    assert stats["is_valid"] is True
    assert stats["bbox"][5] - stats["bbox"][2] > 20


@pytest.mark.parametrize(("base_axis", "base_side", "feature_center"), [
    ("x", -1, [-24, 0]),
    ("y", 1, [0, 12]),
])
@pytest.mark.parametrize(("profile", "cut_area", "solid_count"), [
    ({"kind": "rectangle", "width": 8, "height": 6}, 48, 1),
    ({"kind": "circle", "diameter": 8}, math.pi * 4**2, 1),
    ({"kind": "ring", "outer_diameter": 10, "inner_diameter": 6},
     math.pi * (5**2 - 3**2), 2),
    ({"kind": "slot", "width": 4, "length": 12},
     (12 - 4) * 4 + math.pi * 2**2, 1),
])
def test_perpendicular_flange_bend_preserves_supported_flat_cut_profiles(
        worker, base_axis, base_side, feature_center, profile, cut_area,
        solid_count):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    cut = {
        "op": "face_feature",
        "target_id": "a",
        "mode": "cut",
        "depth": "through",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200},
        "profile": {**profile, "center": feature_center},
    }
    base = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - cut_area},
        "bend_axis": base_axis,
        "position": 0,
        "angle": 90,
        "inside_radius": 3,
        "moving_side": base_side,
        "direction": 1,
    }
    flange = {
        **base,
        "face_ref": {"kind": "outer_planar", "axis": base_axis,
                     "side": base_side, "anchor": [0, 0],
                     "selected_area": 1000},
        "bend_axis": "y" if base_axis == "x" else "x",
        "angle": 70,
        "inside_radius": 2,
        "moving_side": 1,
    }
    response = worker.call("build", {
        "parts": parts,
        "operations": [cut, base, flange],
    })
    assert response["ok"], response.get("error")
    stats = response["result"]["stats"]
    assert stats["volume"] == pytest.approx(80 * 40 * 6 - cut_area * 6, abs=5e-2)
    assert stats["solid_count"] == solid_count
    assert stats["is_valid"] is True


def test_perpendicular_flange_bend_rejects_cut_crossing_base_bend_root(worker):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    common = {
        "op": "sheet_bend",
        "target_id": "a",
        "position": 0,
        "angle": 90,
        "inside_radius": 3,
        "moving_side": 1,
        "direction": 1,
    }
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "depth": "through",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": {"kind": "circle", "diameter": 8,
                            "center": [6, 0]},
            },
            {
                **common,
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1},
                "bend_axis": "x",
            },
            {
                **common,
                "face_ref": {"kind": "outer_planar", "axis": "x", "side": 1},
                "bend_axis": "y",
            },
        ],
    })
    assert response["ok"] is False
    assert response["error"]["code"] == "bend_failed"
    assert "целиком" in response["error"]["message"].lower()


def test_perpendicular_flange_bend_requires_selected_matching_flange(worker):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    common = {
        "op": "sheet_bend",
        "target_id": "a",
        "position": 0,
        "angle": 90,
        "inside_radius": 3,
        "moving_side": 1,
        "direction": 1,
    }
    base = {
        **common,
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1},
        "bend_axis": "x",
    }
    wrong_face = worker.call("build", {
        "parts": parts,
        "operations": [base, {
            **common,
            "face_ref": {"kind": "outer_planar", "axis": "x", "side": -1},
            "bend_axis": "y",
        }],
    })
    assert wrong_face["ok"] is False
    assert wrong_face["error"]["code"] == "reselect_required"

    non_right_angle = worker.call("build", {
        "parts": parts,
        "operations": [{**base, "angle": 60}, {
            **common,
            "face_ref": {"kind": "outer_planar", "axis": "x", "side": 1},
            "bend_axis": "y",
        }],
    })
    assert non_right_angle["ok"] is False
    assert non_right_angle["error"]["code"] == "bend_failed"
    assert "90" in non_right_angle["error"]["message"]


def test_sheet_bend_preserves_flat_through_cuts(worker):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    circle_cut = {
        "op": "face_feature",
        "target_id": "a",
        "mode": "cut",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200},
        "profile": {"kind": "circle", "diameter": 8, "center": [30, 0]},
        "depth": "through",
    }
    bend = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - math.pi * 4**2},
        "bend_axis": "x",
        "angle": 90,
        "inside_radius": 3,
        "direction": 1,
    }
    expected_volume = 80 * 40 * 6 - math.pi * 4**2 * 6

    one_bend = worker.call("build", {
        "parts": parts,
        "operations": [
            circle_cut,
            {**bend, "position": 20, "moving_side": 1},
        ],
    })
    assert one_bend["ok"], one_bend.get("error")
    assert one_bend["result"]["stats"]["volume"] == pytest.approx(
        expected_volume, abs=1e-3)

    two_bends = worker.call("build", {
        "parts": parts,
        "operations": [
            circle_cut,
            {**bend, "position": 20, "moving_side": 1},
            {**bend, "position": -20, "moving_side": -1},
        ],
    })
    assert two_bends["ok"], two_bends.get("error")
    assert two_bends["result"]["stats"]["volume"] == pytest.approx(
        expected_volume, abs=1e-3)

    rectangle_cut = {
        **circle_cut,
        "profile": {"kind": "rectangle", "width": 8, "height": 4,
                    "center": [0, 12]},
    }
    bent_y = worker.call("build", {
        "parts": parts,
        "operations": [
            rectangle_cut,
            {**bend, "bend_axis": "y", "position": 0, "moving_side": 1},
        ],
    })
    assert bent_y["ok"], bent_y.get("error")
    assert bent_y["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6 - 8 * 4 * 6, abs=1e-3)


@pytest.mark.parametrize(("profile", "cut_area", "solid_count"), [
    ({"kind": "rectangle", "width": 8, "height": 6}, 48, 1),
    ({"kind": "circle", "diameter": 8}, math.pi * 4**2, 1),
    ({"kind": "ring", "outer_diameter": 10, "inner_diameter": 6},
     math.pi * (5**2 - 3**2), 2),
    ({"kind": "slot", "width": 4, "length": 12},
     (12 - 4) * 4 + math.pi * 2**2, 1),
])
def test_sheet_bend_preserves_each_supported_flat_cut_profile(
        worker, profile, cut_area, solid_count):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": {**profile, "center": [30, 0]},
                "depth": "through",
            },
            {
                "op": "sheet_bend",
                "target_id": "a",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200 - cut_area},
                "bend_axis": "x",
                "position": 0,
                "angle": 90,
                "inside_radius": 3,
                "moving_side": 1,
                "direction": 1,
            },
        ],
    })
    assert response["ok"], response.get("error")
    assert response["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6 - cut_area * 6, abs=1e-3)
    assert response["result"]["stats"]["solid_count"] == solid_count


@pytest.mark.parametrize(("bend_axis", "profile", "bends"), [
    ("x", {"kind": "rectangle", "width": 12, "height": 8, "center": [0, 0]}, [
        {"position": 0, "moving_side": 1},
    ]),
    ("y", {"kind": "rectangle", "width": 8, "height": 12, "center": [0, 0]}, [
        {"position": 0, "moving_side": 1},
    ]),
    ("x", {"kind": "rectangle", "width": 50, "height": 8, "center": [0, 0]}, [
        {"position": 20, "moving_side": 1},
        {"position": -20, "moving_side": -1},
    ]),
])
def test_rectangular_through_cut_crosses_curved_bend_zones(
        worker, bend_axis, profile, bends):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    cut_area = profile["width"] * profile["height"]
    common_bend = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - cut_area},
        "bend_axis": bend_axis,
        "angle": 90,
        "inside_radius": 3,
        "direction": 1,
    }
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": profile,
                "depth": "through",
            },
            *[{**common_bend, **bend} for bend in bends],
        ],
    })
    assert response["ok"], response.get("error")
    assert response["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6 - cut_area * 6, abs=1e-3)
    assert response["result"]["stats"]["solid_count"] == 1


@pytest.mark.parametrize(("bend_axis", "direction"), [
    ("x", 1),
    ("y", -1),
])
def test_circular_through_cut_crosses_curved_bend_zone(
        worker, bend_axis, direction):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    cut_area = math.pi * 4**2
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": {"kind": "circle", "diameter": 8, "center": [0, 0]},
                "depth": "through",
            },
            {
                "op": "sheet_bend",
                "target_id": "a",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200 - cut_area},
                "bend_axis": bend_axis,
                "position": 0,
                "angle": 90,
                "inside_radius": 3,
                "moving_side": 1,
                "direction": direction,
            },
        ],
    })
    assert response["ok"], response.get("error")
    assert response["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6 - cut_area * 6, abs=1e-3)
    assert response["result"]["stats"]["solid_count"] == 1
    assert response["result"]["stats"]["is_valid"] is True


@pytest.mark.parametrize(("bend_axis", "direction"), [
    ("x", 1),
    ("y", -1),
])
def test_slot_through_cut_crosses_curved_bend_zone(
        worker, bend_axis, direction):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    cut_area = (12 - 4) * 4 + math.pi * 2**2
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": {"kind": "slot", "width": 4, "length": 12,
                            "center": [0, 0]},
                "depth": "through",
            },
            {
                "op": "sheet_bend",
                "target_id": "a",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200 - cut_area},
                "bend_axis": bend_axis,
                "position": 0,
                "angle": 90,
                "inside_radius": 3,
                "moving_side": 1,
                "direction": direction,
            },
        ],
    })
    assert response["ok"], response.get("error")
    assert response["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6 - cut_area * 6, abs=1e-3)
    assert response["result"]["stats"]["solid_count"] == 1
    assert response["result"]["stats"]["is_valid"] is True


@pytest.mark.parametrize(("bend_axis", "direction"), [
    ("x", 1),
    ("y", -1),
])
def test_ring_through_cut_crosses_curved_bend_zone(
        worker, bend_axis, direction):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    ring_area = math.pi * (5**2 - 3**2)
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": {"kind": "ring", "outer_diameter": 10,
                            "inner_diameter": 6, "center": [0, 0]},
                "depth": "through",
            },
            {
                "op": "sheet_bend",
                "target_id": "a",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200 - ring_area},
                "bend_axis": bend_axis,
                "position": 0,
                "angle": 90,
                "inside_radius": 3,
                "moving_side": 1,
                "direction": direction,
            },
        ],
    })
    assert response["ok"], response.get("error")
    assert response["result"]["stats"]["volume"] == pytest.approx(
        80 * 40 * 6 - ring_area * 6, abs=1e-3)
    assert response["result"]["stats"]["solid_count"] == 2
    assert response["result"]["stats"]["is_valid"] is True


@pytest.mark.parametrize(("profile", "cut_area"), [
    ({"kind": "circle", "diameter": 32, "center": [0, 0]}, math.pi * 16**2),
    ({"kind": "ring", "outer_diameter": 32, "inner_diameter": 8,
      "center": [0, 0]}, math.pi * (16**2 - 4**2)),
    ({"kind": "slot", "width": 4, "length": 32, "center": [0, 0]},
     (32 - 4) * 4 + math.pi * 2**2),
])
def test_profiled_through_cut_rejects_multiple_curved_bend_zones(
        worker, profile, cut_area):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    cut_area = math.pi * 16**2
    common_bend = {
        "op": "sheet_bend",
        "target_id": "a",
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - cut_area},
        "bend_axis": "x",
        "angle": 90,
        "inside_radius": 3,
        "direction": 1,
    }
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {
                "op": "face_feature",
                "target_id": "a",
                "mode": "cut",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "profile": profile,
                "depth": "through",
            },
            {**common_bend, "position": -12, "moving_side": -1},
            {**common_bend, "position": 12, "moving_side": 1},
        ],
    })
    assert response["ok"] is False
    assert response["error"]["code"] == "bend_failed"
    assert "только одну" in response["error"]["message"].lower()


def test_sheet_bend_rejects_unsupported_prior_operation(worker):
    parts = [{"part_id": "a", "template": "plate_with_holes",
              "params": {"hole_diameter": 0}}]
    response = worker.call("build", {
        "parts": parts,
        "operations": [
            {"op": "transform", "part_id": "a", "translate": [1, 0, 0]},
            {
                "op": "sheet_bend",
                "target_id": "a",
                "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                             "anchor": [0, 0], "selected_area": 3200},
                "bend_axis": "x",
                "position": 0,
                "angle": 90,
                "inside_radius": 5,
                "moving_side": 1,
                "direction": 1,
            },
        ],
    })
    assert response["ok"] is False
    assert response["error"]["code"] == "bend_failed"
    assert "сквозные вырезы" in response["error"]["message"].lower()


def test_circular_array_and_align(worker):
    doc = {"parts": [{"part_id": "a", "template": "washer",
                      "params": {"outer_diameter": 10, "inner_diameter": 0, "height": 8}}],
           "operations": [{"op": "transform", "part_id": "a", "translate": [25, 0, 0]},
                          {"op": "array_circular", "part_id": "a", "count": 4,
                           "angle": 360, "center": [0, 0, 0]}]}
    r = worker.call("build", doc)
    st = r["result"]["stats"]
    assert st["solid_count"] == 4
    assert st["bbox"][3] - st["bbox"][0] == pytest.approx(60, abs=1e-3)
    doc2 = {"parts": [{"part_id": "a", "template": "bracket_l", "params": {}}],
            "operations": [{"op": "align", "part_id": "a", "axis": "x",
                            "align": "center", "value": 0}]}
    r2 = worker.call("build", doc2)
    bb = r2["result"]["stats"]["bbox"]
    assert bb[0] == pytest.approx(-20, abs=1e-3)


def test_measure(worker):
    r = worker.call("measure", {"type": "face_diameter", "face_index": 0,
                                "template": "washer", "params": {}})
    assert r["result"]["diameter"] == pytest.approx(20, abs=1e-3)
    assert r["result"]["source"] == "brep"
    r2 = worker.call("measure", {"type": "distance",
                                 "p0": [0, 0, 0], "p1": [30, 40, 0]})
    assert r2["result"]["distance"] == pytest.approx(50, abs=1e-3)
    r3 = worker.call("measure", {"type": "face_diameter", "face_index": 99,
                                 "template": "washer", "params": {}})
    assert r3["ok"] is False and r3["error"]["code"] == "bad_ref"
