# Viralizer Agent Architecture

## Architectural rule

The eight agents are logical modules inside the existing FastAPI modular monolith. The central orchestrator owns state transitions. LLMs analyze or generate structured content; deterministic workers perform provider calls, validation, publication, and analytics ingestion.

## Common execution contract

Every execution has `execution_id`, `workflow_run_id`, `customer_id`, `agent_type`, `input_schema_version`, `prompt_version`, `status`, `attempt`, `idempotency_key`, `input_json`, `output_json`, `evidence_json`, `provider_usage_json`, `error_code`, and timestamps. States are `queued`, `running`, `waiting_user`, `retry_wait`, `succeeded`, `failed`, or `cancelled`.

## A1 — Brand Intelligence

- **Purpose:** build an editable, evidence-backed model of the creator/business.
- **Triggers:** onboarding submitted; customer requests refresh; confirmed fields edited.
- **Inputs:** customer type, website URL, authorized social URLs, answers, uploaded assets.
- **Outputs:** voice, positioning, audiences, goals, products/services, offers, visual identity, constraints, evidence/provenance, confidence.
- **Tools:** existing website analysis, authorized account metadata, LLM structured extraction, image analysis.
- **Permissions:** public website fetch; explicit authorization for social data; customer asset access.
- **State:** `pending_sources → analyzing → awaiting_confirmation → confirmed`; partial-source failure remains editable.
- **Errors:** preserve successful evidence, show unavailable sources, allow retry or manual entry.
- **Customer interaction:** correction and confirmation are mandatory before automated recommendations.
- **MVP:** one editable profile; website plus optional social URLs/questions.
- **Future:** performance-based preference learning.
- **Dependencies:** customer profile, encrypted connections, provenance schema.
- **Acceptance:** every field has source type, confidence, and correction path.

## A2 — Trend Discovery

- **Purpose:** normalize timely trends and reusable content patterns.
- **Triggers:** scheduled discovery; user refresh; category request.
- **Inputs:** categories, regions, brand profile, source configuration.
- **Outputs:** normalized trends, source evidence, freshness, mentions, engagement signals, pattern abstractions.
- **Tools:** existing Google News/HN/GDELT/regional/market modules; later authorized social feeds.
- **Permissions:** public APIs/RSS; provider-specific read permissions for connected feeds.
- **State:** `collecting → normalizing → deduplicating → completed`.
- **Errors:** source-isolated retries; never fail the run because one source is unavailable.
- **Customer interaction:** refresh, filter, dismiss, and save.
- **MVP:** reuse existing discovery and store durable trend records.
- **Future:** lifecycle prediction and competitor intelligence.
- **Dependencies:** scheduler, source registry, trend schema.
- **Acceptance:** every trend has timestamp, sources, canonical key, and provenance.

## A3 — Opportunity Ranking

- **Purpose:** recommend five explainable brand- and goal-relevant opportunities.
- **Triggers:** discovery completion; brand confirmation; performance-model update.
- **Inputs:** trends, Viralizer report, brand profile, business goals, historical performance.
- **Outputs:** ranked opportunities, component scores, explanation, risks, recommended format.
- **Tools:** existing Viralizer adapter, discovery heat, role matching; versioned deterministic composite and optional LLM rationale.
- **Permissions:** read customer/trend/metrics only.
- **State:** `enriching → scoring → explaining → completed`.
- **Errors:** mark missing components; never substitute UI estimates as proprietary scores.
- **Customer interaction:** select, dismiss, explain, give feedback.
- **MVP:** five opportunities using Viral Rank + relevance + freshness + feasibility.
- **Future:** calibrated outcome prediction.
- **Dependencies:** A1, A2, external Viralizer contract.
- **Acceptance:** ranking is reproducible from stored feature values and model version.

## A4 — Creative Director

- **Purpose:** turn one opportunity into three original creative choices.
- **Triggers:** opportunity selected.
- **Inputs:** opportunity, brand profile, platform, goal, inspiration patterns, constraints.
- **Outputs:** three concepts with hook, narrative, script, CTA, scenes, rationale, and originality guardrails.
- **Tools:** existing article intelligence, storyboard, editorial, motion, and revision modules; LLM structured output.
- **Permissions:** read selected brand/opportunity/assets.
- **State:** `planning → generating → validating → awaiting_selection`.
- **Errors:** schema retry, grounding failure, similarity rejection, user regeneration.
- **Customer interaction:** select/edit/regenerate a concept.
- **MVP:** exactly three distinct 15-second concepts.
- **Future:** learned templates and experiments.
- **Dependencies:** A1, A3, prompt registry.
- **Acceptance:** concepts pass structure, grounding, safety, and diversity checks.

