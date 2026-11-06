import copy


EDITABLE_FIELDS = {
    "fillet": {"radius"},
    "chamfer": {"distance"},
    "face_offset": {"distance"},
    "face_feature": {"profile", "depth", "mode"},
    "face_dome": {"diameter", "height", "mode"},
    "resize_body": {"size", "anchor"},
    "resize_parametric": {"size", "anchor"},
    "transform": {"translate", "rotate_deg", "pivot"},
    "mesh_transform": {"translate", "rotate_deg", "pivot", "scale"},
    "mesh_deform": {"center", "delta", "radius"},
    "array_linear": {"count", "step"},
    "array_circular": {"count", "angle", "center"},
    "mirror": {"plane"},
    "split": {"plane", "offset"},
    "sheet_bend": {"position", "angle", "inside_radius", "moving_side", "direction"},
}

APPEND_OPERATIONS = {
    "fillet", "chamfer", "face_offset", "face_feature", "resize_body",
    "resize_parametric", "transform", "mesh_transform", "mesh_deform",
}


def edit_operations(operations, index, changes):
    if isinstance(index, bool) or not isinstance(index, int) or not 0 <= index < len(operations):
        raise ValueError("Операция больше не существует. Обновите историю.")
    if not isinstance(changes, dict) or not changes:
        raise ValueError("Укажите изменяемые параметры операции.")
    allowed = EDITABLE_FIELDS.get(operations[index].get("op"), set())
    if operations[index].get("op") in ("mesh_source", "image_relief_source", "step_source"):
        raise ValueError("Исходный импорт нельзя редактировать или отключать как обычную операцию.")
    if not set(changes).issubset(allowed | {"enabled"}):
        raise ValueError("Эти поля операции нельзя изменять. Геометрические ссылки и ID защищены.")
    result = copy.deepcopy(operations)
    if "enabled" in changes and not isinstance(changes["enabled"], bool):
        raise ValueError("Состояние операции должно быть true или false.")
    result[index].update(copy.deepcopy(changes))
    return result
