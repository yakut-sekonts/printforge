#!/usr/bin/env python3
"""Dev-shim PrintForge (M2): IPC-контракт app/shared/ipc.md по HTTP.
ТОЛЬКО ДЛЯ РАЗРАБОТКИ. Запуск: backend/.venv/bin/python scripts/dev_shim.py
"""
import base64
import copy
import hashlib
import json
import re
import struct
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from contextlib import nullcontext
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "backend" / "worker.py"
PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"
sys.path.insert(0, str(ROOT / "scripts"))
import ai_planner
sys.path.insert(0, str(ROOT / "backend"))
from parameter_expressions import canonical_name

_worker = None
_req_n = 0
_ai_tasks = {}
_ai_tasks_lock = threading.Lock()
_command_lock = threading.Lock()
_geometry_task = None
_geometry_task_lock = threading.Lock()


def _cancel_geometry_task():
    global _worker
    with _geometry_task_lock:
        task = _geometry_task
        if task is None:
            return False
        task.set()
    worker = _worker
    if worker is not None and worker.poll() is None:
        worker.kill()
        worker.wait(timeout=10)
    return True


def worker_timeout_seconds(method):
    return 300 if method in {"import", "export"} else 120


def _read_worker_line(worker, method):
    result = {}
    finished = threading.Event()

    def read_line():
        try:
            result["line"] = worker.stdout.readline()
        except BaseException as error:  # noqa: BLE001
            result["error"] = error
        finally:
            finished.set()

    threading.Thread(target=read_line, daemon=True).start()
    timeout = worker_timeout_seconds(method)
    if not finished.wait(timeout=timeout):
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)
        raise geo_error(
            "worker_timeout",
            f"Geometry worker не завершил {method} за {timeout} с. "
            "Процесс остановлен; последняя подтверждённая модель сохранена.")
    if "error" in result:
        raise result["error"]
    return result.get("line", "")


def worker_call(method, params, revision=0):
    global _worker, _req_n, _geometry_task
    cancelled = threading.Event()
    with _geometry_task_lock:
        if _geometry_task is not None:
            raise geo_error("worker_busy", "Другая geometry operation уже выполняется.")
        _geometry_task = cancelled
    try:
        last_failure = "неизвестная transport error"
        for attempt in range(2):
            try:
                if _worker is None or _worker.poll() is not None:
                    _worker = subprocess.Popen(
                        [str(PYTHON), str(WORKER)], stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1)
                _req_n += 1
                req = {"request_id": f"s{_req_n}", "schema_version": 1,
                       "document_id": "doc", "revision": revision,
                       "method": method, "params": params}
                _worker.stdin.write(json.dumps(req) + "\n")
                _worker.stdin.flush()
                line = _read_worker_line(_worker, method)
                if cancelled.is_set():
                    raise geo_error(
                        "geometry_cancelled",
                        "Операция геометрии отменена. Последняя подтверждённая модель сохранена.")
                if not line:
                    raise BrokenPipeError("geometry worker завершился без ответа")
                resp = json.loads(line)
            except RuntimeError:
                _worker = None
                raise
            except (BrokenPipeError, OSError, json.JSONDecodeError) as exc:
                last_failure = str(exc)
                if _worker is not None and _worker.poll() is None:
                    _worker.kill()
                    _worker.wait(timeout=10)
                _worker = None
                if cancelled.is_set():
                    raise geo_error(
                        "geometry_cancelled",
                        "Операция геометрии отменена. Последняя подтверждённая модель сохранена.") from exc
                if attempt == 0:
                    continue
                raise geo_error(
                    "worker_recovery_failed",
                    "Geometry worker повторно завершился после автоматического "
                    f"перезапуска: {last_failure}. Последняя подтверждённая "
                    "модель сохранена.") from exc
            if resp.get("ok"):
                return resp.get("result")
            err = resp.get("error", {})
            raise RuntimeError(json.dumps({
                "code": err.get("code", "geometry_error"),
                "message": err.get("message", "ошибка геометрии"),
                "detail": err.get("detail", "")}, ensure_ascii=False))
        raise geo_error("worker_recovery_failed", last_failure)
    finally:
        with _geometry_task_lock:
            if _geometry_task is cancelled:
                _geometry_task = None


def geo_error(code, message):
    return RuntimeError(json.dumps({"code": code, "message": message,
                                    "detail": ""}, ensure_ascii=False))


DEFAULTS = {
    "box": {"length": 40, "width": 30, "height": 20},
    "cylinder": {"diameter": 30, "height": 30},
    "sphere": {"diameter": 30},
    "plate_with_holes": {"length": 80, "width": 40, "height": 6,
                         "hole_diameter": 4, "hole_offset": 10},
    "washer": {"outer_diameter": 20, "inner_diameter": 6, "height": 4},
    "bracket_l": {"a_length": 40, "a_width": 30, "a_thickness": 5,
                  "b_height": 30},
    "case_with_lid": {"length": 100, "width": 60, "height": 30, "wall": 2,
                      "bottom": 2, "gap": 0.2, "lid_thickness": 2,
                      "lip_height": 4, "lip_wall": 2},
}


