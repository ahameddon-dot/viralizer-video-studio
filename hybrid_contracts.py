from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class SceneRevisionCreate(BaseModel):
    expected_revision: int = Field(ge=1)
    patch: dict[str, Any]
    change_summary: str = Field(default="Scene updated in UI", max_length=500)


class ProjectEventCursor(BaseModel):
    after: int = Field(default=0, ge=0)


ActorType = Literal["user_ui", "user_chat", "system"]
