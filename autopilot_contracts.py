"""Validated contracts for the Growth Autopilot foundation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class WorkflowRunCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=255)
    workflow_type: str = Field(min_length=1, max_length=80)
    input: dict[str, Any] = Field(default_factory=dict)


class WorkflowStepCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=255)
    run_id: str = Field(min_length=1, max_length=64)
    agent_type: str = Field(min_length=1, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=255)
    input: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=20)


class PublicationPayload(BaseModel):
    asset_version_id: str = Field(min_length=1, max_length=255)
    asset_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    caption: str = Field(default="", max_length=20_000)
    title: str = Field(default="", max_length=500)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    destination_id: str = Field(min_length=1, max_length=255)
    scheduled_at: int = Field(default=0, ge=0)


class ApprovalCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=255)
    approved_by: str = Field(min_length=1, max_length=255)
    publication: PublicationPayload


class WebhookReceipt(BaseModel):
    provider: str = Field(min_length=1, max_length=80)
    provider_event_id: str = Field(default="", max_length=255)
    signature_valid: bool
    payload: dict[str, Any]


class ProviderCostCreate(BaseModel):
    customer_id: str = Field(min_length=1, max_length=255)
    provider: str = Field(min_length=1, max_length=80)
    operation: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=255)
    workflow_step_id: str = ""
    quantity: str = "1"
    estimated_cost: str = "0"
    currency: str = Field(default="USD", min_length=3, max_length=3)
    metadata: dict[str, Any] = Field(default_factory=dict)


class BrandProfileUpsert(BaseModel):
    customer_type: Literal["creator", "business"]
    website_url: str = Field(default="", max_length=2_000)
    social_urls: list[str] = Field(default_factory=list, max_length=20)
    voice: list[str] = Field(default_factory=list, max_length=20)
    positioning: str = Field(default="", max_length=2_000)
    audiences: list[str] = Field(default_factory=list, max_length=20)
    goals: list[str] = Field(default_factory=list, max_length=20)
    products_services: list[str] = Field(default_factory=list, max_length=100)
    visual_style: list[str] = Field(default_factory=list, max_length=30)
    constraints: list[str] = Field(default_factory=list, max_length=50)
    confirmed: bool = False


class OpportunityRankRequest(BaseModel):
    topics: list[dict[str, Any]] = Field(min_length=1, max_length=50)
    limit: int = Field(default=5, ge=1, le=10)


class ConceptGenerateRequest(BaseModel):
    opportunity_id: str = Field(min_length=1, max_length=64)
    platform: Literal["youtube_shorts", "instagram", "tiktok", "linkedin"] = "youtube_shorts"
    goal: str = Field(default="", max_length=300)


class AssetVersionCreate(BaseModel):
    workflow_run_id: str = Field(min_length=1, max_length=64)
    concept_id: str = Field(min_length=1, max_length=64)
    media_url: str = Field(min_length=1, max_length=4_000)
    media_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    duration_seconds: float = Field(default=15, gt=0, le=600)
    aspect_ratio: str = Field(default="9:16", max_length=20)
    caption: str = Field(default="", max_length=20_000)
    title: str = Field(default="", max_length=500)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    qc: dict[str, Any] = Field(default_factory=dict)


class ProjectAssetRegistration(BaseModel):
    workflow_run_id: str = Field(min_length=1, max_length=64)
    concept_id: str = Field(min_length=1, max_length=64)
    project_id: str = Field(min_length=1, max_length=64)
    caption: str = Field(default="", max_length=20_000)
    title: str = Field(default="", max_length=500)
    hashtags: list[str] = Field(default_factory=list, max_length=100)


class PublicationApprovalRequest(BaseModel):
    workflow_run_id: str = Field(min_length=1, max_length=64)
    asset_version_id: str = Field(min_length=1, max_length=64)
    destination_id: str = Field(min_length=1, max_length=255)
    caption: str = Field(default="", max_length=20_000)
    title: str = Field(default="", max_length=500)
    hashtags: list[str] = Field(default_factory=list, max_length=100)
    scheduled_at: int = Field(default=0, ge=0)


class MetricSnapshotCreate(BaseModel):
    publication_id: str = Field(min_length=1, max_length=64)
    captured_at: int = Field(default=0, ge=0)
    metrics: dict[str, int | float | None] = Field(default_factory=dict)
    unavailable: list[str] = Field(default_factory=list, max_length=100)
    raw: dict[str, Any] = Field(default_factory=dict)


class ProviderConnectionUpsert(BaseModel):
    provider: Literal["post_for_me", "ga4", "shopify"]
    external_account_id: str = Field(default="", max_length=255)
    display_name: str = Field(default="", max_length=255)
    status: Literal["pending", "connected", "expired", "revoked", "error"] = "pending"
    capabilities: list[str] = Field(default_factory=list, max_length=50)
    secret_reference: str = Field(default="", max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AttributionEventCreate(BaseModel):
    provider: Literal["ga4", "shopify"]
    event_key: str = Field(min_length=1, max_length=255)
    publication_id: str = Field(default="", max_length=64)
    occurred_at: int = Field(default=0, ge=0)
    campaign_id: str = Field(default="", max_length=255)
    source: str = Field(default="", max_length=255)
    medium: str = Field(default="", max_length=255)
    content: str = Field(default="", max_length=255)
    sessions: float = Field(default=0, ge=0)
    conversions: float = Field(default=0, ge=0)
    revenue: float = Field(default=0, ge=0)
    currency: str = Field(default="", max_length=3)
    attribution_status: Literal["attributed", "unattributed", "ambiguous"] = "unattributed"
    raw: dict[str, Any] = Field(default_factory=dict)


class DestructiveConfirmation(BaseModel):
    confirmation: str = Field(min_length=1, max_length=500)


StepStatus = Literal[
    "queued", "running", "waiting_user", "retry_wait", "succeeded", "failed", "cancelled", "dead_letter"
]

