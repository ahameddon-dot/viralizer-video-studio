# Technical Decisions

## TD-001 — Preserve the modular monolith

**Decision:** extend FastAPI/PostgreSQL/Render/R2; no agent microservices for MVP.

**Reason:** existing discovery, creative, media, auth, and worker code is substantial. A durable orchestrator and module boundaries solve the immediate problems with less operational cost. Revisit service extraction only after measured scaling or isolation needs.

## TD-002 — PostgreSQL is workflow truth

**Decision:** durable workflow state, approval, publication, and monitoring schedules live in PostgreSQL. In-memory tasks may accelerate work but cannot be authoritative.

## TD-003 — Introduce versioned migrations before feature tables

**Decision:** stop expanding runtime DDL. Baseline existing tables, review migration output, then add Autopilot entities. No production migration occurs without explicit approval.

## TD-004 — Logical agents, deterministic side effects

**Decision:** use LLMs only for structured analysis/generation. Provider calls, validation, approval, publication, metrics, and attribution are deterministic workers.

## TD-005 — Exact approval is a hard invariant

**Decision:** approval binds hashes of the immutable asset and normalized publication payload. Any edit invalidates approval. The backend publishing service enforces it atomically.

## TD-006 — Provider-independent adapters

**Decision:** implement interfaces for production, publishing, analytics, commerce, and notifications. Post for Me is the first publisher; existing direct publishers remain disabled fallback implementations.

## TD-007 — External Viral Rank is a signal, not local truth

**Decision:** preserve the external score and its availability/version separately from local opportunity components. Never replace a missing proprietary score with a synthetic UI number.

## TD-008 — One customer per owner in MVP

**Decision:** model `customer_id` explicitly but expose one creator/business customer per account. This provides isolation without agency/multi-client UX.

## TD-009 — Store normalized and raw observations

**Decision:** normalized fields power product logic; raw provider responses support reconciliation and future migration. Raw retention is limited and access-restricted.

## TD-010 — Shopify is canonical for order totals

**Decision:** GA4 supplies traffic/engagement and configured conversion reporting; Shopify supplies actual Shopify order totals. Attribution is qualified and never described as incremental causality.

## TD-011 — Monitoring cadence is durable and lifecycle-aware

**Decision:** collect every three hours for the initial high-value window, then reduce frequency. Exact policy is configuration, not an infinite fixed cron per post.

## TD-012 — No automated ad execution

**Decision:** recommendations may include budget ranges and evidence, but no ad-platform write credentials or campaign-creation interface is included in MVP.

## TD-013 — Webhook-first reconciliation

**Decision:** authenticate/deduplicate webhooks and process them asynchronously; poll as fallback. Provider callbacks never directly perform unbounded work.

## TD-014 — Incremental frontend evolution

**Decision:** keep current static V3 UI for MVP and add focused screens/components. A frontend-framework rewrite is not justified until product behavior stabilizes.

## Open material decisions

1. Confirm canonical backend and whether the Flutter/Firebase app must consume it.
2. Approve Post for Me Quickstart versus White Label.
3. Approve migration tool and production rollout process.
4. Confirm Viralizer MCP/Pro commercial contract and score-version availability.
5. Approve retention periods and encryption/key-management owner.
6. Choose transactional email provider only when notification scope is approved.

