"""M2: приёмочные проверки AC-01…AC-05 на уровне worker (аналитические допуски)."""
import json
import math
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent
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
