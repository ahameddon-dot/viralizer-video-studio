# MVP Roadmap

## Release thesis

The smallest complete product is a single-account creator/business loop: confirmed brand → five opportunities → three concepts → one 15-second PixVerse video → exact approval → one YouTube Shorts publication through Post for Me → confirmed result → three-hour metrics. GA4/Shopify follow as a business-customer beta once publication identity and tracking links are stable.

## Phase 0 — Foundation and contracts

- Confirm canonical repo/deployment and Post for Me project mode.
- Baseline versioned migrations.
- Add typed domain contracts and workflow/approval tables.
- Add structured logging, correlation IDs, cost ledger, and connection encryption design.
- Freeze the external Viralizer report contract with fixtures.

Exit: durable workflow skeleton and approval invariant proven in tests, with no production provider call.

## Phase 1 — Brand-to-concept vertical slice

- Editable Brand Intelligence Profile.
- Persist existing trends and create five explainable opportunities.
- Generate three structured, diverse concepts and a 15-second storyboard.
- Reuse existing creative QC and prompt modules.

Exit: customer can confirm brand, select an opportunity, and select one of three concepts.

## Phase 2 — Production and approval

- Wrap existing PixVerse/media pipeline as orchestrated production steps.
- Immutable asset versions, QC, captions, preview, regeneration, cost tracking.
- Approval UI and server-side exact-payload approval gate.

Exit: an approval-ready video can be generated and cryptographically bound to its publication payload.

## Phase 3 — YouTube Shorts publishing

- Post for Me account connection with `posts` and `feeds` permissions.
- YouTube account selection, scheduling, submission, webhooks, reconciliation, reconnect flow.
- Publication status and native ID/URL.

Exit: an explicitly approved YouTube Short publishes once and is confirmed.

## Phase 4 — Growth loop

- Three-hour metric snapshots and dashboard.
- Predicted-versus-actual comparison.
- Evidence-backed next-action recommendations.
- Add Instagram, then TikTok, then LinkedIn based on account/API validation.

Exit: publication has multiple immutable snapshots and recommendations.

## Phase 5 — Commerce beta

- Tracking links and UTM builder.
- GA4 read-only OAuth/property selection and reports.
- Shopify installation, product sync, recent order/journey reporting.
- Qualified attribution dashboard with unattributed totals.

Exit: business customer can trace a publication to eligible traffic/orders without double-counting revenue.

## Release constraints

- No agency support.
- No automatic publication.
- No ad execution.
- No claim that attribution proves incrementality.
- No automatic migration/deployment without approval.

## Success measures

- Onboarding-to-first-preview completion rate.
- Median time from concept selection to approval-ready asset.
- Generation success and bounded retry/cost rates.
- Zero unapproved publications and duplicate posts.
- Publication confirmation rate.
- Metrics collection freshness/completeness by platform.
- Customer acceptance/dismissal rate of opportunities and recommendations.

