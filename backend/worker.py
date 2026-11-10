"""PrintForge: геометрический worker (M2).

Отдельный процесс. Протокол: JSON Lines в stdout, запросы из stdin,
диагностика — stderr. Сетки — бинарным ресурсом (файл + sha256).

Шаблоны и примитивы (точная BRep через build123d/OCP):
- box: прямоугольный параллелепипед L×W×H.
- cylinder: цилиндр ØD×H.
- sphere: сфера ØD, установленная на плоскость Z=0.
- plate_with_holes: пластина L×W×H, 4 сквозных отверстия ØD, отступ O (AC-01).
- washer: шайба OD×ID×H (AC-02).
- bracket_l: L-кронштейн из двух блоков с общим началом координат (AC-04).
- case_with_lid: корпус со стенкой/дном + крышка с бортиком и зазором (AC-03).

Операции поверх шаблона: fillet/chamfer (выбор ребра мягкой геометрической
ссылкой; честная ошибка OCC, без молчаливого подбора другого значения).

Прочее: export_stl/step/3mf, import_step/stl, print_check.
"""
import base64
import copy
import hashlib
import json
import math
import os
import re
import struct
import sys
import tempfile
import traceback
from pathlib import Path

from parameter_expressions import resolve_parts

SCHEMA_VERSION = 1
_session_dir = Path(tempfile.mkdtemp(prefix="printforge-geo-"))


def log(*args):
    print("[worker]", *args, file=sys.stderr, flush=True)


def respond(request_id, ok, **payload):
    out = {"request_id": request_id, "schema_version": SCHEMA_VERSION, "ok": ok}
    out.update(payload)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


from geometry_errors import GeometryError
from interaction_geometry import (
    bind_surface, feature_index_for_face, mate_shape, new_feature_faces, print_placement_checks,
    resolve_feature, sampled_wall_check, surface_reference,
)


# ---------- шаблоны ----------

def _resize_body(shape, operation):
    from build123d import Matrix, Pos

    size = operation.get("size")
    anchor = operation.get("anchor")
    if (not isinstance(size, list) or len(size) != 3 or
            any(isinstance(value, bool) or not isinstance(value, (int, float)) or
                not math.isfinite(value) or value <= 0 for value in size)):
        raise GeometryError("bad_params", "Укажите три конечных размера больше нуля в миллиметрах.")
    if (not isinstance(anchor, list) or len(anchor) != 3 or
            any(isinstance(value, bool) or value not in (-1, 1) for value in anchor)):
        raise GeometryError("bad_params", "Неподвижный угол должен содержать три направления -1 или 1.")
    bounds = shape.bounding_box()
    spans = [bounds.size.X, bounds.size.Y, bounds.size.Z]
    if any(not math.isfinite(value) or value <= 1e-7 for value in spans):
        raise GeometryError("bad_params", "Изменение размеров доступно только объёмным телам.")
    factors = [value / span for value, span in zip(size, spans)]
    fixed = [getattr(bounds.min if side < 0 else bounds.max, axis)
             for side, axis in zip(anchor, ("X", "Y", "Z"))]
    try:
        if max(factors) - min(factors) < 1e-10:
            resized = Pos(*[value * (1 - factors[0]) for value in fixed]) * shape.scale(factors[0])
        else:
            matrix = [[factors[row] if row == column else 0 for column in range(4)]
                      for row in range(3)]
            for row in range(3):
                matrix[row][3] = fixed[row] * (1 - factors[row])
            matrix.append([0, 0, 0, 1])
            resized = shape.transform_geometry(Matrix(matrix))
        if not resized.is_valid or not resized.solids() or resized.volume <= 0:
            raise ValueError("Invalid resized solid")
        return resized
    except Exception as exc:
        raise GeometryError("resize_failed", "Не удалось изменить форму. Исходная модель сохранена.", str(exc)) from exc


def _rebind_design_reference(old_shape, new_shape, operation):
    updated = copy.deepcopy(operation)
    before, after = old_shape.bounding_box(), new_shape.bounding_box()

    def predicted(point):
        return [getattr(after.min, axis) +
                (point[index] - getattr(before.min, axis)) *
                getattr(after.size, axis) / max(1e-9, getattr(before.size, axis))
                for index, axis in enumerate(("X", "Y", "Z"))]

    if operation["op"] in ("fillet", "chamfer"):
        edge = match_edge(old_shape, operation["edge_ref"])
        signature = edge_signature(edge, 0)
        midpoint = signature["midpoint"]
        boundary_axes = sum(min(abs(midpoint[index] - getattr(before.min, axis)),
                                abs(midpoint[index] - getattr(before.max, axis))) < 1e-4
                            for index, axis in enumerate(("X", "Y", "Z")))
        if signature["kind"] != "LINE" or boundary_axes < 2:
            raise GeometryError("preserve_unsupported", "Сохранение элементов пока поддерживает скругления прямых внешних рёбер. Используйте масштабирование либо измените исходную форму.")
        expected = predicted(midpoint)
        candidates = sorted((math.dist(candidate["midpoint"], expected), index, candidate)
                            for index, candidate in enumerate(list_edges(new_shape))
                            if candidate["kind"] == signature["kind"])
        if not candidates or (len(candidates) > 1 and abs(candidates[1][0] - candidates[0][0]) < 1e-6):
            raise GeometryError("reselect_required", "Не удалось однозначно сохранить выбранное ребро при изменении габаритов.")
        updated["edge_ref"] = candidates[0][2]
    elif operation["op"] == "face_offset":
        _, _, old_face = _match_offset_face(old_shape, operation["face_ref"])
        normal = list(old_face.normal_at())
        dominant = max(range(3), key=lambda axis: abs(normal[axis]))
        axis_name = ("X", "Y", "Z")[dominant]
        center = list(old_face.center())
        boundary = getattr(before.max if normal[dominant] > 0 else before.min, axis_name)
        if abs(normal[dominant]) < 0.999 or abs(center[dominant] - boundary) > 1e-4:
            raise GeometryError("preserve_unsupported", "Сохранение элементов после смещения внутренней или наклонной грани пока недоступно.")
        expected = predicted(operation["face_ref"]["center"])
        candidates = []
        for solid_index, solid in enumerate(new_shape.solids()):
            for face in solid.faces():
                reference = face_offset_reference(face, solid_index)
                if reference and sum(value * other for value, other in zip(reference["normal"], normal)) > 1 - 1e-7:
                    candidates.append((math.dist(reference["center"], expected), reference))
        candidates.sort(key=lambda candidate: candidate[0])
        if not candidates or (len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 1e-6):
            raise GeometryError("reselect_required", "Не удалось однозначно сохранить плоскую грань.")
        updated["face_ref"] = candidates[0][1]
    return updated


def _resize_parametric(part, operation, part_id):
    design = part.get("_design")
    if not design:
        raise GeometryError("preserve_unsupported", "У этого тела нет поддерживаемой параметрической истории. Масштабирование всего тела доступно отдельно.")
    size, anchor = operation.get("size"), operation.get("anchor")
    _resize_body(part["shape"], operation)
    bounds = part["shape"].bounding_box()
    spans = [bounds.size.X, bounds.size.Y, bounds.size.Z]
    params = copy.deepcopy(design["params"])
    template = design["template"]
    if template in ("box", "plate_with_holes"):
        for index, name in enumerate(("length", "width", "height")):
            params[name] += size[index] - spans[index]
    elif template in ("cylinder", "washer"):
        if abs(size[0] - size[1]) > 1e-4:
            raise GeometryError("preserve_unsupported", "Для сохранения круглой формы размеры X и Y должны совпадать. Для эллипса выберите масштабирование.")
        params["diameter" if template == "cylinder" else "outer_diameter"] += size[0] - spans[0]
        params["height"] += size[2] - spans[2]
    elif template == "sphere":
        if max(size) - min(size) > 1e-4:
            raise GeometryError("preserve_unsupported", "У сферы размеры X, Y и Z должны совпадать. Для эллипсоида выберите масштабирование.")
        params["diameter"] += size[0] - spans[0]
    else:
        raise GeometryError("preserve_unsupported", "Для этой заготовки сохранение элементов пока недоступно.")
    original, _ = TEMPLATES[template][0](design["params"])
    resized, _ = TEMPLATES[template][0](params)
    rebound = []
    resized_features = []
    for previous in design["operations"]:
        updated = _rebind_design_reference(original, resized, previous)
        old_candidate, new_candidate = copy.deepcopy(previous), copy.deepcopy(updated)
        if previous["op"] == "face_feature":
            old_candidate = resolve_feature(previous, original, design["operations"], previous.get("_history_index", 0))
            new_candidate = resolve_feature(updated, resized, design["operations"], previous.get("_history_index", 0))
            old_candidate.pop("dimension_bindings", None)
            new_candidate.pop("dimension_bindings", None)
        original = apply_part_operations({part_id: {"shape": original}}, [old_candidate])[part_id]["shape"]
        rebuilt = apply_part_operations({part_id: {"shape": resized, "_feature_faces": resized_features}}, [new_candidate])[part_id]
        resized, resized_features = rebuilt["shape"], rebuilt.get("_feature_faces", [])
        rebound.append(updated)
    from build123d import Pos
    new_bounds = resized.bounding_box()
    shift = [getattr(bounds.min if side < 0 else bounds.max, axis) -
             getattr(new_bounds.min if side < 0 else new_bounds.max, axis)
             for side, axis in zip(anchor, ("X", "Y", "Z"))]
    resized = Pos(*shift) * resized
    actual = resized.bounding_box()
    if (not resized.is_valid or any(abs(getattr(actual.size, axis) - expected) > 1e-3
                                    for axis, expected in zip(("X", "Y", "Z"), size))):
        raise GeometryError("preserve_unsupported", "Эта история не позволяет сохранить элементы при заданных габаритах. Исходная модель сохранена.")
    rebound.append({"op": "transform", "part_id": part_id, "translate": shift})
    part["_design"] = {"template": template, "params": params, "operations": rebound}
    part["_feature_faces"] = [(Pos(*shift) * face, index) for face, index in resized_features]
    return resized


def _positive_params(params, *names):
    invalid = [name for name in names if float(params[name]) <= 0]
    if invalid:
        raise GeometryError(
            "bad_params",
            f"Размеры должны быть больше нуля: {', '.join(invalid)}.")


def build_box(p):
    from build123d import Box, Pos
    _positive_params(p, "length", "width", "height")
    length, width, height = p["length"], p["width"], p["height"]
    return Pos(0, 0, height / 2) * Box(length, width, height), {}


def build_cylinder(p):
    from build123d import Cylinder, Pos
    _positive_params(p, "diameter", "height")
    diameter, height = p["diameter"], p["height"]
    return Pos(0, 0, height / 2) * Cylinder(radius=diameter / 2, height=height), {}


def build_sphere(p):
    from build123d import Pos, Sphere
    _positive_params(p, "diameter")
    radius = p["diameter"] / 2
    return Pos(0, 0, radius) * Sphere(radius=radius), {}

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
    "box": (build_box, {
        "length": 40.0, "width": 30.0, "height": 20.0}),
    "cylinder": (build_cylinder, {
        "diameter": 30.0, "height": 30.0}),
    "sphere": (build_sphere, {
        "diameter": 30.0}),
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
    point_count = 2 if str(edge.geom_type).split(".")[-1] == "LINE" else 65
    try:
        points = [
            [round(value, 6) for value in edge.position_at(index / (point_count - 1))]
            for index in range(point_count)
        ]
    except Exception:  # noqa: BLE001
        points = []
    return {
        "solid_index": solid_index,
        "kind": str(edge.geom_type).split(".")[-1],
        "length": round(edge.length, 4),
        "midpoint": [round(c.X, 4), round(c.Y, 4), round(c.Z, 4)],
        "p0": p0, "p1": p1,
        "points": points,
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
            f"Не удалось построить обработку ребра: {feature.lower()} {value:g} мм. "
            "Возможны пересечение соседних поверхностей или неподходящая геометрия ребра. "
            "Проверьте меньший размер или выберите другое ребро.",
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

def _is_planar_face(face):
    from build123d import GeomType
    from OCP.ShapeAnalysis import ShapeAnalysis_CanonicalRecognition
    from OCP.gp import gp_Pln
    return face.geom_type == GeomType.PLANE or (
        face.geom_type == GeomType.BSPLINE and
        ShapeAnalysis_CanonicalRecognition(face.wrapped).IsPlane(1e-7, gp_Pln()))


def _face_area(face):
    from build123d import GeomType
    if face.geom_type != GeomType.BSPLINE:
        return face.area
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    properties = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face.wrapped, properties, 1e-9, False)
    return properties.Mass()


def face_offset_reference(face, solid_index):
    from build123d import CenterOf, GeomType
    if not _is_planar_face(face):
        return None
    center = face.center(CenterOf.MASS)
    normal = face.normal_at()
    return {
        "kind": "planar",
        "solid_index": solid_index,
        "center": [round(value, 6) for value in center],
        "normal": [round(value, 9) for value in normal],
        "area": round(_face_area(face), 6),
    }


def _binary_mesh_resource(blob, name):
    digest = hashlib.sha256(blob).hexdigest()
    path = _session_dir / f"{name}-{digest}.bin"
    if not path.exists():
        descriptor, temporary = tempfile.mkstemp(prefix=f".{name}-", suffix=".tmp", dir=_session_dir)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(blob)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return {"path": str(path), "bytes": len(blob), "sha256": digest}


