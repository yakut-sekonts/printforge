#!/usr/bin/env python3
"""Dev-shim PrintForge: тот же IPC-контракт, что и Tauri (app/shared/ipc.md),
но по HTTP для запуска UI в обычном браузере (проверки дизайна AC-13).

ТОЛЬКО ДЛЯ РАЗРАБОТКИ. В поставку не входит.

Запуск: backend/.venv/bin/python scripts/dev_shim.py  (порт 8787)
"""
import copy
import json
import struct
import subprocess
import sys
import tempfile
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


class Doc:
    def __init__(self):
        self.params = {}
        self.expressions = {}
        self.history = [(dict(self.params), dict(self.expressions))]
        self.index = 0
        self.dirty = False
        self.path = None
        self.revision = 0
        self.stats = None
        self.mesh = None
        self.error = None

    def state(self, slot):
        return {
            "revision": self.revision, "dirty": self.dirty, "path": self.path,
            "slot": slot, "params": self.params,
            "expressions": self.expressions, "stats": self.stats,
            "error": self.error,
            "can_undo": self.index > 0,
            "can_redo": self.index + 1 < len(self.history),
        }

    def commit(self, params, expressions):
        del self.history[self.index + 1:]
        self.history.append((dict(params), dict(expressions)))
        self.index += 1
        self.params, self.expressions = dict(params), dict(expressions)
        self.dirty = True

    def rebuild(self):
        self.revision += 1
        p = {"length": 80, "width": 40, "height": 6,
             "hole_diameter": 4, "hole_offset": 10}
        p.update(self.params)
        try:
            result = worker_call("build_plate", p, self.revision)
            self.stats = result.get("stats")
            self.mesh = result.get("mesh")
            self.error = None
        except RuntimeError as e:
            self.error = json.loads(str(e))


DOCS = {"main": Doc(), "tutorial": Doc()}
ACTIVE = ["main"]


def doc():
    return DOCS[ACTIVE[0]]


def cmd_doc_create_plate(a):
    doc().commit({"length": a["length"], "width": a["width"],
                  "height": a["height"], "hole_diameter": a["hole_diameter"],
                  "hole_offset": a["hole_offset"]}, {})
    doc().rebuild()
    return doc().state(ACTIVE[0])


def cmd_doc_set_parameter(a):
    if not isinstance(a.get("value"), (int, float)) or a["value"] <= 0:
        raise RuntimeError(json.dumps({
            "code": "bad_value",
            "message": f"Значение параметра «{a['name']}» должно быть положительным числом.",
            "detail": ""}, ensure_ascii=False))
    params = dict(doc().params)
    exprs = dict(doc().expressions)
    params[a["name"]] = a["value"]
    if a.get("expression"):
        exprs[a["name"]] = a["expression"]
    else:
        exprs.pop(a["name"], None)
    doc().commit(params, exprs)
    doc().rebuild()
    return doc().state(ACTIVE[0])


def cmd_doc_undo(a):
    d = doc()
    if d.index > 0:
        d.index -= 1
        d.params, d.expressions = copy.deepcopy(d.history[d.index])
        d.dirty = True
        d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_redo(a):
    d = doc()
    if d.index + 1 < len(d.history):
        d.index += 1
        d.params, d.expressions = copy.deepcopy(d.history[d.index])
        d.dirty = True
        d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_get_state(a):
    return doc().state(ACTIVE[0])


def cmd_doc_get_mesh(a):
    if not doc().mesh:
        raise RuntimeError(json.dumps({"code": "no_model",
                                       "message": "модель ещё не построена",
                                       "detail": ""}, ensure_ascii=False))
    data = Path(doc().mesh["path"]).read_bytes()
    nv, nt = struct.unpack_from("<II", data)
    pos = list(struct.unpack_from(f"<{nv*3}f", data, 8))
    idx = list(struct.unpack_from(f"<{nt*3}I", data, 8 + nv * 12))
    return {"vertex_count": nv, "triangle_count": nt, "positions": pos,
            "indices": idx, "face_ranges": doc().mesh["face_ranges"]}


def cmd_doc_save(a):
    d = doc()
    path = Path(a["path"]).expanduser()
    tmp = path.with_suffix(".printforge.tmp")
    manifest = {"schema_version": 1, "app": "PrintForge",
                "app_version": "0.1.0-m1-shim", "units": "mm",
                "kernel": "build123d/OCP"}
    document = {"schema_version": 1, "units": "mm", "parameters": d.params,
                "expressions": d.expressions,
                "operations": [{"op": "plate_with_holes"}]}
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("document.json", json.dumps(document))
    tmp.replace(path)
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
        raise RuntimeError(json.dumps({
            "code": "bad_file",
            "message": "Это не файл проекта PrintForge или файл повреждён.",
            "detail": ""}, ensure_ascii=False))
    params = document.get("parameters") or {}
    if not params:
        raise RuntimeError(json.dumps({
            "code": "bad_file", "message": "В проекте нет параметров модели.",
            "detail": ""}, ensure_ascii=False))
    d.__init__()
    d.commit(params, document.get("expressions") or {})
    d.path = str(path)
    d.dirty = False
    d.rebuild()
    return d.state(ACTIVE[0])


def cmd_doc_export_stl(a):
    if not doc().params:
        raise RuntimeError(json.dumps({
            "code": "no_model", "message": "нет модели для экспорта",
            "detail": ""}, ensure_ascii=False))
    p = {"length": 80, "width": 40, "height": 6,
         "hole_diameter": 4, "hole_offset": 10}
    p.update(doc().params)
    p["path"] = str(Path(a["path"]).expanduser())
    if a.get("linear_deflection"):
        p["linear_deflection"] = a["linear_deflection"]
    return worker_call("export_stl", p, doc().revision)


def cmd_doc_new_tutorial(a):
    DOCS["tutorial"] = Doc()
    ACTIVE[0] = "tutorial"
    return doc().state(ACTIVE[0])


def cmd_doc_switch_slot(a):
    if a["slot"] not in DOCS:
        raise RuntimeError(json.dumps({"code": "bad_slot",
                                       "message": "неизвестный слот",
                                       "detail": ""}, ensure_ascii=False))
    ACTIVE[0] = a["slot"]
    return doc().state(ACTIVE[0])


HANDLERS = {
    "doc_create_plate": cmd_doc_create_plate,
    "doc_set_parameter": cmd_doc_set_parameter,
    "doc_undo": cmd_doc_undo,
    "doc_redo": cmd_doc_redo,
    "doc_get_state": cmd_doc_get_state,
    "doc_get_mesh": cmd_doc_get_mesh,
    "doc_save": cmd_doc_save,
    "doc_open": cmd_doc_open,
    "doc_export_stl": cmd_doc_export_stl,
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
