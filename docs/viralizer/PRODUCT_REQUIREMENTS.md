# Viralizer Growth Autopilot — Product Requirements

## Product outcome

Viralizer Growth Autopilot continuously turns brand-relevant trends into original, approved content and measurable growth recommendations. It is not an autonomous advertising system and must never publish without explicit approval.

## Customers

- **Creator:** an individual optimizing reach, engagement, followers, traffic, and monetization.
- **Business:** one business optimizing awareness, traffic, leads, conversions, and sales.

Excluded: agencies, client hierarchies, multi-client workspaces, agency billing, and delegated client approvals.

## MVP journey

1. Customer signs in and chooses Creator or Business.
2. Customer supplies a website, optional social URLs, goals, and corrections.
3. Viralizer creates an editable Brand Intelligence Profile with observed/inferred/confirmed provenance.
4. Daily discovery returns five personalized opportunities with Viral Rank and explanations.
5. Customer selects an opportunity and receives three original concepts.
6. Customer selects a concept and reviews a timed storyboard.
7. Viralizer produces one 15-second 9:16 PixVerse video plus platform text.
8. Customer reviews the exact asset version, caption, destination, and schedule.
9. Viralizer records approval and publishes through Post for Me to YouTube Shorts first.
10. Viralizer confirms native publication status and stores post ID/URL.
11. Viralizer captures available metrics every three hours and recommends next actions.
12. Business customers may connect GA4 and Shopify for traffic/order reporting.

## Functional requirements

### Brand and opportunities

- BR-1: Store one editable brand profile per customer.
- BR-2: Label every extracted fact `observed`, `inferred`, or `customer_confirmed` and retain its source.
- BR-3: Preserve existing discovery and Viralizer intelligence.
- BR-4: Recommend five opportunities with score components and plain-language rationale.

### Creative and production

- CR-1: Generate three materially distinct concepts per opportunity.
- CR-2: Each concept contains hook, narrative, CTA, platform fit, and a 15-second storyboard.
- CR-3: Avoid copying source expression; store inspiration patterns separately from generated wording/visuals.
- PR-1: Produce one 15-second vertical video and preview in ten minutes or less where provider latency permits.
- PR-2: Support customer brand/product assets and regeneration.
- PR-3: Validate duration, aspect ratio, media availability, and moderation outcome.
- PR-4: Record provider, model, prompt version, attempts, latency, and estimated cost.

### Approval and publishing

- PU-1: No publish operation may execute without an unrevoked approval for the exact asset hash, caption hash, destination, and schedule.
- PU-2: Any change to those approved fields invalidates approval.
- PU-3: Use a provider-independent publishing interface; implement Post for Me first.
- PU-4: Store one publication per destination with provider ID, native ID/URL, and raw result.
- PU-5: Support schedule, retry-safe submission, webhook reconciliation, and clear failure recovery.

### Growth and commerce

- GI-1: Collect supported publication metrics every three hours without fabricating unavailable metrics.
- GI-2: Store normalized and raw metrics and compare predicted versus actual outcomes.
- GI-3: Produce evidence-based recommendations; paid promotion remains advisory only.
- CI-1: Create per-publication UTM links.
- CI-2: GA4 is read-only and reports traffic/conversions associated with campaign identifiers.
- CI-3: Shopify is the canonical order-total source; do not add GA4 and Shopify revenue together.
- CI-4: Support unattributed orders and disclose attribution limitations.

## Non-functional requirements

- Customer-level isolation on every query and object key.
- Encrypted connection secrets; never return provider tokens to browsers.
- Idempotent commands and deduplicated authenticated webhooks.
- Durable, recoverable jobs with bounded retries and dead-letter visibility.
- JSON Schema/Pydantic validation for agent inputs and outputs.
- Prompt and template versioning.
- Audit log for approvals, publications, connection changes, and admin actions.
- Structured logs, correlation IDs, health checks, and actionable alerts.
- Per-customer/provider spend limits and cost reporting.
- Data export/deletion and configurable retention.

## MVP acceptance

A new customer can confirm a brand profile, choose one of five opportunities, select one of three concepts, generate and approve one 15-second video, publish it to a connected YouTube account through Post for Me, observe confirmed status, and see at least one subsequent metrics snapshot. A business can additionally connect read-only GA4 and Shopify and view clearly qualified attribution.

## Explicitly out of scope

Agency features, automated advertising spend, autonomous publication, multi-touch causal attribution, guaranteed virality, and automatic claims that attributed revenue is incremental.