def mesh_resource(part, name, tol=0.1, feature_faces=None):
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
                                "tri_count": len(tris),
                                "face_ref": face_offset_reference(face, si),
                                "surface_ref": surface_reference(face),
                                "feature_index": feature_index_for_face(face, feature_faces)})
            fi += 1
            v_off += len(verts)
    blob = struct.pack("<II", len(positions) // 3, len(indices) // 3)
    blob += struct.pack(f"<{len(positions)}f", *positions)
    blob += struct.pack(f"<{len(indices)}I", *indices)
    return {**_binary_mesh_resource(blob, name),
            "vertex_count": len(positions) // 3,
            "triangle_count": len(indices) // 3,
            "face_ranges": face_ranges}


MAX_EMBEDDED_MESH_BYTES = 25 * 1024 * 1024
MAX_EMBEDDED_IMAGE_BYTES = 8 * 1024 * 1024
IMAGE_RELIEF_MODEL = "heightmap-luminance-v1"


def _trimesh_resource(mesh, name):
    import numpy as np
    positions = np.asarray(mesh.vertices, dtype="float32")
    indices = np.asarray(mesh.faces, dtype="uint32")
    blob = struct.pack("<II", len(positions), len(indices))
    blob += positions.tobytes() + indices.tobytes()
    return {
        **_binary_mesh_resource(blob, name),
        "vertex_count": int(len(positions)),
        "triangle_count": int(len(indices)),
        "face_ranges": [],
    }


def _mesh_diagnostics(mesh):
    import numpy as np
    _, counts = np.unique(mesh.edges_sorted, axis=0, return_counts=True)
    boundary_edges = int((counts == 1).sum())
    non_manifold_edges = int((counts > 2).sum())
    degenerate = int((mesh.area_faces <= 1e-12).sum())
    return {
        "watertight": bool(mesh.is_watertight),
        "winding_consistent": bool(mesh.is_winding_consistent),
        "boundary_edges": boundary_edges,
        "non_manifold_edges": non_manifold_edges,
        "degenerate_triangles": degenerate,
        "components": int(mesh.body_count),
        "euler_number": int(mesh.euler_number),
        "self_intersection": "unknown",
        "self_intersection_detail": (
            "Универсальная проверка самопересечений не заявлена; repair не выдаёт ложный pass."
        ),
    }


def _load_embedded_mesh(operation):
    import base64
    import binascii
    from io import BytesIO
    import numpy as np
    import trimesh

    mesh_format = str(operation.get("format", "stl")).lower()
    if mesh_format not in {"stl", "obj", "ply"}:
        raise GeometryError("bad_params", f"Mesh workflow не поддерживает формат {mesh_format}.")
    encoded = operation.get("source_base64")
    if not isinstance(encoded, str) or not encoded:
        raise GeometryError("bad_params", "Mesh source отсутствует в проекте.")
    try:
        source = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GeometryError("bad_params", "Embedded mesh source повреждён.") from exc
    if len(source) > MAX_EMBEDDED_MESH_BYTES:
        raise GeometryError("mesh_too_large", "Mesh source превышает лимит 25 MiB.")
    try:
        loaded = trimesh.load(BytesIO(source), file_type=mesh_format, force="mesh", process=False)
    except Exception as exc:  # noqa: BLE001
        raise GeometryError("mesh_read_failed", f"Не удалось прочитать {mesh_format.upper()} mesh.") from exc
    if isinstance(loaded, trimesh.Scene):
        geometries = [geometry for geometry in loaded.geometry.values() if len(geometry.faces)]
        if not geometries:
            raise GeometryError("mesh_empty", "Mesh source не содержит треугольников.")
        mesh = trimesh.util.concatenate(geometries)
    else:
        mesh = loaded
    if not isinstance(mesh, trimesh.Trimesh) or len(mesh.faces) == 0:
        raise GeometryError("mesh_empty", "Mesh source не содержит треугольников.")
    scale = float(operation.get("unit_scale", 1.0))
    if not math.isfinite(scale) or scale <= 0:
        raise GeometryError("bad_params", "Масштаб mesh должен быть положительным числом.")
    mesh = mesh.copy()
    mesh.vertices = np.asarray(mesh.vertices, dtype=float) * scale
    # STL repeats vertices per triangle; merge only identical positions so
    # topology diagnostics describe the source surface rather than file layout.
    mesh.merge_vertices()
    mesh.remove_unreferenced_vertices()
    if not np.isfinite(mesh.vertices).all():
        raise GeometryError("mesh_invalid", "Mesh содержит бесконечные или NaN-координаты.")
    return mesh, {
        "source_format": mesh_format,
        "source_bytes": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "unit_scale": scale,
    }


def _image_relief_mesh(operation):
    import base64
    import binascii
    from io import BytesIO
    import numpy as np
    from PIL import Image, ImageOps, UnidentifiedImageError
    import trimesh

    if operation.get("model") != IMAGE_RELIEF_MODEL:
        raise GeometryError("bad_params", f"Поддерживается только model={IMAGE_RELIEF_MODEL}.")
    encoded = operation.get("source_base64")
    if not isinstance(encoded, str) or not encoded:
        raise GeometryError("bad_params", "Изображение отсутствует в проекте.")
    try:
        source = base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise GeometryError("bad_params", "Embedded image source повреждён.") from exc
    if len(source) > MAX_EMBEDDED_IMAGE_BYTES:
        raise GeometryError("image_too_large", "Изображение превышает лимит 8 MiB.")
    try:
        with Image.open(BytesIO(source)) as opened:
            if opened.format not in {"PNG", "JPEG", "WEBP"}:
                raise GeometryError("bad_params", "Поддерживаются PNG, JPEG и WebP.")
            if opened.width * opened.height > 16_000_000:
                raise GeometryError("image_too_large", "Изображение превышает лимит 16 мегапикселей.")
            image = ImageOps.exif_transpose(opened).convert("L")
    except (UnidentifiedImageError, OSError) as exc:
        raise GeometryError("image_read_failed", "Не удалось декодировать изображение.") from exc

    width_mm = float(operation.get("width_mm", 50))
    relief_height = float(operation.get("relief_height", 3))
    base_thickness = float(operation.get("base_thickness", 1.5))
    samples = int(operation.get("samples", 96))
    seed = int(operation.get("seed", 0))
    noise_strength = float(operation.get("noise_strength", 0.015))
    invert = bool(operation.get("invert", False))
    if not all(math.isfinite(value) and value > 0
               for value in [width_mm, relief_height, base_thickness]):
        raise GeometryError("bad_params", "Размер, рельеф и основание должны быть положительными.")
    if not 8 <= samples <= 192:
        raise GeometryError("bad_params", "Samples должен быть в диапазоне 8…192.")
    if not 0 <= noise_strength <= 0.2:
        raise GeometryError("bad_params", "Noise strength должен быть в диапазоне 0…0.2.")
    aspect = image.height / image.width
    columns = samples
    rows = max(8, min(192, int(round(samples * aspect))))
    height_mm = width_mm * image.height / image.width
    resized = image.resize((columns, rows), Image.Resampling.LANCZOS)
    luminance = np.asarray(resized, dtype=float) / 255.0
    if invert:
        luminance = 1.0 - luminance
    rng = np.random.default_rng(seed)
    noise = rng.uniform(-noise_strength, noise_strength, size=luminance.shape)
    normalized = np.clip(luminance + noise, 0.0, 1.0)
    top_z = base_thickness + normalized * relief_height

    x_values = np.linspace(0.0, width_mm, columns)
    y_values = np.linspace(0.0, height_mm, rows)
    xx, yy = np.meshgrid(x_values, y_values)
    top = np.column_stack([xx.ravel(), yy.ravel(), top_z.ravel()])
    bottom = np.column_stack([xx.ravel(), yy.ravel(), np.zeros(rows * columns)])
    vertices = np.vstack([top, bottom])
    offset = rows * columns
    faces = []
    for row in range(rows - 1):
        for column in range(columns - 1):
            a = row * columns + column
            b, c, d = a + 1, a + columns + 1, a + columns
            faces.extend([[a, b, c], [a, c, d]])
            faces.extend([[offset + a, offset + c, offset + b],
                          [offset + a, offset + d, offset + c]])
    boundary = (
        list(range(columns)) +
        [row * columns + columns - 1 for row in range(1, rows)] +
        list(range((rows - 1) * columns + columns - 2, (rows - 1) * columns - 1, -1)) +
        [row * columns for row in range(rows - 2, 0, -1)]
    )
    for index, current in enumerate(boundary):
        following = boundary[(index + 1) % len(boundary)]
        faces.extend([[current, offset + current, offset + following],
                      [current, offset + following, following]])
    mesh = trimesh.Trimesh(vertices, np.asarray(faces, dtype=np.int64), process=False)
    mesh.merge_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)
    if not mesh.is_watertight or not mesh.is_winding_consistent:
        raise GeometryError("image_mesh_failed", "Не удалось построить замкнутый decorative mesh.")
    correlation = float(np.corrcoef(luminance.ravel(), normalized.ravel())[0, 1])
    metadata = {
        "source_format": str(operation.get("format", "image")),
        "source_bytes": len(source),
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "model": IMAGE_RELIEF_MODEL,
        "seed": seed,
        "settings": {
            "width_mm": width_mm,
            "height_mm": height_mm,
            "relief_height": relief_height,
            "base_thickness": base_thickness,
            "samples": samples,
            "grid": [columns, rows],
            "noise_strength": noise_strength,
            "invert": invert,
            "units": "mm",
        },
        "quality": {
            "metric": "luminance_height_correlation",
            "value": correlation,
            "engineering_accuracy": False,
            "pixel_exactness_required": False,
        },
    }
    return mesh, metadata


def _cluster_mesh(mesh, cells_per_axis):
    import numpy as np
    import trimesh
    vertices = np.asarray(mesh.vertices, dtype=float)
    faces = np.asarray(mesh.faces, dtype=np.int64)
    bounds_min, bounds_max = vertices.min(axis=0), vertices.max(axis=0)
    extents = np.maximum(bounds_max - bounds_min, 1e-12)
    keys = np.floor((vertices - bounds_min) / extents * cells_per_axis).astype(np.int64)
    keys = np.minimum(keys, cells_per_axis - 1)
    _, inverse = np.unique(keys, axis=0, return_inverse=True)
    counts = np.bincount(inverse)
    clustered = np.column_stack([
        np.bincount(inverse, weights=vertices[:, axis]) / counts for axis in range(3)
    ])
    remapped = inverse[faces]
    distinct = ((remapped[:, 0] != remapped[:, 1]) &
                (remapped[:, 1] != remapped[:, 2]) &
                (remapped[:, 0] != remapped[:, 2]))
    remapped = remapped[distinct]
    if len(remapped) == 0:
        raise GeometryError("decimation_failed", "Decimation уничтожила все треугольники.")
    sorted_faces = np.sort(remapped, axis=1)
    _, unique_indices = np.unique(sorted_faces, axis=0, return_index=True)
    remapped = remapped[np.sort(unique_indices)]
    clustered_min, clustered_max = clustered.min(axis=0), clustered.max(axis=0)
    clustered_extent = clustered_max - clustered_min
    if np.any(clustered_extent <= 1e-12):
        raise GeometryError("decimation_failed", "Decimation выродила размер mesh.")
    clustered = ((clustered - clustered_min) / clustered_extent) * extents + bounds_min
    candidate = trimesh.Trimesh(clustered, remapped, process=False)
    candidate.remove_unreferenced_vertices()
    return candidate


def _sampled_vertex_error(source, candidate, sample_limit=2000):
    import numpy as np
    from scipy.spatial import cKDTree

    def sample(vertices):
        if len(vertices) <= sample_limit:
            return np.asarray(vertices)
        indices = np.linspace(0, len(vertices) - 1, sample_limit, dtype=int)
        return np.asarray(vertices)[indices]

    source_vertices = sample(source.vertices)
    candidate_vertices = sample(candidate.vertices)
    forward = cKDTree(np.asarray(source.vertices)).query(candidate_vertices, k=1)[0]
    backward = cKDTree(np.asarray(candidate.vertices)).query(source_vertices, k=1)[0]
    distances = np.concatenate([forward, backward])
    return {
        "kind": "sampled_vertex_nearest_neighbor",
        "samples": int(len(distances)),
        "max": float(distances.max(initial=0)),
        "mean": float(distances.mean()) if len(distances) else 0.0,
        "global_hausdorff_guarantee": False,
    }


def _decimate_mesh(mesh, operation):
    target_ratio = float(operation.get("target_ratio", 0.5))
    minimum_ratio = float(operation.get("minimum_ratio", max(0.02, target_ratio - 0.08)))
    maximum_ratio = float(operation.get("maximum_ratio", min(0.98, target_ratio + 0.08)))
    volume_tolerance = float(operation.get("volume_tolerance", 0.05))
    if not 0 < minimum_ratio <= target_ratio <= maximum_ratio < 1:
        raise GeometryError("bad_params", "Decimation ratios должны удовлетворять 0 < min ≤ target ≤ max < 1.")
    if not 0 <= volume_tolerance <= 0.5:
        raise GeometryError("bad_params", "Volume tolerance должна быть в диапазоне 0…0.5.")
    source_triangles = len(mesh.faces)
    if source_triangles < 20:
        raise GeometryError("decimation_failed", "Для decimation требуется не менее 20 треугольников.")
    source_diagnostics = _mesh_diagnostics(mesh)
    source_volume = abs(float(mesh.volume)) if mesh.is_watertight else None
    candidates = []
    for cells in range(4, 129):
        candidate = _cluster_mesh(mesh, cells)
        ratio = len(candidate.faces) / source_triangles
        if ratio < minimum_ratio * 0.75 or ratio > maximum_ratio * 1.25:
            continue
        diagnostics = _mesh_diagnostics(candidate)
        if diagnostics["components"] != source_diagnostics["components"]:
            continue
        if diagnostics["euler_number"] != source_diagnostics["euler_number"]:
            continue
        if source_diagnostics["watertight"] and not diagnostics["watertight"]:
            continue
        volume_error = None
        if source_volume and source_volume > 1e-12:
            volume_error = abs(abs(float(candidate.volume)) - source_volume) / source_volume
            if volume_error > volume_tolerance:
                continue
        candidates.append((abs(ratio - target_ratio), candidate, ratio, diagnostics, volume_error, cells))
    in_range = [candidate for candidate in candidates if minimum_ratio <= candidate[2] <= maximum_ratio]
    if not in_range:
        raise GeometryError(
            "decimation_failed",
            "Не удалось уменьшить mesh в заявленный диапазон без изменения компонент или топологии.")
    _, result, ratio, diagnostics, volume_error, cells = min(in_range, key=lambda item: item[0])
    return result, {
        "algorithm": "topology_checked_vertex_clustering-v1",
        "source_triangles": source_triangles,
        "result_triangles": int(len(result.faces)),
        "target_ratio": target_ratio,
        "accepted_ratio_range": [minimum_ratio, maximum_ratio],
        "actual_ratio": ratio,
        "cells_per_axis": cells,
        "volume_relative_error": volume_error,
        "topology_preserved": True,
        "components": diagnostics["components"],
        "euler_number": diagnostics["euler_number"],
        "shape_error": _sampled_vertex_error(mesh, result),
    }


def _deform_mesh(mesh, operation):
    import numpy as np
    if (any(not isinstance(operation.get(name), list) or len(operation[name]) != 3 or
            any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in operation[name])
            for name in ("center", "delta")) or isinstance(operation.get("radius"), bool)):
        raise GeometryError("bad_params", "Центр и смещение должны содержать три числа, радиус — положительное число.")
    try:
        center = np.asarray(operation["center"], dtype=float)
        delta = np.asarray(operation["delta"], dtype=float)
        radius = float(operation["radius"])
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Укажите центр, радиус и смещение мягкой деформации.") from exc
    if (center.shape != (3,) or delta.shape != (3,) or not np.isfinite(center).all() or
            not np.isfinite(delta).all() or not math.isfinite(radius) or radius <= 0 or
            np.linalg.norm(delta) < 1e-7):
        raise GeometryError("bad_params", "Радиус должен быть положительным, смещение — конечным и ненулевым.")
    distance = np.linalg.norm(mesh.vertices - center, axis=1) / radius
    weight = np.maximum(0, 1 - distance ** 2) ** 2
    if not np.any(weight > 0):
        raise GeometryError("deform_no_vertices", "В радиус кисти не попала ни одна вершина. Увеличьте радиус.")
    result = mesh.copy()
    result.vertices = mesh.vertices + weight[:, None] * delta
    before = np.cross(mesh.triangles[:, 1] - mesh.triangles[:, 0], mesh.triangles[:, 2] - mesh.triangles[:, 0])
    after = np.cross(result.triangles[:, 1] - result.triangles[:, 0], result.triangles[:, 2] - result.triangles[:, 0])
    if (not np.isfinite(result.vertices).all() or np.any(np.einsum("ij,ij->i", before, after) <= 1e-16) or
            (mesh.is_watertight and (not result.is_watertight or result.volume <= 1e-8))):
        raise GeometryError("deform_foldover", "Деформация переворачивает или схлопывает треугольники. Уменьшите смещение или увеличьте радиус.")
    return result


