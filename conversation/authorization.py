from __future__ import annotations

from pathlib import Path
from typing import Any

from conversation.registry import ToolDescriptor, get_tool
from hybrid_project_state import get_project_context


def authorize_tool(root: Path, customer_id: str, tool_name: str, project_context_id: str = "", *, cost_confirmed: bool = False) -> dict[str, Any]:
    tool: ToolDescriptor | None = get_tool(tool_name)
    if not tool:
        return {"authorized": False, "code": "unknown_tool", "reason": "Tool is not in the static registry."}
    if tool.requires_project:
        if not project_context_id:
            return {"authorized": False, "code": "project_required", "reason": "An active Autopilot project is required."}
        try:
            get_project_context(root, customer_id, project_context_id)
        except ValueError:
            return {"authorized": False, "code": "project_forbidden", "reason": "Project was not found for this customer."}
    if tool.authorization == "approval_only" or tool.approval == "exact_content":
        return {"authorized": False, "code": "human_approval_required", "reason": "Exact publication approval must be completed by the human through the existing approval endpoint."}
    if tool.approval == "confirm_cost" and not cost_confirmed:
        return {"authorized": False, "code": "cost_confirmation_required", "reason": "The customer must confirm the provider-cost action."}
    if not tool.model_execution_enabled:
        return {"authorized": False, "code": "manual_tool_only", "reason": "This tool is prepared but is not enabled for conversational execution."}
    return {
        "authorized": True,
        "code": "policy_allows",
        "reason": "Policy allows this conversational tool execution.",
        "execution_enabled": True,
        "authorization_class": tool.authorization,
        "approval": tool.approval,
        "cost": tool.cost,
    }