class Doc:
    _ids = 0
    _instances = 0

    def __init__(self, document_id=None):
        if document_id is None:
            Doc._ids += 1
            document_id = f"doc-{Doc._ids}"
        Doc._instances += 1
        self.doc_id = document_id
        self.document_instance_id = f"instance-{Doc._instances}"
        self.parts = []          # [{part_id, name, template, params}]
        self.expressions = {}
        self.operations = []     # v3-операции (boolean/fillet/chamfer/array/mirror/split/transform)
        self.history = []
        self.index = -1
        self.dirty = False
        self.path = None
        self.revision = 0
        self.stats = None
        self.mesh = None
        self.error = None
        self.applied_actions = {}
        self._part_n = 0
        self.commit()

    @property
    def template(self):
        return self.parts[0]["template"] if self.parts else None

    @property
    def params(self):
        return self.parts[0]["params"] if self.parts else {}

    def snapshot(self):
        return {"parts": copy.deepcopy(self.parts),
                "expressions": dict(self.expressions),
                "operations": copy.deepcopy(self.operations),
                "part_n": self._part_n}

    def restore(self, snap):
        self.parts = copy.deepcopy(snap["parts"])
        self.expressions = dict(snap["expressions"])
        self.operations = copy.deepcopy(snap["operations"])
        self._part_n = snap.get("part_n", len(self.parts))

    def commit(self):
        del self.history[self.index + 1:]
        self.history.append(self.snapshot())
        self.index += 1
        self.dirty = True

    def add_part(self, template, params, name=None):
        parameters = dict(DEFAULTS[template]) | {key: float(value) for key, value in params.items()}
        self._part_n += 1
        pid = f"part-{self._part_n}"
        titles = {"box": "Параллелепипед", "cylinder": "Цилиндр", "sphere": "Сфера",
                  "plate_with_holes": "Пластина", "washer": "Шайба",
                  "bracket_l": "Кронштейн", "case_with_lid": "Корпус"}
        self.parts.append({"part_id": pid, "name": name or titles.get(template, template),
                           "template": template,
                           "params": parameters})
        return pid

    def state(self, slot):
        return {
            "doc_id": self.doc_id,
            "document_instance_id": self.document_instance_id,
            "revision": self.revision,
            "dirty": self.dirty, "path": self.path, "slot": slot,
            "template": self.template, "params": self.params,
            "parts": self.parts,
            "expressions": self.expressions, "operations": self.operations,
            "stats": self.stats, "error": self.error,
            "can_undo": self.index > 0,
            "can_redo": self.index + 1 < len(self.history),
            "history_len": len(self.history), "history_index": self.index,
        }

    def build_params(self):
        if not self.parts and not self.operations:
            return {"template": None, "params": {}, "operations": []}
        # единый v3-путь: реальные part_id во всех статусах и операциях
        ops = []
        for o in self.operations:
            if o.get("op") in ("fillet", "chamfer") and "part_id" not in o:
                o = {**o, "part_id": self.parts[0]["part_id"]}
            ops.append(o)
        return {"parts": self.parts, "operations": ops}

    def rebuild(self):
        self.revision += 1
        if not self.parts and not self.operations:
            self.stats = None
            self.mesh = None
            self.error = None
            return
        try:
            resolved = worker_call("resolve_parameters", {
                "parts": self.parts, "expressions": self.expressions,
            }, self.revision)
            self.parts = resolved["parts"]
            self.expressions = resolved["expressions"]
            result = worker_call("build", self.build_params(), self.revision)
            self.stats = result.get("stats")
            self.mesh = result.get("mesh")
            self.error = None
        except RuntimeError as e:
            # DOC-005: последняя подтверждённая ревизия остаётся
            self.error = json.loads(str(e))


DOCS = {"main": Doc(), "tutorial": Doc()}
ACTIVE = ["main"]
AUTOSAVE = {"path": None, "at": 0}


def doc():
    return DOCS[ACTIVE[0]]


def cmd_doc_create(a):
    template = a.get("template", "plate_with_holes")
    if template not in DEFAULTS:
        raise geo_error("unknown_template", f"Неизвестный шаблон: {template}")
    try:
        parameters = {name: float(value) for name, value in (a.get("params") or {}).items()}
    except (TypeError, ValueError, AttributeError) as error:
        raise geo_error("bad_params", "Параметры формы должны быть числами.") from error
    d = doc()
    d.parts = []
    d.expressions = {}
    d.operations = []
    d._part_n = 0
    d.add_part(template, parameters)
    _rebuild_committed(d)
    return d.state(ACTIVE[0])


def _rebuild_committed(document):
    previous = document.history[document.index]
    candidate = copy.deepcopy(document)
    try:
        candidate.rebuild()
    except Exception:
        document.restore(previous)
        raise
    if candidate.error:
        document.restore(previous)
        document.error = candidate.error
        return
    document.restore(candidate.snapshot())
    document.commit()
    document.revision = candidate.revision
    document.stats = candidate.stats
    document.mesh = candidate.mesh
    document.error = None


def cmd_doc_set_parameter(a):
    d = doc()
    if not d.parts:
        raise geo_error("no_model", "Сначала создайте деталь")
    pid = a.get("part_id") or d.parts[0]["part_id"]
    part = next((p for p in d.parts if p["part_id"] == pid), None)
    if not part:
        raise geo_error("bad_params", f"Деталь не найдена: {pid}")
    try:
        name = canonical_name(a["name"])
    except ValueError as error:
        raise geo_error("bad_value", str(error)) from error
    if name not in DEFAULTS[part["template"]]:
        raise geo_error("bad_value", f"Неизвестный параметр «{name}».")
    part["params"][name] = a.get("value")
    key = f"{pid}.{name}"
    if a.get("expression"):
        d.expressions[key] = a["expression"]
    else:
        d.expressions.pop(key, None)
    _rebuild_committed(d)
    return d.state(ACTIVE[0])


def _apply_op(a, op):
    d = doc()
    d.operations.append(op)
    _rebuild_committed(d)
    return d.state(ACTIVE[0])


def _apply_atomic_op(a, operation):
    document = doc()
    base_revision = document.revision
    candidate = copy.deepcopy(document)
    candidate.operations.append(operation)
    candidate.rebuild()
    if doc() is not document or document.revision != base_revision:
        raise geo_error("document_changed", "Документ изменился перед применением операции.")
    if candidate.error:
        document.error = candidate.error
        return document.state(ACTIVE[0])
    document.restore(candidate.snapshot())
    document.commit()
    document.revision = candidate.revision
    document.stats = candidate.stats
    document.mesh = candidate.mesh
    document.error = None
    return document.state(ACTIVE[0])


def cmd_doc_add_part(a):
    d = doc()
    if not d.parts and not any(operation.get("op") == "step_source" for operation in d.operations):
        raise geo_error("no_model", "Сначала создайте деталь из шаблона")
    template = a.get("template", "plate_with_holes")
    if template not in DEFAULTS:
        raise geo_error("unknown_template", f"Неизвестный шаблон: {template}")
    d.add_part(template, a.get("params") or {})
    _rebuild_committed(d)
    return d.state(ACTIVE[0])


