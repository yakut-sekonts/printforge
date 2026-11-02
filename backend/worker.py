"""PrintForge: геометрический worker (M2).

Отдельный процесс. Протокол: JSON Lines в stdout, запросы из stdin,
диагностика — stderr. Сетки — бинарным ресурсом (файл + sha256).

Шаблоны (точная BRep через build123d/OCP):
- plate_with_holes: пластина L×W×H, 4 сквозных отверстия ØD, отступ O (AC-01).
- washer: шайба OD×ID×H (AC-02).
- bracket_l: L-кронштейн из двух блоков с общим началом координат (AC-04).
- case_with_lid: корпус со стенкой/дном + крышка с бортиком и зазором (AC-03).

Операции поверх шаблона: fillet/chamfer (выбор ребра мягкой геометрической
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


def _apply_edge_feature(part, operation):
    kind = operation.get("op")
    if kind == "fillet":
        parameter = "radius"
        parameter_label = "Радиус скругления"
        error_code = "fillet_failed"
        action = lambda shape, value, edge: shape.fillet(radius=value, edge_list=[edge])
    elif kind == "chamfer":
        parameter = "distance"
        parameter_label = "Размер фаски"
        error_code = "chamfer_failed"
        action = lambda shape, value, edge: shape.chamfer(
            length=value, length2=None, edge_list=[edge])
    else:
        raise GeometryError("unknown_op", f"Неизвестная операция ребра: {kind}")

    try:
        value = float(operation[parameter])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryError("bad_params", f"{parameter_label} должен быть числом больше нуля.") from exc
    if not math.isfinite(value) or value <= 0:
        raise GeometryError("bad_params", f"{parameter_label} должен быть числом больше нуля.")

    edge = match_edge(part, operation["edge_ref"])
    try:
        result = action(part, value, edge)
    except Exception as exc:  # noqa: BLE001
        feature = "Радиус" if kind == "fillet" else "Размер фаски"
        raise GeometryError(
            error_code,
            f"{feature} {value:g} мм слишком велик для выбранного ребра. "
            "Уменьшите значение или выберите другое ребро.",
            detail=str(exc).split("\n")[0]) from exc
    if not result.is_valid or not result.solids():
        raise GeometryError(error_code, "Операция создаёт некорректную геометрию.")
    return result


def apply_operations(part, operations):
    for op in operations or []:
        if op.get("op") in ("fillet", "chamfer"):
            part = _apply_edge_feature(part, op)
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

def profile_prism(profile, plane, depth):
    """Призма из простого профиля (CAD-003): rectangle/circle/ring/slot."""
    from build123d import Pos, Plane
    kind = profile.get("kind")
    cx, cy = (profile.get("center") or [0, 0])[:2]
    with_ = None
    if kind == "rectangle":
        from build123d import Box
        w, h = profile["width"], profile["height"]
        prism = Box(w, h, depth)
    elif kind == "circle":
        from build123d import Cylinder
        prism = Cylinder(radius=profile["diameter"] / 2, height=depth)
    elif kind == "ring":
        from build123d import Cylinder
        od, id_ = profile["outer_diameter"], profile["inner_diameter"]
        if id_ >= od:
            raise GeometryError("bad_params",
                                "Внутренний диаметр кольца должен быть меньше наружного.")
        prism = Cylinder(radius=od / 2, height=depth) - \
            Cylinder(radius=id_ / 2, height=depth * 1.2)
    elif kind == "slot":
        from build123d import Box, Cylinder
        w, ln = profile["width"], profile["length"]
        if ln <= w:
            raise GeometryError("bad_params",
                                "Длина паза должна быть больше его ширины.")
        r = w / 2
        prism = Box(ln - w, w, depth) + \
            Pos(-(ln - w) / 2, 0, 0) * Cylinder(radius=r, height=depth) + \
            Pos((ln - w) / 2, 0, 0) * Cylinder(radius=r, height=depth)
    else:
        raise GeometryError("bad_params", f"неизвестный профиль: {kind}")
    base = Pos(cx, cy, 0)
    if plane == "XZ":
        from build123d import Rotation
        return base * Rotation(90, 0, 0) * prism
    if plane == "YZ":
        from build123d import Rotation
        return base * Rotation(0, 90, 0) * prism
    return base * prism


def _positive_profile_value(profile, name, label):
    try:
        value = float(profile[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryError("bad_params", f"{label} должен быть числом больше нуля.") from exc
    if not math.isfinite(value) or value <= 0:
        raise GeometryError("bad_params", f"{label} должен быть числом больше нуля.")
    return value


def _face_profile_prism(profile, depth):
    from build123d import Align, Box, Cylinder, Pos
    alignment = (Align.CENTER, Align.CENTER, Align.MIN)
    kind = profile.get("kind")
    if kind == "rectangle":
        width = _positive_profile_value(profile, "width", "Ширина профиля")
        height = _positive_profile_value(profile, "height", "Высота профиля")
        return Box(width, height, depth, align=alignment)
    if kind == "circle":
        diameter = _positive_profile_value(profile, "diameter", "Диаметр отверстия")
        return Cylinder(radius=diameter / 2, height=depth, align=alignment)
    if kind == "ring":
        outer = _positive_profile_value(profile, "outer_diameter", "Наружный диаметр")
        inner = _positive_profile_value(profile, "inner_diameter", "Внутренний диаметр")
        if inner >= outer:
            raise GeometryError("bad_params", "Внутренний диаметр кольца должен быть меньше наружного.")
        outer_shape = Cylinder(radius=outer / 2, height=depth, align=alignment)
        inner_shape = Pos(0, 0, -0.01) * Cylinder(
            radius=inner / 2, height=depth + 0.02, align=alignment)
        return outer_shape - inner_shape
    if kind == "slot":
        width = _positive_profile_value(profile, "width", "Ширина паза")
        length = _positive_profile_value(profile, "length", "Длина паза")
        if length <= width:
            raise GeometryError("bad_params", "Длина паза должна быть больше его ширины.")
        straight = length - width
        radius = width / 2
        return (
            Box(straight, width, depth, align=alignment)
            + Pos(-straight / 2, 0, 0) * Cylinder(radius=radius, height=depth, align=alignment)
            + Pos(straight / 2, 0, 0) * Cylinder(radius=radius, height=depth, align=alignment)
        )
    raise GeometryError("bad_params", f"Неизвестный профиль: {kind}")


def _apply_face_feature(target, operation):
    from build123d import Plane
    face_ref = operation.get("face_ref") or {}
    if face_ref.get("kind") != "outer_planar":
        raise GeometryError("reselect_required", "Грань больше не поддерживается. Выберите внешнюю плоскую грань заново.")
    axis = face_ref.get("axis")
    if axis not in ("x", "y", "z"):
        raise GeometryError("bad_params", "Неизвестная ось выбранной грани.")
    side = face_ref.get("side")
    if side not in (-1, 1):
        raise GeometryError("bad_params", "Неизвестная сторона выбранной грани.")
    mode = operation.get("mode")
    if mode not in ("add", "cut"):
        raise GeometryError("bad_params", "Режим элемента должен быть add или cut.")

    bounding_box = target.bounding_box()
    minimum = {"x": bounding_box.min.X, "y": bounding_box.min.Y, "z": bounding_box.min.Z}
    maximum = {"x": bounding_box.max.X, "y": bounding_box.max.Y, "z": bounding_box.max.Z}
    span = maximum[axis] - minimum[axis]
    anchor = face_ref.get("anchor") or [0, 0]
    center = (operation.get("profile") or {}).get("center") or [0, 0]
    if len(anchor) != 2 or len(center) != 2:
        raise GeometryError("bad_params", "Координаты элемента на грани должны содержать U и V.")
    try:
        offsets = [float(anchor[index]) + float(center[index]) for index in range(2)]
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Координаты элемента на грани должны быть числами.") from exc
    if not all(math.isfinite(value) for value in offsets):
        raise GeometryError("bad_params", "Координаты элемента на грани должны быть конечными числами.")

    axis_pairs = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}
    u_axis, v_axis = axis_pairs[axis]
    origin = {
        name: (minimum[name] + maximum[name]) / 2
        for name in ("x", "y", "z")
    }
    origin[u_axis] += offsets[0]
    origin[v_axis] += offsets[1]
    boundary = maximum[axis] if side > 0 else minimum[axis]
    epsilon = 0.01

    depth_value = operation.get("depth")
    if depth_value == "through":
        if mode != "cut":
            raise GeometryError("bad_params", "Сквозная глубина доступна только для выреза.")
        depth = span + 2 * epsilon
    else:
        try:
            depth = float(depth_value)
        except (TypeError, ValueError) as exc:
            raise GeometryError("bad_params", "Глубина должна быть числом больше нуля.") from exc
        if not math.isfinite(depth) or depth <= 0:
            raise GeometryError("bad_params", "Глубина должна быть числом больше нуля.")
        if mode == "cut" and depth >= span - epsilon:
            raise GeometryError(
                "bad_params",
                "Глубина глухого отверстия достигает противоположной стороны. Выберите сквозной вырез.")
        depth += epsilon

    direction = side if mode == "add" else -side
    origin[axis] = boundary - side * epsilon if mode == "add" else boundary + side * epsilon
    unit = {
        "x": (1, 0, 0),
        "y": (0, 1, 0),
        "z": (0, 0, 1),
    }
    normal = tuple(component * direction for component in unit[axis])
    tool = Plane(
        origin=(origin["x"], origin["y"], origin["z"]),
        x_dir=unit[u_axis],
        z_dir=normal,
    ).location * _face_profile_prism(operation.get("profile") or {}, depth)

    initial_volume = target.volume
    result = target + tool if mode == "add" else target - tool
    volume_delta = result.volume - initial_volume
    if mode == "add" and (volume_delta <= 1e-6 or len(result.solids()) != 1):
        raise GeometryError(
            "feature_failed",
            "Профиль не соединяется с выбранной гранью одним телом. Измените размеры или положение.")
    if mode == "cut" and volume_delta >= -1e-6:
        raise GeometryError(
            "feature_failed",
            "Профиль не пересекает выбранную грань. Измените положение или размеры.")
    if not result.is_valid or not result.solids():
        raise GeometryError("feature_failed", "Операция создаёт некорректную геометрию.")
    return result


def _apply_face_dome(target, operation):
    from build123d import Align, Plane, Sphere
    face_ref = operation.get("face_ref") or {}
    if face_ref.get("kind") != "outer_planar":
        raise GeometryError(
            "reselect_required",
            "Грань больше не поддерживается. Выберите внешнюю плоскую грань заново.")
    axis = face_ref.get("axis")
    if axis not in ("x", "y", "z"):
        raise GeometryError("bad_params", "Неизвестная ось выбранной грани.")
    side = face_ref.get("side")
    if side not in (-1, 1):
        raise GeometryError("bad_params", "Неизвестная сторона выбранной грани.")
    mode = operation.get("mode")
    if mode not in ("add", "cut"):
        raise GeometryError("bad_params", "Режим сферического сегмента должен быть add или cut.")

    diameter = _positive_profile_value(
        operation, "diameter", "Диаметр сферического сегмента")
    height = _positive_profile_value(
        operation, "height", "Высота сферического сегмента")
    base_radius = diameter / 2
    if height > base_radius + 1e-9:
        raise GeometryError(
            "bad_params",
            "Высота выпуклости или вмятины не должна превышать половину диаметра.")

    bounding_box = target.bounding_box()
    minimum = {"x": bounding_box.min.X, "y": bounding_box.min.Y, "z": bounding_box.min.Z}
    maximum = {"x": bounding_box.max.X, "y": bounding_box.max.Y, "z": bounding_box.max.Z}
    span = maximum[axis] - minimum[axis]
    if mode == "cut" and height >= span - 0.01:
        raise GeometryError(
            "bad_params",
            "Глубина вмятины достигает противоположной стороны. Уменьшите высоту.")

    anchor = face_ref.get("anchor") or [0, 0]
    center = operation.get("center") or [0, 0]
    if len(anchor) != 2 or len(center) != 2:
        raise GeometryError("bad_params", "Координаты сегмента должны содержать U и V.")
    try:
        offsets = [float(anchor[index]) + float(center[index]) for index in range(2)]
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Координаты сегмента должны быть числами.") from exc
    if not all(math.isfinite(value) for value in offsets):
        raise GeometryError("bad_params", "Координаты сегмента должны быть конечными числами.")

    axis_pairs = {"x": ("y", "z"), "y": ("x", "z"), "z": ("x", "y")}
    u_axis, v_axis = axis_pairs[axis]
    origin = {name: (minimum[name] + maximum[name]) / 2 for name in ("x", "y", "z")}
    origin[u_axis] += offsets[0]
    origin[v_axis] += offsets[1]
    origin[axis] = maximum[axis] if side > 0 else minimum[axis]
    for local_axis in (u_axis, v_axis):
        coordinate = origin[local_axis]
        if (coordinate - base_radius < minimum[local_axis] - 1e-6 or
                coordinate + base_radius > maximum[local_axis] + 1e-6):
            raise GeometryError(
                "dome_failed",
                "Основание сферического сегмента выходит за границы детали. Уменьшите диаметр или измените положение.")

    sphere_radius = (base_radius ** 2 + height ** 2) / (2 * height)
    if not math.isfinite(sphere_radius):
        raise GeometryError("bad_params", "Размеры сферического сегмента слишком велики.")
    angle_ratio = max(-1.0, min(1.0, (sphere_radius - height) / sphere_radius))
    base_angle = math.degrees(math.asin(angle_ratio))
    cap = Sphere(
        sphere_radius,
        arc_size1=base_angle,
        arc_size2=90,
        align=(Align.CENTER, Align.CENTER, Align.MIN),
    )
    direction = side if mode == "add" else -side
    unit = {"x": (1, 0, 0), "y": (0, 1, 0), "z": (0, 0, 1)}
    normal = tuple(component * direction for component in unit[axis])
    tool = Plane(
        origin=(origin["x"], origin["y"], origin["z"]),
        x_dir=unit[u_axis],
        z_dir=normal,
    ).location * cap

    initial_volume = target.volume
    result = target + tool if mode == "add" else target - tool
    actual_delta = abs(result.volume - initial_volume)
    expected_delta = cap.volume
    if (len(result.solids()) != len(target.solids()) or
            abs(actual_delta - expected_delta) > max(1e-4, expected_delta * 1e-6)):
        raise GeometryError(
            "dome_failed",
            "Основание сферического сегмента не полностью лежит на выбранной грани. Измените размер или положение.")
    if not result.is_valid or not result.solids():
        raise GeometryError("dome_failed", "Операция создаёт некорректную геометрию.")
    return result


def _flat_sheet_feature_data(operation, bend_axis):
    face_ref = operation.get("face_ref") or {}
    if (operation.get("op") != "face_feature" or
            operation.get("mode") != "cut" or operation.get("depth") != "through" or
            face_ref.get("kind") != "outer_planar" or
            face_ref.get("axis") != "z" or face_ref.get("side") != 1):
        raise GeometryError(
            "bend_failed",
            "Перед изгибом поддерживаются только сквозные вырезы на верхней грани пластины.")

    anchor = face_ref.get("anchor") or [0, 0]
    profile = operation.get("profile") or {}
    center = profile.get("center") or [0, 0]
    if len(anchor) != 2 or len(center) != 2:
        raise GeometryError(
            "bend_failed", "Координаты выреза должны содержать U и V.")
    try:
        center_x = float(anchor[0]) + float(center[0])
        center_y = float(anchor[1]) + float(center[1])
    except (TypeError, ValueError) as exc:
        raise GeometryError(
            "bend_failed", "Координаты выреза должны быть числами.") from exc
    if not all(math.isfinite(value) for value in (center_x, center_y)):
        raise GeometryError(
            "bend_failed", "Координаты выреза должны быть конечными числами.")

    kind = profile.get("kind")
    if kind == "rectangle":
        half_x = _positive_profile_value(profile, "width", "Ширина профиля") / 2
        half_y = _positive_profile_value(profile, "height", "Высота профиля") / 2
    elif kind == "circle":
        radius = _positive_profile_value(profile, "diameter", "Диаметр отверстия") / 2
        half_x = half_y = radius
    elif kind == "ring":
        outer = _positive_profile_value(profile, "outer_diameter", "Наружный диаметр")
        inner = _positive_profile_value(profile, "inner_diameter", "Внутренний диаметр")
        if inner >= outer:
            raise GeometryError(
                "bad_params", "Внутренний диаметр кольца должен быть меньше наружного.")
        half_x = half_y = outer / 2
    elif kind == "slot":
        width = _positive_profile_value(profile, "width", "Ширина паза")
        length = _positive_profile_value(profile, "length", "Длина паза")
        if length <= width:
            raise GeometryError("bad_params", "Длина паза должна быть больше его ширины.")
        half_x = length / 2
        half_y = width / 2
    else:
        raise GeometryError(
            "bend_failed", "Профиль выреза не поддерживается переносом через изгиб.")

    return {
        "profile": profile,
        "kind": kind,
        "center_x": center_x,
        "center_y": center_y,
        "developed_center": center_x if bend_axis == "x" else center_y,
        "developed_extent": half_x if bend_axis == "x" else half_y,
        "station_width": 2 * (half_y if bend_axis == "x" else half_x),
        "canonical_width": center_y if bend_axis == "x" else -center_x,
    }


def _apply_sheet_bends(part_info, operations, flat_features=None):
    from build123d import (Align, Box, Cylinder, Edge, Plane, Pos, Rectangle,
                          Rotation, Side, Solid, Wire)
    from build123d import make_brake_formed

    if part_info.get("template") != "plate_with_holes":
        raise GeometryError(
            "bend_failed",
            "Точный изгиб доступен только для пластины.")
    if not operations or len(operations) > 4:
        raise GeometryError(
            "bend_failed",
            "Поддерживаются от одной до четырёх последовательных линий изгиба.")

    params = part_info["params"]
    thickness = params["height"]
    bend_axis = operations[0].get("bend_axis")
    if bend_axis not in ("x", "y"):
        raise GeometryError("bad_params", "Ось изгиба должна быть X или Y.")
    length = params["length"] if bend_axis == "x" else params["width"]
    station_width = params["width"] if bend_axis == "x" else params["length"]
    bends = []
    for operation in operations:
        face_ref = operation.get("face_ref") or {}
        if (face_ref.get("kind") != "outer_planar" or
                face_ref.get("axis") != "z" or face_ref.get("side") != 1):
            raise GeometryError(
                "reselect_required",
                "Для следующего изгиба выберите верхнюю плоскую грань неподвижного участка.")
        if operation.get("bend_axis") != bend_axis:
            raise GeometryError(
                "bend_failed",
                "Последовательные изгибы должны быть параллельны и использовать одну ось.")
        try:
            position = float(operation.get("position", 0))
            angle = float(operation["angle"])
            inside_radius = float(operation["inside_radius"])
            moving_side = int(operation.get("moving_side", 1))
            direction = int(operation.get("direction", 1))
        except (KeyError, TypeError, ValueError) as exc:
            raise GeometryError("bad_params", "Параметры изгиба повреждены.") from exc
        if not all(math.isfinite(value) for value in (position, angle, inside_radius)):
            raise GeometryError("bad_params", "Параметры изгиба должны быть конечными числами.")
        if angle < 5 or angle > 170:
            raise GeometryError("bad_params", "Угол изгиба должен быть от 5° до 170°.")
        if inside_radius <= 0:
            raise GeometryError("bad_params", "Внутренний радиус изгиба должен быть больше нуля.")
        if moving_side not in (-1, 1) or direction not in (-1, 1):
            raise GeometryError("bad_params", "Направление и подвижная сторона изгиба повреждены.")
        developed_position = position + length / 2
        angle_radians = math.radians(angle)
        bend_allowance = (inside_radius + thickness / 2) * angle_radians
        zone_start = developed_position - bend_allowance / 2
        zone_end = developed_position + bend_allowance / 2
        if zone_start <= 0.01 or zone_end >= length - 0.01:
            raise GeometryError(
                "bend_failed",
                "Линия изгиба слишком близко к краю для заданных угла, радиуса и толщины.")
        bends.append({
            "position": position,
            "angle": angle_radians,
            "delta": direction * angle_radians,
            "inside_radius": inside_radius,
            "path_radius": inside_radius if direction > 0 else inside_radius + thickness,
            "moving_side": moving_side,
            "direction": direction,
            "zone_start": zone_start,
            "zone_end": zone_end,
        })

    bends.sort(key=lambda bend: bend["position"])
    for left, right in zip(bends, bends[1:]):
        if left["zone_end"] >= right["zone_start"] - 0.01:
            raise GeometryError(
                "bend_failed",
                "Зоны последовательных изгибов пересекаются. Разнесите линии или уменьшите радиус.")
    positive_side_started = False
    for bend in bends:
        if bend["moving_side"] > 0:
            positive_side_started = True
        elif positive_side_started:
            raise GeometryError(
                "bend_failed",
                "Левая группа линий должна сгибать −ось, правая — +ось.")

    def advance(point, tangent_angle, delta, radius):
        absolute_delta = abs(delta)
        local_x = radius * math.sin(absolute_delta)
        local_z = math.copysign(radius * (1 - math.cos(absolute_delta)), delta)
        cosine = math.cos(tangent_angle)
        sine = math.sin(tangent_angle)
        return (
            point[0] + local_x * cosine - local_z * sine,
            point[1] + local_x * sine + local_z * cosine,
        )

    tangent_angle = -sum(
        bend["delta"] for bend in bends if bend["moving_side"] < 0)
    point = (0.0, 0.0)
    developed_cursor = 0.0
    edges = []
    path_sections = []
    straight_segments = []
    for bend in bends:
        straight_end = bend["zone_start"]
        straight_length = straight_end - developed_cursor
        tangent = (math.cos(tangent_angle), math.sin(tangent_angle))
        line_end = (
            point[0] + straight_length * tangent[0],
            point[1] + straight_length * tangent[1],
        )
        edges.append(Edge.make_line(point, line_end))
        straight_segments.append({
            "start": developed_cursor,
            "end": straight_end,
            "point": point,
            "angle": tangent_angle,
        })
        path_sections.append({
            "kind": "straight",
            "start": developed_cursor,
            "end": straight_end,
            "point": point,
            "angle": tangent_angle,
        })
        point = line_end
        arc_start = point
        arc_start_angle = tangent_angle
        arc_end = advance(point, tangent_angle, bend["delta"], bend["path_radius"])
        edges.append(Edge.make_tangent_arc(point, tangent, arc_end))
        path_sections.append({
            "kind": "arc",
            "start": bend["zone_start"],
            "end": bend["zone_end"],
            "point": arc_start,
            "angle": arc_start_angle,
            "delta": bend["delta"],
            "radius": bend["path_radius"],
        })
        point = arc_end
        tangent_angle += bend["delta"]
        developed_cursor = bend["zone_end"]

    final_length = length - developed_cursor
    tangent = (math.cos(tangent_angle), math.sin(tangent_angle))
    final_point = (
        point[0] + final_length * tangent[0],
        point[1] + final_length * tangent[1],
    )
    edges.append(Edge.make_line(point, final_point))
    straight_segments.append({
        "start": developed_cursor,
        "end": length,
        "point": point,
        "angle": tangent_angle,
    })
    path_sections.append({
        "kind": "straight",
        "start": developed_cursor,
        "end": length,
        "point": point,
        "angle": tangent_angle,
    })

    negative_bends = [bend for bend in bends if bend["moving_side"] < 0]
    positive_bends = [bend for bend in bends if bend["moving_side"] > 0]
    if not negative_bends:
        anchor_developed = 0.0
    elif not positive_bends:
        anchor_developed = length
    else:
        anchor_developed = (
            negative_bends[-1]["zone_end"] + positive_bends[0]["zone_start"]
        ) / 2

    def point_on_straight(developed):
        for segment in straight_segments:
            if segment["start"] - 1e-9 <= developed <= segment["end"] + 1e-9:
                distance = developed - segment["start"]
                angle = segment["angle"]
                return (
                    segment["point"][0] + distance * math.cos(angle),
                    segment["point"][1] + distance * math.sin(angle),
                    angle,
                )
        raise GeometryError("bend_failed", "Не удалось сопоставить точку развёртки после изгиба.")

    def point_on_path(developed, section):
        if section["kind"] == "straight":
            distance = developed - section["start"]
            angle = section["angle"]
            return (
                section["point"][0] + distance * math.cos(angle),
                section["point"][1] + distance * math.sin(angle),
                angle,
            )
        fraction = ((developed - section["start"]) /
                    (section["end"] - section["start"]))
        partial_delta = section["delta"] * fraction
        arc_point = advance(
            section["point"], section["angle"], partial_delta, section["radius"])
        return arc_point[0], arc_point[1], section["angle"] + partial_delta

    def state_on_path(developed):
        for section in path_sections:
            if section["start"] - 1e-9 <= developed <= section["end"] + 1e-9:
                return point_on_path(developed, section)
        raise GeometryError(
            "bend_failed", "Не удалось сопоставить границу выреза с bend-path.")

    anchor_x, anchor_z, anchor_angle = point_on_straight(anchor_developed)
    if abs(anchor_angle) > 1e-7:
        raise GeometryError(
            "bend_failed",
            "Неподвижные участки последовательных изгибов конфликтуют.")
    shift_x = -length / 2 + anchor_developed - anchor_x
    shift_z = -anchor_z
    try:
        bend_line = Pos(shift_x, shift_z, 0) * Wire(edges)
        raw = make_brake_formed(
            thickness, station_width, bend_line, side=Side.RIGHT)
        bent = Pos(0, -station_width / 2, thickness) * Rotation(90, 0, 0) * raw
    except Exception as exc:  # noqa: BLE001
        raise GeometryError(
            "bend_failed",
            "Не удалось построить точный изгиб. Измените угол, радиус или положение.",
            detail=str(exc).split("\n")[0]) from exc

    trim_size = 4 * max(length, station_width, thickness) + 100

    def trim_to_developed_interval(feature_tool, developed_start, developed_end):
        for boundary, keep_direction in (
                (developed_start, 1), (developed_end, -1)):
            path_x, path_z, path_angle = state_on_path(boundary)
            tangent = (
                keep_direction * math.cos(path_angle),
                0,
                keep_direction * math.sin(path_angle),
            )
            trim_origin = (
                path_x + shift_x,
                0,
                thickness + path_z + shift_z,
            )
            trim_box = Plane(
                origin=trim_origin,
                x_dir=tangent,
                z_dir=(0, 1, 0),
            ).location * Box(
                trim_size, trim_size, trim_size,
                align=(Align.MIN, Align.CENTER, Align.CENTER),
            )
            feature_tool &= trim_box
        return feature_tool

    hole_diameter = params.get("hole_diameter", 0)
    if hole_diameter > 0:
        hole_radius = hole_diameter / 2
        hole_offset = params["hole_offset"]
        half_x = params["length"] / 2 - hole_offset
        half_y = params["width"] / 2 - hole_offset
        hole_centers = [
            (-half_x, -half_y), (half_x, -half_y),
            (-half_x, half_y), (half_x, half_y),
        ]
        for original_x, original_y in hole_centers:
            original_length = original_x if bend_axis == "x" else original_y
            developed_position = original_length + length / 2
            for bend in bends:
                if (developed_position + hole_radius >= bend["zone_start"] and
                        developed_position - hole_radius <= bend["zone_end"]):
                    raise GeometryError(
                        "bend_failed",
                        "Зона изгиба пересекает отверстие. Сместите линию изгиба или измените отверстия.")
            canonical_width = original_y if bend_axis == "x" else -original_x
            inner_x, inner_z, local_angle = point_on_straight(developed_position)
            inner_x += shift_x
            inner_z += shift_z
            normal_x = math.sin(local_angle)
            normal_z = -math.cos(local_angle)
            hole_origin = (
                inner_x + thickness / 2 * normal_x,
                canonical_width,
                thickness + inner_z + thickness / 2 * normal_z,
            )
            hole_normal = (normal_x, 0, normal_z)
            hole_tool = Plane(origin=hole_origin, z_dir=hole_normal).location * Cylinder(
                radius=hole_radius,
                height=thickness + 2,
                align=(Align.CENTER, Align.CENTER, Align.CENTER),
            )
            bent -= hole_tool

    for operation in flat_features or []:
        feature = _flat_sheet_feature_data(operation, bend_axis)
        developed_position = feature["developed_center"] + length / 2
        developed_extent = feature["developed_extent"]
        crossing_bends = [bend for bend in bends
                          if developed_position + developed_extent >= bend["zone_start"] and
                          developed_position - developed_extent <= bend["zone_end"]]
        if crossing_bends:
            if feature["kind"] not in ("rectangle", "circle", "ring", "slot"):
                raise GeometryError(
                    "bend_failed",
                    "Криволинейную bend-зону пока могут пересекать прямоугольный, "
                    "круглый, кольцевой through-вырез или паз.")
            if feature["kind"] in ("circle", "ring", "slot") and len(crossing_bends) > 1:
                raise GeometryError(
                    "bend_failed",
                    "Круглый, кольцевой through-вырез или паз пока может пересекать только одну "
                    "криволинейную bend-зону.")
            developed_start = max(0.0, developed_position - developed_extent)
            developed_end = min(length, developed_position + developed_extent)
            profiled_result = None
            try:
                if feature["kind"] == "rectangle":
                    raw_feature = make_brake_formed(
                        thickness, feature["station_width"], bend_line,
                        side=Side.RIGHT)
                    feature_tools = [
                        Pos(
                            0,
                            feature["canonical_width"] - feature["station_width"] / 2,
                            thickness,
                        )
                        * Rotation(90, 0, 0)
                        * raw_feature
                    ]
                else:
                    sample_count = 64
                    endpoint_width = 1e-3

                    def sampled_profile(profile_start, profile_end, width_at,
                                        exact_profile_area, profile_breaks=None):
                        profile_breaks = profile_breaks or []
                        stations = {
                            profile_start, profile_end,
                            *profile_breaks,
                            *(section["start"] for section in path_sections
                              if profile_start < section["start"] < profile_end),
                            *(section["end"] for section in path_sections
                              if profile_start < section["end"] < profile_end),
                            *(profile_start +
                              (profile_end - profile_start) * index / sample_count
                              for index in range(sample_count + 1)),
                        }
                        ordered_stations = sorted({
                            round(station, 12) for station in stations})
                        full_widths = [
                            max(endpoint_width, width_at(station))
                            for station in ordered_stations
                        ]
                        sampled_area = sum(
                            (full_widths[index] + full_widths[index + 1]) / 2
                            * (ordered_stations[index + 1] - ordered_stations[index])
                            for index in range(len(ordered_stations) - 1)
                        )
                        if sampled_area <= 1e-9:
                            raise GeometryError(
                                "bend_failed", "Площадь профильного выреза равна нулю.")
                        return {
                            "stations": ordered_stations,
                            "widths": full_widths,
                            "area_scale": exact_profile_area / sampled_area,
                        }

                    def circle_sample(radius):
                        profile_start = max(0.0, developed_position - radius)
                        profile_end = min(length, developed_position + radius)

                        def circle_width(station):
                            relative = (station - developed_position) / radius
                            return 2 * radius * math.sqrt(
                                max(0.0, 1 - relative**2))

                        return sampled_profile(
                            profile_start,
                            profile_end,
                            circle_width,
                            math.pi * radius**2,
                        )

                    def loft_profile(sample, width_scale=1.0,
                                     section_height=thickness + 2):
                        section_wires = []
                        for station, width in zip(
                                sample["stations"], sample["widths"]):
                            path_x, path_z, path_angle = state_on_path(station)
                            outward = (-math.sin(path_angle), 0, math.cos(path_angle))
                            section_center = (
                                path_x + shift_x - thickness / 2 * outward[0],
                                feature["canonical_width"],
                                thickness + path_z + shift_z -
                                thickness / 2 * outward[2],
                            )
                            section_plane = Plane(
                                origin=section_center,
                                x_dir=(0, 1, 0),
                                z_dir=(math.cos(path_angle), 0, math.sin(path_angle)),
                            )
                            section_wires.append(
                                section_plane.location
                                * Rectangle(
                                    width * sample["area_scale"] * width_scale,
                                    section_height,
                                ).wires()[0]
                            )
                        return Solid.make_loft(section_wires, ruled=True)

                    if feature["kind"] == "circle":
                        radius = feature["developed_extent"]
                        exact_area = math.pi * radius**2
                        outer_sample = circle_sample(radius)

                        def profile_tool(width_scale):
                            return loft_profile(outer_sample, width_scale)
                    elif feature["kind"] == "ring":
                        outer_radius = feature["developed_extent"]
                        inner_radius = _positive_profile_value(
                            feature["profile"], "inner_diameter",
                            "Внутренний диаметр") / 2
                        exact_area = math.pi * (outer_radius**2 - inner_radius**2)
                        outer_sample = circle_sample(outer_radius)
                        inner_sample = circle_sample(inner_radius)

                        def profile_tool(width_scale):
                            outer_tool = loft_profile(outer_sample, width_scale)
                            inner_tool = loft_profile(
                                inner_sample,
                                width_scale,
                                section_height=thickness + 2.04,
                            )
                            return outer_tool - inner_tool
                    else:
                        profile_breaks = []
                        if bend_axis == "x":
                            slot_length = 2 * feature["developed_extent"]
                            slot_width = feature["station_width"]
                            cap_radius = slot_width / 2
                            straight_half = (slot_length - slot_width) / 2
                            profile_breaks = [
                                developed_position - straight_half,
                                developed_position + straight_half,
                            ]

                            def profile_width(station):
                                cap_offset = max(
                                    0.0,
                                    abs(station - developed_position) - straight_half,
                                )
                                return 2 * math.sqrt(
                                    max(0.0, cap_radius**2 - cap_offset**2))
                        else:
                            slot_width = 2 * feature["developed_extent"]
                            slot_length = feature["station_width"]
                            cap_radius = slot_width / 2
                            straight_length = slot_length - slot_width

                            def profile_width(station):
                                offset = station - developed_position
                                return straight_length + 2 * math.sqrt(
                                    max(0.0, cap_radius**2 - offset**2))
                        exact_area = (
                            (slot_length - slot_width) * slot_width
                            + math.pi * (slot_width / 2)**2
                        )
                        slot_sample = sampled_profile(
                            developed_start,
                            developed_end,
                            profile_width,
                            exact_area,
                            profile_breaks,
                        )

                        def profile_tool(width_scale):
                            return loft_profile(slot_sample, width_scale)

                    feature_tool = profile_tool(1.0)
                    profiled_result = bent - feature_tool
                    expected_removed_volume = exact_area * thickness
                    removed_volume = bent.volume - profiled_result.volume
                    if removed_volume <= 1e-6:
                        raise GeometryError(
                            "bend_failed",
                            "Профильный вырез не пересекает согнутую пластину.")
                    correction = expected_removed_volume / removed_volume
                    if abs(correction - 1) > 1e-7:
                        feature_tool = profile_tool(correction)
                        profiled_result = bent - feature_tool

                if feature["kind"] == "rectangle":
                    feature_tools = [
                        trim_to_developed_interval(
                            feature_tool, developed_start, developed_end)
                        for feature_tool in feature_tools
                    ]
            except GeometryError:
                raise
            except Exception as exc:  # noqa: BLE001
                raise GeometryError(
                    "bend_failed",
                    "Не удалось перенести вырез через bend-зону.",
                    detail=str(exc).split("\n")[0]) from exc
            previous_volume = bent.volume
            if profiled_result is not None:
                bent = profiled_result
            else:
                for feature_tool in feature_tools:
                    bent -= feature_tool
            if previous_volume - bent.volume <= 1e-6:
                raise GeometryError(
                    "bend_failed",
                    "Вырез не пересекает согнутую пластину.")
            continue

        inner_x, inner_z, local_angle = point_on_straight(developed_position)
        inner_x += shift_x
        inner_z += shift_z
        inward_x = math.sin(local_angle)
        inward_z = -math.cos(local_angle)
        feature_origin = (
            inner_x + thickness / 2 * inward_x,
            feature["canonical_width"],
            thickness + inner_z + thickness / 2 * inward_z,
        )
        tangent = (math.cos(local_angle), 0, math.sin(local_angle))
        outward = (-math.sin(local_angle), 0, math.cos(local_angle))
        profile_x = tangent if bend_axis == "x" else (0, -1, 0)
        tool_depth = thickness + 2
        centered_profile = Pos(0, 0, -tool_depth / 2) * _face_profile_prism(
            feature["profile"], tool_depth)
        feature_tool = Plane(
            origin=feature_origin,
            x_dir=profile_x,
            z_dir=outward,
        ).location * centered_profile
        previous_volume = bent.volume
        bent -= feature_tool
        if previous_volume - bent.volume <= 1e-6:
            raise GeometryError(
                "bend_failed",
                "Не удалось перенести пользовательский вырез на согнутую пластину.")

    if bend_axis == "y":
        bent = Rotation(0, 0, 90) * bent

    initial = part_info["shape"]
    volume_tolerance = max(1e-4, initial.volume * 1e-7)
    if (not bent.is_valid or len(bent.solids()) != len(initial.solids()) or
            abs(bent.volume - initial.volume) > volume_tolerance):
        raise GeometryError(
            "bend_failed",
            "Изгиб создаёт самопересечение или меняет объём. Уменьшите угол или радиус.")
    return bent


def _rotate_about(shape, center, angle_deg):
    """Поворот вокруг оси Z через точку center."""
    from build123d import Pos, Rotation
    cx, cy, cz = center
    return Pos(cx, cy, cz) * Rotation(0, 0, angle_deg) * Pos(-cx, -cy, -cz) * shape


def apply_part_operations(parts, operations):
    """Операции над деталями документа v3. parts: {part_id: {"shape": Shape,
    "name": str}}. Возвращает изменённый словарь."""
    from build123d import Compound, Pos
    from build123d import Plane
    for operation_index, op in enumerate(operations or []):
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
        elif kind in ("fillet", "chamfer"):
            if pid not in parts:
                raise GeometryError("bad_params", "Деталь для обработки ребра не найдена.")
            parts[pid]["shape"] = _apply_edge_feature(parts[pid]["shape"], op)
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
        elif kind == "profile_extrude":
            prof = op.get("profile") or {}
            plane = op.get("plane", "XY")
            mode = op.get("mode", "add")
            depth = op.get("depth")
            if mode == "cut":
                target = parts[op["target_id"]]["shape"]
                bb = target.bounding_box()
                d = float(depth) if depth not in (None, "through") else \
                    (bb.max.Z - bb.min.Z + 2 * max(1, abs(bb.max.Z), 1))
                z0 = bb.min.Z - 1 if depth == "through" else bb.min.Z
                prism = profile_prism(prof, plane, d) if plane == "XY" else \
                    profile_prism(prof, plane, d)
                if depth == "through" and plane == "XY":
                    from build123d import Pos as _Pos
                    prism = _Pos(0, 0, z0) * prism
                parts[op["target_id"]]["shape"] = target - prism
            else:
                if depth in (None, "through"):
                    raise GeometryError("bad_params",
                                        "Для выдавливания нужна глубина в мм.")
                prism = profile_prism(prof, plane, float(depth))
                new_id = f"part-profile-{len(parts) + 1}"
                parts[new_id] = {"shape": prism,
                                 "name": f"Профиль ({prof.get('kind')})"}
        elif kind == "face_feature":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Деталь для элемента на грани не найдена.")
            parts[target_id]["shape"] = _apply_face_feature(parts[target_id]["shape"], op)
        elif kind == "face_dome":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Деталь для выпуклости или вмятины не найдена.")
            parts[target_id]["shape"] = _apply_face_dome(parts[target_id]["shape"], op)
        elif kind == "sheet_bend":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Деталь для изгиба не найдена.")
            prior_operations = (operations or [])[:operation_index]
            seen_bend = False
            flat_features = []
            bend_operations = []
            for previous in prior_operations:
                previous_target = previous.get("target_id", previous.get("part_id"))
                if previous_target != target_id:
                    raise GeometryError(
                        "bend_failed",
                        "Перед изгибом допустимы только операции той же пластины.")
                if previous.get("op") == "face_feature" and not seen_bend:
                    _flat_sheet_feature_data(previous, op.get("bend_axis"))
                    flat_features.append(previous)
                elif previous.get("op") == "sheet_bend":
                    seen_bend = True
                    bend_operations.append(previous)
                else:
                    raise GeometryError(
                        "bend_failed",
                        "Перед изгибом допустимы сквозные вырезы, затем изгибы должны идти подряд.")
            if any(previous.get("bend_axis") != op.get("bend_axis")
                   for previous in bend_operations):
                raise GeometryError(
                    "bend_failed",
                    "Последовательные изгибы должны быть параллельны и использовать одну ось.")
            bend_operations.append(op)
            parts[target_id]["shape"] = _apply_sheet_bends(
                parts[target_id], bend_operations, flat_features)
        elif kind == "array_circular":
            from build123d import Compound
            n = int(op["count"])
            if n < 2:
                raise GeometryError("bad_params", "В массиве должно быть хотя бы 2 элемента.")
            total = float(op.get("angle", 360))
            center = op.get("center") or [0, 0, 0]
            base = parts[pid]["shape"]
            step = total / n if abs(total - 360) < 1e-9 else total / (n - 1)
            copies = [_rotate_about(base, center, step * i) for i in range(n)]
            parts[pid]["shape"] = Compound(children=copies)
        elif kind == "align":
            base = parts[pid]["shape"]
            bb = base.bounding_box()
            axis = op.get("axis", "x")
            mode = op.get("align", "center")
            value = float(op.get("value", 0))
            ai = {"x": 0, "y": 1, "z": 2}[axis]
            lo = (bb.min.X, bb.min.Y, bb.min.Z)[ai]
            hi = (bb.max.X, bb.max.Y, bb.max.Z)[ai]
            cur = {"center": (lo + hi) / 2, "min": lo, "max": hi}[mode]
            delta = value - cur
            t = [0, 0, 0]
            t[ai] = delta
            from build123d import Pos as _Pos
            parts[pid]["shape"] = _Pos(*t) * base
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
        parts[p["part_id"]] = {
            "shape": shape,
            "name": p.get("name", template),
            "template": template,
            "params": tp,
        }
    parts = apply_part_operations(parts, params.get("operations"))
    compound = Compound(children=[p["shape"] for p in parts.values()])
    extra = {"parts": [{"part_id": pid, "name": p["name"],
                        "volume": p["shape"].volume,
                        "solid_count": len(p["shape"].solids())}
                       for pid, p in parts.items()]}
    # дополнительные данные шаблона (case_volume и т.п.) для одиночной детали
    if len(params.get("parts") or []) == 1:
        p0 = params["parts"][0]
        _, tex = TEMPLATES[p0["template"]][0](
            merged_params(p0["template"], p0.get("params")))
        for k, v in tex.items():
            extra.setdefault(k, v)
    return compound, extra


# ---------- методы ----------

def build_any(params):
    if params.get("parts"):
        return handle_build_v3(params)
    return build_document(params)


def handle_build(params):
    part, extra = build_any(params)
    if "parts" not in extra:
        # одиночный шаблон: синтезируем запись живого тела для списка деталей
        extra["parts"] = [{"part_id": "part-1",
                           "name": (params or {}).get("template",
                                                     "plate_with_holes"),
                           "volume": part.volume,
                           "solid_count": len(part.solids())}]
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


def handle_measure(params):
    """CAD-009: измерения по точной BRep. Указывает источник (brep)."""
    part, _ = build_any(params)
    kind = params.get("type", "bbox")
    if kind == "bbox":
        bb = part.bounding_box()
        return {"source": "brep", "bbox": [bb.min.X, bb.min.Y, bb.min.Z,
                                           bb.max.X, bb.max.Y, bb.max.Z],
                "size": [bb.max.X - bb.min.X, bb.max.Y - bb.min.Y,
                         bb.max.Z - bb.min.Z]}
    if kind == "volume":
        return {"source": "brep", "volume": part.volume,
                "solid_count": len(part.solids())}
    if kind == "face_diameter":
        fi = int(params["face_index"])
        faces = part.faces()
        if fi < 0 or fi >= len(faces):
            raise GeometryError("bad_ref", "Грань не найдена. Выберите грань заново.")
        f = faces[fi]
        if str(f.geom_type).split(".")[-1] != "CYLINDER":
            raise GeometryError(
                "bad_ref", "Выбранная грань не цилиндрическая — диаметр не определён.")
        return {"source": "brep", "diameter": 2 * f.radius}
    if kind == "distance":
        p0, p1 = params["p0"], params["p1"]
        return {"source": "brep", "distance": math.dist(p0, p1)}
    raise GeometryError("bad_params", f"неизвестное измерение: {kind}")


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
    "measure": handle_measure,
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
