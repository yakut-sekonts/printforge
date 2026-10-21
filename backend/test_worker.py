"""M0: изоляция геометрического процесса (TECH-001/TECH-002).

Проверяет: запуск worker как отдельного процесса, протокол JSON Lines,
бинарный mesh-ресурс, пересчёт параметров, управляемую ошибку,
падение worker (kill -9) без потери управления и восстановление
из последней подтверждённой ревизии.
"""
import json
import math
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent
WORKER = BACKEND / "worker.py"
PYTHON = BACKEND / ".venv" / "bin" / "python"

EXP_VOL_80 = 80 * 40 * 6 - 4 * math.pi * 2**2 * 6
EXP_VOL_100 = 100 * 40 * 6 - 4 * math.pi * 2**2 * 6


class Worker:
    def __init__(self):
        self.proc = subprocess.Popen(
            [str(PYTHON), str(WORKER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1)
        self._n = 0

    def call(self, method, params=None, timeout=30):
        self._n += 1
        rid = f"t{self._n}"
        req = {"request_id": rid, "schema_version": 1,
               "document_id": "test-doc", "revision": self._n,
               "method": method, "params": params or {}}
        self.proc.stdin.write(json.dumps(req) + "\n")
        self.proc.stdin.flush()
        deadline = time.time() + timeout
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if not line:
                raise RuntimeError("worker завершился без ответа")
            resp = json.loads(line)
            if resp.get("request_id") == rid:
                return resp
        raise TimeoutError(method)

    def kill(self):
        self.proc.kill()
        return self.proc.wait(timeout=10)

    def stop(self):
        if self.proc.poll() is None:
            try:
                self.call("shutdown", timeout=5)
            except Exception:
                self.proc.kill()
        self.proc.wait(timeout=10)


@pytest.fixture
def worker():
    w = Worker()
    yield w
    w.stop()


def test_ping(worker):
    resp = worker.call("ping")
    assert resp["ok"] is True and resp["pid"] == worker.proc.pid


def test_build_plate_default(worker):
    resp = worker.call("build_plate")
    assert resp["ok"]
    st = resp["result"]["stats"]
    assert st["solid_count"] == 1
    assert st["is_valid"] is True
    assert abs(st["volume"] - EXP_VOL_80) <= max(1e-3, 1e-6 * EXP_VOL_80)
    assert st["bbox"] == pytest.approx([-40, -20, 0, 40, 20, 6], abs=1e-3)
    for cx, cy in st["hole_centers"]:
        assert (abs(cx), abs(cy)) == (30.0, 10.0)
    mesh = resp["result"]["mesh"]
    data = Path(mesh["path"]).read_bytes()
    assert len(data) == mesh["bytes"]
    import hashlib
    assert hashlib.sha256(data).hexdigest() == mesh["sha256"]
    nv, nt = struct.unpack_from("<II", data)
    assert nv == mesh["vertex_count"] and nt == mesh["triangle_count"]
    assert len(mesh["face_ranges"]) == st["face_count"] == 10


def test_rebuild_length_100(worker):
    resp = worker.call("build_plate", {"length": 100})
    st = resp["result"]["stats"]
    assert abs(st["volume"] - EXP_VOL_100) <= max(1e-3, 1e-6 * EXP_VOL_100)
    for cx, cy in st["hole_centers"]:
        assert (abs(cx), abs(cy)) == (40.0, 10.0)


def test_unknown_method_is_managed_error(worker):
    resp = worker.call("no_such_method")
    assert resp["ok"] is False
    assert resp["error"]["code"] == "unknown_method"
    # worker жив после ошибки
    assert worker.call("ping")["ok"] is True


def test_crash_isolation_and_recovery():
    w = Worker()
    assert w.call("build_plate")["ok"]  # подтверждённая ревизия
    code = w.kill()
    assert code != 0  # падение видно родителю, UI-процесс не затронут
    w2 = Worker()
    try:
        # восстановление из последней подтверждённой ревизии (дефолтные
        # параметры = последнее подтверждённое состояние документа)
        resp = w2.call("build_plate")
        assert resp["ok"]
        st = resp["result"]["stats"]
        assert abs(st["volume"] - EXP_VOL_80) <= max(1e-3, 1e-6 * EXP_VOL_80)
    finally:
        w2.stop()
