"""PrintForge: геометрический worker (M2).

Отдельный процесс. Протокол: JSON Lines в stdout, запросы из stdin,
диагностика — stderr. Сетки — бинарным ресурсом (файл + sha256).

Шаблоны (точная BRep через build123d/OCP):
- plate_with_holes: пластина L×W×H, 4 сквозных отверстия ØD, отступ O (AC-01).
- washer: шайба OD×ID×H (AC-02).
- bracket_l: L-кронштейн из двух блоков с общим началом координат (AC-04).
- case_with_lid: корпус со стенкой/дном + крышка с бортиком и зазором (AC-03).

Операции поверх шаблона: fillet (выбор ребра мягкой геометрической
ссылкой; честная ошибка OCC, без молчаливого подбора другого значения).

Прочее: export_stl/step/3mf, import_step/stl, print_check.
"""
import hashlib
import json
import math
import os
import struct
import sys
import tempfile
import traceback
from pathlib import Path

SCHEMA_VERSION = 1
_session_dir = Path(tempfile.mkdtemp(prefix="printforge-geo-"))


def log(*args):
    print("[worker]", *args, file=sys.stderr, flush=True)


def respond(request_id, ok, **payload):
    out = {"request_id": request_id, "schema_version": SCHEMA_VERSION, "ok": ok}
    out.update(payload)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


class GeometryError(Exception):
    """Понятная пользователю ошибка операции."""

    def __init__(self, code, message, detail=""):
        super().__init__(message)
        self.code, self.message, self.detail = code, message, detail


# ---------- шаблоны ----------

def build_plate(p):
    from build123d import Box, Cylinder, Pos
    L, W, H = p["length"], p["width"], p["height"]
    d, off = p["hole_diameter"], p["hole_offset"]
    part = Pos(0, 0, H / 2) * Box(L, W, H)
    if d > 0:
        hx, hy = L / 2 - off, W / 2 - off
        if hx <= 0 or hy <= 0:
            raise GeometryError(
                "bad_params",
                f"Отступ {off} мм не помещается при размерах {L} × {W} мм. "
                "Увеличьте деталь или уменьшите отступ.")
        for sx in (-hx, hx):
            for sy in (-hy, hy):
                part -= Pos(sx, sy, H / 2) * Cylinder(radius=d / 2, height=H * 2)
    return part, {"hole_centers": [[-L / 2 + off, -W / 2 + off],
                                   [L / 2 - off, -W / 2 + off],
                                   [-L / 2 + off, W / 2 - off],
                                   [L / 2 - off, W / 2 - off]] if d > 0 else []}


def build_washer(p):
    from build123d import Cylinder, Pos
    od, id_, h = p["outer_diameter"], p["inner_diameter"], p["height"]
    if id_ >= od:
        raise GeometryError(
            "bad_params",
            f"Внутренний диаметр {id_} мм должен быть меньше наружного {od} мм.")
    part = Pos(0, 0, h / 2) * Cylinder(radius=od / 2, height=h)
    part -= Pos(0, 0, h / 2) * Cylinder(radius=id_ / 2, height=h * 2)
    return part, {}


def build_bracket(p):
    from build123d import Box, Pos
    al, aw, at, bh = p["a_length"], p["a_width"], p["a_thickness"], p["b_height"]
    a = Pos(al / 2, aw / 2, at / 2) * Box(al, aw, at)
    b = Pos(al / 2, at / 2, bh / 2) * Box(al, at, bh)
    return a + b, {}


def build_case(p):
    from build123d import Box, Pos
    L, W, H = p["length"], p["width"], p["height"]
    wall, bottom = p["wall"], p["bottom"]
    gap, lid_t = p["gap"], p["lid_thickness"]
    lip_h, lip_w = p["lip_height"], p["lip_wall"]
    ci_x, ci_y, ci_z = L - 2 * wall, W - 2 * wall, H - bottom
    if min(ci_x, ci_y, ci_z) <= 0:
        raise GeometryError(
            "bad_params",
            "Стенка или дно слишком толстые: полость исчезает. "
            "Уменьшите толщину или увеличьте корпус.")
    case = Pos(0, 0, H / 2) * Box(L, W, H)
    case -= Pos(0, 0, bottom + ci_z / 2) * Box(ci_x, ci_y, ci_z)
    # крышка: пластина + центрированный бортик (рамка)
    lid = Pos(0, 0, H + lid_t / 2) * Box(L, W, lid_t)
    ro_x, ro_y = ci_x - 2 * gap, ci_y - 2 * gap
    ri_x, ri_y = ro_x - 2 * lip_w, ro_y - 2 * lip_w
    if min(ro_x, ro_y, ri_x, ri_y) <= 0:
        raise GeometryError(
            "bad_params", "Бортик крышки не помещается при заданном зазоре.")
    rim = Pos(0, 0, H - lip_h / 2) * Box(ro_x, ro_y, lip_h)
    rim -= Pos(0, 0, H - lip_h / 2) * Box(ri_x, ri_y, lip_h * 1.2)
    lid += rim
    from build123d import Compound
    # корпус и крышка — раздельные тела (контакт по плоскости не объединять)
    return Compound(children=[case, lid]), {
        "case_volume": case.volume, "lid_volume": lid.volume,
        "intersection_volume": (case & lid).volume}