## A5 — Production

- **Purpose:** produce an approval-ready asset and platform copy.
- **Triggers:** concept selected and storyboard approved or implicitly advanced.
- **Inputs:** storyboard, asset references, generation settings, platform requirements.
- **Outputs:** immutable asset version, preview, media metadata, caption/title/hashtags, QC report, cost.
- **Tools:** existing PixVerse clients, OpenAI/Cloudflare image tools, media finisher, R2, durable media worker.
- **Permissions:** provider generation and customer asset access.
- **State:** `preflight → generating → downloading → finishing → qc → ready_review`.
- **Errors:** bounded provider retries, moderation classification, resumable finishing, no duplicate charges through idempotency.
- **Customer interaction:** preview, edit text, regenerate.
- **MVP:** one 15-second 9:16 video plus copy.
- **Future:** variants and automated editing.
- **Dependencies:** A4, storage, cost ledger.
- **Acceptance:** playable asset, 15-second target, 9:16, passed QC, immutable version/hash.

## A6 — Publishing

- **Purpose:** connect accounts and publish only explicitly approved content.
- **Triggers:** approval recorded; schedule due; provider webhook.
- **Inputs:** exact asset version, caption, account, schedule, approval ID.
- **Outputs:** publication record, provider post/result IDs, native URL/ID, status, errors.
- **Tools:** Post for Me adapter initially; existing direct adapters retained behind the interface but disabled by default.
- **Permissions:** Post for Me project API; user-authorized `posts`, and `feeds` where analytics are requested.
- **State:** `draft → awaiting_approval → approved → scheduled → submitting → processing → published|failed|cancelled`.
- **Errors:** retry safe transport errors; never automatically change content; reconnect on auth failure.
- **Customer interaction:** approve exact payload, schedule, cancel before submission, view results.
- **MVP:** YouTube Shorts through Post for Me.
- **Future:** Instagram, TikTok, LinkedIn and native adapters.
- **Dependencies:** approvals, connections, webhook inbox.
- **Acceptance:** no unapproved payload can reach a provider; native result is reconciled.

## A7 — Growth Intelligence

- **Purpose:** monitor outcomes and recommend next actions.
- **Triggers:** publication confirmed; three-hour due time; manual refresh.
- **Inputs:** publications, provider feed metrics, predicted scores, creative metadata.
- **Outputs:** metric snapshots, deltas, prediction error, creative-pattern insights, recommendations.
- **Tools:** Post for Me feed with `expand=metrics`, later native analytics.
- **Permissions:** `feeds`; platform/account limitations apply.
- **State:** `scheduled → collecting → normalizing → analyzing → next_due`.
- **Errors:** store availability/missing-metric flags; backoff on quota/rate limits.
- **Customer interaction:** dashboard and recommendation feedback.
- **MVP:** available views/likes/comments/shares and distribution metrics every three hours.
- **Future:** experiments and promotion recommendations.
- **Dependencies:** A6, scheduler, metrics taxonomy.
- **Acceptance:** raw and normalized immutable snapshots; unavailable metrics are never zero-filled.

## A8 — Commerce Intelligence

- **Purpose:** connect publications to traffic and eligible orders without overstating causality.
- **Triggers:** publication link created; periodic GA4/Shopify sync; order webhook.
- **Inputs:** tracking links, GA4 reports, Shopify products/orders/journey, consent configuration.
- **Outputs:** sessions, engagement, conversions, attributed orders/revenue, unattributed totals, confidence/limitations.
- **Tools:** GA4 Data API; Shopify GraphQL Admin API and webhooks.
- **Permissions:** GA `analytics.readonly`; Shopify `read_products` and `read_orders` initially; avoid protected customer fields.
- **State:** `connecting → syncing → matching → reporting`.
- **Errors:** token refresh/reconnect, quota backoff, delayed-data reconciliation.
- **Customer interaction:** connection, property/store selection, attribution disclosure.
- **MVP:** UTM reporting and Shopify order totals/journey matching.
- **Future:** Amazon Attribution and CRM.
- **Dependencies:** A6, tracking links, encrypted credentials.
- **Acceptance:** Shopify remains canonical for order totals; GA4 revenue is not added to it.

