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
