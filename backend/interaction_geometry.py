import copy
import math

from geometry_errors import GeometryError


def finite(value, label):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GeometryError("bad_params", f"{label}: укажите конечное число.")
    return float(value)


def point3(value, label):
    if not isinstance(value, list) or len(value) != 3:
        raise GeometryError("bad_params", f"{label}: нужны три координаты.")
    return [finite(component, label) for component in value]


def surface_reference(face):
    from build123d import CenterOf
    kind = face.geom_type.name
    if kind not in ("PLANE", "CYLINDER"):
        return None
    center = [float(value) for value in face.center(CenterOf.MASS)]
    reference = {"kind": kind.lower(), "center": center, "area": float(face.area)}
    if kind == "PLANE":
        reference["direction"] = [float(value) for value in face.normal_at()]
    else:
        from OCP.BRepAdaptor import BRepAdaptor_Surface
        axis = face.axis_of_rotation
        if axis is None:
            return None
        reference.update(direction=list(axis.direction), origin=list(axis.position), radius=float(BRepAdaptor_Surface(face.wrapped).Cylinder().Radius()))
    return reference


def match_surface(shape, reference):
    if not isinstance(reference, dict) or reference.get("kind") not in ("plane", "cylinder"):
        raise GeometryError("reselect_required", "Выберите плоскую или цилиндрическую поверхность заново.")
    center = point3(reference.get("center"), "Центр поверхности")
    direction = point3(reference.get("direction"), "Направление поверхности")
    candidates = []
    for face in shape.faces():
        candidate = surface_reference(face)
        if not candidate or candidate["kind"] != reference["kind"]:
            continue
        alignment = sum(first * second for first, second in zip(candidate["direction"], direction))
        if alignment < 1 - 1e-6:
            continue
        if candidate["kind"] == "cylinder" and abs(candidate["radius"] - finite(reference.get("radius"), "Радиус")) > 1e-5:
            continue
        candidates.append((math.dist(candidate["center"], center), face, candidate))
    candidates.sort(key=lambda item: item[0])
    if not candidates or candidates[0][0] > 1e-4 or (len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 1e-6):
        raise GeometryError("reselect_required", "Поверхность изменилась или неоднозначна. Выберите её заново.")
    return candidates[0][1], candidates[0][2]


def normalized_surface_center(shape, reference):
    bounds = shape.bounding_box()
    return [(reference["center"][axis] - minimum) / max(1e-9, maximum - minimum)
            for axis, (minimum, maximum) in enumerate(zip(bounds.min, bounds.max))]


def bind_surface(shape, reference, feature_faces=None):
    face, _ = match_surface(shape, reference)
    faces = list(shape.faces())
    return {"index": next(index for index, candidate in enumerate(faces) if candidate.is_same(face)),
            "kind": reference["kind"], "face_count": len(faces),
            "topology": [face.geom_type.name for face in faces], "direction": reference["direction"],
            "feature_index": feature_index_for_face(face, feature_faces), "normalized_center": normalized_surface_center(shape, reference)}


def bound_surface(shape, binding, feature_faces=None):
    faces = list(shape.faces())
    index = binding.get("index")
    if (isinstance(index, bool) or not isinstance(index, int) or len(faces) != binding.get("face_count")
            or not 0 <= index < len(faces) or [face.geom_type.name for face in faces] != binding.get("topology")):
        raise GeometryError("reselect_required", "Топология сборочной поверхности изменилась. Пересоздайте связь.")
    if binding.get("feature_index") is not None:
        matches = [face for face in faces if feature_index_for_face(face, feature_faces) == binding["feature_index"]
                   and face.geom_type.name.lower() == binding.get("kind")]
        if len(matches) != 1:
            raise GeometryError("reselect_required", "Сборочный элемент неоднозначен или изменился. Пересоздайте связь.")
        reference = surface_reference(matches[0])
    else:
        reference = surface_reference(faces[index])
        if reference and math.dist(normalized_surface_center(shape, reference), point3(binding.get("normalized_center"), "Привязка поверхности")) > 1e-4:
            raise GeometryError("reselect_required", "Положение грани в топологии изменилось. Пересоздайте связь.")
    if not reference or reference["kind"] != binding.get("kind"):
        raise GeometryError("reselect_required", "Тип сборочной поверхности изменился. Пересоздайте связь.")
    if math.dist(reference["direction"], point3(binding.get("direction"), "Нормаль связи")) > 1e-5:
        raise GeometryError("reselect_required", "Ориентация сборочной поверхности изменилась. Пересоздайте связь.")
    return reference