def cmd_doc_boolean(a):
    # документ хранит определения обеих деталей; worker при повторении
    # детерминированно применяет операцию (инструмент поглощается в построении)
    return _apply_op(a, {"op": "boolean", "boolean": a.get("boolean", "union"),
                         "target_id": a["target_id"], "tool_id": a["tool_id"],
                         "keep_tool": bool(a.get("keep_tool", False))})


def cmd_doc_array(a):
    return _apply_op(a, {"op": "array_linear", "part_id": a["part_id"],
                         "count": int(a["count"]),
                         "step": a.get("step") or [0, 0, 0]})


def cmd_doc_mirror(a):
    return _apply_op(a, {"op": "mirror", "part_id": a["part_id"],
                         "plane": a.get("plane", "YZ")})


def cmd_doc_split(a):
    operation = {"op": "split", "part_id": a["part_id"],
                 "plane": a.get("plane", "XZ"), "offset": a.get("offset", 0)}
    if a.get("separate", False):
        operation["separate"] = True
        return _apply_atomic_op(a, operation)
    return _apply_op(a, operation)


def cmd_doc_transform(a):
    return _apply_op(a, {"op": "transform", "part_id": a["part_id"],
                         "translate": a.get("translate") or [0, 0, 0]})


def cmd_doc_profile_extrude(a):
    op = {"op": "profile_extrude", "mode": a.get("mode", "add"),
          "plane": a.get("plane", "XY"), "profile": a["profile"]}
    if a.get("depth") is not None:
        op["depth"] = a["depth"]
    if a.get("target_id"):
        op["target_id"] = a["target_id"]
    elif op["mode"] == "cut":
        d = doc()
        if d.parts:
            op["target_id"] = d.parts[0]["part_id"]
    return _apply_op(a, op)