TEMPLATES = {
    "plate_with_holes": (build_plate, {
        "length": 80.0, "width": 40.0, "height": 6.0,
        "hole_diameter": 4.0, "hole_offset": 10.0}),
    "washer": (build_washer, {
        "outer_diameter": 20.0, "inner_diameter": 6.0, "height": 4.0}),
    "bracket_l": (build_bracket, {
        "a_length": 40.0, "a_width": 30.0, "a_thickness": 5.0, "b_height": 30.0}),
    "case_with_lid": (build_case, {
        "length": 100.0, "width": 60.0, "height": 30.0, "wall": 2.0,
        "bottom": 2.0, "gap": 0.2, "lid_thickness": 2.0,
        "lip_height": 4.0, "lip_wall": 2.0}),
}


def merged_params(template, params):
    out = dict(TEMPLATES[template][1])
    for k, v in (params or {}).items():
        if k in out:
            out[k] = float(v)
    return out


# ---------- рёбра и скругление ----------

def edge_signature(edge, solid_index):
    c = edge.center()
    try:
        p0 = tuple(round(v, 4) for v in edge.start_point())
        p1 = tuple(round(v, 4) for v in edge.end_point())
    except Exception:  # noqa: BLE001
        p0 = p1 = None
    return {
        "solid_index": solid_index,
        "kind": str(edge.geom_type).split(".")[-1],
        "length": round(edge.length, 4),
        "midpoint": [round(c.X, 4), round(c.Y, 4), round(c.Z, 4)],
        "p0": p0, "p1": p1,
    }


def list_edges(part):
    edges = []
    for si, solid in enumerate(part.solids()):
        for edge in solid.edges():
            edges.append(edge_signature(edge, si))
    return edges


def match_edge(part, ref):
    """Повторный поиск ребра по мягкой ссылке (DOC-003). Не Face17/Edge8."""
    from build123d import GeomType
    kind, mp, ln = ref.get("kind"), ref.get("midpoint"), ref.get("length")
    if not kind or not mp:
        raise GeometryError("bad_ref", "Ссылка на ребро повреждена. Выберите ребро заново.")
    try:
        gt = getattr(GeomType, kind)
    except AttributeError:
        gt = None
    candidates = []
    for solid in part.solids():
        for e in solid.edges():
            if gt is not None and e.geom_type != gt:
                continue
            if abs(e.length - ln) > max(0.5, 0.05 * ln):
                continue
            c = e.center()
            dist = math.dist((c.X, c.Y, c.Z), mp)
            candidates.append((dist, e))
    if not candidates:
        raise GeometryError(
            "reselect_required",
            "Ребро не найдено после перестроения модели. Выберите ребро заново.")
    candidates.sort(key=lambda t: t[0])
    if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 1e-3:
        raise GeometryError(
            "reselect_required",
            "После перестроения несколько одинаковых рёбер. Уточните выбор.")
    if candidates[0][0] > 2.0:
        raise GeometryError(
            "reselect_required",
            "Ребро сместилось после перестроения. Выберите его заново.")
    return candidates[0][1]


def apply_operations(part, operations):
    for op in operations or []:
        if op.get("op") == "fillet":
            r = float(op["radius"])
            if r <= 0:
                raise GeometryError("bad_params", "Радиус скругления должен быть больше нуля.")
            edge = match_edge(part, op["edge_ref"])
            try:
                part = part.fillet(radius=r, edge_list=[edge])
            except Exception as e:  # noqa: BLE001
                raise GeometryError(
                    "fillet_failed",
                    f"Радиус {r:g} мм слишком велик для выбранного ребра. "
                    "Уменьшите радиус или выберите другое ребро.",
                    detail=str(e).split("\n")[0]) from e
        else:
            raise GeometryError("unknown_op", f"Неизвестная операция: {op.get('op')}")
    return part


# ---------- сетка и статистика ----------