def mate_shape(parts, operation):
    from build123d import Plane, Vector
    moving_id, fixed_id = operation.get("part_id"), operation.get("fixed_id")
    if moving_id == fixed_id or moving_id not in parts or fixed_id not in parts:
        raise GeometryError("bad_params", "Для связи нужны два разных существующих тела.")
    moving, fixed = parts[moving_id]["shape"], parts[fixed_id]["shape"]
    source = bound_surface(moving, operation.get("moving_surface") or {}, parts[moving_id].get("_feature_faces"))
    target = bound_surface(fixed, operation.get("fixed_surface") or {}, parts[fixed_id].get("_feature_faces"))
    kind = operation.get("kind")
    if kind not in ("plane", "axis") or source["kind"] != target["kind"] or source["kind"] != {"plane": "plane", "axis": "cylinder"}[kind]:
        raise GeometryError("bad_params", "Совместите две плоскости или две цилиндрические оси.")
    gap = finite(operation.get("gap", 0), "Зазор")
    source_normal, target_normal = source["direction"], target["direction"]
    if kind == "plane":
        target_normal = [-value for value in target_normal]
    def surface_origin(reference):
        if kind != "axis":
            return reference["center"]
        origin, direction = reference["origin"], reference["direction"]
        projection = sum((center - start) * component for center, start, component in zip(reference["center"], origin, direction))
        return [start + projection * component for start, component in zip(origin, direction)]

    source_origin, target_origin = surface_origin(source), surface_origin(target)
    target_origin = [value + gap * normal for value, normal in zip(target_origin, target["direction"])]

    def frame(origin, normal):
        normal_vector = Vector(normal).normalized()
        basis = Vector(1, 0, 0) if abs(normal_vector.X) < 0.9 else Vector(0, 1, 0)
        tangent = (basis - normal_vector * basis.dot(normal_vector)).normalized()
        return Plane(origin=origin, x_dir=tangent, z_dir=normal_vector).location

    location = frame(target_origin, target_normal) * frame(source_origin, source_normal).inverse()
    return location * moving, location


def resolve_feature(operation, shape, operations, index):
    bindings = operation.get("dimension_bindings")
    if bindings is None:
        return operation
    if not isinstance(bindings, dict) or set(bindings) - {"u", "v", "equal_diameter"}:
        raise GeometryError("bad_params", "Неизвестная зависимость размера.")
    result = copy.deepcopy(operation)
    profile = result.get("profile") or {}
    if profile.get("kind") not in ("circle", "rectangle"):
        raise GeometryError("bad_params", "Закрепление размеров поддерживает круг и прямоугольник.")
    face_axis = (result.get("face_ref") or {}).get("axis")
    axes = {"x": (1, 2), "y": (0, 2), "z": (0, 1)}.get(face_axis)
    if axes is None:
        raise GeometryError("bad_params", "Закрепите размер на внешней плоской грани.")
    bounds = shape.bounding_box()
    minimum, maximum = list(bounds.min), list(bounds.max)
    center = list(profile.get("center") or [0, 0])
    for coordinate, name in enumerate(("u", "v")):
        binding = bindings.get(name)
        if binding is None:
            continue
        if not isinstance(binding, dict) or binding.get("edge") not in ("min", "max"):
            raise GeometryError("bad_params", "Укажите край min/max для закреплённого отступа.")
        offset = finite(binding.get("offset"), "Отступ центра от края")
        if offset < 0:
            raise GeometryError("bad_params", "Отступ центра от края не может быть отрицательным.")
        axis = axes[coordinate]
        extent = maximum[axis] - minimum[axis]
        center[coordinate] = -extent / 2 + offset if binding["edge"] == "min" else extent / 2 - offset
    source = bindings.get("equal_diameter")
    if source is not None:
        if isinstance(source, bool) or not isinstance(source, int) or not 0 <= source < index:
            raise GeometryError("dependency_conflict", "Равный диаметр может ссылаться только на более раннее отверстие.")
        by_index = {operation.get("_history_index", position): operation for position, operation in enumerate(operations)}
        previous = by_index.get(source, {})
        if (previous.get("op") != "face_feature" or previous.get("enabled") is False
                or previous.get("profile", {}).get("kind") != "circle" or profile.get("kind") != "circle"):
            raise GeometryError("dependency_conflict", "Источник равного диаметра отсутствует, выключен или не является кругом.")
        visited = set()
        while previous.get("dimension_bindings", {}).get("equal_diameter") is not None:
            next_index = previous["dimension_bindings"]["equal_diameter"]
            if isinstance(next_index, bool) or not isinstance(next_index, int) or next_index in visited or not 0 <= next_index < source:
                raise GeometryError("dependency_conflict", "Цикл или неверная ссылка зависимости диаметра.")
            visited.add(next_index)
            source, previous = next_index, by_index.get(next_index, {})
            if previous.get("enabled") is False or previous.get("op") != "face_feature":
                raise GeometryError("dependency_conflict", "Источник зависимости выключен или удалён.")
        profile["diameter"] = finite(previous.get("profile", {}).get("diameter"), "Диаметр источника")
    profile["center"] = center
    result["profile"] = profile
    return result


