# Test and Acceptance Plan

## Test layers

### Unit

- Pydantic schema validation and forward/backward version fixtures.
- Brand provenance/confidence merging.
- Trend canonicalization and opportunity feature calculation.
- Approval payload canonicalization/hash and invalidation.
- Provider error classification, retry budgets, metric normalization, UTM generation, and attribution rules.

### Contract

- Recorded/sanitized fixtures for Viralizer reports, PixVerse jobs, Post for Me accounts/posts/results/feeds/webhooks, GA4 reports/quota errors, and Shopify GraphQL/webhooks.
- Assert unknown fields are preserved in raw payloads and unsupported metrics remain unavailable.
- No contract test uses production credentials.

### Repository/integration

- PostgreSQL constraints, customer isolation, transactions, leases, `SKIP LOCKED`, idempotency, and migrations up/down in disposable databases.
- R2 adapter with a fake S3 endpoint or mock; verify object-key customer partitioning.
- Secret encryption/decryption and key rotation fixtures.

### Workflow resilience

- Restart after every state transition.
- Concurrent workers claiming the same step.
- Duplicate command and webhook replay.
- Timeout after provider accepted a request but before response.
- Retry exhaustion/dead-letter/recovery.
- Cancellation and disconnected-account scenarios.

### Security

- Cross-customer object/API access denied.
- OAuth state/callback tampering.
- Webhook invalid signature, stale timestamp, body mutation, and replay.
- SSRF protection for website/media URLs.
- Upload type/size validation and malicious filename handling.
- Logs and API errors contain no tokens, secrets, or raw authorization headers.
- Approval bypass attempts fail at service and database boundaries.

### AI quality

- Golden brand-profile fixtures with provenance.
- Opportunity ranking offline corpus with expected ordering bands and explanations.
- Three-concept diversity, grounding, brand consistency, claims, and copying checks.
- Storyboard timing/schema and PixVerse prompt safety.
- Human review rubric sampled before prompt/template promotion.

### Performance and cost

- Discovery concurrency and external-source degradation.
- Workflow queue depth and lease throughput.
- Three-hour metrics fan-out under expected customer volume.
- Generation latency percentiles and maximum provider attempts/cost per workflow.
- GA4/Shopify/Post for Me quota/rate-limit backoff.

## Critical acceptance scenarios

1. Creator completes brand confirmation and receives five sourced opportunities.
2. Selecting one opportunity produces three distinct, valid concepts.
3. Selected concept produces a playable 15-second vertical preview or a recoverable failure.
4. Editing caption after approval revokes approval and blocks publication.
5. Duplicate publish commands and webhooks create one native publication record.
6. A published post gains immutable three-hour snapshots; unavailable metrics are shown as unavailable.
7. GA4 and Shopify failures do not block social publishing.
8. Shopify totals are not added to GA4 revenue and unattributed orders remain visible.
9. Paid-promotion output is a recommendation only; no ad API is callable.
10. Deleting/disconnecting an account prevents future provider calls and follows retention policy.

## Release gates

- All critical tests pass in CI.
- Migration reviewed and exercised against a sanitized production-like schema.
- Threat model and credential storage reviewed.
- Provider sandbox acceptance passes for the enabled platform.
- Cost ceilings and alert thresholds configured.
- Runbook covers provider outage, queue backlog, webhook failure, accidental approval revocation, and account disconnect.
- Product/legal approval of privacy, attribution wording, and data retention.

