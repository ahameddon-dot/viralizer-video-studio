"""Provider-free orchestration for inspectable Growth Autopilot agent work."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from autopilot_contracts import AgentObjectiveCreate, AgentSelection
from autopilot_store import create_workflow_run, enqueue_workflow_step, get_workflow_run
from creatorthon_store import _connect


def _load(value: Any) -> dict[str, Any]:
    try:
        return json.loads(value or "{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def create_objective(root: Path, customer_id: str, request: AgentObjectiveCreate | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, AgentObjectiveCreate) else AgentObjectiveCreate.model_validate(request)
    with _connect(root) as db:
        brand = db.execute("SELECT id FROM autopilot_brand_profiles WHERE customer_id=? AND status='confirmed' ORDER BY version DESC LIMIT 1", (customer_id,)).fetchone()
    if not brand:
        raise ValueError("Confirm a Brand Intelligence Profile before starting an agent objective.")
    payload = model.model_dump(mode="json")
    run = create_workflow_run(root, {"customer_id": customer_id, "workflow_type": "growth_objective", "input": payload})
    enqueue_workflow_step(root, {"customer_id": customer_id, "run_id": run["id"], "agent_type": "trend_discovery", "idempotency_key": f"{run['id']}:trend_discovery", "input": payload})
    with _connect(root) as db:
        db.execute("UPDATE autopilot_workflow_runs SET status='running' WHERE id=? AND customer_id=?", (run["id"], customer_id))
    return get_workflow_run(root, customer_id, run["id"]) or {"run": run, "steps": []}


def wait_for_user(root: Path, customer_id: str, run_id: str, agent_type: str, input_data: dict[str, Any]) -> dict[str, Any]:
    step, _ = enqueue_workflow_step(root, {"customer_id": customer_id, "run_id": run_id, "agent_type": agent_type, "idempotency_key": f"{run_id}:{agent_type}", "input": input_data})
    now = int(time.time())
    with _connect(root) as db:
        db.execute("UPDATE autopilot_workflow_steps SET status='waiting_user',updated_at=? WHERE id=? AND customer_id=?", (now, step["id"], customer_id))
        db.execute("UPDATE autopilot_workflow_runs SET status='waiting_user',updated_at=? WHERE id=? AND customer_id=?", (now, run_id, customer_id))
        row = db.execute("SELECT * FROM autopilot_workflow_steps WHERE id=?", (step["id"],)).fetchone()
    return dict(row)


def make_selection(root: Path, customer_id: str, run_id: str, selection_type: str, request: AgentSelection | dict[str, Any]) -> dict[str, Any]:
    model = request if isinstance(request, AgentSelection) else AgentSelection.model_validate(request)
    if selection_type not in {"opportunity_selection", "concept_selection"}:
        raise ValueError("Unsupported selection type.")
    with _connect(root) as db:
        run = db.execute("SELECT * FROM autopilot_workflow_runs WHERE id=? AND customer_id=?", (run_id, customer_id)).fetchone()
        step = db.execute("SELECT * FROM autopilot_workflow_steps WHERE run_id=? AND customer_id=? AND agent_type=? AND status='waiting_user' ORDER BY created_at DESC LIMIT 1", (run_id, customer_id, selection_type)).fetchone()
        if not run or not step:
            raise ValueError("The workflow is not waiting for this selection.")
        table = "autopilot_opportunities" if selection_type == "opportunity_selection" else "autopilot_creative_concepts"
        entity = db.execute(f"SELECT id FROM {table} WHERE id=? AND customer_id=?", (model.entity_id, customer_id)).fetchone()
        if not entity:
            raise ValueError("The selected item does not belong to this customer.")
        now = int(time.time())
        output = json.dumps({"selected_id": model.entity_id}, separators=(",", ":"))
        db.execute("UPDATE autopilot_workflow_steps SET status='succeeded',output_json=?,updated_at=? WHERE id=?", (output, now, dict(step)["id"]))
        db.execute("UPDATE autopilot_workflow_runs SET status='running',updated_at=? WHERE id=?", (now, run_id))
    run_input = _load(dict(run)["input_json"])
    next_agent = "creative_direction" if selection_type == "opportunity_selection" else "production_planning"
    next_input = dict(run_input)
    next_input["opportunity_id" if selection_type == "opportunity_selection" else "concept_id"] = model.entity_id
    enqueue_workflow_step(root, {"customer_id": customer_id, "run_id": run_id, "agent_type": next_agent, "idempotency_key": f"{run_id}:{next_agent}:{model.entity_id}", "input": next_input})
    return get_workflow_run(root, customer_id, run_id) or {}
