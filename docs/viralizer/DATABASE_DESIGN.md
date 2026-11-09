# Growth Autopilot Database Design

## Approach

Extend the existing PostgreSQL schema; keep SQLite only for focused local tests. Introduce a real migration tool before new tables. Use UUID/ULID identifiers, `customer_id` on every customer-owned row, UTC timestamps, JSONB for raw provider payloads, and normalized columns for queryable metrics. Do not alter production during planning.

## Existing tables to retain

Retain profiles, projects, reports, assets, YouTube connections, caches, workflow state, audit/event settings, media jobs, and worker heartbeat. Gradually wrap their SQL in repository modules; do not perform a big-bang rewrite.

## Proposed entities

### Identity and connections

- `customers(id, owner_user_id, type, name, timezone, status, created_at)`; one customer per account in MVP.
- `brand_profiles(id, customer_id, version, status, profile_json, confirmed_at, created_at)`.
- `brand_facts(id, brand_profile_id, field_path, value_json, provenance, confidence, source_url, confirmed_by)`.
- `integration_connections(id, customer_id, provider, external_account_id, encrypted_credentials, scopes_json, status, expires_at)`.
- `connected_social_accounts(id, connection_id, platform, provider_account_id, display_name, capabilities_json, status)`.
- `commerce_connections(id, customer_id, provider, external_property_id, encrypted_credentials, scopes_json, status)`.
- `products(id, customer_id, provider_product_id, title, url, image_url, raw_json, updated_at)`.

### Intelligence and creative lifecycle

- `trends(id, canonical_key, title, category, first_seen_at, last_seen_at, status)`.
- `trend_observations(id, trend_id, source, source_item_id, observed_at, signals_json, raw_json)`.
- `opportunities(id, customer_id, trend_id, model_version, score, components_json, rationale, status)`.
- `creative_concepts(id, opportunity_id, version, concept_json, prompt_version, status)`.
- `storyboards(id, concept_id, version, storyboard_json, duration_seconds, status)`.
- `content_assets(id, customer_id, project_id, kind, storage_key, mime_type, duration_ms, width, height)`.
- `content_asset_versions(id, asset_id, version, sha256, generation_job_id, metadata_json, immutable_at)`.
- `generation_jobs(id, customer_id, workflow_step_id, provider, provider_job_id, idempotency_key, status, cost_json, error_json)`.

### Approval and publication

- `content_approvals(id, customer_id, asset_version_id, payload_hash, destination_id, scheduled_at, status, approved_by, approved_at, revoked_at)`.
- `publishing_jobs(id, approval_id, provider, provider_post_id, idempotency_key, status, attempt, next_attempt_at, error_json)`.
- `publications(id, customer_id, publishing_job_id, platform, provider, provider_result_id, native_post_id, native_url, published_at, status, raw_result_json)`.
- `provider_webhook_events(id, provider, provider_event_id, body_hash, signature_valid, received_at, processed_at, payload_json)`.

### Measurement and learning

- `metric_snapshots(id, publication_id, observed_at, metrics_json, availability_json, raw_json, provider)` with unique `(publication_id, observed_at, provider)`.
- `tracking_links(id, publication_id, destination_url, short_code, utm_json, created_at)`.
- `conversion_events(id, customer_id, publication_id nullable, provider, external_event_id, occurred_at, order_id nullable, value, currency, attribution_json, raw_json)`.
- `recommendations(id, customer_id, publication_id nullable, type, evidence_json, recommendation, status, created_at)`.
- `workflow_runs`, `workflow_steps`, and `agent_execution_logs` following the common execution contract.
- `provider_cost_events(id, customer_id, execution_id, provider, operation, quantity, estimated_cost, currency, occurred_at)`.

## Constraints and indexes

- Unique customer/provider external account IDs.
- Unique idempotency keys per provider operation.
- Unique provider event IDs plus body-hash fallback.
- Unique provider publication/result IDs.
- Foreign keys preserve lineage; restrict deletion of approved/published asset versions.
- Index due jobs on `(status, next_attempt_at)` and metrics on `(publication_id, observed_at desc)`.
- Index opportunities on `(customer_id, status, score desc)`.

## Isolation and retention

All repository methods require `customer_id`; background jobs derive it from the claimed row and never accept it from untrusted webhook content. Encrypt tokens with envelope encryption and key rotation metadata. Store only attribution fields needed for reporting; avoid Shopify protected customer fields in MVP. Raw payload retention should be configurable, proposed 90 days, while normalized aggregates may be retained longer. Deletion must tombstone/audit provider activity and remove customer media/credentials subject to legal requirements.

## Migration sequence

1. Adopt migration tooling and baseline existing runtime DDL.
2. Add customers/brand/connections.
3. Add workflow execution tables.
4. Add intelligence and creative lineage.
5. Add approvals/publications/webhooks.
6. Add metrics/tracking/conversions/recommendations/costs.
7. Backfill existing profiles/projects without deleting legacy fields.

