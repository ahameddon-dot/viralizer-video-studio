# Durable Workflow Specification

## State machine

`onboarding → brand_analysis → brand_confirmation → discovery → ranking → opportunity_selection → concept_generation → concept_selection → storyboard → production → preview → approval → scheduling → publication → monitoring → attribution → recommendations`

User gates are explicit `waiting_user` steps. A workflow run never advances past brand confirmation, opportunity selection, concept selection, or publication approval without a recorded user command.

## Orchestrator behavior

- Persist the workflow run and each step before dispatch.
- Use PostgreSQL leases modeled on `durable_media_pipeline.py`; do not rely on web-process memory.
- Claim due steps with `FOR UPDATE SKIP LOCKED`.
- Every command includes a stable idempotency key unique to customer, operation, and immutable input version.
- Validate input/output against versioned Pydantic models.
- Store evidence, prompt/template version, provider usage, latency, and errors.
- Retry only classified transient failures with exponential backoff and jitter.
- Permanent failures enter `failed_action_required`; exhausted transient failures enter `dead_letter`.
- Cancellation propagates only to cancellable future steps and provider jobs where supported.

## Approval invariant

An approval binds:

- `customer_id`
- `asset_version_id` and SHA-256 hash
- normalized caption/title/hashtag hash
- `connected_social_account_id`
- requested schedule
- approver user ID and timestamp

The publishing service recalculates and compares hashes inside the same transaction that creates the publishing job. Any mismatch or later edit revokes the approval and returns the workflow to `awaiting_approval`.

## Publication and webhooks

Create one publication record per destination. The provider request uses `publication_id` as the local idempotency reference where supported. Webhooks are first written to `provider_webhook_events` with provider event ID/body hash, receipt time, signature status, and processing state. A unique constraint deduplicates delivery. Acknowledge valid webhook receipt quickly, then process asynchronously. Poll only as reconciliation fallback.

## Three-hour monitoring

On publication confirmation, create `next_metrics_at = published_at + 3h`. The worker claims due publications, retrieves available lifetime metrics, stores an immutable snapshot, computes deltas from the prior snapshot, and schedules the next run. Stop or reduce frequency according to a configurable lifecycle policy; proposed MVP: every three hours for 72 hours, then daily through day 14.

## Recovery examples

- Discovery source failure: complete with partial evidence and source warning.
- Viralizer unavailable: retain opportunity with `viralizer_status=unavailable`; do not invent a score.
- PixVerse moderation rejection: classify, offer a policy-safe regeneration, and require review.
- Media finishing crash: resume the durable media job without repeating completed provider generation.
- Post for Me timeout: reconcile by idempotency/reference before retrying.
- Social account disconnected: pause publication and request reconnection; approval remains valid only if payload is unchanged.
- GA4/Shopify delay: retain prior snapshot, mark data stale, and retry within quota.

## Audit events

Record run created, step transitions, user selections, asset versions, approval granted/revoked, provider submissions, webhook receipts, publication results, connection changes, metric ingestion, recommendations, and administrative interventions. Do not log access tokens or sensitive raw headers.

## Workflow acceptance

- Restarting the web service or worker cannot lose a committed step.
- Replaying any command or webhook produces no duplicate generation, publication, or metric snapshot.
- A failed step exposes an actionable customer/admin status.
- Every published item traces back to its opportunity, concept, asset version, and approval.