def mesh_resource(part, name, tol=0.1):
    positions, indices, face_ranges = [], [], []
    v_off = 0
    fi = 0
    for si, solid in enumerate(part.solids()):
        for face in solid.faces():
            verts, tris = face.tessellate(tol)
            for v in verts:
                x, y, z = tuple(v)
                positions.extend((float(x), float(y), float(z)))
            for a, b, c in tris:
                indices.extend((int(a) + v_off, int(b) + v_off, int(c) + v_off))
            face_ranges.append({"face_index": fi, "solid_index": si,
                                "tri_start": len(indices) // 3 - len(tris),
                                "tri_count": len(tris)})
            fi += 1
            v_off += len(verts)
    blob = struct.pack("<II", len(positions) // 3, len(indices) // 3)
    blob += struct.pack(f"<{len(positions)}f", *positions)
    blob += struct.pack(f"<{len(indices)}I", *indices)
    path = _session_dir / f"{name}.bin"
    path.write_bytes(blob)
    return {"path": str(path), "bytes": len(blob),
            "sha256": hashlib.sha256(blob).hexdigest(),
            "vertex_count": len(positions) // 3,
            "triangle_count": len(indices) // 3,
            "face_ranges": face_ranges}


def stats_of(part, extra=None, with_edges=True):
    bb = part.bounding_box()
    st = {
        "volume": part.volume,
        "solid_count": len(part.solids()),
        "face_count": len(part.faces()),
        "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
        "is_valid": bool(part.is_valid),
    }
    if with_edges:
        st["edges"] = list_edges(part)
    if extra:
        st.update(extra)
    return st


def build_document(params):
    template = (params or {}).get("template", "plate_with_holes")
    if template not in TEMPLATES:
        raise GeometryError("unknown_template", f"Неизвестный шаблон: {template}")
    tp = merged_params(template, params.get("params"))
    part, extra = TEMPLATES[template][0](tp)
    part = apply_operations(part, params.get("operations"))
    return part, extra


# ---------- многодетальный документ (v3) ----------

def apply_part_operations(parts, operations):
    """Операции над деталями документа v3. parts: {part_id: {"shape": Shape,
    "name": str}}. Возвращает изменённый словарь."""
    from build123d import Compound, Pos
    from build123d import Plane
    for op in operations or []:
        kind = op.get("op")
        pid = op.get("part_id")
        if kind == "boolean":
            target = parts[op["target_id"]]["shape"]
            tool = parts[op["tool_id"]]["shape"]
            bt = op.get("boolean", "union")
            if bt == "union":
                parts[op["target_id"]]["shape"] = target + tool
            elif bt == "subtract":
                parts[op["target_id"]]["shape"] = target - tool
            elif bt == "intersect":
                parts[op["target_id"]]["shape"] = target & tool
            else:
                raise GeometryError("bad_params", f"неизвестная булева операция: {bt}")
            if not op.get("keep_tool", False):
                del parts[op["tool_id"]]
        elif kind == "fillet":
            r = float(op["radius"])
            edge = match_edge(parts[pid]["shape"], op["edge_ref"])
            try:
                parts[pid]["shape"] = parts[pid]["shape"].fillet(radius=r, edge_list=[edge])
            except Exception as e:  # noqa: BLE001
                raise GeometryError(
                    "fillet_failed",
                    f"Радиус {r:g} мм слишком велик для выбранного ребра. "
                    "Уменьшите радиус или выберите другое ребро.",
                    detail=str(e).split("\n")[0]) from e
        elif kind == "transform":
            t = op.get("translate") or [0, 0, 0]
            parts[pid]["shape"] = Pos(*t) * parts[pid]["shape"]
        elif kind == "array_linear":
            n = int(op["count"])
            step = op.get("step") or [0, 0, 0]
            if n < 2:
                raise GeometryError("bad_params", "В массиве должно быть хотя бы 2 элемента.")
            base = parts[pid]["shape"]
            copies = [Pos(step[0] * i, step[1] * i, step[2] * i) * base
                      for i in range(n)]
            parts[pid]["shape"] = Compound(children=copies)
        elif kind == "mirror":
            plane = op.get("plane", "YZ")
            base = parts[pid]["shape"]
            pl = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}.get(plane)
            if pl is None:
                raise GeometryError("bad_params", f"неизвестная плоскость: {plane}")
            parts[pid]["shape"] = base.mirror(pl)
        elif kind == "split":
            plane = op.get("plane", "XZ")
            off = float(op.get("offset", 0))
            pl = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}.get(plane)
            if pl is None:
                raise GeometryError("bad_params", f"неизвестная плоскость: {plane}")
            base = parts[pid]["shape"]
            from build123d import Keep
            cut = base.split(pl.offset(off), keep=Keep.BOTH)
            if isinstance(cut, tuple):
                halves = [s for part_ in cut if part_ is not None
                          for s in part_.solids()]
            else:
                halves = cut.solids()
            if len(halves) < 2:
                raise GeometryError(
                    "split_failed",
                    "Плоскость не разделяет деталь на две части. Сместите плоскость внутрь тела.")
            name = parts[pid]["name"]
            parts[pid]["shape"] = halves[0]
            parts[pid]["name"] = f"{name} (часть 1)"
            new_id = f"{pid}-part2"
            parts[new_id] = {"shape": halves[1], "name": f"{name} (часть 2)"}
        else:
            raise GeometryError("unknown_op", f"Неизвестная операция: {kind}")
    return parts


