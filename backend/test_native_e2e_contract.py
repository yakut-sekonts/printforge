import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import run_native_ai_cancel_e2e  # noqa: E402

pytestmark = [pytest.mark.contract, pytest.mark.ai]


def test_loopback_plan_binds_ids_from_native_provider_request():
    body = {
        "messages": [{
            "role": "system",
            "content": 'Документ: {"document_id":7,"document_instance_id":9,"revision":3}',
        }],
    }
    plan = run_native_ai_cancel_e2e.plan_from_request(body)
    assert plan["document_id"] == 7
    assert plan["document_instance_id"] == 9
    assert plan["base_revision"] == 3
    assert plan["operations"][0]["command_id"] == "part.create.from_template"
    assert json.dumps(plan, ensure_ascii=False)


def test_native_cancel_gates_require_socket_close_geometry_kill_and_recovery():
    common = {
        "provider": {"request_count": 1, "response_started": True},
        "frontend": {
            "cancellation": {"cancelled": True, "geometry_cancelled": False},
            "outcome": {"ok": False, "error": {"code": "ai_cancelled"}},
            "state_unchanged": True,
        },
    }
    scenarios = {
        "ai-http-cancel": {
            **common,
            "provider": {**common["provider"], "client_disconnected": True},
        },
        "ai-cad-cancel": {
            **common,
            "frontend": {
                **common["frontend"],
                "cancellation": {"cancelled": True, "geometry_cancelled": True},
                "recovery": {"is_valid": True, "solid_count": 1},
            },
        },
    }
    signature = {"checked": True, "valid": True}
    gates = run_native_ai_cancel_e2e.evaluate_report(scenarios, signature)
    assert all(gate["status"] == "passed" for gate in gates.values())
    scenarios["ai-http-cancel"]["provider"]["client_disconnected"] = False
    assert run_native_ai_cancel_e2e.evaluate_report(
        scenarios, signature)["provider_http_cancel"]["status"] == "failed"
