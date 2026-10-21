#!/usr/bin/env python3
"""Dev-shim PrintForge (M2): IPC-контракт app/shared/ipc.md по HTTP.
ТОЛЬКО ДЛЯ РАЗРАБОТКИ. Запуск: backend/.venv/bin/python scripts/dev_shim.py
"""
import copy
import json
import struct
import subprocess
import sys
import time
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKER = ROOT / "backend" / "worker.py"
PYTHON = ROOT / "backend" / ".venv" / "bin" / "python"

_worker = None
_req_n = 0


def worker_call(method, params, revision=0):
    global _worker, _req_n
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
    line = _worker.stdout.readline()
    resp = json.loads(line)
    if resp.get("ok"):
        return resp.get("result")
    err = resp.get("error", {})
    raise RuntimeError(json.dumps({
        "code": err.get("code", "geometry_error"),
        "message": err.get("message", "ошибка геометрии"),
        "detail": err.get("detail", "")}, ensure_ascii=False))


def geo_error(code, message):
    return RuntimeError(json.dumps({"code": code, "message": message,
                                    "detail": ""}, ensure_ascii=False))


DEFAULTS = {
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

    def __init__(self):
        Doc._ids += 1
        self.doc_id = f"doc-{Doc._ids}"
        self.template = None
        self.params = {}
        self.expressions = {}
        self.operations = []
        self.history = []
        self.index = -1
        self.dirty = False
        self.path = None
        self.revision = 0
        self.stats = None
        self.mesh = None
        self.error = None
        self.commit()

    def snapshot(self):
        return {"template": self.template, "params": copy.deepcopy(self.params),
                "expressions": dict(self.expressions),
                "operations": copy.deepcopy(self.operations)}

    def restore(self, snap):
        self.template = snap["template"]
        self.params = copy.deepcopy(snap["params"])
        self.expressions = dict(snap["expressions"])
        self.operations = copy.deepcopy(snap["operations"])

    def commit(self):
        del self.history[self.index + 1:]
        self.history.append(self.snapshot())
        self.index += 1
        self.dirty = True

    def state(self, slot):
        return {
            "doc_id": self.doc_id, "revision": self.revision,
            "dirty": self.dirty, "path": self.path, "slot": slot,
            "template": self.template, "params": self.params,
            "expressions": self.expressions, "operations": self.operations,
            "stats": self.stats, "error": self.error,
            "can_undo": self.index > 0,
            "can_redo": self.index + 1 < len(self.history),
            "history_len": len(self.history), "history_index": self.index,
        }

    def build_params(self):
        return {"template": self.template, "params": self.params,
                "operations": self.operations}

    def rebuild(self):
        if not self.template:
            return
        self.revision += 1
        try:
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
    d = doc()
    d.template = template
    d.params = dict(DEFAULTS[template])
    d.params.update({k: float(v) for k, v in (a.get("params") or {}).items()})
    d.expressions = {}
    d.operations = []
    d.commit()
    d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_set_parameter(a):
    d = doc()
    if not d.template:
        raise geo_error("no_model", "Сначала создайте деталь")
    if not isinstance(a.get("value"), (int, float)) or a["value"] <= 0:
        raise geo_error("bad_value",
                        f"Значение параметра «{a['name']}» должно быть положительным числом.")
    d.params[a["name"]] = a["value"]
    if a.get("expression"):
        d.expressions[a["name"]] = a["expression"]
    else:
        d.expressions.pop(a["name"], None)
    d.commit()
    d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_fillet(a):
    d = doc()
    radius = a.get("radius")
    if not isinstance(radius, (int, float)) or radius <= 0:
        raise geo_error("bad_value", "Радиус скругления должен быть больше нуля.")
    d.operations = [op for op in d.operations if op.get("op") != "fillet"]
    d.operations.append({"op": "fillet", "radius": radius,
                         "edge_ref": a["edge_ref"]})
    d.commit()
    d.rebuild()
    if d.error:
        # неудачная операция откатывается из истории, но ошибка видна (DOC-005)
        d.history.pop()
        d.index -= 1
        d.restore(d.history[d.index])
        d.dirty = True
    return d.state(ACTIVE[0])


def cmd_doc_clear_error(a):
    doc().error = None
    return doc().state(ACTIVE[0])


def cmd_doc_undo(a):
    d = doc()
    if d.index > 0:
        d.index -= 1
        d.restore(d.history[d.index])
        d.dirty = True
        d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_redo(a):
    d = doc()
    if d.index + 1 < len(d.history):
        d.index += 1
        d.restore(d.history[d.index])
        d.dirty = True
        d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_get_state(a):
    return doc().state(ACTIVE[0])


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
    manifest = {"schema_version": 2, "app": "PrintForge",
                "app_version": "0.1.0-m2", "units": "mm",
                "kernel": "build123d/OCP"}
    document = {"schema_version": 2, "units": "mm", "template": d.template,
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
    d = doc()
    path = Path(a["path"]).expanduser()
    try:
        with zipfile.ZipFile(path) as z:
            document = json.loads(z.read("document.json"))
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError):
        raise geo_error("bad_file", "Это не файл проекта PrintForge или файл повреждён.")
    template = document.get("template") or "plate_with_holes"
    if template not in DEFAULTS:
        raise geo_error("bad_file", f"Неизвестный шаблон в проекте: {template}")
    d.__init__()
    d.template = template
    d.params = {k: float(v) for k, v in (document.get("parameters") or {}).items()}
    d.expressions = document.get("expressions") or {}
    d.operations = document.get("operations") or []
    d.commit()
    d.path = str(path)
    d.dirty = False
    d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_export(a):
    d = doc()
    if not d.template:
        raise geo_error("no_model", "нет модели для экспорта")
    fmt = a.get("format", "stl")
    p = d.build_params()
    p.update({"format": fmt, "path": str(Path(a["path"]).expanduser())})
    if a.get("linear_deflection"):
        p["linear_deflection"] = a["linear_deflection"]
    return worker_call("export", p, d.revision)


def cmd_doc_import(a):
    fmt = a.get("format", "stl")
    return worker_call("import", {"format": fmt,
                                  "path": str(Path(a["path"]).expanduser()),
                                  "unit_scale": a.get("unit_scale", 1.0)})


def cmd_print_check(a):
    d = doc()
    if not d.template:
        raise geo_error("no_model", "Сначала создайте деталь")
    p = d.build_params()
    p["printer"] = a.get("printer") or {}
    return worker_call("print_check", p, d.revision)


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
    "doc_clear_error": cmd_doc_clear_error,
    "doc_undo": cmd_doc_undo,
    "doc_redo": cmd_doc_redo,
    "doc_get_state": cmd_doc_get_state,
    "doc_get_mesh": cmd_doc_get_mesh,
    "doc_save": cmd_doc_save,
    "doc_open": cmd_doc_open,
    "doc_export": cmd_doc_export,
    "doc_export_stl": cmd_doc_export_stl,
    "doc_import": cmd_doc_import,
    "print_check": cmd_print_check,
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
            result = handler(args)
            # автосохранение: debounce 30 с после изменений (DOC-007)
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
    HTTPServer(("127.0.0.1", 8787), Handler).serve_forever()
