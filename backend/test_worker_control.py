import json
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dev_shim  # noqa: E402

pytestmark = pytest.mark.contract


class FakeStdin:
    def __init__(self, started):
        self.started = started
        self.writes = 0

    def write(self, _value):
        self.writes += 1

    def flush(self):
        self.started.set()


class FakeStdout:
    def __init__(self, stopped):
        self.stopped = stopped

    def readline(self):
        self.stopped.wait(timeout=5)
        return ""


class BlockingWorker:
    def __init__(self):
        self.started = threading.Event()
        self.stopped = threading.Event()
        self.stdin = FakeStdin(self.started)
        self.stdout = FakeStdout(self.stopped)
        self.returncode = None

    def poll(self):
        return self.returncode

    def kill(self):
        self.returncode = -9
        self.stopped.set()

    def wait(self, timeout=None):
        assert self.stopped.wait(timeout=timeout)
        return self.returncode


def test_geometry_cancel_interrupts_active_request_without_retry(monkeypatch):
    worker = BlockingWorker()
    monkeypatch.setattr(dev_shim, "_worker", worker)
    monkeypatch.setattr(dev_shim, "_geometry_task", None)
    errors = []

    def run_request():
        try:
            dev_shim.worker_call("build", {"template": "plate_with_holes"}, revision=7)
        except RuntimeError as error:
            errors.append(json.loads(str(error)))

    thread = threading.Thread(target=run_request)
    thread.start()
    assert worker.started.wait(timeout=5)
    assert dev_shim.cmd_geometry_cancel({}) == {"cancelled": True}
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert errors[0]["code"] == "geometry_cancelled"
    assert worker.stdin.writes == 1
    assert dev_shim._worker is None
    assert dev_shim._geometry_task is None
    assert dev_shim.cmd_geometry_cancel({}) == {"cancelled": False}


def test_geometry_timeout_kills_worker_without_retry(monkeypatch):
    worker = BlockingWorker()
    monkeypatch.setattr(dev_shim, "_worker", worker)
    monkeypatch.setattr(dev_shim, "_geometry_task", None)
    monkeypatch.setattr(dev_shim, "worker_timeout_seconds", lambda _method: 0.01)

    with pytest.raises(RuntimeError) as caught:
        dev_shim.worker_call("build", {"template": "plate_with_holes"}, revision=8)

    error = json.loads(str(caught.value))
    assert error["code"] == "worker_timeout"
    assert worker.stdin.writes == 1
    assert worker.poll() == -9
    assert dev_shim._worker is None
    assert dev_shim._geometry_task is None


def test_cancelled_parameter_rebuild_restores_confirmed_document(monkeypatch):
    document = dev_shim.Doc()
    document.add_part("plate_with_holes", {})
    document.commit()
    document.stats = {"volume": 1}
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"

    def cancelled_build(*_args, **_kwargs):
        raise dev_shim.geo_error("geometry_cancelled", "Операция отменена")

    monkeypatch.setattr(dev_shim, "worker_call", cancelled_build)
    history_len = len(document.history)
    state = dev_shim.cmd_doc_set_parameter({"name": "length", "value": 120})

    assert state["params"]["length"] == 80
    assert state["error"]["code"] == "geometry_cancelled"
    assert len(document.history) == history_len
    assert document.stats == {"volume": 1}