def _build_mesh_workflow(params):
    operations = params.get("operations") or []
    if params.get("parts"):
        raise GeometryError("mesh_mode_mixed", "Mesh workflow нельзя смешивать с параметрическими BRep-деталями.")
    if not operations or operations[0].get("op") not in {"mesh_source", "image_relief_source"}:
        raise GeometryError("mesh_source_missing", "Mesh workflow должен начинаться с embedded source.")
    source_kind = operations[0].get("op")
    if source_kind == "mesh_source":
        mesh, source_metadata = _load_embedded_mesh(operations[0])
    else:
        mesh, source_metadata = _image_relief_mesh(operations[0])
    history = [{"op": source_kind, **source_metadata,
                "diagnostics": _mesh_diagnostics(mesh)}]
    for operation in operations[1:]:
        kind = operation.get("op")
        if operation.get("enabled") is False:
            continue
        if kind == "mesh_transform":
            import numpy as np
            import trimesh
            translate = operation.get("translate") or [0, 0, 0]
            rotate = operation.get("rotate_deg") or [0, 0, 0]
            pivot = operation.get("pivot") or [0, 0, 0]
            scale = operation.get("scale", 1.0)
            if any(not isinstance(vector, list) or len(vector) != 3 or
                   any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector)
                   for vector in (translate, rotate, pivot)):
                raise GeometryError("bad_params", "Mesh transform требует translate/rotate_deg XYZ.")
            scale_values = ([float(scale)] * 3 if isinstance(scale, (int, float))
                            else [float(value) for value in scale])
            if len(scale_values) != 3 or any(not math.isfinite(value) or value <= 0 for value in scale_values):
                raise GeometryError("bad_params", "Mesh scale должен содержать положительные значения.")
            matrix = trimesh.transformations.euler_matrix(
                *[math.radians(float(value)) for value in rotate], axes="sxyz")
            matrix[:3, :3] = matrix[:3, :3] @ np.diag(scale_values)
            matrix[:3, 3] = np.asarray(translate) + np.asarray(pivot) - matrix[:3, :3] @ np.asarray(pivot)
            mesh.apply_transform(matrix)
            history.append({"op": kind, "translate": translate, "rotate_deg": rotate,
                            "scale": scale_values})
        elif kind == "mesh_deform":
            mesh = _deform_mesh(mesh, operation)
            history.append(copy.deepcopy(operation))
        elif kind == "mesh_repair":
            import trimesh
            action = operation.get("action", "fill_holes")
            if action != "fill_holes":
                raise GeometryError("bad_params", f"Неподдерживаемый mesh repair: {action}.")
            before = _mesh_diagnostics(mesh)
            repaired = mesh.copy()
            filled = bool(trimesh.repair.fill_holes(repaired))
            trimesh.repair.fix_normals(repaired, multibody=True)
            repaired.remove_unreferenced_vertices()
            after = _mesh_diagnostics(repaired)
            if not filled or after["boundary_edges"] >= before["boundary_edges"]:
                raise GeometryError("mesh_repair_no_change", "Не найден поддерживаемый треугольный/четырёхугольный дефект для закрытия.")
            mesh = repaired
            history.append({"op": kind, "action": action, "before": before, "after": after})
        elif kind == "mesh_decimate":
            mesh, decimation = _decimate_mesh(mesh, operation)
            history.append({"op": kind, **decimation})
        else:
            raise GeometryError("unknown_mesh_op", f"Неизвестная mesh operation: {kind}.")
    diagnostics = _mesh_diagnostics(mesh)
    bounds = mesh.bounds
    stats = {
        "volume": float(abs(mesh.volume)) if mesh.is_watertight else None,
        "solid_count": diagnostics["components"],
        "face_count": int(len(mesh.faces)),
        "bbox": [float(value) for value in [*bounds[0], *bounds[1]]],
        "bbox_mesh": [float(value) for value in mesh.bounding_box.extents],
        "is_valid": bool(mesh.is_watertight and mesh.is_winding_consistent),
        "triangle_count": int(len(mesh.faces)),
        "mesh_mode": True,
        "mesh_diagnostics": diagnostics,
        "mesh_history": history,
        "parts": [{
            "part_id": "mesh-1",
            "bbox": [float(value) for value in [*bounds[0], *bounds[1]]],
            "name": "Декоративный mesh" if source_kind == "image_relief_source" else "Mesh",
            "volume": (
                float(abs(mesh.volume)) if mesh.is_watertight else None),
            "solid_count": diagnostics["components"],
            "metadata": {"mode": "mesh", "source_sha256": source_metadata["source_sha256"]},
        }],
    }
    return mesh, stats


def _is_mesh_workflow(params):
    operations = params.get("operations") or []
    return bool(operations and operations[0].get("op") in {
        "mesh_source", "image_relief_source"})


def _export_trimesh_3mf(mesh, path):
    import xml.etree.ElementTree as element_tree
    import zipfile

    namespace = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
    element_tree.register_namespace("", namespace)
    model = element_tree.Element(f"{{{namespace}}}model", {
        "unit": "millimeter", "xml:lang": "en-US",
    })
    resources = element_tree.SubElement(model, f"{{{namespace}}}resources")
    object_node = element_tree.SubElement(resources, f"{{{namespace}}}object", {
        "id": "1", "type": "model", "name": "PrintForge mesh",
    })
    mesh_node = element_tree.SubElement(object_node, f"{{{namespace}}}mesh")
    vertices_node = element_tree.SubElement(mesh_node, f"{{{namespace}}}vertices")
    for vertex in mesh.vertices:
        element_tree.SubElement(vertices_node, f"{{{namespace}}}vertex", {
            "x": format(float(vertex[0]), ".9g"),
            "y": format(float(vertex[1]), ".9g"),
            "z": format(float(vertex[2]), ".9g"),
        })
    triangles_node = element_tree.SubElement(mesh_node, f"{{{namespace}}}triangles")
    for triangle in mesh.faces:
        element_tree.SubElement(triangles_node, f"{{{namespace}}}triangle", {
            "v1": str(int(triangle[0])), "v2": str(int(triangle[1])),
            "v3": str(int(triangle[2])),
        })
    build = element_tree.SubElement(model, f"{{{namespace}}}build")
    element_tree.SubElement(build, f"{{{namespace}}}item", {"objectid": "1"})
    model_bytes = element_tree.tostring(model, encoding="utf-8", xml_declaration=True)
    content_types = b'''<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Override PartName="/3D/3dmodel.model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>'''
    relationships = b'''<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>'''
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("3D/3dmodel.model", model_bytes)


def shape_volume(part):
    from build123d import GeomType
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    volume = 0.0
    for solid in part.solids():
        if any(face.geom_type == GeomType.BSPLINE for face in solid.faces()):
            properties = GProp_GProps()
            error = BRepGProp.VolumePropertiesGK_s(solid.wrapped, properties, 1e-9, True, True)
            if error < 0 or not math.isfinite(properties.Mass()):
                raise GeometryError("measurement_failed", "Не удалось точно вычислить объём изменённой формы.")
            volume += properties.Mass()
        else:
            volume += solid.volume
    return volume


def shape_bounds(part):
    bounds = part.bounding_box()
    return [bounds.min.X, bounds.min.Y, bounds.min.Z, bounds.max.X, bounds.max.Y, bounds.max.Z]


def stats_of(part, extra=None, with_edges=True):
    bb = part.bounding_box()
    st = {
        "volume": shape_volume(part),
        "solid_count": len(part.solids()),
        "face_count": len(part.faces()),
        "bbox": [bb.min.X, bb.min.Y, bb.min.Z, bb.max.X, bb.max.Y, bb.max.Z],
        "is_valid": bool(part.is_valid),
    }
    if with_edges:
        st["edges"] = list_edges(part)
    if extra:
        st.update({key: value for key, value in extra.items() if not key.startswith("_")})
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
        from build123d import Rotation
        width = _positive_profile_value(profile, "width", "Ширина паза")
        length = _positive_profile_value(profile, "length", "Длина паза")
        if length <= width:
            raise GeometryError("bad_params", "Длина паза должна быть больше его ширины.")
        straight = length - width
        radius = width / 2
        slot = (
            Box(straight, width, depth, align=alignment)
            + Pos(-straight / 2, 0, 0) * Cylinder(radius=radius, height=depth, align=alignment)
            + Pos(straight / 2, 0, 0) * Cylinder(radius=radius, height=depth, align=alignment)
        )
        return Rotation(0, 0, 90) * slot if profile.get("_quarter_turn") else slot
    raise GeometryError("bad_params", f"Неизвестный профиль: {kind}")


def _match_offset_face(target, reference):
    from build123d import CenterOf, GeomType
    if not isinstance(reference, dict) or reference.get("kind") != "planar":
        raise GeometryError(
            "unsupported_face",
            "Тянуть можно только плоскую грань. Выберите плоскую область модели.")
    try:
        center = [float(value) for value in reference["center"]]
        normal = [float(value) for value in reference["normal"]]
        area = float(reference["area"])
        if (len(center) != 3 or len(normal) != 3 or
                not all(math.isfinite(value) for value in center + normal + [area]) or
                area <= 0):
            raise ValueError
        normal_length = math.sqrt(sum(value * value for value in normal))
        if normal_length <= 1e-9:
            raise ValueError
        normal = [value / normal_length for value in normal]
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise GeometryError(
            "bad_ref", "Ссылка на грань повреждена. Выберите грань заново.") from exc
    candidates = []
    for solid_index, solid in enumerate(target.solids()):
        for face in solid.faces():
            if not _is_planar_face(face):
                continue
            if abs(_face_area(face) - area) > max(1e-4, area * 1e-6):
                continue
            if math.dist(tuple(face.center(CenterOf.MASS)), center) > 1e-4:
                continue
            alignment = sum(value * expected for value, expected in zip(face.normal_at(), normal))
            if alignment > 1 - 1e-7:
                candidates.append((solid_index, solid, face))
    if len(candidates) != 1:
        raise GeometryError(
            "reselect_required",
            "Грань изменилась после перестроения или выбор неоднозначен. Выберите грань заново.")
    return candidates[0]


def _apply_face_offset(target, operation):
    from build123d import Compound, extrude
    try:
        distance = float(operation["distance"])
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise GeometryError("bad_params", "Введите ненулевое смещение грани в миллиметрах.") from exc
    if not math.isfinite(distance) or abs(distance) < 1e-6:
        raise GeometryError("bad_params", "Введите ненулевое смещение грани в миллиметрах.")
    solid_index, solid, face = _match_offset_face(target, operation.get("face_ref"))
    direction = [value * (1 if distance > 0 else -1) for value in face.normal_at()]
    try:
        prism = extrude(face, amount=abs(distance), dir=direction)
        result = solid + prism if distance > 0 else solid - prism
        expected_change = _face_area(face) * abs(distance)
        tolerance = max(1e-4, expected_change * 1e-6)
        actual_change = (shape_volume(result) - shape_volume(solid)) * (1 if distance > 0 else -1)
        if (not result.is_valid or len(result.solids()) != 1 or
                result.volume <= 1e-8 or abs(actual_change - expected_change) > tolerance):
            raise GeometryError(
                "face_offset_failed",
                "Смещение пересекает другие поверхности, разделяет или удаляет тело. "
                "Уменьшите расстояние или выберите другую плоскую грань.")
        solids = list(target.solids())
        for other_index, other in enumerate(solids):
            if other_index == solid_index:
                continue
            intersection = result & other
            if intersection is not None and intersection.volume > tolerance:
                raise GeometryError(
                    "face_offset_failed",
                    "Грань упирается в другую часть этой детали. Уменьшите смещение.")
        solids[solid_index] = result
        return result if len(solids) == 1 else Compound(children=solids)
    except GeometryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise GeometryError(
            "face_offset_failed",
            "Не удалось переместить плоскую грань. Уменьшите смещение или выберите другую грань.",
            detail=str(exc).split("\n")[0]) from exc


def _apply_face_shell(target, operation):
    from build123d import Compound

    thickness = operation.get("thickness")
    if isinstance(thickness, bool) or not isinstance(thickness, (int, float)) or not math.isfinite(thickness) or thickness <= 0:
        raise GeometryError("bad_params", "Толщина стенки должна быть конечным числом больше нуля.")
    solid_index, solid, face = _match_offset_face(target, operation.get("face_ref"))
    bounds = solid.bounding_box()
    size = [bounds.size.X, bounds.size.Y, bounds.size.Z]
    normal = tuple(face.normal_at())
    axis = max(range(3), key=lambda index: abs(normal[index]))
    if (not solid.is_valid or len(solid.faces()) != 6 or
            abs(abs(normal[axis]) - 1) > 1e-7 or
            abs(solid.volume - math.prod(size)) > max(1e-5, solid.volume * 1e-7)):
        raise GeometryError("shell_unsupported", "Пока оболочка доступна для прямоугольного тела без отверстий и скруглений.")
    other = [size[index] for index in range(3) if index != axis]
    if thickness >= size[axis] or any(2 * thickness >= dimension for dimension in other):
        raise GeometryError("bad_params", "Толщина слишком велика для выбранного тела. Уменьшите её.")
    expected_volume = solid.volume - (size[axis] - thickness) * math.prod(dimension - 2 * thickness for dimension in other)
    try:
        result = solid.hollow([face], -thickness)
        if (not result.is_valid or len(result.solids()) != 1 or result.volume <= 0 or
                abs(result.volume - expected_volume) > max(1e-4, expected_volume * 1e-6)):
            raise ValueError("Unexpected shell geometry")
        solids = list(target.solids())
        solids[solid_index] = result
        return result if len(solids) == 1 else Compound(children=solids)
    except Exception as exc:
        raise GeometryError("shell_failed", "Не удалось построить оболочку. Уменьшите толщину или выберите другую грань.", detail=str(exc).split("\n")[0]) from exc


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
        if profile.get("_quarter_turn"):
            half_x = width / 2
            half_y = length / 2
        else:
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
        "slot_long_along_developed": (
            kind == "slot" and
            ((bend_axis == "x") != bool(profile.get("_quarter_turn")))
        ),
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
                        if feature["slot_long_along_developed"]:
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


