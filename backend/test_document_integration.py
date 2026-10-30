"""Документ: сохранение идентичности проекта и новое instance при reopen."""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dev_shim  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def _stop_worker():
    worker = dev_shim._worker
    if worker is not None and worker.poll() is None:
        worker.terminate()
        worker.wait(timeout=10)
    dev_shim._worker = None


def test_save_reopen_preserves_document_id_and_replaces_instance(monkeypatch, tmp_path):
    _stop_worker()
    document = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", document)
    dev_shim.ACTIVE[0] = "main"
    try:
        created = dev_shim.cmd_doc_create({
            "template": "plate_with_holes",
            "params": {"length": 100},
        })
        project = tmp_path / "identity.printforge"
        saved = dev_shim.cmd_doc_save({"path": str(project)})
        assert saved["dirty"] is False

        reopened = dev_shim.cmd_doc_open({"path": str(project)})
        assert reopened["doc_id"] == created["doc_id"]
        assert reopened["document_instance_id"] != created["document_instance_id"]
        assert reopened["params"]["length"] == 100
        assert reopened["stats"]["volume"] == pytest.approx(created["stats"]["volume"], rel=1e-6)
        assert reopened["dirty"] is False
    finally:
        _stop_worker()