def new_feature_faces(before, after, operation):
    previous = list(before.faces())
    result = []
    for face in after.faces():
        if any(face.is_same(old) for old in previous):
            continue
        if operation["op"] in ("face_feature", "fillet", "chamfer"):
            reference = surface_reference(face)
            if reference and reference["kind"] == "plane":
                matching_plane = False
                for old in previous:
                    other = surface_reference(old)
                    if other and other["kind"] == "plane":
                        parallel = abs(sum(first * second for first, second in zip(reference["direction"], other["direction"]))) > 1 - 1e-7
                        distance = abs(sum((first - second) * normal for first, second, normal in zip(reference["center"], other["center"], reference["direction"])))
                        if parallel and distance < 1e-6:
                            matching_plane = True
                            break
                if matching_plane:
                    continue
        result.append(face)
    return result


def feature_index_for_face(face, feature_faces):
    from build123d import CenterOf
    matches = set()
    center = face.center(CenterOf.MASS)
    for created, index in feature_faces or []:
        if face.is_same(created) or (face.geom_type == created.geom_type and abs(face.area - created.area) <= max(1e-6, face.area * 1e-8)
                                    and (center - created.center(CenterOf.MASS)).length < 1e-5):
            matches.add(index)
    return next(iter(matches)) if len(matches) == 1 else None


def print_placement_checks(bounds, profile):
    limits = [profile.get(axis) for axis in ("x", "y", "z")]
    if not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > 0 for value in limits):
        return [{"id": "bed_position", "title": "Размещение на столе", "status": "unknown", "detail": "Задайте положительные размеры стола."}]
    inside = bounds[0] >= -limits[0] / 2 - 1e-6 and bounds[3] <= limits[0] / 2 + 1e-6 and bounds[1] >= -limits[1] / 2 - 1e-6 and bounds[4] <= limits[1] / 2 + 1e-6 and bounds[2] >= -1e-6 and bounds[5] <= limits[2] + 1e-6
    return [{"id": "bed_position", "title": "Абсолютное размещение в рабочей области", "status": "pass" if inside else "fail",
             "detail": "Начало XY — центр стола; Z=0 — поверхность стола."},
            {"id": "bed_contact", "title": "Контакт со столом", "status": "pass" if abs(bounds[2]) <= 1e-5 else "fail",
             "detail": f"Нижняя точка Z={bounds[2]:.3f} мм."}]


def sampled_wall_check(shape, threshold=0.8):
    from build123d import Vector
    threshold = finite(threshold, "Минимальная стенка")
    if threshold <= 0:
        raise GeometryError("bad_params", "Минимальная стенка должна быть больше нуля.")
    issues = []
    sampled = 0
    for solid_index, solid in enumerate(shape.solids()):
        faces = list(solid.faces())
        if len(faces) > 250:
            return {"id": "wall_thickness", "title": "Оценка тонких участков", "status": "unknown", "detail": "Более 250 граней в теле: полный обход слишком дорог. Универсальная проверка толщины не выполнена."}
        for face_index, face in enumerate(faces):
            for u_value, v_value in ((0.5, 0.5), (0.25, 0.5), (0.75, 0.5)):
                point = face.position_at(u_value, v_value)
                if face.distance_to(point) > 1e-5:
                    continue
                normal = face.normal_at(point)
                probe = point - normal * min(0.01, threshold / 10)
                if not solid.is_inside(probe):
                    continue
                sampled += 1
                for other in faces:
                    if other.is_same(face):
                        continue
                    distance, nearest, _ = other.distance_to_with_closest_points(point)
                    if distance <= 1e-5 or distance >= threshold:
                        continue
                    delta = nearest - point
                    if delta.normalized().dot(normal) > -0.8 or not solid.is_inside(point + delta * 0.5):
                        continue
                    issues.append({"solid_index": solid_index, "face_local_index": face_index,
                                   "point": list(point), "thickness": float(distance)})
                    break
    return {"id": "wall_thickness", "title": "Оценка тонких участков", "status": "fail" if issues else "unknown",
            "detail": f"Порог {threshold:g} мм; проверено {sampled} точек. " + (f"Найдено подозрительных участков: {len(issues)}. " if issues else "В выборке тонкие участки не найдены. ") + "Выборочная оценка не гарантирует минимальную толщину всей модели.", "issues": issues}