def _apply_perpendicular_flange_bend(
        part_info, base_operation, flange_operation, flat_features=None):
    from build123d import Align, Box, Plane

    params = part_info["params"]
    thickness = params["height"]
    base_axis = base_operation.get("bend_axis")
    flange_axis = flange_operation.get("bend_axis")
    if base_axis not in ("x", "y") or flange_axis not in ("x", "y"):
        raise GeometryError("bad_params", "Ось изгиба должна быть X или Y.")
    if flange_axis == base_axis:
        raise GeometryError(
            "bend_failed",
            "Изгиб выбранного фланца должен быть перпендикулярен базовой линии изгиба.")

    try:
        base_angle = float(base_operation["angle"])
        base_radius = float(base_operation["inside_radius"])
        base_position = float(base_operation.get("position", 0))
        base_moving_side = int(base_operation.get("moving_side", 1))
        base_direction = int(base_operation.get("direction", 1))
    except (KeyError, TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Параметры базового изгиба повреждены.") from exc
    if abs(base_angle - 90) > 1e-7:
        raise GeometryError(
            "bend_failed",
            "Перпендикулярный изгиб пока доступен только на фланце базового изгиба 90°.")
    if base_moving_side not in (-1, 1) or base_direction not in (-1, 1):
        raise GeometryError("bad_params", "Направление базового изгиба повреждено.")

    face_ref = flange_operation.get("face_ref") or {}
    if (face_ref.get("kind") != "outer_planar" or
            face_ref.get("axis") != base_axis or
            int(face_ref.get("side", 0)) != base_moving_side):
        raise GeometryError(
            "reselect_required",
            "Выберите внешнюю плоскую грань фланца базового изгиба.")

    developed_length = params["length"] if base_axis == "x" else params["width"]
    flange_width = params["width"] if base_axis == "x" else params["length"]
    base_delta = base_direction * math.radians(base_angle)
    bend_allowance = (base_radius + thickness / 2) * abs(base_delta)
    developed_center = base_position + developed_length / 2
    zone_start = developed_center - bend_allowance / 2
    zone_end = developed_center + bend_allowance / 2
    path_radius = base_radius if base_direction > 0 else base_radius + thickness

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

    initial_angle = -base_delta if base_moving_side < 0 else 0.0
    line_start = (0.0, 0.0)
    line_end = (
        zone_start * math.cos(initial_angle),
        zone_start * math.sin(initial_angle),
    )
    arc_end = advance(line_end, initial_angle, base_delta, path_radius)
    final_angle = initial_angle + base_delta
    final_point = (
        arc_end[0] + (developed_length - zone_end) * math.cos(final_angle),
        arc_end[1] + (developed_length - zone_end) * math.sin(final_angle),
    )
    if base_moving_side < 0:
        anchor_developed = developed_length
        anchor_point = final_point
        root_point = line_end
        root_tangent_2d = (-math.cos(initial_angle), -math.sin(initial_angle))
        flange_depth = zone_start
    else:
        anchor_developed = 0.0
        anchor_point = line_start
        root_point = arc_end
        root_tangent_2d = (math.cos(final_angle), math.sin(final_angle))
        flange_depth = developed_length - zone_end
    if flange_depth <= 0.1:
        raise GeometryError("bend_failed", "Фланец слишком короткий для второго изгиба.")

    shift_x = -developed_length / 2 + anchor_developed - anchor_point[0]
    shift_z = -anchor_point[1]
    root_cross = root_point[0] + shift_x
    root_z = thickness + root_point[1] + shift_z
    if base_axis == "x":
        root = (root_cross, 0.0, root_z)
        tangent = (root_tangent_2d[0], 0.0, root_tangent_2d[1])
        selected_normal = (float(base_moving_side), 0.0, 0.0)
        perpendicular_axis = (0.0, 1.0, 0.0)
    else:
        root = (0.0, root_cross, root_z)
        tangent = (0.0, root_tangent_2d[0], root_tangent_2d[1])
        selected_normal = (0.0, float(base_moving_side), 0.0)
        perpendicular_axis = (1.0, 0.0, 0.0)
    thickness_axis = tuple(base_direction * value for value in selected_normal)
    local_x_axis = (
        tangent[1] * thickness_axis[2] - tangent[2] * thickness_axis[1],
        tangent[2] * thickness_axis[0] - tangent[0] * thickness_axis[2],
        tangent[0] * thickness_axis[1] - tangent[1] * thickness_axis[0],
    )
    local_axis_sign = round(sum(
        local_x_axis[index] * perpendicular_axis[index] for index in range(3)))
    if local_axis_sign not in (-1, 1):
        raise GeometryError("bend_failed", "Не удалось определить локальные оси фланца.")

    target_boundary = (zone_start if base_moving_side < 0 else zone_end) - developed_length / 2
    flange_features = []
    for operation in flat_features or []:
        feature = _flat_sheet_feature_data(operation, base_axis)
        feature_min = feature["developed_center"] - feature["developed_extent"]
        feature_max = feature["developed_center"] + feature["developed_extent"]
        if base_moving_side < 0:
            on_target_flange = feature_max < target_boundary - 1e-7
            touches_target_flange = feature_min < target_boundary + 1e-7
        else:
            on_target_flange = feature_min > target_boundary + 1e-7
            touches_target_flange = feature_max > target_boundary - 1e-7
        if on_target_flange:
            flange_features.append(feature)
        elif touches_target_flange:
            raise GeometryError(
                "bend_failed",
                "Пользовательский вырез должен целиком лежать на прямом участке выбранного фланца.")

    overlap = 1e-4
    synthetic_depth = flange_depth + overlap
    synthetic_params = {
        "length": flange_width,
        "width": synthetic_depth,
        "height": thickness,
        "hole_diameter": 0,
        "hole_offset": 0,
    }
    synthetic_shape, _ = build_plate(synthetic_params)
    try:
        flange_position = local_axis_sign * float(flange_operation.get("position", 0))
        flange_moving_side = local_axis_sign * int(flange_operation.get("moving_side", 1))
        flange_direction = base_direction * int(flange_operation.get("direction", 1))
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Параметры изгиба фланца повреждены.") from exc
    synthetic_operation = {
        **flange_operation,
        "face_ref": {
            "kind": "outer_planar",
            "axis": "z",
            "side": 1,
            "anchor": [0, 0],
            "selected_area": flange_width * synthetic_depth,
        },
        "bend_axis": "x",
        "position": flange_position,
        "moving_side": flange_moving_side,
        "direction": flange_direction,
    }

    synthetic_features = []
    synthetic_face_ref = {
        "kind": "outer_planar", "axis": "z", "side": 1,
        "anchor": [0, 0], "selected_area": flange_width * synthetic_depth,
    }

    def append_synthetic_feature(profile, center):
        synthetic_features.append({
            "op": "face_feature",
            "mode": "cut",
            "face_ref": synthetic_face_ref,
            "profile": {**profile, "center": center},
            "depth": "through",
        })

    hole_diameter = params.get("hole_diameter", 0)
    if hole_diameter > 0:
        hole_offset = params["hole_offset"]
        original_x = params["length"] / 2 - hole_offset
        original_y = params["width"] / 2 - hole_offset
        for center_x, center_y in (
                (-original_x, -original_y), (original_x, -original_y),
                (-original_x, original_y), (original_x, original_y)):
            base_coordinate = center_x if base_axis == "x" else center_y
            base_developed = base_coordinate + developed_length / 2
            on_target_flange = (
                base_developed < zone_start if base_moving_side < 0
                else base_developed > zone_end
            )
            if not on_target_flange:
                continue
            perpendicular_coordinate = center_y if base_axis == "x" else center_x
            depth_from_root = (
                zone_start - base_developed if base_moving_side < 0
                else base_developed - zone_end
            )
            append_synthetic_feature(
                {"kind": "circle", "diameter": hole_diameter},
                [
                    local_axis_sign * perpendicular_coordinate,
                    depth_from_root - flange_depth / 2 + overlap / 2,
                ],
            )

    for feature in flange_features:
        base_developed = feature["developed_center"] + developed_length / 2
        perpendicular_coordinate = (
            feature["center_y"] if base_axis == "x" else feature["center_x"])
        depth_from_root = (
            zone_start - base_developed if base_moving_side < 0
            else base_developed - zone_end
        )
        center = [
            local_axis_sign * perpendicular_coordinate,
            depth_from_root - flange_depth / 2 + overlap / 2,
        ]
        profile = dict(feature["profile"])
        if feature["kind"] == "rectangle" and base_axis == "x":
            profile["width"], profile["height"] = (
                profile["height"], profile["width"])
        if feature["kind"] == "slot" and base_axis == "x":
            profile["_quarter_turn"] = True
        append_synthetic_feature(profile, center)

    for feature in synthetic_features:
        synthetic_shape = _apply_face_feature(synthetic_shape, feature)
    synthetic_info = {
        "template": "plate_with_holes",
        "params": synthetic_params,
        "shape": synthetic_shape,
    }

    base_bent = _apply_sheet_bends(part_info, [base_operation], flat_features)
    synthetic_bent = _apply_sheet_bends(
        synthetic_info, [synthetic_operation], synthetic_features)
    plane_origin = tuple(
        root[index] + (flange_depth - overlap) / 2 * tangent[index]
        for index in range(3)
    )
    transformed_flange = Plane(
        origin=plane_origin,
        x_dir=local_x_axis,
        z_dir=thickness_axis,
    ).location * synthetic_bent

    cut_origin = tuple(
        root[index] + flange_depth / 2 * tangent[index] +
        thickness / 2 * thickness_axis[index]
        for index in range(3)
    )
    cut_tool = Plane(
        origin=cut_origin,
        x_dir=local_x_axis,
        z_dir=thickness_axis,
    ).location * Box(
        flange_width + 2, flange_depth, thickness + 2,
        align=(Align.CENTER, Align.CENTER, Align.CENTER),
    )
    result = (base_bent - cut_tool) + transformed_flange
    initial = part_info["shape"]
    volume_tolerance = max(1e-3, initial.volume * 2e-6)
    if (not result.is_valid or len(result.solids()) != len(initial.solids()) or
            abs(result.volume - initial.volume) > volume_tolerance):
        raise GeometryError(
            "bend_failed",
            "Изгиб фланца создаёт самопересечение или меняет объём. "
            "Сместите линию или уменьшите угол и радиус.",
            detail=(f"valid={result.is_valid}; solids={len(result.solids())}; "
                    f"volume={result.volume:.6f}; expected={initial.volume:.6f}"))
    return result


def _rotate_about(shape, center, angle_deg):
    """Поворот вокруг оси Z через точку center."""
    from build123d import Pos, Rotation
    cx, cy, cz = center
    return Pos(cx, cy, cz) * Rotation(0, 0, angle_deg) * Pos(-cx, -cy, -cz) * shape


def _finite_point(value, label):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise GeometryError("bad_params", f"{label} должна содержать две координаты.")
    try:
        point = (float(value[0]), float(value[1]))
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", f"{label} должна содержать числа.") from exc
    if not all(math.isfinite(component) for component in point):
        raise GeometryError("bad_params", f"{label} должна содержать конечные числа.")
    return point


def _sketch_plane(plane_name, origin=(0, 0, 0)):
    from build123d import Plane
    planes = {
        "XY": ((1, 0, 0), (0, 0, 1)),
        "XZ": ((1, 0, 0), (0, -1, 0)),
        "YZ": ((0, 1, 0), (1, 0, 0)),
    }
    directions = planes.get(plane_name)
    if directions is None:
        raise GeometryError("bad_params", f"Неизвестная плоскость эскиза: {plane_name}")
    return Plane(origin=origin, x_dir=directions[0], z_dir=directions[1])


def _solve_constrained_sketch(sketch, drag=None, tolerance=1e-7):
    """Solve a small 2D geometric constraint system without fixing free DOF."""
    import numpy as np

    entities = sketch.get("entities") or []
    constraints = sketch.get("constraints") or []
    if not entities:
        raise GeometryError("bad_params", "Эскиз не содержит геометрических элементов.")
    if len(entities) > 160 or len(constraints) > 400:
        raise GeometryError("sketch_too_large", "Эскиз поддерживает до 160 элементов и 400 ограничений. Разделите его на несколько операций.")
    entity_by_id = {}
    spans = {}
    values = []
    for entity in entities:
        entity_id = entity.get("id")
        kind = entity.get("type")
        if not entity_id or entity_id in entity_by_id:
            raise GeometryError("bad_params", "Каждый элемент эскиза должен иметь уникальный id.")
        start = len(values)
        if kind in ("line", "arc"):
            points = [entity.get("start"), entity.get("end")]
            if kind == "arc":
                points.append(entity.get("mid"))
            if any(not isinstance(point, list) or len(point) != 2 for point in points):
                raise GeometryError("bad_params", f"Линия {entity_id} должна иметь start/end [x, y].")
            values.extend(float(value) for point_value in points for value in point_value)
        elif kind == "circle":
            center = entity.get("center")
            radius = entity.get("radius")
            if not isinstance(center, list) or len(center) != 2 or radius is None:
                raise GeometryError("bad_params", f"Окружность {entity_id} должна иметь center и radius.")
            values.extend([float(center[0]), float(center[1]), float(radius)])
        else:
            raise GeometryError("bad_params", f"Неподдерживаемый элемент эскиза: {kind}.")
        spans[entity_id] = (start, len(values), kind)
        entity_by_id[entity_id] = entity

    initial = np.asarray(values, dtype=float)
    if not np.isfinite(initial).all():
        raise GeometryError("bad_params", "Координаты эскиза должны быть конечными числами.")

    def point(vector, reference):
        if not isinstance(reference, list) or len(reference) != 2:
            raise GeometryError("bad_params", "Ссылка на точку должна иметь вид [entity_id, point].")
        entity_id, point_name = reference
        if entity_id not in spans:
            raise GeometryError("bad_params", f"Элемент эскиза не найден: {entity_id}.")
        start, _, kind = spans[entity_id]
        offsets = {"start": 0, "end": 2, **({"mid": 4} if kind == "arc" else {})} if kind in ("line", "arc") else {"center": 0}
        if point_name not in offsets:
            raise GeometryError("bad_params", f"У элемента {entity_id} нет точки {point_name}.")
        offset = start + offsets[point_name]
        return vector[offset:offset + 2]

    def line(vector, entity_id):
        if entity_id not in spans or spans[entity_id][2] != "line":
            raise GeometryError("bad_params", f"Линия эскиза не найдена: {entity_id}.")
        start = spans[entity_id][0]
        p0, p1 = vector[start:start + 2], vector[start + 2:start + 4]
        delta = p1 - p0
        length = float(np.linalg.norm(delta))
        if length <= 1e-12:
            raise GeometryError("sketch_degenerate", f"Линия {entity_id} имеет нулевую длину.")
        return p0, p1, delta, length

    def circle(vector, entity_id):
        if entity_id not in spans or spans[entity_id][2] != "circle":
            raise GeometryError("bad_params", f"Окружность эскиза не найдена: {entity_id}.")
        start = spans[entity_id][0]
        radius = float(vector[start + 2])
        if radius <= 1e-12:
            raise GeometryError("sketch_degenerate", f"Окружность {entity_id} имеет нулевой радиус.")
        return vector[start:start + 2], radius

    constraint_ranges = []

    def constraint_residuals(vector):
        residuals = []
        ranges = []
        for constraint in constraints:
            first_residual = len(residuals)
            kind = constraint.get("type")
            if kind == "coincident":
                residuals.extend(point(vector, constraint.get("a")) - point(vector, constraint.get("b")))
            elif kind == "horizontal":
                p0, p1, _, _ = line(vector, constraint.get("entity"))
                residuals.append(p1[1] - p0[1])
            elif kind == "vertical":
                p0, p1, _, _ = line(vector, constraint.get("entity"))
                residuals.append(p1[0] - p0[0])
            elif kind in {"parallel", "perpendicular"}:
                _, _, first, first_length = line(vector, constraint.get("a"))
                _, _, second, second_length = line(vector, constraint.get("b"))
                if kind == "parallel":
                    residuals.append((first[0] * second[1] - first[1] * second[0]) /
                                     (first_length * second_length))
                else:
                    residuals.append(float(np.dot(first, second)) / (first_length * second_length))
            elif kind == "tangent":
                p0, _, delta, length = line(vector, constraint.get("line"))
                center, radius = circle(vector, constraint.get("circle"))
                signed_distance = (delta[0] * (center[1] - p0[1]) -
                                   delta[1] * (center[0] - p0[0])) / length
                residuals.append(signed_distance - float(constraint.get("side", 1)) * radius)
            elif kind == "equal":
                first_id, second_id = constraint.get("a"), constraint.get("b")
                first_kind = spans.get(first_id, (None, None, None))[2]
                second_kind = spans.get(second_id, (None, None, None))[2]
                if first_kind == second_kind == "line":
                    residuals.append(line(vector, first_id)[3] - line(vector, second_id)[3])
                elif first_kind == second_kind == "circle":
                    residuals.append(circle(vector, first_id)[1] - circle(vector, second_id)[1])
                else:
                    raise GeometryError("bad_params", "Equal поддерживает две линии или две окружности.")
            elif kind == "dimension":
                dimension_kind = constraint.get("kind", "distance")
                target = float(constraint.get("value"))
                if dimension_kind in {"length", "radius"}:
                    entity_id = constraint.get("entity")
                    actual = (line(vector, entity_id)[3] if dimension_kind == "length"
                              else circle(vector, entity_id)[1])
                else:
                    first = point(vector, constraint.get("a"))
                    second = point(vector, constraint.get("b"))
                    delta = second - first
                    if dimension_kind == "distance":
                        actual = float(np.linalg.norm(delta))
                    elif dimension_kind == "distance_x":
                        actual = float(delta[0])
                    elif dimension_kind == "distance_y":
                        actual = float(delta[1])
                    else:
                        raise GeometryError("bad_params", f"Неизвестный тип размера: {dimension_kind}.")
                residuals.append(actual - target)
            elif kind == "fix":
                if constraint.get("point") is not None:
                    actual = point(vector, constraint.get("point"))
                    target = np.asarray(constraint.get("value", actual), dtype=float)
                    if target.shape != (2,):
                        raise GeometryError("bad_params", "Fix point требует value [x, y].")
                    residuals.extend(actual - target)
                else:
                    entity_id = constraint.get("entity")
                    if entity_id not in spans:
                        raise GeometryError("bad_params", f"Элемент эскиза не найден: {entity_id}.")
                    start, end, _ = spans[entity_id]
                    target = np.asarray(constraint.get("value", initial[start:end]), dtype=float)
                    if target.shape != (end - start,):
                        raise GeometryError("bad_params", f"Fix {entity_id} имеет неверное число координат.")
                    residuals.extend(vector[start:end] - target)
            else:
                raise GeometryError("bad_params", f"Неизвестное ограничение: {kind}.")
            ranges.append((first_residual, len(residuals)))
        constraint_ranges[:] = ranges
        if drag:
            if "radius" in drag:
                target = drag["radius"]
                if isinstance(target, bool) or not isinstance(target, (int, float)) or not np.isfinite(target) or target <= 0:
                    raise GeometryError("bad_params", "Drag требует положительный конечный радиус.")
                residuals.append(circle(vector, drag.get("entity"))[1] - target)
            else:
                actual = point(vector, drag.get("point"))
                target = np.asarray(drag.get("value"), dtype=float)
                if target.shape != (2,) or not np.isfinite(target).all():
                    raise GeometryError("bad_params", "Drag требует конечные координаты value [x, y].")
                residuals.extend(actual - target)
        return np.asarray(residuals, dtype=float)

    def jacobian(vector, residual):
        matrix = np.empty((len(residual), len(vector)), dtype=float)
        for column in range(len(vector)):
            step = 1e-6 * max(1.0, abs(float(vector[column])))
            shifted = vector.copy()
            shifted[column] += step
            matrix[:, column] = (constraint_residuals(shifted) - residual) / step
        return matrix

    if not constraints and not drag:
        solved = initial.copy()
        residual = np.empty(0)
        matrix = np.empty((0, len(initial)))
    else:
        solved = initial.copy()
        damping = 1e-8
        for _ in range(80):
            residual = constraint_residuals(solved)
            matrix = jacobian(solved, residual)
            if residual.size == 0 or float(np.max(np.abs(residual))) <= tolerance:
                break
            normal = matrix.T @ matrix + damping * np.eye(len(solved))
            delta = np.linalg.solve(normal, -(matrix.T @ residual))
            candidate = solved + delta
            candidate_residual = constraint_residuals(candidate)
            if np.linalg.norm(candidate_residual) < np.linalg.norm(residual):
                solved = candidate
                damping = max(damping / 4, 1e-12)
            else:
                damping = min(damping * 10, 1e8)
        residual = constraint_residuals(solved)
        matrix = jacobian(solved, residual)

    max_residual = float(np.max(np.abs(residual))) if residual.size else 0.0
    rank = int(np.linalg.matrix_rank(matrix, tol=1e-7)) if matrix.size else 0
    degrees_of_freedom = max(0, len(solved) - rank)
    if max_residual > tolerance * 10:
        conflicts = [index for index, (start, end) in enumerate(constraint_ranges) if end > start and float(np.max(np.abs(residual[start:end]))) > tolerance * 10]
        raise GeometryError(
            "constraint_conflict",
            f"Ограничения противоречат друг другу; максимальная невязка {max_residual:.6g}.",
            detail=json.dumps({"max_residual": max_residual, "degrees_of_freedom": degrees_of_freedom, "conflicting_constraints": conflicts}))

    solved_entities = []
    for entity in entities:
        start, _, kind = spans[entity["id"]]
        if kind in ("line", "arc"):
            solved_entities.append({**entity,
                                    "start": solved[start:start + 2].tolist(),
                                    "end": solved[start + 2:start + 4].tolist(),
                                    **({"mid": solved[start + 4:start + 6].tolist()} if kind == "arc" else {})})
        else:
            solved_entities.append({**entity,
                                    "center": solved[start:start + 2].tolist(),
                                    "radius": float(solved[start + 2])})
    redundant = max(0, len(residual) - rank)
    return {
        "status": "fully_constrained" if degrees_of_freedom == 0 else "under_constrained",
        "degrees_of_freedom": degrees_of_freedom,
        "constraint_rank": rank,
        "residual_count": int(len(residual)),
        "redundant_constraints": redundant,
        "max_residual": max_residual,
        "entities": solved_entities,
    }


def _solved_sketch_profile(sketch, solution):
    entity_by_id = {entity["id"]: entity for entity in solution["entities"]}
    regions = sketch.get("regions") or []
    if not regions:
        line_ids = [entity["id"] for entity in solution["entities"] if entity["type"] in ("line", "arc")]
        circle_ids = [entity["id"] for entity in solution["entities"] if entity["type"] == "circle"]
        if line_ids:
            regions = [{"outer": line_ids, "holes": []}]
        elif len(circle_ids) == 1:
            circle_entity = entity_by_id[circle_ids[0]]
            return {"regions": [{"outer": {"kind": "circle", "center": circle_entity["center"],
                                              "radius": circle_entity["radius"]}, "holes": []}]}
        else:
            raise GeometryError("bad_params", "Для нескольких контуров задайте sketch.regions.")

    def contour(entity_ids):
        if isinstance(entity_ids, str):
            entity = entity_by_id.get(entity_ids)
            if not entity or entity["type"] != "circle":
                raise GeometryError("bad_params", f"Контур не найден: {entity_ids}.")
            return {"kind": "circle", "center": entity["center"], "radius": entity["radius"]}
        segments = []
        for entity_id in entity_ids:
            entity = entity_by_id.get(entity_id)
            if not entity or entity["type"] not in ("line", "arc"):
                raise GeometryError("bad_params", f"Линия контура не найдена: {entity_id}.")
            segments.append({"type": entity["type"], "start": entity["start"], "end": entity["end"],
                             **({"mid": entity["mid"]} if entity["type"] == "arc" else {})})
        return {"kind": "segments", "segments": segments}

    return {"regions": [{
        "outer": contour(region.get("outer")),
        "holes": [contour(hole) for hole in region.get("holes") or []],
    } for region in regions]}


def _sketch_point(point, plane_name, offset=0):
    u, v = _finite_point(point, "Точка эскиза")
    if plane_name == "XY":
        return (u, v, offset)
    if plane_name == "XZ":
        return (u, offset, v)
    if plane_name == "YZ":
        return (offset, u, v)
    raise GeometryError("bad_params", f"Неизвестная плоскость эскиза: {plane_name}")


def _points_close(left, right, tolerance=1e-6):
    return math.dist(left, right) <= tolerance


def _sketch_wire(contour, plane_name="XY", offset=0):
    from build123d import Edge, Wire
    kind = contour.get("kind")
    if kind == "polygon":
        points = contour.get("points") or []
        if len(points) < 3:
            raise GeometryError("sketch_open", "Замкнутый контур должен содержать минимум три точки.")
        world_points = [_sketch_point(point, plane_name, offset) for point in points]
        if len(world_points) > 3 and _points_close(world_points[0], world_points[-1]):
            world_points.pop()
        if len(world_points) < 3:
            raise GeometryError("sketch_degenerate", "Контур вырожден и не образует область.")
        wire = Wire.make_polygon(world_points, close=True)
    elif kind == "circle":
        center = _finite_point(contour.get("center") or [0, 0], "Центр окружности")
        radius = _positive_profile_value(contour, "radius", "Радиус окружности")
        plane = _sketch_plane(plane_name, _sketch_point(center, plane_name, offset))
        wire = Wire.make_circle(radius, plane)
    elif kind == "segments":
        segments = contour.get("segments") or []
        if not segments:
            raise GeometryError("sketch_open", "Контур не содержит линий или дуг.")
        edges = []
        first_start = None
        previous_end = None
        for index, segment in enumerate(segments):
            start = _sketch_point(segment.get("start"), plane_name, offset)
            end = _sketch_point(segment.get("end"), plane_name, offset)
            if previous_end is not None and not _points_close(previous_end, start):
                raise GeometryError(
                    "sketch_open",
                    f"Сегменты {index} и {index + 1} не соединены. Совместите их конечные точки.")
            segment_kind = segment.get("type", "line")
            if segment_kind == "line":
                if _points_close(start, end):
                    raise GeometryError("sketch_degenerate", "Линия эскиза имеет нулевую длину.")
                edge = Edge.make_line(start, end)
            elif segment_kind == "arc":
                middle = _sketch_point(segment.get("mid"), plane_name, offset)
                try:
                    edge = Edge.make_three_point_arc(start, middle, end)
                except Exception as exc:
                    raise GeometryError(
                        "sketch_degenerate", "Три точки дуги не должны лежать на одной прямой.") from exc
            else:
                raise GeometryError("bad_params", f"Неизвестный сегмент эскиза: {segment_kind}")
            edges.append(edge)
            first_start = first_start or start
            previous_end = end
        if not _points_close(previous_end, first_start):
            raise GeometryError("sketch_open", "Последняя точка контура не соединена с первой.")
        wire = Wire(edges, sequenced=True)
    else:
        raise GeometryError("bad_params", f"Неизвестный тип контура: {kind}")
    if not wire.is_closed:
        raise GeometryError("sketch_open", "Контур эскиза не замкнут.")
    return wire


def _sketch_faces(profile, plane_name="XY", offset=0):
    from build123d import Face
    regions = profile.get("regions") or []
    if not regions:
        raise GeometryError("bad_params", "Эскиз должен содержать хотя бы одну замкнутую область.")
    if len(regions) > 20:
        raise GeometryError("bad_params", "Эскиз поддерживает не более 20 отдельных областей.")
    faces = []
    for region in regions:
        outer = _sketch_wire(region.get("outer") or {}, plane_name, offset)
        holes = [
            _sketch_wire(contour, plane_name, offset)
            for contour in (region.get("holes") or [])
        ]
        try:
            face = Face(outer, holes)
        except Exception as exc:
            raise GeometryError(
                "sketch_invalid", "Контуры не образуют корректную область эскиза.") from exc
        if not face.is_valid or face.area <= 1e-8:
            raise GeometryError(
                "sketch_invalid",
                "Эскиз самопересекается, вырожден или содержит некорректное отверстие.")
        faces.append(face)
    return faces


def _validated_generated_shape(shape, operation_name):
    if shape is None or not shape.is_valid or not shape.solids() or shape_volume(shape) <= 1e-8:
        raise GeometryError(
            "extended_operation_failed",
            f"Операция «{operation_name}» не создала корректное объёмное тело.")
    return shape


def _generated_part(parts, operation, shape, default_id, default_name, metadata=None):
    from build123d import Compound
    result_id = operation.get("result_id") or default_id
    if result_id in parts:
        raise GeometryError("bad_params", f"Идентификатор результата уже существует: {result_id}")
    solids = shape.solids()
    stored_shape = shape if len(solids) == 1 else Compound(children=solids)
    parts[result_id] = {
        "shape": stored_shape,
        "name": operation.get("name") or default_name,
        "template": "generated",
        "params": {},
    }
    if metadata:
        parts[result_id]["metadata"] = metadata


def _apply_step_source(parts, operation, operation_index):
    from build123d import import_step
    encoded = operation.get("source_base64")
    source_limit = 25 * 1024 * 1024
    if not isinstance(encoded, str) or len(encoded) > ((source_limit + 2) // 3) * 4:
        raise GeometryError("step_source_invalid", "Встроенный STEP отсутствует или превышает 25 MiB.")
    try:
        source = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as error:
        raise GeometryError("step_source_invalid", "Встроенный STEP повреждён.") from error
    if not source or len(source) > source_limit:
        raise GeometryError("step_source_invalid", "STEP должен быть непустым и не превышать 25 MiB.")
    source_hash = hashlib.sha256(source).hexdigest()
    if source_hash != operation.get("source_sha256"):
        raise GeometryError("step_source_invalid", "Контрольная сумма встроенного STEP не совпадает.")
    path = _session_dir / f"source-{source_hash}.step"
    if not path.is_file():
        path.write_bytes(source)
    try:
        shape = import_step(path)
        _validated_generated_shape(shape, "Импорт STEP")
    except Exception as error:
        raise GeometryError("step_invalid", "STEP не содержит корректных замкнутых объёмных тел.") from error
    _generated_part(
        parts, operation, shape, f"part-step-{operation_index + 1}", "Импортированный STEP",
        {"format": "step", "embedded_source": True, "source_sha256": source_hash,
         "source_name": operation.get("source_name", "source.step")},
    )


def _apply_sketch_extrude(parts, operation, operation_index):
    from build123d import Compound, extrude
    depth = _positive_profile_value(operation, "depth", "Глубина выдавливания")
    plane_name = operation.get("plane", "XY")
    faces = _sketch_faces(operation.get("profile") or {}, plane_name)
    solids = [extrude(face, amount=depth) for face in faces]
    shape = solids[0] if len(solids) == 1 else Compound(children=solids)
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Выдавливание эскиза"),
        f"part-sketch-{operation_index + 1}", "Эскиз",
    )


def _apply_constrained_sketch_extrude(parts, operation, operation_index):
    from build123d import Compound, Plane, extrude
    from interaction_geometry import point3
    depth = _positive_profile_value(operation, "depth", "Глубина выдавливания")
    solution = _solve_constrained_sketch(
        operation.get("sketch") or {}, operation.get("drag"))
    profile = _solved_sketch_profile(operation.get("sketch") or {}, solution)
    faces = _sketch_faces(profile, operation.get("plane", "XY"))
    frame = operation.get("frame")
    if frame is not None:
        location = Plane(origin=point3(frame.get("origin"), "Начало эскиза"),
                         x_dir=point3(frame.get("x_dir"), "Ось эскиза"),
                         z_dir=point3(frame.get("normal"), "Нормаль эскиза")).location
        faces = [location * face for face in faces]
    mode = operation.get("mode", "new")
    if mode not in ("new", "add", "cut"):
        raise GeometryError("bad_params", "Выберите новое тело, добавление или вырез.")
    solids = [extrude(face, amount=-depth if mode == "cut" else depth) for face in faces]
    shape = solids[0] if len(solids) == 1 else Compound(children=solids)
    if mode != "new":
        target_id = operation.get("target_id")
        if target_id not in parts:
            raise GeometryError("bad_params", "Деталь для эскиза не найдена.")
        original = parts[target_id]["shape"]
        result = original + shape if mode == "add" else original - shape
        _validated_generated_shape(result, "Эскиз на грани")
        if len(result.solids()) != len(original.solids()) or abs(shape_volume(result) - shape_volume(original)) < 1e-7:
            raise GeometryError("sketch_invalid", "Контур не пересекает выбранное тело или разделяет его. Измените положение и глубину.")
        parts[target_id]["shape"] = result
        return
    metadata = {
        "solver_status": solution["status"],
        "degrees_of_freedom": solution["degrees_of_freedom"],
        "constraint_rank": solution["constraint_rank"],
        "redundant_constraints": solution["redundant_constraints"],
        "max_residual": solution["max_residual"],
        "solved_entities": solution["entities"],
    }
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Ограниченный эскиз"),
        f"part-constrained-sketch-{operation_index + 1}",
        "Ограниченный эскиз", metadata,
    )


