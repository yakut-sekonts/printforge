"""PrintForge: геометрический worker (M0).

Отдельный процесс. Протокол: JSON Lines в stdout (одна строка = один ответ),
запросы — JSON Lines из stdin. Диагностика — только stderr.
Большие сетки не идут через JSON: worker пишет бинарный ресурс во временный
каталог сессии и возвращает handle (путь + размер + sha256).

Методы M0:
- ping: проверка живости.
- build_plate: построить пластину с отверстиями (AC-01), вернуть статистику
  и handle бинарной сетки (positions+indices, float32/uint32, little-endian).
- shutdown: завершиться.

Формат запроса:
  {"request_id": "...", "schema_version": 1, "document_id": "...",
   "revision": 0, "method": "build_plate", "params": {...}}
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
    out = {"request_id": request_id, "schema_version": SCHEMA_VERSION,
           "ok": ok}
    out.update(payload)
    sys.stdout.write(json.dumps(out) + "\n")
    sys.stdout.flush()


def build_plate(length, width, height, hole_d, hole_offset):
    from build123d import Box, Cylinder, GeomType, Pos
    hx = length / 2 - hole_offset
    hy = width / 2 - hole_offset
    part = Pos(0, 0, height / 2) * Box(length, width, height)
    for sx in (-hx, hx):
        for sy in (-hy, hy):
            part -= Pos(sx, sy, height / 2) * Cylinder(
                radius=hole_d / 2, height=height * 2)
    return part, hx, hy


def mesh_resource(part, name, tol=0.1):
    """Тесселяция по граням: positions float32, indices uint32,
    face_ranges для мэппинга треугольник -> грань."""
    positions = []
    indices = []
    face_ranges = []
    v_off = 0
    for fi, face in enumerate(part.faces()):
        verts, tris = face.tessellate(tol)
        for v in verts:
            x, y, z = tuple(v)
            positions.extend((float(x), float(y), float(z)))
        for a, b, c in tris:
            indices.extend((int(a) + v_off, int(b) + v_off, int(c) + v_off))
        face_ranges.append({"face_index": fi,
                            "tri_start": (len(indices) // 3)
                            - len(tris),
                            "tri_count": len(tris)})
        v_off += len(verts)
    blob = struct.pack("<II", len(positions) // 3, len(indices) // 3)
    blob += struct.pack(f"<{len(positions)}f", *positions)
    blob += struct.pack(f"<{len(indices)}I", *indices)
    path = _session_dir / f"{name}.bin"
    path.write_bytes(blob)
    return {
        "path": str(path),
        "bytes": len(blob),
        "sha256": hashlib.sha256(blob).hexdigest(),
        "vertex_count": len(positions) // 3,
        "triangle_count": len(indices) // 3,
        "face_ranges": face_ranges,
    }


def handle_build_plate(params):
    length = float(params.get("length", 80))
    width = float(params.get("width", 40))
    height = float(params.get("height", 6))
    hole_d = float(params.get("hole_diameter", 4))
    hole_offset = float(params.get("hole_offset", 10))
    part, hx, hy = build_plate(length, width, height, hole_d, hole_offset)
    bb = part.bounding_box()
    mesh = mesh_resource(part, "plate")
    return {
        "mesh": mesh,
        "stats": {
            "volume": part.volume,
            "solid_count": len(part.solids()),
            "face_count": len(part.faces()),
            "bbox": [bb.min.X, bb.min.Y, bb.min.Z,
                     bb.max.X, bb.max.Y, bb.max.Z],
            "hole_centers": [[-hx, -hy], [hx, -hy], [-hx, hy], [hx, hy]],
            "is_valid": bool(part.is_valid),
        },
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
            respond(None, False, error={"code": "bad_json",
                                        "message": str(e)})
            continue
        rid = req.get("request_id")
        method = req.get("method")
        try:
            if method == "ping":
                respond(rid, True, pid=os.getpid())
            elif method == "build_plate":
                respond(rid, True, result=handle_build_plate(
                    req.get("params") or {}))
            elif method == "shutdown":
                respond(rid, True)
                return 0
            else:
                respond(rid, False, error={"code": "unknown_method",
                                           "message": str(method)})
        except Exception as e:  # noqa: BLE001
            traceback.print_exc(file=sys.stderr)
            respond(rid, False, error={
                "code": "geometry_error",
                "message": str(e),
                "detail": traceback.format_exc(limit=5),
            })
    return 0


if __name__ == "__main__":
    sys.exit(main())