def handle_build_v3(params):
    from build123d import Compound
    parts = {}
    for p in params.get("parts") or []:
        template = p.get("template")
        if template not in TEMPLATES:
            raise GeometryError("unknown_template", f"Неизвестный шаблон: {template}")
        tp = merged_params(template, p.get("params"))
        shape, _ = TEMPLATES[template][0](tp)
        parts[p["part_id"]] = {"shape": shape, "name": p.get("name", template)}
    parts = apply_part_operations(parts, params.get("operations"))
    compound = Compound(children=[p["shape"] for p in parts.values()])
    extra = {"parts": [{"part_id": pid, "name": p["name"],
                        "volume": p["shape"].volume,
                        "solid_count": len(p["shape"].solids())}
                       for pid, p in parts.items()]}
    return compound, extra


# ---------- методы ----------

def build_any(params):
    if params.get("parts"):
        return handle_build_v3(params)
    return build_document(params)


def handle_build(params):
    part, extra = build_any(params)
    return {"stats": stats_of(part, extra),
            "mesh": mesh_resource(part, "model")}


def handle_export(params):
    fmt = params.get("format", "stl")
    path = params.get("path")
    if not path:
        raise GeometryError("bad_params", "не указан путь экспорта")
    part, extra = build_any(params)
    if fmt == "stl":
        from build123d import export_stl
        export_stl(part, path, tolerance=float(params.get("linear_deflection", 0.02)))
    elif fmt == "step":
        from build123d import export_step
        export_step(part, path)
    elif fmt == "3mf":
        from build123d import Mesher
        m = Mesher()
        m.add_shape(part)
        m.write(path)
    else:
        raise GeometryError("bad_params", f"неизвестный формат: {fmt}")
    return {"path": path, "bytes": Path(path).stat().st_size,
            "format": fmt, "stats": stats_of(part, extra, with_edges=False)}


def handle_import(params):
    fmt = params.get("format")
    path = params.get("path")
    if not path:
        raise GeometryError("bad_params", "не указан путь импорта")
    if fmt == "step":
        from build123d import import_step
        part = import_step(path)
        return {"stats": stats_of(part, with_edges=False),
                "mesh": mesh_resource(part, "import"),
                "mode": "brep"}
    if fmt == "stl":
        import trimesh
        scale = float(params.get("unit_scale", 1.0))
        mesh = trimesh.load(path)
        positions = (mesh.vertices * scale).astype("float32")
        indices = mesh.faces.astype("uint32")
        blob = struct.pack("<II", len(positions), len(indices))
        blob += positions.tobytes() + indices.tobytes()
        rpath = _session_dir / "import.bin"
        rpath.write_bytes(blob)
        ext = mesh.bounding_box.extents * scale
        return {"stats": {
                    "volume": float(mesh.volume) * scale ** 3 if mesh.is_watertight else None,
                    "solid_count": int(mesh.body_count),
                    "face_count": None,
                    "bbox": None,
                    "bbox_mesh": [float(x) for x in ext],
                    "is_valid": bool(mesh.is_watertight),
                    "triangle_count": int(len(indices)),
                },
                "mesh": {"path": str(rpath), "bytes": len(blob),
                         "sha256": hashlib.sha256(blob).hexdigest(),
                         "vertex_count": len(positions),
                         "triangle_count": len(indices),
                         "face_ranges": []},
                "mode": "mesh"}
    raise GeometryError("bad_params", f"неизвестный формат импорта: {fmt}")


