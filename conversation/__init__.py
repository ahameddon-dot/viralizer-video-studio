"""Conversation orchestration feature state."""

import os

MODEL_ORCHESTRATION_ENABLED = bool(os.getenv("OPENAI_API_KEY", "").strip()) and os.getenv("CONVERSATION_AI_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}
