# Implementation Tasks

## Dependency-ordered backlog

### Epic 0 — Decisions and baseline

1. Confirm `viralizer-video-studio` as canonical backend and define the Flutter app relationship.
2. Select Post for Me Quickstart versus White Label and obtain a sandbox project.
3. Document the external Viralizer MCP/Pro contract, ownership, pricing, and SLA.

### Epic 1 — Safe persistence foundation

4. Select migration tooling compatible with PostgreSQL and local tests; generate a reviewed baseline of existing runtime-created tables.
5. Add Pydantic domain schemas for Customer, BrandProfile, WorkflowRun/Step, Approval, Publication, and MetricSnapshot.
6. Add repository modules that require `customer_id`; add encryption abstraction and key-version metadata.
7. Add structured event logging, correlation IDs, provider-cost events, and redaction tests.

### Epic 2 — Orchestrator

8. Implement PostgreSQL-backed workflow/step tables, leasing, heartbeat, retry classification, idempotency, cancellation, and dead-letter states.
9. Add worker command dispatch and admin/read-only run inspection.
10. Add webhook inbox with signature state, unique provider event IDs/body hashes, and asynchronous processing.

### Epic 3 — Brand and intelligence

11. Implement Brand Profile version/provenance storage and confirmation UI.
12. Adapt website/product analysis into A1 structured outputs.
13. Persist normalized discovery observations without replacing current endpoints.
14. Implement versioned opportunity scoring from Viral Rank, relevance, freshness, feasibility, and goal fit.
15. Add ranking fixtures, explanations, and five-opportunity UI.

### Epic 4 — Creative and production

16. Define versioned Concept and Storyboard schemas.
17. Wrap existing creative modules to generate exactly three diverse concepts.
18. Wrap PixVerse/media finishing as orchestrator steps with immutable asset versions and cost tracking.
19. Add preview, caption editing, regeneration, and QC states.

### Epic 5 — Approval and publishing

20. Implement approval hash computation, revocation, and atomic publishing guard.
21. Implement Post for Me adapter, connection redirect/callback, account sync, and capability storage.
22. Implement YouTube Shorts submission, scheduling, result webhooks, polling fallback, and reconciliation.
23. Add customer publication status, reconnect, cancel/retry, and audit views.

### Epic 6 — Growth

24. Implement three-hour due scheduling and feed-based metric ingestion.
25. Normalize metrics with availability metadata and retain raw responses.
26. Build performance dashboard and prediction-error/recommendation service.
27. Validate Instagram, TikTok, and LinkedIn sequentially.

### Epic 7 — Commerce

28. Add unique tracking links/UTMs per publication.
29. Add GA4 read-only OAuth/property selection, batched reports, quota monitoring, and cache.
30. Add Shopify install/offline token, minimal scopes, products/orders/journey sync, and webhooks.
31. Build attribution report with Shopify-canonical revenue and unattributed orders.

## First engineering sprint

Goal: prove the durable and safe foundation without touching production integrations.

1. Adopt migration tooling and create an existing-schema baseline for review.
2. Add workflow, workflow-step, approval, webhook-inbox, and provider-cost migration drafts.
3. Implement typed workflow contracts and a PostgreSQL repository.
4. Implement one no-provider vertical workflow: mocked opportunity → mocked concept → mocked asset → approval.
5. Enforce approval hash validation in a fake publishing adapter.
6. Add restart, concurrency, idempotency, webhook replay, and approval-invalidation tests.
7. Add a read-only workflow-status endpoint and minimal internal status view.

Sprint acceptance: two workers cannot execute the same step; retries do not duplicate effects; changing any approved payload field blocks publication; no provider credentials or calls are required.