def _apply_revolve(parts, operation, operation_index):
    from build123d import Axis, Compound, revolve
    angle = _positive_profile_value(operation, "angle", "Угол вращения")
    if angle > 360:
        raise GeometryError("bad_params", "Угол вращения не должен превышать 360°.")
    axis = operation.get("axis") or {}
    point = axis.get("point") or [0, 0, 0]
    direction = axis.get("direction") or [0, 0, 1]
    if len(point) != 3 or len(direction) != 3:
        raise GeometryError("bad_params", "Ось вращения должна содержать точку и направление XYZ.")
    try:
        values = [float(value) for value in [*point, *direction]]
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Ось вращения должна содержать числа.") from exc
    if not all(math.isfinite(value) for value in values) or math.dist((0, 0, 0), values[3:]) <= 1e-9:
        raise GeometryError("bad_params", "Направление оси вращения не должно быть нулевым.")
    faces = _sketch_faces(
        operation.get("profile") or {}, operation.get("plane", "XZ"))
    try:
        solids = [
            revolve(face, axis=Axis(values[:3], values[3:]), revolution_arc=angle)
            for face in faces
        ]
    except Exception as exc:
        raise GeometryError(
            "revolve_failed",
            "Профиль пересекает ось или создаёт самопересечение. Измените профиль или ось.") from exc
    shape = solids[0] if len(solids) == 1 else Compound(children=solids)
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Вращение"),
        f"part-revolve-{operation_index + 1}", "Тело вращения",
    )


def _path_wire(path):
    from build123d import Wire
    points = path.get("points") or []
    if len(points) < 2:
        raise GeometryError("bad_params", "Траектория должна содержать минимум две точки XYZ.")
    try:
        world_points = [tuple(float(value) for value in point) for point in points]
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Координаты траектории должны быть числами.") from exc
    if any(len(point) != 3 or not all(math.isfinite(value) for value in point)
           for point in world_points):
        raise GeometryError("bad_params", "Каждая точка траектории должна содержать три конечных числа.")
    if any(_points_close(world_points[index - 1], world_points[index])
           for index in range(1, len(world_points))):
        raise GeometryError("bad_params", "Соседние точки траектории не должны совпадать.")
    return Wire.make_polygon(world_points, close=False), world_points


def _apply_sweep(parts, operation, operation_index):
    from build123d import Face, Plane, Wire, sweep
    path, points = _path_wire(operation.get("path") or {})
    section = operation.get("section") or {}
    if section.get("kind") != "circle":
        raise GeometryError("bad_params", "Первый slice sweep поддерживает круглое сечение.")
    radius = _positive_profile_value(section, "radius", "Радиус sweep-сечения")
    tangent = tuple(points[1][index] - points[0][index] for index in range(3))
    section_plane = Plane(origin=points[0], z_dir=tangent)
    section_face = Face(Wire.make_circle(radius, section_plane))
    try:
        shape = sweep(section_face, path, is_frenet=bool(operation.get("frenet", False)))
    except Exception as exc:
        raise GeometryError(
            "sweep_failed",
            "Sweep создаёт самопересечение или некорректную ориентацию сечения.") from exc
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Sweep"),
        f"part-sweep-{operation_index + 1}", "Sweep",
    )


def _apply_loft(parts, operation, operation_index):
    from build123d import loft
    sections = operation.get("sections") or []
    if len(sections) < 2:
        raise GeometryError("bad_params", "Loft требует минимум два сечения.")
    faces = []
    for section in sections:
        offset = float(section.get("offset", 0))
        if not math.isfinite(offset):
            raise GeometryError("bad_params", "Смещение loft-сечения должно быть конечным числом.")
        section_faces = _sketch_faces(
            section.get("profile") or {}, section.get("plane", "XY"), offset)
        if len(section_faces) != 1:
            raise GeometryError("bad_params", "Каждое loft-сечение должно содержать одну область.")
        faces.append(section_faces[0])
    try:
        shape = loft(faces, ruled=bool(operation.get("ruled", True)))
    except Exception as exc:
        raise GeometryError(
            "loft_failed", "Loft не построен. Проверьте порядок и совместимость сечений.") from exc
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Loft"),
        f"part-loft-{operation_index + 1}", "Loft",
    )


