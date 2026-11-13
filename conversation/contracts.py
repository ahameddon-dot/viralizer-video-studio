from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationCreate(BaseModel):
    title: str = Field(default="", max_length=200)
    active_project_context_id: str = Field(default="", max_length=64)


class MessageCreate(BaseModel):
    content: dict[str, Any]
    correlation_id: str = Field(default="", max_length=128)


class ConversationRespond(BaseModel):
    message_id: str = Field(default="", max_length=64)
    cost_confirmed: bool = False


class MemoryFactCreate(BaseModel):
    fact_key: str = Field(min_length=1, max_length=120, pattern=r"^[a-z0-9_.-]+$")
    value: Any
    source_message_id: str = Field(default="", max_length=64)
    confidence: float = Field(default=0.0, ge=0, le=1)


class MemoryFactConfirmation(BaseModel):
    accept: bool = True


class ToolExecutionPropose(BaseModel):
    message_id: str = Field(default="", max_length=64)
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, Any] = Field(default_factory=dict)
    workflow_run_id: str = Field(default="", max_length=64)
    cost_confirmed: bool = False
    idempotency_key: str = Field(min_length=1, max_length=255)
    correlation_id: str = Field(min_length=1, max_length=128)


class ToolExecutionConfirmation(BaseModel):
    confirm_provider_cost: bool = False


MessageRole = Literal["user", "assistant", "system", "tool"]
