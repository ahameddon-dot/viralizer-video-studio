# Viralizer Current System Audit

Status: planning baseline, 2026-11-10. This document distinguishes confirmed repository findings from proposals. No production services were called.

## Audit boundary

The canonical source reviewed is the Git repository at `mnt/data/viralizer_hot_topic_generator`, remote `ahameddon-dot/viralizer-video-studio`, branch `ui-preview`. The workspace also contains a separate Flutter/Firebase repository (`viralizer-app`) and many deployment snapshots; their ownership and production relationship remain unconfirmed.

## Confirmed implementation

- FastAPI modular monolith in `app.py`, served by Uvicorn and deployed to Render with a separate media worker (`Dockerfile`, `render.yaml`).
- Static HTML/CSS/JavaScript applications in `static/`; the V3 UI uses History API routing and FastAPI fallback routes rather than a frontend framework.
- PostgreSQL production persistence through `psycopg`, with SQLite-compatible local behavior and handwritten SQL in `creatorthon_store.py`.
- Google OAuth, signed session cookies, workspace-password fallback, admin authentication, per-user records, event admission controls, and encrypted YouTube refresh-token storage.
- Google News, Hacker News, GDELT, regional news, Polymarket, and Kalshi discovery (`daily_trends.py`, `global_sources.py`, `regional_trends.py`, `betting_topics.py`).
- External Viralizer MCP/Pro report integration (`mcp_outline_client.py`). The repository consumes Viral Rank; it does not contain the proprietary Viral Rank formula.
- Role-aware opportunity ranking in `app.py`, discovery heat ranking in `daily_trends.py`, and prediction-market scoring in `betting_topics.py`.
- Creative analysis, objective refinement, article intelligence, storyboarding, motion direction, creative revision, narration, and QC modules.
- PixVerse, PixVerse Growth, Runway, HeyGen, OpenAI image/TTS, and Cloudflare image integrations.
- FFmpeg/Pillow media finishing, R2 storage, database-backed media jobs, leases, retries, and worker heartbeat (`durable_media_pipeline.py`).
- Direct publishing to Instagram, Facebook, LinkedIn, and YouTube (`social_publisher.py`).
- Unit/regression tests for creative grounding, provider behavior, media durability, publishing, and UI contracts under `tests/`.

## Partially implemented

- Brand knowledge exists as profile, website/product analysis, uploaded assets, and inferred creative context, but not as an editable, provenance-aware Brand Intelligence Profile.
- Opportunity ranking has several useful signals but no single versioned, explainable customer-specific model.
- Publishing exists, but Post for Me is absent and approval is not a domain-level invariant enforced for every publication.
- Channel automation and periodic research exist, but there is no cross-platform three-hour publication monitoring loop.
- Workflow state and job tables exist, but there is no central auditable orchestrator spanning all eight agents.
- Health endpoints and worker heartbeat exist, but centralized structured telemetry and alerting are not evident.

## Missing

- Post for Me adapter, connection lifecycle, webhook inbox, and per-destination publication result model.
- GA4 and Shopify connections, tracking links, conversion attribution, and commerce dashboards.
- Durable brand profiles, content approvals, publications, metric snapshots, recommendations, provider webhook events, and agent execution logs as first-class entities.
- Versioned database migrations; current tables are created by runtime SQL.
- Prompt/template version registry and end-to-end API cost ledger.
- TikTok publishing/analytics path in the primary repository.

## Viral Rank findings

`mcp_outline_client.py` normalizes `Viral Topic Rank` into `viral_rank`. `daily_trends.py`, `betting_topics.py`, the Studio, and generator consume that field. `tests/test_viralizer_pro_topic_api.py` tests API start/poll behavior, not rank calculation. The rank service is reusable through the current adapter, but its contract, version, latency, commercial terms, and failure semantics must be formalized.

The dashboard's `pixel_ui.js` synthesizes display scores from discovery heat when a real score is missing. This value must be labeled `estimated` or removed from decision-critical views.

## Database inventory

Existing tables include profiles, projects, reports, assets, event accounts, YouTube connections, insight jobs, topic caches, workflow states, audit/event settings, media jobs, and worker heartbeat. They are useful foundations but do not model the full Customer → Brand → Opportunity → Concept → Asset → Approval → Publication → Metrics → Conversion chain.

## Security, scalability, and cost risks

1. Environment-wide social credentials do not support safe customer-owned connections.
2. Runtime DDL makes upgrades and rollback difficult.
3. In-memory tasks/caches can disappear on restart or duplicate across web instances.
4. `app.py` combines routing, domain policy, integrations, and orchestration, increasing regression risk.
5. Publication approval is not an immutable server-side gate.
6. Provider webhooks need signature validation, replay protection, and deduplication.
7. Raw provider responses may contain personal or customer data and require retention controls.
8. Generation retries can create uncontrolled provider spend without budgets and idempotency.
9. External Viral Rank is a critical dependency without local explainability.
10. Analytics availability differs by social platform and account type.

## Reuse and refactor decisions

Reuse FastAPI, PostgreSQL, Render, R2, discovery modules, Viralizer adapter, creative pipeline, PixVerse clients, media finisher, and durable worker pattern. Refactor by adding domain services and repositories alongside `app.py`; do not rewrite the product or introduce microservices for MVP. Move publication policy into a service that requires an exact approval record. Introduce migrations before adding Autopilot tables.