def _apply_shell(parts, operation, operation_index):
    from build123d import Cylinder, Pos
    outer_radius = _positive_profile_value(operation, "outer_radius", "Наружный радиус")
    height = _positive_profile_value(operation, "height", "Высота оболочки")
    wall = _positive_profile_value(operation, "wall", "Толщина стенки")
    bottom = _positive_profile_value(operation, "bottom", "Толщина дна")
    if wall >= outer_radius:
        raise GeometryError("bad_params", "Толщина стенки должна быть меньше наружного радиуса.")
    if bottom >= height:
        raise GeometryError("bad_params", "Толщина дна должна быть меньше высоты оболочки.")
    shape = Pos(0, 0, height / 2) * Cylinder(outer_radius, height)
    cavity_height = height - bottom
    cavity = Pos(0, 0, bottom + cavity_height / 2) * Cylinder(
        outer_radius - wall, cavity_height)
    shape -= cavity
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Оболочка"),
        f"part-shell-{operation_index + 1}", "Оболочка",
    )


def _apply_draft_prism(parts, operation, operation_index):
    from build123d import Face, Wire, loft
    width = _positive_profile_value(operation, "width", "Ширина основания")
    depth = _positive_profile_value(operation, "depth", "Глубина основания")
    height = _positive_profile_value(operation, "height", "Высота тела")
    try:
        angle = float(operation.get("angle", 0))
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Угол уклона должен быть числом.") from exc
    if not math.isfinite(angle) or abs(angle) >= 89:
        raise GeometryError("bad_params", "Модуль угла уклона должен быть меньше 89°.")
    inset = height * math.tan(math.radians(angle))
    top_width = width - 2 * inset
    top_depth = depth - 2 * inset
    if min(top_width, top_depth) <= 1e-6:
        raise GeometryError(
            "bad_params", "Уклон сводит верхнее сечение в ноль. Уменьшите угол или высоту.")

    def rectangle_face(face_width, face_depth, z):
        return Face(Wire.make_polygon([
            (-face_width / 2, -face_depth / 2, z),
            (face_width / 2, -face_depth / 2, z),
            (face_width / 2, face_depth / 2, z),
            (-face_width / 2, face_depth / 2, z),
        ], close=True))

    shape = loft([
        rectangle_face(width, depth, 0),
        rectangle_face(top_width, top_depth, height),
    ], ruled=True)
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Тело с уклоном"),
        f"part-draft-{operation_index + 1}", "Тело с уклоном",
    )


def _apply_rib(parts, operation, operation_index):
    from build123d import Box, Face, Pos, Wire, extrude
    base_length = _positive_profile_value(operation, "base_length", "Длина основания")
    base_width = _positive_profile_value(operation, "base_width", "Ширина основания")
    base_thickness = _positive_profile_value(operation, "base_thickness", "Толщина основания")
    rib_length = _positive_profile_value(operation, "rib_length", "Длина ребра")
    rib_height = _positive_profile_value(operation, "rib_height", "Высота ребра")
    rib_width = _positive_profile_value(operation, "rib_width", "Толщина ребра")
    overlap = _positive_profile_value(operation, "overlap", "Заглубление ребра")
    if rib_length > base_length / 2 or rib_width > base_width:
        raise GeometryError("bad_params", "Ребро выходит за границы основания.")
    if overlap >= base_thickness:
        raise GeometryError("bad_params", "Заглубление ребра должно быть меньше толщины основания.")
    base = Pos(0, 0, base_thickness / 2) * Box(base_length, base_width, base_thickness)
    rib_face = Face(Wire.make_polygon([
        (0, -rib_width / 2, base_thickness - overlap),
        (rib_length, -rib_width / 2, base_thickness - overlap),
        (0, -rib_width / 2, base_thickness + rib_height),
    ], close=True))
    rib = extrude(rib_face, amount=rib_width, dir=(0, 1, 0))
    shape = base + rib
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Ребро жёсткости"),
        f"part-rib-{operation_index + 1}", "Ребро жёсткости",
    )


FIT_FIXTURES = {
    "nut_m5": {
        "version": "1", "kind": "hex", "nominal_size": 8.0, "depth": 4.0,
        "label": "Гайка M5, карман 8 × 4 мм",
    },
    "bearing_608": {
        "version": "1", "kind": "circle", "nominal_size": 22.0, "depth": 7.0,
        "label": "Подшипник 608, карман Ø22 × 7 мм",
    },
    "heat_insert_m3": {
        "version": "1", "kind": "stepped", "nominal_size": 4.6,
        "pilot_size": 4.0, "depth": 5.0,
        "label": "Термовставка M3, Ø4.6 × 5 мм, пилот Ø4 мм",
    },
}

VECTOR_SOURCE_LIMIT = 1_000_000
DXF_UNIT_TO_MM = {
    1: 25.4, 2: 304.8, 4: 1.0, 5: 10.0, 6: 1000.0,
    7: 1_000_000.0, 8: 0.0000254, 9: 0.0254, 10: 914.4,
    11: 1e-7, 12: 1e-6, 13: 0.001, 14: 100.0,
}
TEXT_FONT_VERSION = "JetBrains Mono 2.211"
TEXT_FONT_SHA256 = "48715a42ec242c21e9f02692891e147d022299a52e48d5e413e1a942193ffeda"
THREAD_PROFILE_VERSION = "metric-60-v1"


def _source_text(operation):
    source = operation.get("source_text")
    if not isinstance(source, str) or not source.strip():
        raise GeometryError("bad_params", "Векторный источник пуст.")
    if len(source.encode("utf-8")) > VECTOR_SOURCE_LIMIT:
        raise GeometryError("bad_params", "Векторный источник превышает лимит 1 МБ.")
    return source


def _validate_svg(source):
    from xml.etree import ElementTree
    lowered = source.lower()
    if "<!doctype" in lowered or "<!entity" in lowered or "url(" in lowered or "@import" in lowered:
        raise GeometryError("vector_unsafe", "SVG содержит запрещённую внешнюю или entity-ссылку.")
    try:
        root = ElementTree.fromstring(source)
    except ElementTree.ParseError as exc:
        raise GeometryError("vector_invalid", "SVG не является корректным XML.") from exc
    forbidden = {"script", "image", "foreignobject"}
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1].lower()
        if tag in forbidden:
            raise GeometryError("vector_unsafe", f"SVG-элемент {tag} не поддерживается.")
        for name, value in element.attrib.items():
            local_name = name.rsplit("}", 1)[-1].lower()
            if local_name == "href" and value and not value.startswith("#"):
                raise GeometryError("vector_unsafe", "SVG не должен загружать внешние ресурсы.")
    factors = {"mm": 1, "cm": 10, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "q": 0.25}
    length_attributes = {"width", "height", "x", "y", "x1", "x2", "y1", "y2", "r", "rx", "ry", "stroke-width"}
    length_pattern = re.compile(r"\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(mm|cm|in|pt|pc|q)\s*", re.IGNORECASE)
    for element in root.iter():
        for name, value in list(element.attrib.items()):
            if name.rsplit("}", 1)[-1] not in length_attributes:
                continue
            match = length_pattern.fullmatch(value)
            if match:
                element.set(name, format(float(match[1]) * factors[match[2].lower()], ".17g"))
    return ElementTree.tostring(root, encoding="unicode")


def _vector_faces(shapes):
    from build123d import Face, Wire
    faces = [shape for shape in shapes if isinstance(shape, Face)]
    wires = [shape for shape in shapes if isinstance(shape, Wire)]
    if len(faces) + len(wires) != len(shapes):
        raise GeometryError("vector_unsupported", "Источник содержит неподдерживаемую векторную сущность.")
    if any(not wire.is_closed for wire in wires):
        raise GeometryError("vector_open", "Векторный контур не замкнут.")
    if wires:
        candidates = [{"wire": wire, "face": Face(wire), "parent": None} for wire in wires]
        candidates.sort(key=lambda item: item["face"].area, reverse=True)
        for index, item in enumerate(candidates):
            point = item["wire"].center()
            parents = [
                (parent_index, parent)
                for parent_index, parent in enumerate(candidates[:index])
                if parent["face"].is_inside(point)
            ]
            if parents:
                item["parent"] = min(parents, key=lambda entry: entry[1]["face"].area)[0]

        def depth(index):
            value = 0
            parent = candidates[index]["parent"]
            while parent is not None:
                value += 1
                parent = candidates[parent]["parent"]
            return value

        for index, item in enumerate(candidates):
            if depth(index) % 2:
                continue
            holes = [
                child["wire"] for child_index, child in enumerate(candidates)
                if child["parent"] == index and depth(child_index) % 2 == 1
            ]
            faces.append(Face(item["wire"], holes))
    if not faces or any(not face.is_valid or face.area <= 1e-8 for face in faces):
        raise GeometryError("vector_invalid", "Векторные контуры не образуют корректную область.")
    return faces


def _apply_vector_extrude(parts, operation, operation_index):
    from io import StringIO
    from build123d import Compound, import_dxf, import_svg, extrude
    source = _source_text(operation)
    vector_format = str(operation.get("format", "")).lower()
    if vector_format == "svg":
        source = _validate_svg(source)
        try:
            shapes = list(import_svg(StringIO(source), flip_y=False))
        except Exception as exc:
            raise GeometryError("vector_invalid", "SVG не удалось преобразовать в контуры.") from exc
    elif vector_format == "dxf":
        import ezdxf
        try:
            document = ezdxf.read(StringIO(source))
        except Exception as exc:
            raise GeometryError("vector_invalid", "DXF не удалось прочитать.") from exc
        allowed_entities = {"LWPOLYLINE", "POLYLINE", "LINE", "ARC", "CIRCLE", "ELLIPSE", "SPLINE"}
        unsupported = sorted({entity.dxftype() for entity in document.modelspace()} - allowed_entities)
        if unsupported:
            raise GeometryError(
                "vector_unsupported", f"DXF содержит неподдерживаемые сущности: {', '.join(unsupported)}")
        unit_code = int(document.header.get("$INSUNITS", 0))
        if unit_code == 0:
            try:
                unit_scale = float(operation["unit_scale"])
            except (KeyError, TypeError, ValueError) as exc:
                raise GeometryError(
                    "vector_units_required", "DXF без единиц требует явный масштаб в миллиметрах.") from exc
        else:
            unit_scale = DXF_UNIT_TO_MM.get(unit_code)
            if unit_scale is None:
                raise GeometryError("vector_units_required", f"Единицы DXF с кодом {unit_code} не поддерживаются.")
        try:
            shapes = [shape.scale(unit_scale) for shape in import_dxf(StringIO(source))]
        except Exception as exc:
            raise GeometryError("vector_invalid", "DXF не удалось преобразовать в контуры.") from exc
    else:
        raise GeometryError("bad_params", "Векторный формат должен быть svg или dxf.")
    height = _positive_profile_value(operation, "height", "Высота векторного выдавливания")
    faces = _vector_faces(shapes)
    solids = [extrude(face, amount=height) for face in faces]
    shape = solids[0] if len(solids) == 1 else Compound(children=solids)
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Векторное выдавливание"),
        f"part-vector-{operation_index + 1}", "Векторное тело",
        {"format": vector_format, "embedded_source": True},
    )


def _text_font_path():
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "assets" / "jetbrainsmono.ttf"
    development = (
        Path(__file__).resolve().parent.parent / "design-sources" / "impeccable" /
        "ui" / "component-review" / "fonts" / "jetbrainsmono.ttf")
    path = bundled if bundled.is_file() else development
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != TEXT_FONT_SHA256:
        raise GeometryError("font_missing", "Фиксированный шрифт JetBrains Mono 2.211 отсутствует или изменён.")
    return path


def _apply_text_relief(parts, operation, operation_index):
    from build123d import Box, Pos, Text, extrude
    text = operation.get("text")
    if not isinstance(text, str) or not text or len(text) > 80 or "\n" in text:
        raise GeometryError("bad_params", "Текст должен содержать от 1 до 80 символов в одной строке.")
    font_size = _positive_profile_value(operation, "font_size", "Размер текста")
    relief_height = _positive_profile_value(operation, "relief_height", "Высота рельефа")
    body_length = _positive_profile_value(operation, "body_length", "Длина основания")
    body_width = _positive_profile_value(operation, "body_width", "Ширина основания")
    body_height = _positive_profile_value(operation, "body_height", "Толщина основания")
    mode = operation.get("mode", "add")
    if mode not in {"add", "cut"}:
        raise GeometryError("bad_params", "Режим текста должен быть add или cut.")
    if mode == "cut" and relief_height >= body_height:
        raise GeometryError("bad_params", "Глубина гравировки должна оставлять дно основания.")
    try:
        sketch = Text(text, font_size, font_path=_text_font_path()).fix()
    except Exception as exc:
        raise GeometryError("font_glyph_missing", "Шрифт не содержит один из символов текста.") from exc
    text_box = sketch.bounding_box().size
    if text_box.X >= body_length or text_box.Y >= body_width:
        raise GeometryError("bad_params", "Текст не помещается на основании.")
    base = Pos(0, 0, body_height / 2) * Box(body_length, body_width, body_height)
    tool_z = body_height if mode == "add" else body_height - relief_height
    tool = extrude(Pos(0, 0, tool_z) * sketch, amount=relief_height)
    shape = base + tool if mode == "add" else base - tool
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Текстовый рельеф"),
        f"part-text-{operation_index + 1}", "Текстовый рельеф",
        {
            "font": TEXT_FONT_VERSION, "font_sha256": TEXT_FONT_SHA256,
            "text": text, "mode": mode,
        },
    )


def _threaded_external_shape(major_diameter, pitch, length, left_hand=False):
    from build123d import Cylinder, Face, Helix, Pos, Wire, sweep
    depth = 0.61343 * pitch
    core_radius = major_diameter / 2 - depth
    if core_radius <= 0:
        raise GeometryError("bad_params", "Диаметр слишком мал для заданного шага резьбы.")
    path_radius = (core_radius + major_diameter / 2) / 2
    half_width = depth * math.tan(math.radians(30))
    overlap = min(0.03, depth * 0.05)
    profile = Face(Wire.make_polygon([
        (core_radius - overlap, 0, -half_width),
        (major_diameter / 2, 0, 0),
        (core_radius - overlap, 0, half_width),
    ], close=True))
    helix = Helix(
        pitch=pitch, height=length, radius=path_radius, lefthand=left_hand)
    tooth = sweep(profile, helix, is_frenet=True)
    envelope = Pos(0, 0, length / 2) * Cylinder(major_diameter / 2, length)
    core = Pos(0, 0, length / 2) * Cylinder(core_radius, length)
    return _validated_generated_shape(core + (tooth & envelope), "Винтовая резьба"), core_radius


