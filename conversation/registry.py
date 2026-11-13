from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


AuthorizationClass = Literal["customer_read", "customer_write", "costed_write", "approval_only"]
CostClass = Literal["none", "low", "provider_cost"]
ApprovalPolicy = Literal["none", "confirm_change", "confirm_cost", "exact_content"]


@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    version: str
    implementation: str
    input_schema: str
    output_schema: str
    authorization: AuthorizationClass
    cost: CostClass
    approval: ApprovalPolicy
    requires_project: bool = False
    resumable: bool = False
    model_execution_enabled: bool = False
    wrapper_required: bool = False

    def public(self) -> dict:
        return asdict(self)


_TOOLS = (
    ToolDescriptor("get_brand_profile", "1", "autopilot_intelligence:get_brand_profile", "GetBrandProfileInput", "BrandProfileOutput", "customer_read", "none", "none", model_execution_enabled=True),
    ToolDescriptor("analyze_brand_sources", "1", "autopilot_brand_analysis:analyze_brand_sources", "AnalyzeBrandSourcesInput", "BrandSourceAnalysisOutput", "customer_read", "low", "none", model_execution_enabled=True),
    ToolDescriptor("discover_topics", "2", "viralizer_topic_source:fetch_v3_worldwide_topics", "DiscoverTopicsInput", "TopicsOutput", "customer_read", "low", "none", model_execution_enabled=True),
    ToolDescriptor("rank_opportunities", "1", "autopilot_intelligence:rank_opportunities", "RankOpportunitiesInput", "OpportunitiesOutput", "customer_write", "none", "none", model_execution_enabled=True),
    ToolDescriptor("create_concepts", "1", "autopilot_intelligence:generate_concepts", "CreateConceptsInput", "ConceptsOutput", "customer_write", "none", "none", model_execution_enabled=True),
    ToolDescriptor("generate_storyboard", "1", "storyboard_director + autopilot_intelligence", "GenerateStoryboardInput", "StoryboardOutput", "costed_write", "low", "confirm_cost", True, True, model_execution_enabled=True, wrapper_required=True),
    ToolDescriptor("generate_keyframe", "1", "app:keyframe_service + autopilot_intelligence:record_keyframe", "GenerateKeyframeInput", "KeyframeOutput", "costed_write", "provider_cost", "confirm_cost", True, True, model_execution_enabled=True, wrapper_required=True),
    ToolDescriptor("animate_scene", "1", "pixverse_client:PixVerseClient.generate_from_image", "AnimateSceneInput", "AnimationJobOutput", "costed_write", "provider_cost", "confirm_cost", True, True, model_execution_enabled=True, wrapper_required=True),
    ToolDescriptor("finalize_video", "1", "media_finisher + autopilot_lifecycle:create_asset_version", "FinalizeVideoInput", "AssetVersionOutput", "costed_write", "low", "confirm_cost", True, True, model_execution_enabled=True, wrapper_required=True),
    ToolDescriptor("prepare_publication", "1", "autopilot_store:publication_payload_hash + approval_card_wrapper", "PreparePublicationInput", "ExactApprovalCardOutput", "approval_only", "none", "exact_content", requires_project=True, wrapper_required=True),
    ToolDescriptor("get_growth_report", "1", "autopilot_growth:growth_dashboard", "GrowthReportInput", "GrowthReportOutput", "customer_read", "none", "none", model_execution_enabled=True),
)

TOOL_REGISTRY = {tool.name: tool for tool in _TOOLS}


def get_tool(name: str) -> ToolDescriptor | None:
    return TOOL_REGISTRY.get(name)


def public_registry() -> list[dict]:
    return [tool.public() for tool in _TOOLS]
