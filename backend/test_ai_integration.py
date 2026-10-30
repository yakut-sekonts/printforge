"""M3 deterministic AI pipeline через production shim и настоящий CAD-worker."""
import copy
import json
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ai_planner  # noqa: E402
import dev_shim  # noqa: E402

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel, pytest.mark.ai]


def _stop_worker():
    worker = dev_shim._worker
    if worker is not None and worker.poll() is None:
        worker.terminate()
        worker.wait(timeout=10)
    dev_shim._worker = None


@pytest.fixture
def isolated_shim(monkeypatch):
    _stop_worker()
    main = dev_shim.Doc()
    tutorial = dev_shim.Doc()
    monkeypatch.setitem(dev_shim.DOCS, "main", main)
    monkeypatch.setitem(dev_shim.DOCS, "tutorial", tutorial)
    dev_shim.ACTIVE[0] = "main"
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "scripted",
        "base_url": "",
        "model": "scripted-v1",
        "api_key": "",
    })
    yield main
    _stop_worker()


def _transaction_args(response, *, action_id=None, operations=None):
    return {
        "operations": operations or response["plan"]["operations"],
        "base_revision": response["plan"]["base_revision"],
        "document_instance_id": response["plan"]["document_instance_id"],
        "plan_hash": response["plan_hash"],
        "action_id": action_id or response["action_id"],
        "mode": "apply",
    }


def _semantic_state(document):
    return {
        "parts": copy.deepcopy(document.parts),
        "expressions": copy.deepcopy(document.expressions),
        "operations": copy.deepcopy(document.operations),
        "revision": document.revision,
        "dirty": document.dirty,
        "history_len": len(document.history),
        "history_index": document.index,
    }


def test_ai_washer_preview_apply_export_and_single_undo(isolated_shim, tmp_path):
    before = _semantic_state(isolated_shim)
    response = dev_shim.cmd_ai_plan({
        "text": "Создай шайбу: наружный диаметр 20 мм, внутренний 6 мм, высота 4 мм",
    })

    expected_volume = 364 * math.pi
    assert response["preview"]["stats"]["volume"] == pytest.approx(
        expected_volume, abs=max(0.001, 1e-6 * expected_volume))
    assert response["preview"]["stats"]["solid_count"] == 1
    assert response["preview"]["plan_hash"] == response["plan_hash"]
    assert _semantic_state(isolated_shim) == before

    applied = dev_shim.cmd_doc_transaction(_transaction_args(response))
    assert applied["stats"]["volume"] == pytest.approx(
        expected_volume, abs=max(0.001, 1e-6 * expected_volume))
    assert applied["history_len"] == before["history_len"] + 1
    applied_revision = applied["revision"]

    exported = tmp_path / "ai-washer.stl"
    result = dev_shim.cmd_doc_export({
        "path": str(exported),
        "format": "stl",
        "linear_deflection": 0.02,
    })
    assert result["stats"]["volume"] == pytest.approx(expected_volume, rel=0.005)
    assert exported.stat().st_size > 0

    undone = dev_shim.cmd_doc_undo({})
    assert undone["parts"] == []
    assert undone["revision"] > applied_revision
    assert undone["can_redo"] is True
    redone = dev_shim.cmd_doc_redo({})
    assert redone["stats"]["volume"] == pytest.approx(expected_volume, rel=1e-6)
    assert redone["revision"] > undone["revision"]


def test_manual_cad_works_with_ai_disabled(isolated_shim, monkeypatch):
    monkeypatch.setattr(ai_planner, "_PROVIDER_CONFIG", {
        "provider": "disabled", "base_url": "", "model": "", "api_key": "",
    })
    state = dev_shim.cmd_doc_create({"template": "washer", "params": {}})
    assert state["stats"]["volume"] == pytest.approx(364 * math.pi, rel=1e-6)
    with pytest.raises(RuntimeError, match="ai_disabled"):
        dev_shim.cmd_ai_plan({"text": "создай шайбу"})


def test_ai_apply_is_atomic_when_last_operation_fails(isolated_shim):
    operations = [
        {
            "command_id": "part.create.from_template",
            "target_id": None,
            "parameters": {"template": "bracket_l", "params": {}},
        },
        {
            "command_id": "op.fillet",
            "target_id": "part-1",
            "parameters": {"radius": 50, "edge_ref": None},
        },
    ]
    before = _semantic_state(isolated_shim)
    digest = ai_planner.plan_hash({
        "schema_version": 1,
        "document_id": isolated_shim.doc_id,
        "document_instance_id": isolated_shim.document_instance_id,
        "base_revision": isolated_shim.revision,
        "units": "mm",
        "operations": operations,
    })

    with pytest.raises(RuntimeError, match="План не применён"):
        dev_shim.cmd_doc_transaction({
            "operations": operations,
            "base_revision": isolated_shim.revision,
            "document_instance_id": isolated_shim.document_instance_id,
            "plan_hash": digest,
            "action_id": "atomic-failure",
            "mode": "apply",
        })

    assert _semantic_state(isolated_shim) == before
    assert "atomic-failure" not in isolated_shim.applied_actions