def _apply_thread_pair(parts, operation, operation_index):
    from build123d import Face, Pos, Wire, extrude
    major_diameter = _positive_profile_value(operation, "major_diameter", "Наружный диаметр")
    pitch = _positive_profile_value(operation, "pitch", "Шаг резьбы")
    length = _positive_profile_value(operation, "length", "Длина резьбы")
    nut_height = _positive_profile_value(operation, "nut_height", "Высота гайки")
    nut_across_flats = _positive_profile_value(
        operation, "nut_across_flats", "Размер гайки под ключ")
    clearance = _positive_profile_value(operation, "clearance", "Диаметральный зазор")
    if str(operation.get("profile_version", THREAD_PROFILE_VERSION)) != THREAD_PROFILE_VERSION:
        raise GeometryError("bad_params", "Поддерживается только профиль metric-60-v1.")
    hand = operation.get("hand", "right")
    if hand not in {"right", "left"}:
        raise GeometryError("bad_params", "Направление резьбы должно быть right или left.")
    if int(operation.get("starts", 1)) != 1:
        raise GeometryError("bad_params", "Текущий thread-pair поддерживает однозаходную резьбу.")
    if length < pitch or nut_height >= length:
        raise GeometryError("bad_params", "Длина резьбы должна быть не меньше шага и больше высоты гайки.")
    if nut_across_flats <= major_diameter + clearance:
        raise GeometryError("bad_params", "Гайка не оставляет стенку вокруг резьбы.")

    bolt, core_radius = _threaded_external_shape(
        major_diameter, pitch, length, hand == "left")
    assembly_z = (length - nut_height) / 2
    nut_radius = nut_across_flats / math.sqrt(3)
    nut_points = [
        (nut_radius * math.cos(math.radians(30 + 60 * index)),
         nut_radius * math.sin(math.radians(30 + 60 * index)), assembly_z)
        for index in range(6)
    ]
    nut_blank = extrude(Face(Wire.make_polygon(nut_points, close=True)), amount=nut_height)
    cutter_length = nut_height + 2 * pitch
    cutter, _ = _threaded_external_shape(
        major_diameter + clearance, pitch, cutter_length, hand == "left")
    nut = nut_blank - (Pos(0, 0, assembly_z - pitch) * cutter)
    _validated_generated_shape(nut, "Внутренняя резьба")
    intersection_volume = (bolt & nut).volume
    if intersection_volume > 1e-6:
        raise GeometryError(
            "thread_clearance_failed",
            "Резьбовая пара пересекается. Увеличьте зазор или измените размеры.",
            detail=f"intersection_volume={intersection_volume:.9f}")
    base_id = operation.get("result_id") or f"thread-{operation_index + 1}"
    bolt_id, nut_id = f"{base_id}-bolt", f"{base_id}-nut"
    if bolt_id in parts or nut_id in parts:
        raise GeometryError("bad_params", f"Идентификатор результата уже существует: {base_id}")
    common = {
        "profile_version": THREAD_PROFILE_VERSION,
        "major_diameter": major_diameter,
        "pitch": pitch,
        "lead": pitch,
        "starts": 1,
        "hand": hand,
        "clearance": clearance,
        "working_length": length,
        "assembly_intersection_volume": intersection_volume,
    }
    parts[bolt_id] = {
        "shape": bolt, "name": "Резьбовой стержень", "template": "generated", "params": {},
        "metadata": {**common, "role": "external", "core_radius": core_radius},
    }
    parts[nut_id] = {
        "shape": nut, "name": "Резьбовая гайка", "template": "generated", "params": {},
        "metadata": {**common, "role": "internal", "nut_height": nut_height},
    }


def _apply_clearance_calibration(parts, operation, operation_index):
    from build123d import Box, Cylinder, Pos, Text, extrude
    values = operation.get("values") or []
    if not isinstance(values, list) or not 2 <= len(values) <= 10:
        raise GeometryError("bad_params", "Калибровка требует от 2 до 10 значений зазора.")
    try:
        clearances = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Значения зазора должны быть числами.") from exc
    if (any(not math.isfinite(value) or value < 0 for value in clearances) or
            len(set(clearances)) != len(clearances)):
        raise GeometryError("bad_params", "Зазоры должны быть конечными, неотрицательными и уникальными.")
    nominal_diameter = _positive_profile_value(
        operation, "nominal_diameter", "Номинальный диаметр")
    coupon_length = _positive_profile_value(operation, "coupon_length", "Длина образца")
    coupon_width = _positive_profile_value(operation, "coupon_width", "Ширина образца")
    thickness = _positive_profile_value(operation, "thickness", "Толщина образца")
    spacing = _positive_profile_value(operation, "spacing", "Шаг размещения")
    font_size = _positive_profile_value(operation, "font_size", "Размер метки")
    label_height = _positive_profile_value(operation, "label_height", "Высота метки")
    if spacing < coupon_length:
        raise GeometryError("bad_params", "Шаг размещения должен быть не меньше длины образца.")
    if nominal_diameter + max(clearances) >= min(coupon_length, coupon_width):
        raise GeometryError("bad_params", "Максимальное отверстие не оставляет стенку образца.")
    font_path = _text_font_path()
    base_id = operation.get("result_id") or f"calibration-{operation_index + 1}"
    for index, clearance in enumerate(clearances):
        part_id = f"{base_id}-{index + 1}"
        if part_id in parts:
            raise GeometryError("bad_params", f"Идентификатор результата уже существует: {part_id}")
        center_x = index * spacing
        base = Pos(center_x, 0, thickness / 2) * Box(
            coupon_length, coupon_width, thickness)
        effective_diameter = nominal_diameter + clearance
        hole = Pos(center_x, coupon_width / 5, thickness / 2) * Cylinder(
            effective_diameter / 2, thickness * 2)
        label = f"{clearance:.2f}"
        label_sketch = Text(label, font_size, font_path=font_path).fix()
        label_box = label_sketch.bounding_box().size
        if label_box.X >= coupon_length or label_box.Y >= coupon_width / 2:
            raise GeometryError("bad_params", "Метка зазора не помещается на образце.")
        label_tool = extrude(
            Pos(center_x, -coupon_width / 4, thickness) * label_sketch,
            amount=label_height)
        shape = _validated_generated_shape((base - hole) + label_tool, "Калибровочный образец")
        parts[part_id] = {
            "shape": shape,
            "name": f"Зазор {label} мм",
            "template": "generated",
            "params": {},
            "metadata": {
                "calibration_profile": operation.get("profile_name") or "Без профиля",
                "sample_index": index,
                "label": label,
                "clearance": clearance,
                "clearance_mode": "diametral",
                "nominal_diameter": nominal_diameter,
                "effective_diameter": effective_diameter,
                "font": TEXT_FONT_VERSION,
            },
        }


def _apply_split_connector_pair(parts, operation, operation_index):
    from build123d import Box, Cylinder, Pos, Rotation
    length = _positive_profile_value(operation, "length", "Длина исходной детали")
    width = _positive_profile_value(operation, "width", "Ширина исходной детали")
    height = _positive_profile_value(operation, "height", "Высота исходной детали")
    pin_radius = _positive_profile_value(operation, "pin_radius", "Радиус штифта")
    pin_length = _positive_profile_value(operation, "pin_length", "Длина штифта")
    radial_clearance = _positive_profile_value(
        operation, "radial_clearance", "Радиальный зазор")
    print_separation = _positive_profile_value(
        operation, "print_separation", "Зазор печатного размещения")
    overlap = min(0.2, pin_length * 0.1)
    hole_extra = min(0.5, pin_length * 0.2)
    if pin_length + hole_extra >= length / 2:
        raise GeometryError("bad_params", "Штифт и отверстие не помещаются в половине детали.")
    if pin_radius + radial_clearance >= min(width / 4, height / 2):
        raise GeometryError("bad_params", "Соединитель не оставляет достаточную стенку.")

    left = Pos(-length / 4, 0, height / 2) * Box(length / 2, width, height)
    right = Pos(length / 4, 0, height / 2) * Box(length / 2, width, height)
    connector_centers = []
    for center_y in (-width / 4, width / 4):
        pin = (
            Pos((pin_length - overlap) / 2, center_y, height / 2)
            * Rotation(0, 90, 0)
            * Cylinder(pin_radius, pin_length + overlap)
        )
        hole_length = pin_length + hole_extra
        hole = (
            Pos(hole_length / 2, center_y, height / 2)
            * Rotation(0, 90, 0)
            * Cylinder(pin_radius + radial_clearance, hole_length)
        )
        left += pin
        right -= hole
        connector_centers.append([0, center_y, height / 2])
    left = _validated_generated_shape(left, "Половина со штифтами")
    right = _validated_generated_shape(right, "Половина с ответными отверстиями")
    assembly_intersection = (left & right).volume
    if assembly_intersection > 1e-6:
        raise GeometryError(
            "connector_intersection",
            "Штифты пересекаются с ответной частью. Увеличьте зазор.",
            detail=f"intersection_volume={assembly_intersection:.9f}")
    placement_y = width + print_separation
    placed_right = Pos(0, placement_y, 0) * right
    base_id = operation.get("result_id") or f"connector-{operation_index + 1}"
    left_id, right_id = f"{base_id}-pins", f"{base_id}-sockets"
    if left_id in parts or right_id in parts:
        raise GeometryError("bad_params", f"Идентификатор результата уже существует: {base_id}")
    common = {
        "source_bbox": [length, width, height],
        "source_volume": length * width * height,
        "split_axis": "x",
        "connector_centers": connector_centers,
        "pin_radius": pin_radius,
        "pin_length": pin_length,
        "radial_clearance": radial_clearance,
        "assembly_intersection_volume": assembly_intersection,
    }
    parts[left_id] = {
        "shape": left, "name": "Часть со штифтами", "template": "generated", "params": {},
        "metadata": {**common, "role": "pins", "print_translation": [0, 0, 0]},
    }
    parts[right_id] = {
        "shape": placed_right, "name": "Часть с отверстиями", "template": "generated", "params": {},
        "metadata": {
            **common, "role": "sockets", "print_translation": [0, placement_y, 0],
            "assembly_translation": [0, -placement_y, 0],
        },
    }


def _apply_fit_pocket(parts, operation, operation_index):
    from build123d import Box, Cylinder, Face, Pos, Wire, extrude
    fixture_id = operation.get("fixture_id")
    fixture = FIT_FIXTURES.get(fixture_id)
    if fixture is None:
        raise GeometryError("bad_params", f"Неизвестная размерная fixture посадки: {fixture_id}")
    requested_version = str(operation.get("fixture_version", fixture["version"]))
    if requested_version != fixture["version"]:
        raise GeometryError(
            "bad_params",
            f"Fixture {fixture_id} версии {requested_version} не поддерживается; доступна {fixture['version']}.")
    body_length = _positive_profile_value(operation, "body_length", "Длина корпуса")
    body_width = _positive_profile_value(operation, "body_width", "Ширина корпуса")
    body_height = _positive_profile_value(operation, "body_height", "Высота корпуса")
    try:
        clearance = float(operation.get("clearance", 0))
    except (TypeError, ValueError) as exc:
        raise GeometryError("bad_params", "Зазор посадки должен быть числом.") from exc
    if not math.isfinite(clearance) or clearance < 0:
        raise GeometryError("bad_params", "Зазор посадки должен быть конечным и неотрицательным.")
    clearance_mode = operation.get("clearance_mode", "diametral")
    if clearance_mode == "radial":
        size_delta, center_x = 2 * clearance, 0.0
    elif clearance_mode == "diametral":
        size_delta, center_x = clearance, 0.0
    elif clearance_mode == "one_sided":
        size_delta, center_x = clearance, clearance / 2
    else:
        raise GeometryError("bad_params", f"Неизвестный смысл зазора: {clearance_mode}")
    effective_size = fixture["nominal_size"] + size_delta
    depth = float(operation.get("pocket_depth", fixture["depth"]))
    if not math.isfinite(depth) or depth <= 0 or depth >= body_height:
        raise GeometryError("bad_params", "Глубина посадки должна оставлять дно корпуса.")
    if effective_size >= min(body_length, body_width):
        raise GeometryError("bad_params", "Посадка не оставляет стенку корпуса.")

    body = Pos(0, 0, body_height / 2) * Box(body_length, body_width, body_height)
    cutter_origin_z = body_height - depth
    kind = fixture["kind"]
    if kind == "circle":
        cutter = Pos(center_x, 0, cutter_origin_z + depth / 2) * Cylinder(
            effective_size / 2, depth)
    elif kind == "hex":
        radius = effective_size / math.sqrt(3)
        points = [
            (center_x + radius * math.cos(math.radians(30 + 60 * index)),
             radius * math.sin(math.radians(30 + 60 * index)), cutter_origin_z)
            for index in range(6)
        ]
        cutter = extrude(Face(Wire.make_polygon(points, close=True)), amount=depth)
    else:
        insert = Pos(center_x, 0, cutter_origin_z + depth / 2) * Cylinder(
            effective_size / 2, depth)
        pilot_size = fixture["pilot_size"] + size_delta
        pilot_height = body_height - depth
        pilot = Pos(center_x, 0, pilot_height / 2) * Cylinder(pilot_size / 2, pilot_height)
        cutter = insert + pilot
    shape = body - cutter
    metadata = {
        "fixture_id": fixture_id,
        "fixture_version": fixture["version"],
        "fixture_label": fixture["label"],
        "clearance": clearance,
        "clearance_mode": clearance_mode,
        "effective_size": effective_size,
        "pocket_center_x": center_x,
        "pocket_depth": depth,
    }
    _generated_part(
        parts, operation, _validated_generated_shape(shape, "Посадка"),
        f"part-fit-{operation_index + 1}", "Посадка", metadata,
    )