def handle_print_check(params):
    """PRINT-001/002: отдельный результат каждой проверки."""
    part, _ = build_any(params)
    checks = []
    bb = part.bounding_box()
    solids = part.solids()
    checks.append({"id": "brep_valid", "title": "Валидность BRep",
                   "status": "pass" if part.is_valid else "fail"})
    checks.append({"id": "solids", "title": "Замкнутые тела",
                   "status": "pass" if len(solids) >= 1 else "fail",
                   "detail": f"{len(solids)} шт."})
    checks.append({"id": "volume", "title": "Положительный объём",
                   "status": "pass" if part.volume > 0 else "fail",
                   "detail": f"{part.volume:.1f} мм³"})
    profile = params.get("printer") or {}
    bx = (bb.max.X - bb.min.X, bb.max.Y - bb.min.Y, bb.max.Z - bb.min.Z)
    limits = (profile.get("x"), profile.get("y"), profile.get("z"))
    if all(limits):
        over = [d for d, lim in zip(bx, limits) if d > lim]
        checks.append({"id": "bed_fit", "title": "Габарит в рабочей области",
                       "status": "pass" if not over else "fail",
                       "detail": f"деталь {bx[0]:.0f} × {bx[1]:.0f} × {bx[2]:.0f} мм, "
                                 f"стол {limits[0]} × {limits[1]} × {limits[2]} мм"})
    else:
        checks.append({"id": "bed_fit", "title": "Габарит в рабочей области",
                       "status": "unknown", "detail": "профиль принтера не задан"})
    checks.append({"id": "wall_thickness", "title": "Минимальная стенка",
                   "status": "unknown",
                   "detail": "универсальный анализ не реализован (P2)"})
    return {"checks": checks}


def handle_mesh_check(params):
    """PRINT-001 для импортированной сетки: отдельный статус каждой проверки."""
    import trimesh
    path = params.get("path")
    if not path:
        raise GeometryError("bad_params", "не указан путь сетки")
    mesh = trimesh.load(path)
    checks = []
    faces = mesh.faces
    areas = mesh.area_faces
    degen = int((areas <= 1e-12).sum())
    checks.append({"id": "degenerate", "title": "Вырожденные треугольники",
                   "status": "pass" if degen == 0 else "fail",
                   "detail": f"{degen} шт."})
    try:
        import numpy as np
        _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
        boundary = int((counts == 1).sum())
    except Exception:  # noqa: BLE001
        boundary = -1
    checks.append({"id": "boundary", "title": "Открытые края (граничные рёбра)",
                   "status": "pass" if boundary == 0 else "fail",
                   "detail": f"{boundary} рёбер" if boundary >= 0 else "не удалось оценить"})
    try:
        wound = bool(mesh.is_winding_consistent)
    except Exception:  # noqa: BLE001
        wound = None
    checks.append({"id": "winding", "title": "Согласованная ориентация",
                   "status": ("pass" if wound else "fail") if wound is not None else "unknown"})
    comps = int(mesh.body_count)
    checks.append({"id": "components", "title": "Число компонент",
                   "status": "pass" if comps == 1 else "fail",
                   "detail": f"{comps} шт."})
    checks.append({"id": "self_intersection", "title": "Самопересечения",
                   "status": "unknown",
                   "detail": "универсальный анализ не реализован (P2)"})
    checks.append({"id": "watertight", "title": "Замкнутая оболочка",
                   "status": "pass" if mesh.is_watertight else "fail"})
    return {"checks": checks, "triangle_count": int(len(faces)),
            "bbox_mesh": [float(x) for x in mesh.bounding_box.extents]}


HANDLERS = {
    "ping": lambda p: {"pid": os.getpid()},
    "build_plate": lambda p: handle_build({"template": "plate_with_holes",
                                           "params": p}),
    "build": handle_build,
    "export": handle_export,
    "export_stl": lambda p: handle_export({**p, "format": "stl",
                                           "template": "plate_with_holes",
                                           "params": p}),
    "import": handle_import,
    "print_check": handle_print_check,
    "mesh_check": handle_mesh_check,
}


def main():
    log("worker started, pid", os.getpid())
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError as e:
            respond(None, False, error={"code": "bad_json", "message": str(e)})
            continue
        rid, method = req.get("request_id"), req.get("method")
        try:
            if method == "shutdown":
                respond(rid, True)
                return 0
            handler = HANDLERS.get(method)
            if not handler:
                respond(rid, False, error={"code": "unknown_method",
                                           "message": str(method)})
                continue
            respond(rid, True, result=handler(req.get("params") or {}))
        except GeometryError as e:
            respond(rid, False, error={"code": e.code, "message": e.message,
                                       "detail": e.detail})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            respond(rid, False, error={"code": "geometry_error",
                                       "message": str(e),
                                       "detail": traceback.format_exc(limit=5)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
