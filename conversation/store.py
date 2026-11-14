from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path
from typing import Any

from conversation.authorization import authorize_tool
from conversation.redaction import redact
from conversation.registry import get_tool
from creatorthon_store import _connect
from hybrid_project_state import get_project_context


def _json(value: Any) -> str:
    return json.dumps(redact(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _load(value: Any, default: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, ValueError):
        return default


def create_conversation(root: Path, customer_id: str, title: str = "", active_project_context_id: str = "", created_by: str = "") -> dict[str, Any]:
    if active_project_context_id:
        get_project_context(root, customer_id, active_project_context_id)
    now, conversation_id = int(time.time()), uuid.uuid4().hex
    with _connect(root) as db:
        row = db.execute(
            """INSERT INTO conversation_threads
            (id,customer_id,title,status,active_project_context_id,created_by,created_at,updated_at)
            VALUES(?,?,?,'active',?,?,?,?) RETURNING *""",
            (conversation_id, customer_id, " ".join(title.split())[:200], active_project_context_id or None, created_by, now, now),
        ).fetchone()
    return dict(row)


def list_conversations(root: Path, customer_id: str, limit: int = 50) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM conversation_threads WHERE customer_id=? ORDER BY updated_at DESC LIMIT ?",
            (customer_id, max(1, min(100, limit))),
        ).fetchall()
    return [dict(row) for row in rows]


def get_conversation(root: Path, customer_id: str, conversation_id: str, include_messages: bool = True) -> dict[str, Any]:
    with _connect(root) as db:
        row = db.execute("SELECT * FROM conversation_threads WHERE id=? AND customer_id=?", (conversation_id, customer_id)).fetchone()
        if not row:
            raise ValueError("Conversation was not found for this customer.")
        result = dict(row)
        if include_messages:
            messages = [dict(item) for item in db.execute(
                "SELECT * FROM conversation_messages WHERE conversation_id=? AND customer_id=? ORDER BY sequence",
                (conversation_id, customer_id),
            ).fetchall()]
        else:
            messages = []
    for message in messages:
        message["content"] = _load(message.pop("content_json"), {})
    result["messages"] = messages
    return result


def attach_project(root: Path, customer_id: str, conversation_id: str, project_context_id: str) -> dict[str, Any]:
    """Attach the shared Hybrid/UI project to a conversation after concept creation."""
    get_project_context(root, customer_id, project_context_id)
    with _connect(root) as db:
        row = db.execute(
            """UPDATE conversation_threads SET active_project_context_id=?,updated_at=?
            WHERE id=? AND customer_id=? AND status='active' RETURNING *""",
            (project_context_id, int(time.time()), conversation_id, customer_id),
        ).fetchone()
    if not row:
        raise ValueError("Conversation was not found for this customer.")
    return dict(row)


def append_message(root: Path, customer_id: str, conversation_id: str, role: str, content: dict[str, Any], correlation_id: str = "") -> dict[str, Any]:
    if role not in {"user", "assistant", "system", "tool"}:
        raise ValueError("Unsupported conversation role.")
    if not isinstance(content, dict) or not content:
        raise ValueError("Message content is required.")
    now, message_id = int(time.time()), uuid.uuid4().hex
    with _connect(root) as db:
        thread = db.execute("SELECT id,status FROM conversation_threads WHERE id=? AND customer_id=?", (conversation_id, customer_id)).fetchone()
        if not thread:
            raise ValueError("Conversation was not found for this customer.")
        if dict(thread)["status"] != "active":
            raise ValueError("Conversation is archived.")
        sequence_row = db.execute(
            """UPDATE conversation_threads SET message_sequence=message_sequence+1,updated_at=?
            WHERE id=? AND customer_id=? AND status='active' RETURNING message_sequence""",
            (now, conversation_id, customer_id),
        ).fetchone()
        sequence = int(dict(sequence_row)["message_sequence"])
        row = db.execute(
            """INSERT INTO conversation_messages
            (id,conversation_id,customer_id,role,content_json,sequence,correlation_id,created_at)
            VALUES(?,?,?,?,?,?,?,?) RETURNING *""",
            (message_id, conversation_id, customer_id, role, _json(content), sequence, correlation_id[:128], now),
        ).fetchone()
    result = dict(row)
    result["content"] = _load(result.pop("content_json"), {})
    return result


def propose_memory_fact(root: Path, customer_id: str, conversation_id: str, fact_key: str, value: Any,
                        source_message_id: str = "", confidence: float = 0.0) -> dict[str, Any]:
    if not re.fullmatch(r"[a-z0-9_.-]{1,120}", fact_key):
        raise ValueError("Memory fact key is invalid.")
    if not 0 <= float(confidence) <= 1:
        raise ValueError("Memory confidence must be between 0 and 1.")
    get_conversation(root, customer_id, conversation_id, include_messages=False)
    now, fact_id = int(time.time()), uuid.uuid4().hex
    with _connect(root) as db:
        if source_message_id:
            source = db.execute("SELECT id FROM conversation_messages WHERE id=? AND conversation_id=? AND customer_id=?", (source_message_id, conversation_id, customer_id)).fetchone()
            if not source:
                raise ValueError("Source message was not found for this customer conversation.")
        row = db.execute(
            """INSERT INTO conversation_memory_facts
            (id,customer_id,conversation_id,fact_key,value_json,source_message_id,confidence,confirmation_status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,'proposed',?,?) RETURNING *""",
            (fact_id, customer_id, conversation_id, fact_key, _json(value), source_message_id or None, str(float(confidence)), now, now),
        ).fetchone()
    result = dict(row); result["value"] = _load(result.pop("value_json"), None)
    return result


def confirm_memory_fact(root: Path, customer_id: str, fact_id: str, confirmed_by: str, accept: bool = True) -> dict[str, Any]:
    now = int(time.time())
    with _connect(root) as db:
        fact = db.execute("SELECT * FROM conversation_memory_facts WHERE id=? AND customer_id=?", (fact_id, customer_id)).fetchone()
        if not fact:
            raise ValueError("Memory fact was not found for this customer.")
        current = dict(fact)
        if current["confirmation_status"] != "proposed":
            raise ValueError("Memory fact is no longer awaiting confirmation.")
        status = "confirmed" if accept else "rejected"
        if accept:
            db.execute(
                "UPDATE conversation_memory_facts SET confirmation_status='superseded',updated_at=? WHERE customer_id=? AND fact_key=? AND confirmation_status='confirmed' AND id<>?",
                (now, customer_id, current["fact_key"], fact_id),
            )
        row = db.execute(
            "UPDATE conversation_memory_facts SET confirmation_status=?,confirmed_by=?,updated_at=? WHERE id=? AND customer_id=? RETURNING *",
            (status, confirmed_by, now, fact_id, customer_id),
        ).fetchone()
    result = dict(row); result["value"] = _load(result.pop("value_json"), None)
    return result


def confirmed_memory(root: Path, customer_id: str) -> list[dict[str, Any]]:
    with _connect(root) as db:
        rows = db.execute(
            "SELECT * FROM conversation_memory_facts WHERE customer_id=? AND confirmation_status='confirmed' ORDER BY updated_at DESC",
            (customer_id,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row); item["value"] = _load(item.pop("value_json"), None); result.append(item)
    return result


def propose_tool_execution(root: Path, customer_id: str, conversation_id: str, tool_name: str, arguments: dict[str, Any],
                           idempotency_key: str, correlation_id: str, message_id: str = "", workflow_run_id: str = "",
                           cost_confirmed: bool = False) -> dict[str, Any]:
    conversation = get_conversation(root, customer_id, conversation_id, include_messages=False)
    tool = get_tool(tool_name)
    if not tool:
        raise ValueError("Tool is not in the static registry.")
    project_id = str(conversation.get("active_project_context_id") or "")
    decision = authorize_tool(root, customer_id, tool_name, project_id, cost_confirmed=cost_confirmed)
    now, execution_id = int(time.time()), uuid.uuid4().hex
    status = "proposed" if decision.get("authorized") else "blocked"
    approval_status = "required" if decision.get("code") in {"cost_confirmation_required", "human_approval_required"} else "not_required"
    with _connect(root) as db:
        if message_id and not db.execute("SELECT id FROM conversation_messages WHERE id=? AND conversation_id=? AND customer_id=?", (message_id, conversation_id, customer_id)).fetchone():
            raise ValueError("Tool message was not found for this customer conversation.")
        if workflow_run_id and not db.execute("SELECT id FROM autopilot_workflow_runs WHERE id=? AND customer_id=?", (workflow_run_id, customer_id)).fetchone():
            raise ValueError("Workflow run was not found for this customer.")
        row = db.execute(
            """INSERT INTO conversation_tool_executions
            (id,conversation_id,customer_id,message_id,workflow_run_id,project_context_id,tool_name,tool_version,
             arguments_json,authorization_json,cost_class,approval_status,status,idempotency_key,correlation_id,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(customer_id,idempotency_key) DO NOTHING RETURNING *""",
            (execution_id, conversation_id, customer_id, message_id or None, workflow_run_id or None, project_id or None,
             tool.name, tool.version, _json(arguments), _json(decision), tool.cost, approval_status, status,
             idempotency_key, correlation_id, now, now),
        ).fetchone()
        if not row:
            row = db.execute("SELECT * FROM conversation_tool_executions WHERE customer_id=? AND idempotency_key=?", (customer_id, idempotency_key)).fetchone()
    result = dict(row)
    for source, target in (("arguments_json", "arguments"), ("authorization_json", "authorization"), ("result_json", "result"), ("error_json", "error")):
        result[target] = _load(result.pop(source), {})
    return result


def complete_tool_execution(root: Path, customer_id: str, execution_id: str, result: Any = None, error: Any = None) -> dict[str, Any]:
    """Finalize one audited tool execution without persisting provider secrets."""
    now, status = int(time.time()), "failed" if error else "succeeded"
    with _connect(root) as db:
        row = db.execute(
            """UPDATE conversation_tool_executions SET status=?,result_json=?,error_json=?,updated_at=?
            WHERE id=? AND customer_id=? AND status='proposed' RETURNING *""",
            (status, _json(result or {}), _json(error or {}), now, execution_id, customer_id),
        ).fetchone()
    if not row:
        raise ValueError("Tool execution was not found or is no longer pending.")
    item = dict(row)
    for source, target in (("arguments_json", "arguments"), ("authorization_json", "authorization"), ("result_json", "result"), ("error_json", "error")):
        item[target] = _load(item.pop(source), {})
    return item


def confirm_tool_execution(root: Path, customer_id: str, conversation_id: str, execution_id: str) -> dict[str, Any]:
    """Convert one blocked provider-cost proposal into an executable audited action."""
    with _connect(root) as db:
        row = db.execute(
            "SELECT * FROM conversation_tool_executions WHERE id=? AND customer_id=? AND conversation_id=?",
            (execution_id, customer_id, conversation_id),
        ).fetchone()
        if not row:
            raise ValueError("Tool execution was not found for this conversation.")
        current = dict(row)
        authorization = _load(current.get("authorization_json"), {})
        if current.get("status") != "blocked" or authorization.get("code") != "cost_confirmation_required":
            raise ValueError("This action is not awaiting provider-cost confirmation.")
        decision = authorize_tool(root, customer_id, str(current.get("tool_name") or ""), str(current.get("project_context_id") or ""), cost_confirmed=True)
        if not decision.get("execution_enabled"):
            raise PermissionError(str(decision.get("reason") or "The action is not authorized."))
        updated = db.execute(
            """UPDATE conversation_tool_executions SET authorization_json=?,approval_status='confirmed',status='proposed',updated_at=?
            WHERE id=? AND customer_id=? AND conversation_id=? AND status='blocked' RETURNING *""",
            (_json(decision), int(time.time()), execution_id, customer_id, conversation_id),
        ).fetchone()
    if not updated:
        raise ValueError("This action has already been handled.")
    result = dict(updated)
    for source, target in (("arguments_json", "arguments"), ("authorization_json", "authorization"), ("result_json", "result"), ("error_json", "error")):
        result[target] = _load(result.pop(source), {})
    return result


def link_workflow(root: Path, customer_id: str, conversation_id: str, workflow_run_id: str, project_context_id: str = "", purpose: str = "") -> dict[str, Any]:
    get_conversation(root, customer_id, conversation_id, include_messages=False)
    if project_context_id:
        get_project_context(root, customer_id, project_context_id)
    now = int(time.time())
    with _connect(root) as db:
        if not db.execute("SELECT id FROM autopilot_workflow_runs WHERE id=? AND customer_id=?", (workflow_run_id, customer_id)).fetchone():
            raise ValueError("Workflow run was not found for this customer.")
        row = db.execute(
            """INSERT INTO conversation_workflow_links
            (conversation_id,customer_id,project_context_id,workflow_run_id,purpose,created_at)
            VALUES(?,?,?,?,?,?) ON CONFLICT(conversation_id,workflow_run_id)
            DO UPDATE SET project_context_id=excluded.project_context_id,purpose=excluded.purpose RETURNING *""",
            (conversation_id, customer_id, project_context_id or None, workflow_run_id, purpose[:200], now),
        ).fetchone()
    return dict(row)