def apply_part_operations(parts, operations):
    """Операции над деталями документа v3. parts: {part_id: {"shape": Shape,
    "name": str}}. Возвращает изменённый словарь."""
    from build123d import Compound, Pos
    from build123d import Plane
    mates = {}
    for operation_index, op in enumerate(operations or []):
        kind = op.get("op")
        if op.get("enabled") is False:
            continue
        pid = op.get("part_id")
        changed_id = op.get("target_id", pid)
        before_feature = parts[changed_id]["shape"] if changed_id in parts and kind in ("face_feature", "fillet", "chamfer") else None
        if kind == "step_source":
            _apply_step_source(parts, op, operation_index)
        elif kind == "sketch_extrude":
            _apply_sketch_extrude(parts, op, operation_index)
        elif kind == "constrained_sketch_extrude":
            _apply_constrained_sketch_extrude(parts, op, operation_index)
        elif kind == "revolve":
            _apply_revolve(parts, op, operation_index)
        elif kind == "sweep":
            _apply_sweep(parts, op, operation_index)
        elif kind == "loft":
            _apply_loft(parts, op, operation_index)
        elif kind == "shell":
            _apply_shell(parts, op, operation_index)
        elif kind == "draft_prism":
            _apply_draft_prism(parts, op, operation_index)
        elif kind == "rib":
            _apply_rib(parts, op, operation_index)
        elif kind == "fit_pocket":
            _apply_fit_pocket(parts, op, operation_index)
        elif kind == "vector_extrude":
            _apply_vector_extrude(parts, op, operation_index)
        elif kind == "text_relief":
            _apply_text_relief(parts, op, operation_index)
        elif kind == "thread_pair":
            _apply_thread_pair(parts, op, operation_index)
        elif kind == "clearance_calibration":
            _apply_clearance_calibration(parts, op, operation_index)
        elif kind == "split_connector_pair":
            _apply_split_connector_pair(parts, op, operation_index)
        elif kind == "boolean":
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
        elif kind == "resize_parametric":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Тело для изменения габаритов не найдено.")
            parts[target_id]["shape"] = _resize_parametric(parts[target_id], op, target_id)
        elif kind == "resize_body":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Тело для изменения формы не найдено.")
            parts[target_id]["shape"] = _resize_body(parts[target_id]["shape"], op)
        elif kind == "transform":
            from build123d import Rotation
            t = op.get("translate") or [0, 0, 0]
            rotation = op.get("rotate_deg") or [0, 0, 0]
            pivot = op.get("pivot") or [0, 0, 0]
            if any(not isinstance(vector, list) or len(vector) != 3 or
                   any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) for value in vector)
                   for vector in (t, rotation, pivot)):
                raise GeometryError("bad_params", "Перемещение, поворот и центр должны содержать три конечных числа.")
            location = Pos(*t) * Pos(*pivot) * Rotation(*rotation) * Pos(*[-value for value in pivot])
            parts[pid]["shape"] = location * parts[pid]["shape"]
            parts[pid]["_feature_faces"] = [(location * face, index) for face, index in parts[pid].get("_feature_faces", [])]
        elif kind == "mate":
            if pid in mates:
                raise GeometryError("dependency_conflict", "У тела уже есть активная сборочная связь. Измените или выключите её.")
            mates[pid] = op
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
        elif kind == "face_offset":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Деталь для перемещения грани не найдена.")
            parts[target_id]["shape"] = _apply_face_offset(parts[target_id]["shape"], op)
        elif kind == "face_shell":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Деталь для оболочки не найдена.")
            parts[target_id]["shape"] = _apply_face_shell(parts[target_id]["shape"], op)
        elif kind == "face_feature":
            target_id = op.get("target_id")
            if target_id not in parts:
                raise GeometryError("bad_params", "Деталь для элемента на грани не найдена.")
            resolved = resolve_feature(op, parts[target_id]["shape"], operations, op.get("_history_index", operation_index))
            parts[target_id]["shape"] = _apply_face_feature(parts[target_id]["shape"], resolved)
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
            perpendicular = [previous for previous in bend_operations
                             if previous.get("bend_axis") != op.get("bend_axis")]
            if perpendicular:
                face_ref = op.get("face_ref") or {}
                if face_ref.get("axis") == "z":
                    raise GeometryError(
                        "bend_failed",
                        "Последовательные изгибы должны быть параллельны и использовать одну ось.")
                if len(bend_operations) != 1:
                    raise GeometryError(
                        "bend_failed",
                        "Перпендикулярный изгиб фланца должен следовать сразу после одного базового изгиба.")
                parts[target_id]["shape"] = _apply_perpendicular_flange_bend(
                    parts[target_id], bend_operations[0], op, flat_features)
            else:
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
            if pid in parts:
                parts[pid].pop("_design", None)
            plane = op.get("plane", "XZ")
            try:
                off = float(op.get("offset", 0))
            except (TypeError, ValueError, OverflowError) as exc:
                raise GeometryError("bad_params", "Положение плоскости должно быть конечным числом.") from exc
            if not math.isfinite(off):
                raise GeometryError("bad_params", "Положение плоскости должно быть конечным числом.")
            pl = {"XY": Plane.XY, "XZ": Plane.XZ, "YZ": Plane.YZ}.get(plane)
            if pl is None:
                raise GeometryError("bad_params", f"неизвестная плоскость: {plane}")
            if pid not in parts:
                raise GeometryError("bad_params", "Деталь для разделения не найдена.")
            base = parts[pid]["shape"]
            from build123d import Keep
            kernel_offset = -off if op.get("separate", False) and plane == "XZ" else off
            cut = base.split(pl.offset(kernel_offset), keep=Keep.BOTH)
            pending = [cut]
            halves = []
            while pending:
                candidate = pending.pop(0)
                if isinstance(candidate, (list, tuple)):
                    pending[0:0] = candidate
                elif candidate is not None:
                    halves.extend(candidate.solids())
            if len(halves) < 2:
                raise GeometryError(
                    "split_failed",
                    "Плоскость не разделяет деталь на две части. Сместите плоскость внутрь тела.")
            name = parts[pid]["name"]
            if op.get("separate", False):
                if len(halves) <= len(base.solids()):
                    raise GeometryError(
                        "split_failed",
                        "Плоскость не пересекает материал детали. Сместите плоскость внутрь тела.")
                if any(not solid.is_valid or solid.volume <= 1e-8 for solid in halves):
                    raise GeometryError("split_failed", "Разделение создаёт некорректную геометрию.")
                total_volume = sum(solid.volume for solid in halves)
                base_volume = shape_volume(base)
                if abs(total_volume - base_volume) > max(1e-4, abs(base_volume) * 1e-6):
                    raise GeometryError("split_failed", "Разделение изменяет объём детали. Выберите другую плоскость.")
                halves.sort(key=lambda solid: tuple(round(value, 7) for value in solid.center()))
                generated_ids = [
                    f"{pid}-split-{operation_index + 1}-part-{half_index + 1}"
                    for half_index in range(1, len(halves))
                ]
                if any(new_id in parts for new_id in generated_ids):
                    raise GeometryError("split_failed", "Идентификаторы частей конфликтуют. Повторите разделение.")
                parts[pid]["shape"] = halves[0]
                parts[pid]["name"] = f"{name} (часть 1)"
                for half_index, new_id in enumerate(generated_ids, start=1):
                    parts[new_id] = {
                        "shape": halves[half_index],
                        "name": f"{name} (часть {half_index + 1})",
                    }
                continue
            parts[pid]["shape"] = halves[0]
            parts[pid]["name"] = f"{name} (часть 1)"
            new_id = f"{pid}-part2"
            parts[new_id] = {"shape": halves[1], "name": f"{name} (часть 2)"}
        else:
            raise GeometryError("unknown_op", f"Неизвестная операция: {kind}")
        changed_id = op.get("target_id", pid)
        if before_feature is not None:
            created = new_feature_faces(before_feature, parts[changed_id]["shape"], op)
            parts[changed_id].setdefault("_feature_faces", []).extend((face, op.get("_history_index", operation_index)) for face in created)
        if changed_id in parts and kind != "resize_parametric":
            design = parts[changed_id].get("_design")
            if design and kind in ("fillet", "chamfer", "face_offset", "face_feature", "face_dome", "transform") and not any(op.get("rotate_deg") or []):
                design["operations"].append({**copy.deepcopy(op), "_history_index": op.get("_history_index", operation_index)})
            else:
                parts[changed_id].pop("_design", None)
        if kind == "split":
            for result_id, part in parts.items():
                if result_id.startswith(f"{pid}-split-"):
                    part.pop("_design", None)
    applied, visiting = set(), set()

    def apply_mate(part_id):
        if part_id in applied or part_id not in mates:
            return
        if part_id in visiting:
            raise GeometryError("dependency_conflict", "Сборочные связи образуют цикл. Освободите одну из деталей.")
        visiting.add(part_id)
        operation = mates[part_id]
        apply_mate(operation.get("fixed_id"))
        shape, location = mate_shape(parts, operation)
        parts[part_id]["shape"] = shape
        parts[part_id]["_feature_faces"] = [(location * face, index) for face, index in parts[part_id].get("_feature_faces", [])]
        visiting.remove(part_id)
        applied.add(part_id)

    for part_id in mates:
        apply_mate(part_id)
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
            **({"_design": {"template": template, "params": copy.deepcopy(tp), "operations": []}}
               if template in ("box", "plate_with_holes", "cylinder", "washer", "sphere") else {}),
        }
    parts = apply_part_operations(parts, params.get("operations"))
    compound = Compound(children=[p["shape"] for p in parts.values()])
    extra = {"_feature_faces": [feature for part in parts.values() for feature in part.get("_feature_faces", [])], "parts": [{
        "part_id": pid, "name": p["name"],
        "volume": shape_volume(p["shape"]),
        "bbox": shape_bounds(p["shape"]),
        "parametric_resize": "_design" in p,
        "size_constraint": "uniform" if p.get("template") == "sphere" else "radial" if p.get("template") in ("cylinder", "washer") else "free",
        "solid_count": len(p["shape"].solids()),
        **({"metadata": p["metadata"]} if p.get("metadata") else {}),
    } for pid, p in parts.items()]}
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
    if "parts" in params:
        return handle_build_v3(params)
    return build_document(params)


def handle_designer_action(params):
    from designer_actions import APPEND_OPERATIONS, edit_operations
    document = copy.deepcopy(params.get("document") or {})
    action = params.get("action") or {}
    operations = document.get("operations") or []
    kind = action.get("type")
    if kind == "append":
        operation = action.get("operation")
        if not isinstance(operation, dict) or operation.get("op") not in APPEND_OPERATIONS:
            raise GeometryError("bad_params", "Операция не поддерживается ручным инструментом.")
        operation = copy.deepcopy(operation)
        if operation["op"] == "mate":
            current = {}
            for item in document.get("parts") or []:
                shape, _ = TEMPLATES[item["template"]][0](merged_params(item["template"], item.get("params")))
                current[item["part_id"]] = {"shape": shape, "name": item.get("name", "Деталь")}
            current = apply_part_operations(current, operations)
            moving_id, fixed_id = operation.get("part_id"), operation.get("fixed_id")
            if moving_id not in current or fixed_id not in current or moving_id == fixed_id:
                raise GeometryError("bad_params", "Выберите поверхности двух разных деталей.")
            operation["moving_surface"] = bind_surface(current[moving_id]["shape"], operation.get("moving_surface"), current[moving_id].get("_feature_faces"))
            operation["fixed_surface"] = bind_surface(current[fixed_id]["shape"], operation.get("fixed_surface"), current[fixed_id].get("_feature_faces"))
        document["operations"] = operations + [operation]
    elif kind == "edit":
        try:
            document["operations"] = edit_operations(operations, action.get("index"), action.get("changes"))
        except ValueError as exc:
            raise GeometryError("bad_params", str(exc)) from exc
    elif kind == "convert_mesh":
        if _is_mesh_workflow(document):
            raise GeometryError("bad_params", "Документ уже является сеткой.")
        import numpy as np
        import trimesh
        shape, _ = build_any(document)
        resource = mesh_resource(shape, "sculpt-source")
        data = Path(resource["path"]).read_bytes()
        vertex_count, triangle_count = struct.unpack_from("<II", data)
        vertices = np.frombuffer(data, dtype="<f4", count=vertex_count * 3, offset=8).reshape((-1, 3))
        faces = np.frombuffer(data, dtype="<u4", count=triangle_count * 3, offset=8 + vertex_count * 12).reshape((-1, 3))
        if len(faces) > 200_000:
            raise GeometryError("mesh_too_large", "Для мягкой формы нужен mesh не более 200 000 треугольников.")
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=True)
        mesh.update_faces(mesh.nondegenerate_faces())
        mesh.update_faces(mesh.unique_faces())
        mesh.remove_unreferenced_vertices()
        if not mesh.is_watertight or not mesh.is_winding_consistent:
            raise GeometryError("mesh_conversion_failed", "Не удалось получить замкнутую сетку. Исходный BRep сохранён.")
        diagonal = float(np.linalg.norm(mesh.extents))
        for _level in range(7):
            if len(mesh.faces) * 4 > 200_000 or mesh.edges_unique_length.max() <= max(0.2, diagonal / 30):
                break
            vertices, faces = trimesh.remesh.subdivide(mesh.vertices, mesh.faces)
            mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        if not mesh.is_watertight:
            raise GeometryError("mesh_conversion_failed", "Уплотнение нарушило замкнутость. Исходный BRep сохранён.")
        source = mesh.export(file_type="stl")
        document = {"parts": [], "operations": [{
            "op": "mesh_source", "format": "stl", "source_name": "CAD-to-mesh.stl",
            "source_base64": base64.b64encode(source).decode("ascii"), "unit_scale": 1,
        }]}
    else:
        raise GeometryError("bad_params", "Неизвестное действие конструктора.")
    return {"parts": document.get("parts") or [], "operations": document.get("operations") or []}


def handle_build(params):
    if _is_mesh_workflow(params):
        mesh, stats = _build_mesh_workflow(params)
        return {"stats": stats, "mesh": _trimesh_resource(mesh, "model")}
    part, extra = build_any(params)
    if "parts" not in extra:
        # одиночный шаблон: синтезируем запись живого тела для списка деталей
        extra["parts"] = [{"part_id": "part-1",
                           "name": (params or {}).get("template",
                                                     "plate_with_holes"),
                           "volume": shape_volume(part),
                           "bbox": shape_bounds(part),
                           "solid_count": len(part.solids())}]
    feature_faces = extra.pop("_feature_faces", [])
    return {"stats": stats_of(part, extra),
            "mesh": mesh_resource(part, "model", feature_faces=feature_faces)}


def handle_solve_sketch(params):
    return _solve_constrained_sketch(
        params.get("sketch") or {}, params.get("drag"),
        float(params.get("tolerance", 1e-7)))


def handle_resolve_parameters(params):
    try:
        return resolve_parts(params.get("parts") or [], params.get("expressions") or {},
                             {name: values[1] for name, values in TEMPLATES.items()})
    except ValueError as error:
        raise GeometryError("bad_params", str(error)) from error


def handle_image_relief_preview(params):
    operation = {**params, "op": "image_relief_source"}
    return handle_build({"parts": [], "operations": [operation]})


def handle_image_relief_settings_hash(params):
    try:
        source_hash = params["source_sha256"]
        if not isinstance(source_hash, str) or re.fullmatch(r"[a-f0-9]{64}", source_hash) is None:
            raise ValueError("Контрольная сумма изображения повреждена.")
        settings = {
            "path": str(Path(params["path"]).expanduser().resolve()),
            "source_sha256": source_hash,
            "model": params.get("model", "heightmap-luminance-v1"),
            "seed": int(params.get("seed", 0)),
            "width_mm": float(params.get("width_mm", 50)),
            "relief_height": float(params.get("relief_height", 3)),
            "base_thickness": float(params.get("base_thickness", 1.5)),
            "samples": int(params.get("samples", 96)),
            "noise_strength": float(params.get("noise_strength", 0.015)),
            "invert": bool(params.get("invert", False)),
        }
        payload = json.dumps(settings, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (KeyError, TypeError, ValueError, OverflowError) as error:
        raise GeometryError("bad_params", "Не удалось проверить настройки preview изображения.") from error
    return {"settings_sha256": hashlib.sha256(payload).hexdigest()}


def handle_export(params):
    fmt = params.get("format", "stl")
    path = params.get("path")
    if not path:
        raise GeometryError("bad_params", "не указан путь экспорта")
    if _is_mesh_workflow(params):
        if fmt == "step":
            raise GeometryError(
                "mesh_step_unsupported",
                "Mesh нельзя экспортировать как точное параметрическое STEP-тело. Используйте STL или 3MF.")
        if fmt not in {"stl", "3mf"}:
            raise GeometryError("bad_params", f"Неизвестный mesh-формат экспорта: {fmt}")
        mesh, stats = _build_mesh_workflow(params)
        try:
            if fmt == "3mf":
                _export_trimesh_3mf(mesh, path)
            else:
                mesh.export(path, file_type=fmt)
        except Exception as exc:  # noqa: BLE001
            raise GeometryError("mesh_export_failed", f"Не удалось экспортировать mesh в {fmt.upper()}.") from exc
        return {"path": path, "bytes": Path(path).stat().st_size,
                "format": fmt, "stats": stats}
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
        for solid in part.solids():
            m.add_shape(solid)
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
                "mesh": {**_binary_mesh_resource(blob, "import"),
                         "vertex_count": len(positions),
                         "triangle_count": len(indices),
                         "face_ranges": []},
                "mode": "mesh"}
    raise GeometryError("bad_params", f"неизвестный формат импорта: {fmt}")


def handle_print_check(params):
    """PRINT-001/002: отдельный результат каждой проверки."""
    if _is_mesh_workflow(params):
        mesh, _ = _build_mesh_workflow(params)
        diagnostics = _mesh_diagnostics(mesh)
        return {"checks": [
            {"id": "mesh_watertight", "title": "Замкнутая mesh-оболочка",
             "status": "pass" if diagnostics["watertight"] else "fail"},
            {"id": "mesh_winding", "title": "Согласованная ориентация",
             "status": "pass" if diagnostics["winding_consistent"] else "fail"},
            {"id": "mesh_boundary", "title": "Открытые края",
             "status": "pass" if diagnostics["boundary_edges"] == 0 else "fail",
             "detail": f"{diagnostics['boundary_edges']} рёбер"},
            {"id": "mesh_self_intersection", "title": "Самопересечения",
             "status": "unknown", "detail": diagnostics["self_intersection_detail"]},
        ] + print_placement_checks(mesh.bounds.reshape(-1).tolist(), params.get("printer") or {}) + [
            {"id": "wall_thickness", "title": "Оценка тонких участков", "status": "unknown", "detail": "Выборочный анализ толщины доступен только для точного BRep; сетка не проверена."}
        ]}
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
                   "status": "pass" if shape_volume(part) > 0 else "fail",
                   "detail": f"{shape_volume(part):.1f} мм³"})
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
    checks.extend(print_placement_checks(shape_bounds(part), profile))
    checks.append(sampled_wall_check(part, profile.get("minimum_wall", 0.8)))
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
        return {"source": "brep", "volume": shape_volume(part),
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
        p0, p1 = params.get("p0"), params.get("p1")
        if any(not isinstance(point, (list, tuple)) or len(point) != 3 or
               any(not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) for value in point)
               for point in (p0, p1)):
            raise GeometryError("bad_params", "Координаты обеих точек должны быть тремя конечными числами.")
        return {"source": "brep", "distance": math.dist(p0, p1)}
    raise GeometryError("bad_params", f"неизвестное измерение: {kind}")


HANDLERS = {
    "ping": lambda p: {"pid": os.getpid()},
    "build_plate": lambda p: handle_build({"template": "plate_with_holes",
                                           "params": p}),
    "build": handle_build,
    "designer_action": handle_designer_action,
    "solve_sketch": handle_solve_sketch,
    "resolve_parameters": handle_resolve_parameters,
    "image_relief_preview": handle_image_relief_preview,
    "image_relief_settings_hash": handle_image_relief_settings_hash,
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