def cmd_doc_sketch_extrude(a):
    return _apply_op(a, {
        "op": "sketch_extrude",
        "profile": a["profile"],
        "plane": a.get("plane", "XY"),
        "depth": a["depth"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_sketch_solve(a):
    return worker_call("solve_sketch", {
        "sketch": a["sketch"],
        "drag": a.get("drag"),
        "tolerance": a.get("tolerance", 1e-7),
    }, doc().revision)


def cmd_doc_constrained_sketch_extrude(a):
    return _apply_op(a, {
        "op": "constrained_sketch_extrude",
        "sketch": a["sketch"],
        "drag": a.get("drag"),
        "plane": a.get("plane", "XY"),
        "depth": a["depth"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_revolve(a):
    return _apply_op(a, {
        "op": "revolve",
        "profile": a["profile"],
        "plane": a.get("plane", "XZ"),
        "axis": a.get("axis") or {"point": [0, 0, 0], "direction": [0, 0, 1]},
        "angle": a["angle"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_sweep(a):
    return _apply_op(a, {
        "op": "sweep",
        "section": a["section"],
        "path": a["path"],
        "frenet": bool(a.get("frenet", False)),
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_loft(a):
    return _apply_op(a, {
        "op": "loft",
        "sections": a["sections"],
        "ruled": bool(a.get("ruled", True)),
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_shell(a):
    return _apply_op(a, {
        "op": "shell",
        "outer_radius": a["outer_radius"],
        "height": a["height"],
        "wall": a["wall"],
        "bottom": a["bottom"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_draft_prism(a):
    return _apply_op(a, {
        "op": "draft_prism",
        "width": a["width"],
        "depth": a["depth"],
        "height": a["height"],
        "angle": a["angle"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_rib(a):
    return _apply_op(a, {
        "op": "rib",
        "base_length": a["base_length"],
        "base_width": a["base_width"],
        "base_thickness": a["base_thickness"],
        "rib_length": a["rib_length"],
        "rib_height": a["rib_height"],
        "rib_width": a["rib_width"],
        "overlap": a["overlap"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_fit_pocket(a):
    operation = {
        "op": "fit_pocket",
        "fixture_id": a["fixture_id"],
        "fixture_version": a.get("fixture_version", "1"),
        "body_length": a["body_length"],
        "body_width": a["body_width"],
        "body_height": a["body_height"],
        "clearance": a.get("clearance", 0),
        "clearance_mode": a.get("clearance_mode", "diametral"),
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    }
    if a.get("pocket_depth") is not None:
        operation["pocket_depth"] = a["pocket_depth"]
    return _apply_op(a, operation)


def cmd_doc_vector_extrude(a):
    path = Path(a["path"])
    try:
        source_text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise geo_error("file_read_failed", f"Не удалось прочитать векторный файл: {exc}") from exc
    operation = {
        "op": "vector_extrude",
        "format": a["format"],
        "source_text": source_text,
        "height": a["height"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    }
    if a.get("unit_scale") is not None:
        operation["unit_scale"] = a["unit_scale"]
    return _apply_op(a, operation)


def cmd_doc_text_relief(a):
    return _apply_op(a, {
        "op": "text_relief",
        "text": a["text"],
        "font_size": a["font_size"],
        "relief_height": a["relief_height"],
        "body_length": a["body_length"],
        "body_width": a["body_width"],
        "body_height": a["body_height"],
        "mode": a.get("mode", "add"),
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_thread_pair(a):
    return _apply_op(a, {
        "op": "thread_pair",
        "profile_version": a.get("profile_version", "metric-60-v1"),
        "major_diameter": a["major_diameter"],
        "pitch": a["pitch"],
        "length": a["length"],
        "hand": a.get("hand", "right"),
        "starts": int(a.get("starts", 1)),
        "clearance": a["clearance"],
        "nut_height": a["nut_height"],
        "nut_across_flats": a["nut_across_flats"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_clearance_calibration(a):
    return _apply_op(a, {
        "op": "clearance_calibration",
        "values": a["values"],
        "nominal_diameter": a["nominal_diameter"],
        "coupon_length": a["coupon_length"],
        "coupon_width": a["coupon_width"],
        "thickness": a["thickness"],
        "spacing": a["spacing"],
        "font_size": a["font_size"],
        "label_height": a["label_height"],
        "profile_name": a.get("profile_name"),
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_split_connector_pair(a):
    return _apply_op(a, {
        "op": "split_connector_pair",
        "length": a["length"],
        "width": a["width"],
        "height": a["height"],
        "pin_radius": a["pin_radius"],
        "pin_length": a["pin_length"],
        "radial_clearance": a["radial_clearance"],
        "print_separation": a["print_separation"],
        "result_id": a.get("result_id"),
        "name": a.get("name"),
    })


def cmd_doc_designer_action(a):
    document = doc()
    slot = ACTIVE[0]
    if document.revision != a.get("expected_revision") or document.document_instance_id != a.get("expected_instance"):
        raise geo_error("document_changed", "Документ изменился. Выберите область заново.")
    candidate = copy.deepcopy(document)
    prepared = worker_call("designer_action", {"document": candidate.build_params(), "action": a.get("action")}, document.revision)
    candidate.parts = prepared["parts"]
    candidate.operations = prepared["operations"]
    if not candidate.parts:
        candidate.expressions = {}
    candidate.rebuild()
    if doc() is not document or document.revision != a["expected_revision"] or ACTIVE[0] != slot:
        raise geo_error("document_changed", "Документ изменился перед применением.")
    if a.get("preview"):
        if candidate.error:
            raise RuntimeError(json.dumps(candidate.error, ensure_ascii=False))
        return {"stats": candidate.stats, "mesh": candidate.mesh, "base_revision": document.revision,
                "document_instance_id": document.document_instance_id}
    if candidate.error:
        document.error = candidate.error
        return document.state(slot)
    document.restore(candidate.snapshot())
    document.commit()
    document.revision = candidate.revision
    document.stats, document.mesh, document.error = candidate.stats, candidate.mesh, None
    return document.state(slot)


def cmd_doc_resize_body(a):
    return _apply_atomic_op(a, {
        "op": "resize_body", "target_id": a["target_id"],
        "size": a["size"], "anchor": a["anchor"],
    })


def cmd_doc_face_offset(a):
    return _apply_atomic_op(a, {
        "op": "face_offset",
        "target_id": a["target_id"],
        "face_ref": a["face_ref"],
        "distance": a["distance"],
    })


def cmd_doc_face_feature(a):
    mode = a.get("mode")
    if mode not in ("add", "cut"):
        raise geo_error("bad_params", "Режим элемента должен быть add или cut.")
    return _apply_op(a, {
        "op": "face_feature",
        "target_id": a["target_id"],
        "mode": mode,
        "face_ref": a["face_ref"],
        "profile": a["profile"],
        "depth": a["depth"],
    })


def cmd_doc_face_dome(a):
    mode = a.get("mode")
    if mode not in ("add", "cut"):
        raise geo_error("bad_params", "Режим сферического сегмента должен быть add или cut.")
    return _apply_op(a, {
        "op": "face_dome",
        "target_id": a["target_id"],
        "mode": mode,
        "face_ref": a["face_ref"],
        "center": a.get("center") or [0, 0],
        "diameter": a["diameter"],
        "height": a["height"],
    })


def cmd_doc_sheet_bend(a):
    return _apply_op(a, {
        "op": "sheet_bend",
        "target_id": a["target_id"],
        "face_ref": a["face_ref"],
        "bend_axis": a["bend_axis"],
        "position": a["position"],
        "angle": a["angle"],
        "inside_radius": a["inside_radius"],
        "moving_side": a["moving_side"],
        "direction": a["direction"],
    })


def cmd_doc_array_circular(a):
    return _apply_op(a, {"op": "array_circular", "part_id": a["part_id"],
                         "count": int(a["count"]),
                         "angle": float(a.get("angle", 360)),
                         "center": a.get("center") or [0, 0, 0]})


def cmd_doc_align(a):
    return _apply_op(a, {"op": "align", "part_id": a["part_id"],
                         "axis": a.get("axis", "x"),
                         "align": a.get("align", "center"),
                         "value": float(a.get("value", 0))})


def cmd_measure(a):
    d = doc()
    if not d.parts and not d.operations:
        raise geo_error("no_model", "Сначала создайте деталь")
    p = d.build_params()
    p["type"] = a.get("type", "bbox")
    for k in ("face_index", "p0", "p1"):
        if k in a:
            p[k] = a[k]
    return worker_call("measure", p, d.revision)


def cmd_doc_fillet(a):
    radius = a.get("radius")
    if not isinstance(radius, (int, float)) or radius <= 0:
        raise geo_error("bad_value", "Радиус скругления должен быть больше нуля.")
    op = {"op": "fillet", "radius": radius, "edge_ref": a["edge_ref"]}
    d = doc()
    if a.get("part_id"):
        op["part_id"] = a["part_id"]
    elif d.parts:
        op["part_id"] = d.parts[0]["part_id"]
    return _apply_op(a, op)


def cmd_doc_chamfer(a):
    distance = a.get("distance")
    if not isinstance(distance, (int, float)) or distance <= 0:
        raise geo_error("bad_value", "Размер фаски должен быть больше нуля.")
    op = {"op": "chamfer", "distance": distance, "edge_ref": a["edge_ref"]}
    d = doc()
    if a.get("part_id"):
        op["part_id"] = a["part_id"]
    elif d.parts:
        op["part_id"] = d.parts[0]["part_id"]
    return _apply_op(a, op)


def cmd_doc_clear_error(a):
    doc().error = None
    return doc().state(ACTIVE[0])


def _restore_history(document, index):
    candidate = copy.deepcopy(document)
    candidate.index = index
    candidate.restore(candidate.history[index])
    candidate.rebuild()
    if candidate.error:
        document.error = candidate.error
        return
    document.restore(candidate.snapshot())
    document.index = index
    document.dirty = True
    document.revision = candidate.revision
    document.stats = candidate.stats
    document.mesh = candidate.mesh
    document.error = None


def cmd_doc_undo(a):
    d = doc()
    if d.index > 0:
        _restore_history(d, d.index - 1)
    return d.state(ACTIVE[0])


def cmd_doc_redo(a):
    d = doc()
    if d.index + 1 < len(d.history):
        _restore_history(d, d.index + 1)
    return d.state(ACTIVE[0])


def cmd_doc_get_state(a):
    return doc().state(ACTIVE[0])


def cmd_doc_get_imported_mesh(a):
    data = Path(a["path"]).read_bytes()
    nv, nt = struct.unpack_from("<II", data)
    pos = list(struct.unpack_from(f"<{nv*3}f", data, 8))
    idx = list(struct.unpack_from(f"<{nt*3}I", data, 8 + nv * 12))
    return {"vertex_count": nv, "triangle_count": nt, "positions": pos,
            "indices": idx, "face_ranges": []}


def cmd_doc_get_mesh(a):
    if not doc().mesh:
        raise geo_error("no_model", "модель ещё не построена")
    data = Path(doc().mesh["path"]).read_bytes()
    nv, nt = struct.unpack_from("<II", data)
    pos = list(struct.unpack_from(f"<{nv*3}f", data, 8))
    idx = list(struct.unpack_from(f"<{nt*3}I", data, 8 + nv * 12))
    return {"vertex_count": nv, "triangle_count": nt, "positions": pos,
            "indices": idx, "face_ranges": doc().mesh["face_ranges"]}


def save_doc(d, path):
    tmp = path.with_suffix(".printforge.tmp")
    requires_schema_four = any(
        part.get("template") in ("box", "cylinder", "sphere") for part in d.parts
    ) or any(
        operation.get("op") == "face_offset" or
        (operation.get("op") == "split" and operation.get("separate", False))
        for operation in d.operations)
    requires_schema_six = any(
        operation.get("op") in {"resize_body", "resize_parametric", "mesh_deform"} or
        "enabled" in operation or
        (operation.get("op") == "transform" and ("rotate_deg" in operation or "pivot" in operation)) or
        (operation.get("op") == "mesh_transform" and "pivot" in operation)
        for operation in d.operations)
    requires_schema_seven = any(operation.get("op") == "mate" or "dimension_bindings" in operation or "frame" in operation or any(entity.get("type") == "arc" for entity in operation.get("sketch", {}).get("entities", [])) for operation in d.operations)
    requires_schema_eight = any(operation.get("op") == "face_shell" for operation in d.operations)
    schema_version = 8 if requires_schema_eight else 7 if requires_schema_seven else 6 if requires_schema_six else 5 if any(operation.get("op") == "step_source" for operation in d.operations) else 4 if requires_schema_four else 3
    manifest = {"schema_version": schema_version, "app": "PrintForge",
                "app_version": "0.1.0-m2", "units": "mm",
                "kernel": "build123d/OCP"}
    document = {"schema_version": schema_version, "units": "mm",
                "document_id": d.doc_id, "template": d.template,
                "parts": d.parts,
                "parameters": d.params, "expressions": d.expressions,
                "operations": d.operations}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("document.json", json.dumps(document))
    tmp.replace(path)


def cmd_doc_save(a):
    d = doc()
    path = Path(a["path"]).expanduser()
    save_doc(d, path)
    d.path = str(path)
    d.dirty = False
    return d.state(ACTIVE[0])


def cmd_doc_open(a):
    path = Path(a["path"]).expanduser()
    try:
        with zipfile.ZipFile(path) as z:
            document = json.loads(z.read("document.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise geo_error("bad_file", "Это не файл проекта PrintForge или файл повреждён.")
    schema_version = int(document.get("schema_version", 1))
    if schema_version > 8:
        raise geo_error(
            "unsupported_project_version",
            f"Проект создан в более новой версии формата ({schema_version}). Обновите PrintForge.")
    template = document.get("template")
    operations = document.get("operations") or []
    if template is not None and template not in DEFAULTS:
        raise geo_error("bad_file", f"Неизвестный шаблон в проекте: {template}")
    candidate = Doc(document.get("document_id"))
    if document.get("parts"):
        candidate.parts = document["parts"]
        candidate._part_n = max([len(candidate.parts)] + [int(part["part_id"].removeprefix("part-")) for part in candidate.parts if re.fullmatch(r"part-\d+", str(part.get("part_id", "")))])
    elif template is not None:
        candidate.add_part(template, {k: float(v) for k, v in (document.get("parameters") or {}).items()})
    candidate.expressions = document.get("expressions") or {}
    candidate.operations = operations
    candidate.rebuild()
    if candidate.error:
        raise RuntimeError(json.dumps(candidate.error, ensure_ascii=False))
    candidate.commit()
    candidate.path = str(path)
    candidate.dirty = False
    DOCS[ACTIVE[0]] = candidate
    return candidate.state(ACTIVE[0])


def cmd_doc_export(a):
    d = doc()
    if not d.parts and not d.operations:
        raise geo_error("no_model", "нет модели для экспорта")
    fmt = a.get("format", "stl")
    p = d.build_params()
    p.update({"format": fmt, "path": str(Path(a["path"]).expanduser())})
    if a.get("linear_deflection"):
        p["linear_deflection"] = a["linear_deflection"]
    return worker_call("export", p, d.revision)


def cmd_doc_import(a):
    fmt = a.get("format", "stl")
    if fmt == "step":
        path = Path(a["path"]).expanduser()
        try:
            source = path.read_bytes()
        except OSError as error:
            raise geo_error("file_read_failed", f"Не удалось прочитать STEP: {error}") from error
        if not source or len(source) > 25 * 1024 * 1024:
            raise geo_error("step_source_invalid", "STEP должен быть непустым и не превышать 25 MiB.")
        candidate = Doc()
        candidate.operations = [{
            "op": "step_source",
            "source_base64": base64.b64encode(source).decode("ascii"),
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "source_name": path.name,
        }]
        candidate.rebuild()
        if candidate.error:
            raise RuntimeError(json.dumps(candidate.error, ensure_ascii=False))
        candidate.commit()
        DOCS[ACTIVE[0]] = candidate
        return {"stats": candidate.stats, "mesh": candidate.mesh, "mode": "brep",
                "document": candidate.state(ACTIVE[0])}
    return worker_call("import", {"format": fmt,
                                  "path": str(Path(a["path"]).expanduser()),
                                  "unit_scale": a.get("unit_scale", 1.0)})


def _require_mesh_document(document):
    if not document.operations or document.operations[0].get("op") not in {
            "mesh_source", "image_relief_source"}:
        raise geo_error("mesh_source_missing", "Сначала примените STL как mesh-документ.")


def cmd_doc_mesh_import_apply(a):
    d = doc()
    path = Path(a["path"]).expanduser()
    mesh_format = str(a.get("format", "stl")).lower()
    if mesh_format not in {"stl", "obj", "ply"}:
        raise geo_error("bad_params", f"Mesh workflow не поддерживает формат {mesh_format}.")
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise geo_error("file_read_failed", f"Не удалось прочитать mesh: {exc}") from exc
    if len(source) > 25 * 1024 * 1024:
        raise geo_error("mesh_too_large", "Mesh source превышает лимит 25 MiB.")
    try:
        unit_scale = float(a.get("unit_scale", 1.0))
    except (TypeError, ValueError) as error:
        raise geo_error("bad_params", "Масштаб mesh должен быть числом.") from error
    d.parts = []
    d.expressions = {}
    d.operations = [{
        "op": "mesh_source",
        "format": mesh_format,
        "source_base64": base64.b64encode(source).decode("ascii"),
        "unit_scale": unit_scale,
        "source_name": path.name,
    }]
    d._part_n = 0
    _rebuild_committed(d)
    return d.state(ACTIVE[0])


def cmd_doc_mesh_transform(a):
    _require_mesh_document(doc())
    return _apply_op(a, {
        "op": "mesh_transform",
        "translate": a.get("translate") or [0, 0, 0],
        "rotate_deg": a.get("rotate_deg") or [0, 0, 0],
        "scale": a.get("scale", 1),
    })


def cmd_doc_mesh_repair(a):
    _require_mesh_document(doc())
    return _apply_op(a, {"op": "mesh_repair", "action": a.get("action", "fill_holes")})


def cmd_doc_mesh_decimate(a):
    _require_mesh_document(doc())
    operation = {"op": "mesh_decimate", "target_ratio": a["target_ratio"]}
    for key in ("minimum_ratio", "maximum_ratio", "volume_tolerance"):
        if a.get(key) is not None:
            operation[key] = a[key]
    return _apply_op(a, operation)


def _image_relief_operation(a):
    path = Path(a["path"]).expanduser()
    try:
        source = path.read_bytes()
    except OSError as exc:
        raise geo_error("file_read_failed", f"Не удалось прочитать изображение: {exc}") from exc
    if len(source) > 8 * 1024 * 1024:
        raise geo_error("image_too_large", "Изображение превышает лимит 8 MiB.")
    source_sha256 = hashlib.sha256(source).hexdigest()
    expected = a.get("expected_sha256")
    if expected and expected != source_sha256:
        raise geo_error("image_changed", "Изображение изменилось после preview. Выполните preview повторно.")
    image_format = path.suffix.lower().lstrip(".")
    if image_format == "jpg":
        image_format = "jpeg"
    return {
        "op": "image_relief_source",
        "format": image_format,
        "source_base64": base64.b64encode(source).decode("ascii"),
        "source_name": path.name,
        "model": a.get("model", "heightmap-luminance-v1"),
        "seed": int(a.get("seed", 0)),
        "width_mm": float(a.get("width_mm", 50)),
        "relief_height": float(a.get("relief_height", 3)),
        "base_thickness": float(a.get("base_thickness", 1.5)),
        "samples": int(a.get("samples", 96)),
        "noise_strength": float(a.get("noise_strength", 0.015)),
        "invert": bool(a.get("invert", False)),
    }, source_sha256


def cmd_image_relief_preview(a):
    operation, source_sha256 = _image_relief_operation(a)
    result = worker_call("image_relief_preview", {
        key: value for key, value in operation.items() if key != "op"
    }, doc().revision)
    binding = worker_call("image_relief_settings_hash", {
        **operation, "path": a["path"], "source_sha256": source_sha256,
    }, doc().revision)
    return {**result, "source_sha256": source_sha256, **binding}


def cmd_doc_image_relief_apply(a):
    operation, source_sha256 = _image_relief_operation(a)
    binding = worker_call("image_relief_settings_hash", {
        **operation, "path": a["path"], "source_sha256": source_sha256,
    }, doc().revision)
    if not a.get("expected_settings_sha256") or a["expected_settings_sha256"] != binding["settings_sha256"]:
        raise geo_error("image_settings_changed", "Настройки изменились после preview. Выполните preview повторно.")
    d = doc()
    d.parts = []
    d.expressions = {}
    d.operations = [operation]
    d._part_n = 0
    _rebuild_committed(d)
    return d.state(ACTIVE[0])


def cmd_print_check(a):
    d = doc()
    if not d.parts and not d.operations:
        raise geo_error("no_model", "Сначала создайте деталь")
    p = d.build_params()
    p["printer"] = a.get("printer") or {}
    return worker_call("print_check", p, d.revision)


class PlanOperationError(ValueError):
    def __init__(self, index, cause):
        super().__init__(str(cause))
        self.index = index


def _apply_plan_ops_to(d, ops):
    """Применить проверенные операции плана к документу d как один снимок."""
    for index, op in enumerate(ops, 1):
        try:
            cid = op["command_id"]
            params = op["parameters"]
            if cid == "part.create.from_template":
                d.parts = []
                d.expressions = {}
                d.operations = []
                d._part_n = 0
                d.add_part(params["template"], params.get("params") or {})
            elif cid == "parameter.set":
                part = next(p for p in d.parts if p["part_id"] == op["target_id"])
                part["params"][params["name"]] = float(params["value"])
                d.expressions.pop(f"{op['target_id']}.{params['name']}", None)
            elif cid == "op.fillet":
                d.operations = [o for o in d.operations if o.get("op") != "fillet"]
                fop = {"op": "fillet", "radius": float(params["radius"]),
                       "edge_ref": params.get("edge_ref")}
                tid = op.get("target_id") or (d.parts[0]["part_id"] if d.parts else None)
                if tid:
                    fop["part_id"] = tid
                d.operations.append(fop)
        except (KeyError, StopIteration, TypeError, ValueError) as error:
            raise PlanOperationError(index, error) from error


def _first_failing_plan_operation(d, ops):
    """Локализовать первую геометрически невалидную операцию только при ошибке."""
    for index in range(1, len(ops) + 1):
        probe = copy.deepcopy(d)
        try:
            _apply_plan_ops_to(probe, ops[:index])
        except PlanOperationError as error:
            return error.index
        probe.rebuild()
        if probe.error:
            return index
    return len(ops)


def cmd_doc_transaction(a):
    """Единая транзакция (DOC-004): preview на копии либо apply одним шагом
    истории. Операции — уже провалидированный декларативный набор."""
    d = doc()
    instance_id = a.get("document_instance_id", d.document_instance_id)
    if instance_id != d.document_instance_id:
        raise geo_error("plan_stale", "План относится к другому открытию документа.")
    supplied_hash = a.get("plan_hash")
    expected_hash = ai_planner.plan_hash({
        "schema_version": 1,
        "document_id": d.doc_id,
        "document_instance_id": d.document_instance_id,
        "base_revision": a.get("base_revision", d.revision),
        "units": "mm",
        "operations": a.get("operations") or [],
    })
    if supplied_hash is not None and supplied_hash != expected_hash:
        raise geo_error("plan_conflict", "План изменён после предпросмотра; пересчитайте его.")
    action_id = a.get("action_id")
    if action_id and action_id in d.applied_actions:
        if d.applied_actions[action_id] != expected_hash:
            raise geo_error("action_conflict", "action_id уже использован для другого плана.")
        state = d.state(ACTIVE[0])
        state["idempotent_replay"] = True
        return state
    base = a.get("base_revision", d.revision)
    if base != d.revision:
        raise geo_error("plan_stale",
                        "Документ изменился, пока формировалось предложение. Пересчитайте.")
    ops = a.get("operations") or []
    if not ops:
        raise geo_error("plan_invalid", "Пустой набор операций.")
    if a.get("mode", "preview") == "preview":
        tmp = copy.deepcopy(d)
        try:
            _apply_plan_ops_to(tmp, ops)
            tmp.rebuild()
        except PlanOperationError as error:
            raise geo_error(
                "geometry_error",
                f"Предпросмотр не удался на операции {error.index}: {error}") from error
        preview_error = tmp.error
        if preview_error:
            preview_error = {
                **preview_error,
                "operation_index": _first_failing_plan_operation(d, ops),
            }
        return {"mode": "preview", "stats": tmp.stats, "error": preview_error,
                "parts": tmp.parts, "plan_hash": expected_hash,
                "base_revision": base,
                "document_instance_id": d.document_instance_id}
    # Сначала строим копию. Рабочий документ меняется только на commit boundary.
    tmp = copy.deepcopy(d)
    try:
        _apply_plan_ops_to(tmp, ops)
    except PlanOperationError as error:
        raise geo_error(
            "geometry_error",
            f"План не применён: операция {error.index}: {error}") from error
    tmp.rebuild()
    if tmp.error:
        operation_index = _first_failing_plan_operation(d, ops)
        raise geo_error(
            "geometry_error",
            f"План не применён: операция {operation_index}: "
            f"{tmp.error.get('message', 'ошибка геометрии')}")
    current = doc()
    if current is not d or current.document_instance_id != instance_id or current.revision != base:
        raise geo_error("plan_stale", "Документ изменился перед применением плана.")
    if action_id and action_id in d.applied_actions:
        if d.applied_actions[action_id] != expected_hash:
            raise geo_error("action_conflict", "action_id уже использован для другого плана.")
        state = d.state(ACTIVE[0])
        state["idempotent_replay"] = True
        return state
    d.restore(tmp.snapshot())
    d.commit()
    d.revision = tmp.revision
    d.stats = tmp.stats
    d.mesh = tmp.mesh
    d.error = None
    if action_id:
        d.applied_actions[action_id] = expected_hash
    return d.state(ACTIVE[0])


def cmd_ai_providers(a):
    return ai_planner.provider_info()


def cmd_ai_configure(a):
    try:
        return ai_planner.configure_provider(
            a.get("provider") or "disabled",
            a.get("base_url") or "",
            a.get("model") or "",
            a.get("api_key"),
            bool(a.get("clear_api_key")),
        )
    except ValueError as error:
        raise geo_error("ai_settings_invalid", str(error)) from error


def cmd_ai_test_connection(a):
    try:
        return ai_planner.test_connection()
    except (ValueError, OSError) as error:
        raise geo_error("ai_connection_failed", str(error)) from error


def cmd_ai_plan(a):
    d = doc()
    text = (a.get("text") or "").strip()
    if not text:
        raise geo_error("bad_request", "Пустой запрос.")
    task_id = str(a.get("task_id") or f"legacy-{uuid.uuid4()}")
    if (not task_id or len(task_id) > 128
            or any(not (char.isascii() and (char.isalnum() or char in "-_:"))
                   for char in task_id)):
        raise geo_error("bad_request", "Некорректный task_id AI-задачи.")
    cancelled = threading.Event()
    with _ai_tasks_lock:
        if task_id in _ai_tasks:
            raise geo_error("ai_task_conflict", "AI-задача с таким task_id уже выполняется.")
        _ai_tasks[task_id] = cancelled
    try:
        return ai_planner.ai_plan(
            text, d,
            lambda ops, base, digest: cmd_doc_transaction({
                "operations": ops,
                "base_revision": base,
                "document_instance_id": d.document_instance_id,
                "plan_hash": digest,
                "mode": "preview",
            }),
            cancelled.is_set,
        )
    finally:
        with _ai_tasks_lock:
            _ai_tasks.pop(task_id, None)


def cmd_ai_cancel(a):
    task_id = str(a.get("task_id") or "")
    with _ai_tasks_lock:
        task = _ai_tasks.get(task_id)
        if task is not None:
            task.set()
    geometry_cancelled = _cancel_geometry_task() if task is not None else False
    return {"task_id": task_id, "cancelled": task is not None,
            "geometry_cancelled": geometry_cancelled}


def cmd_geometry_cancel(_args):
    return {"cancelled": _cancel_geometry_task()}


def cmd_ai_chat(a):
    return {"content": ai_planner.ai_chat(a.get("messages") or [],
                                          bool(a.get("want_json")))}


def cmd_doc_new_tutorial(a):
    DOCS["tutorial"] = Doc()
    ACTIVE[0] = "tutorial"
    return doc().state(ACTIVE[0])


def cmd_doc_switch_slot(a):
    if a["slot"] not in DOCS:
        raise geo_error("bad_slot", "неизвестный слот")
    ACTIVE[0] = a["slot"]
    return doc().state(ACTIVE[0])


# Обратная совместимость с M1 UI
def cmd_doc_create_plate(a):
    a = dict(a)
    a["template"] = "plate_with_holes"
    return cmd_doc_create(a)


def cmd_doc_export_stl(a):
    a = dict(a)
    a["format"] = "stl"
    return cmd_doc_export(a)


HANDLERS = {
    "doc_create": cmd_doc_create,
    "doc_create_plate": cmd_doc_create_plate,
    "doc_set_parameter": cmd_doc_set_parameter,
    "doc_fillet": cmd_doc_fillet,
    "doc_chamfer": cmd_doc_chamfer,
    "doc_clear_error": cmd_doc_clear_error,
    "doc_undo": cmd_doc_undo,
    "doc_redo": cmd_doc_redo,
    "doc_get_state": cmd_doc_get_state,
    "doc_get_mesh": cmd_doc_get_mesh,
    "doc_get_imported_mesh": cmd_doc_get_imported_mesh,
    "doc_save": cmd_doc_save,
    "doc_open": cmd_doc_open,
    "doc_export": cmd_doc_export,
    "doc_export_stl": cmd_doc_export_stl,
    "doc_import": cmd_doc_import,
    "doc_mesh_import_apply": cmd_doc_mesh_import_apply,
    "doc_mesh_transform": cmd_doc_mesh_transform,
    "doc_mesh_repair": cmd_doc_mesh_repair,
    "doc_mesh_decimate": cmd_doc_mesh_decimate,
    "image_relief_preview": cmd_image_relief_preview,
    "doc_image_relief_apply": cmd_doc_image_relief_apply,
    "print_check": cmd_print_check,
    "doc_add_part": cmd_doc_add_part,
    "doc_boolean": cmd_doc_boolean,
    "doc_array": cmd_doc_array,
    "doc_mirror": cmd_doc_mirror,
    "doc_split": cmd_doc_split,
    "doc_transform": cmd_doc_transform,
    "doc_profile_extrude": cmd_doc_profile_extrude,
    "doc_sketch_extrude": cmd_doc_sketch_extrude,
    "sketch_solve": cmd_sketch_solve,
    "doc_constrained_sketch_extrude": cmd_doc_constrained_sketch_extrude,
    "doc_revolve": cmd_doc_revolve,
    "doc_sweep": cmd_doc_sweep,
    "doc_loft": cmd_doc_loft,
    "doc_shell": cmd_doc_shell,
    "doc_draft_prism": cmd_doc_draft_prism,
    "doc_rib": cmd_doc_rib,
    "doc_fit_pocket": cmd_doc_fit_pocket,
    "doc_vector_extrude": cmd_doc_vector_extrude,
    "doc_text_relief": cmd_doc_text_relief,
    "doc_thread_pair": cmd_doc_thread_pair,
    "doc_clearance_calibration": cmd_doc_clearance_calibration,
    "doc_split_connector_pair": cmd_doc_split_connector_pair,
    "doc_resize_body": cmd_doc_resize_body,
    "doc_designer_action": cmd_doc_designer_action,
    "doc_face_offset": cmd_doc_face_offset,
    "doc_face_feature": cmd_doc_face_feature,
    "doc_face_dome": cmd_doc_face_dome,
    "doc_sheet_bend": cmd_doc_sheet_bend,
    "doc_array_circular": cmd_doc_array_circular,
    "doc_align": cmd_doc_align,
    "measure": cmd_measure,
    "doc_transaction": cmd_doc_transaction,
    "ai_providers": cmd_ai_providers,
    "ai_configure": cmd_ai_configure,
    "ai_test_connection": cmd_ai_test_connection,
    "ai_plan": cmd_ai_plan,
    "ai_cancel": cmd_ai_cancel,
    "geometry_cancel": cmd_geometry_cancel,
    "ai_chat": cmd_ai_chat,
    "doc_new_tutorial": cmd_doc_new_tutorial,
    "doc_switch_slot": cmd_doc_switch_slot,
}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_POST(self):
        global AUTOSAVE
        name = self.path.removeprefix("/api/")
        handler = HANDLERS.get(name)
        length = int(self.headers.get("content-length", 0))
        args = json.loads(self.rfile.read(length) or b"{}")
        if not handler:
            self.send_response(404)
            self._cors()
            self.end_headers()
            return
        try:
            guard = nullcontext() if name in {"ai_cancel", "geometry_cancel"} else _command_lock
            with guard:
                result = handler(args)
                # автосохранение: debounce 30 с после изменений (DOC-007)
                pure_preview = name == "doc_designer_action" and args.get("preview") is True
                if name != "ai_cancel" and not pure_preview and ACTIVE[0] == "main":
                    d = doc()
                    if d.dirty and d.path and time.time() - AUTOSAVE["at"] > 30:
                        save_doc(d, Path(d.path))
                        d.dirty = False
                        AUTOSAVE = {"path": d.path, "at": time.time()}
            body = json.dumps(result, ensure_ascii=False).encode()
            self.send_response(200)
        except RuntimeError as e:
            body = json.dumps({"error": str(e)}, ensure_ascii=False).encode()
            self.send_response(500)
        except Exception as e:  # noqa: BLE001
            body = json.dumps({"error": json.dumps({
                "code": "internal", "message": str(e), "detail": ""
            }, ensure_ascii=False)}, ensure_ascii=False).encode()
            self.send_response(500)
        self._cors()
        self.send_header("content-type", "application/json")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("dev-shim: http://localhost:8787 (Ctrl+C для остановки)",
          file=sys.stderr)
    ThreadingHTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