def test_plan_binding_idempotency_conflict_and_instance_guard(isolated_shim):
    response = dev_shim.cmd_ai_plan({
        "text": "Создай шайбу: наружный диаметр 20 мм, внутренний 6 мм, высота 4 мм",
    })
    args = _transaction_args(response)

    changed_args = {**args, "plan_hash": "0" * 64}
    with pytest.raises(RuntimeError, match="plan_conflict"):
        dev_shim.cmd_doc_transaction(changed_args)

    first = dev_shim.cmd_doc_transaction(args)
    replay = dev_shim.cmd_doc_transaction(args)
    assert replay["idempotent_replay"] is True
    assert replay["revision"] == first["revision"]
    assert replay["history_len"] == first["history_len"]

    different_operations = [{
        "command_id": "part.create.from_template",
        "target_id": None,
        "parameters": {
            "template": "washer",
            "params": {"outer_diameter": 24, "inner_diameter": 6, "height": 4},
        },
    }]
    different_hash = ai_planner.plan_hash({
        "schema_version": 1,
        "document_id": response["plan"]["document_id"],
        "document_instance_id": response["plan"]["document_instance_id"],
        "base_revision": response["plan"]["base_revision"],
        "units": "mm",
        "operations": different_operations,
    })
    with pytest.raises(RuntimeError, match="action_conflict"):
        dev_shim.cmd_doc_transaction({
            **args,
            "operations": different_operations,
            "plan_hash": different_hash,
        })

    replacement = dev_shim.Doc(isolated_shim.doc_id)
    dev_shim.DOCS["main"] = replacement
    with pytest.raises(RuntimeError, match="другому открытию"):
        dev_shim.cmd_doc_transaction(args)


def test_stale_plan_and_aba_never_commit(isolated_shim):
    created = dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {}})
    operation = [{
        "command_id": "parameter.set",
        "target_id": created["parts"][0]["part_id"],
        "parameters": {"name": "length", "value": 100},
    }]
    plan = {
        "schema_version": 1,
        "document_id": created["doc_id"],
        "document_instance_id": created["document_instance_id"],
        "base_revision": created["revision"],
        "units": "mm",
        "operations": operation,
    }
    digest = ai_planner.plan_hash(plan)
    dev_shim.cmd_doc_transaction({
        "operations": operation,
        "base_revision": created["revision"],
        "document_instance_id": created["document_instance_id"],
        "plan_hash": digest,
        "mode": "preview",
    })

    changed = dev_shim.cmd_doc_set_parameter({"name": "length", "value": 90})
    restored = dev_shim.cmd_doc_undo({})
    assert restored["params"]["length"] == 80
    assert restored["revision"] > changed["revision"]
    before_history = restored["history_len"]

    with pytest.raises(RuntimeError, match="plan_stale"):
        dev_shim.cmd_doc_transaction({
            "operations": operation,
            "base_revision": created["revision"],
            "document_instance_id": created["document_instance_id"],
            "plan_hash": digest,
            "action_id": "aba",
            "mode": "apply",
        })
    after = dev_shim.cmd_doc_get_state({})
    assert after["params"]["length"] == 80
    assert after["history_len"] == before_history


def test_only_one_of_two_plans_from_same_revision_commits(isolated_shim):
    first_plan = dev_shim.cmd_ai_plan({"text": "создай шайбу 20 на 6, высота 4"})
    second_plan = dev_shim.cmd_ai_plan({"text": "создай шайбу 24 на 6, высота 4"})
    assert first_plan["plan"]["base_revision"] == second_plan["plan"]["base_revision"]

    first = dev_shim.cmd_doc_transaction(_transaction_args(first_plan))
    with pytest.raises(RuntimeError, match="plan_stale"):
        dev_shim.cmd_doc_transaction(_transaction_args(second_plan))
    state = dev_shim.cmd_doc_get_state({})
    assert state["revision"] == first["revision"]
    assert state["history_len"] == first["history_len"]


def test_revision_is_checked_again_at_commit_boundary(isolated_shim, monkeypatch):
    created = dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {}})
    operation = [{
        "command_id": "parameter.set",
        "target_id": created["parts"][0]["part_id"],
        "parameters": {"name": "length", "value": 100},
    }]
    digest = ai_planner.plan_hash({
        "schema_version": 1,
        "document_id": created["doc_id"],
        "document_instance_id": created["document_instance_id"],
        "base_revision": created["revision"],
        "units": "mm",
        "operations": operation,
    })
    real_worker_call = dev_shim.worker_call
    injected = False

    def worker_call_with_concurrent_edit(method, params, revision=0):
        nonlocal injected
        result = real_worker_call(method, params, revision)
        if method == "build" and not injected:
            injected = True
            isolated_shim.parts[0]["params"]["length"] = 90
            isolated_shim.commit()
            isolated_shim.revision += 1
        return result

    monkeypatch.setattr(dev_shim, "worker_call", worker_call_with_concurrent_edit)
    with pytest.raises(RuntimeError, match="перед применением"):
        dev_shim.cmd_doc_transaction({
            "operations": operation,
            "base_revision": created["revision"],
            "document_instance_id": created["document_instance_id"],
            "plan_hash": digest,
            "action_id": "commit-boundary",
            "mode": "apply",
        })
    assert isolated_shim.params["length"] == 90
    assert "commit-boundary" not in isolated_shim.applied_actions
