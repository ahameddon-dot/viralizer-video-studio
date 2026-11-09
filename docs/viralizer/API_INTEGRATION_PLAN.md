# API Integration Plan

Verified against official provider documentation on 2026-11-10. Exact commercial pricing must be confirmed in provider accounts/contracts before implementation; no production APIs were called.

## Provider interface policy

Each integration sits behind a typed adapter with capability discovery, normalized errors, idempotency, rate-limit metadata, and raw-response retention. Provider-specific fields remain in `raw_json`; business logic consumes normalized models.

## PixVerse

### Decision

Reuse `pixverse_client.py` and `pixverse_growth_client.py` behind a `ProductionProvider` interface. PixVerse is already the most technically ready integration in the repository.

### Required capabilities

Submit 15-second 9:16 image/video generation, upload references, poll/reconcile jobs, retrieve assets, edit/regenerate where supported, and expose moderation errors. Never promise a ten-minute provider SLA.

### Security/cost controls

Server-only keys, immutable request fingerprints, customer daily limits, maximum attempts, moderation-safe retry rules, and cost events. Verify the account's current models, duration/resolution support, quotas, and pricing immediately before implementation because these are commercial/account-specific.

## Post for Me

### Verified capabilities

Official documentation describes generated social-account auth URLs, connected-account listing, instant or scheduled social posts, per-destination post results, webhooks, and account feeds with optional metrics. Feed/analytics access requires requesting the `feeds` permission in addition to posting permissions. Metrics vary by platform/account; LinkedIn personal-page analytics are documented as unavailable while Company Pages may be supported.

### Adapter methods

`create_connection_url`, `list_accounts`, `create_post`, `get_post`, `cancel_post_if_supported`, `get_account_feed`, `verify_webhook`, and `normalize_event`.

### Flow

Generate a fresh auth URL on customer action; process both redirect success/failure and `social.account.created`. Submit only after backend approval verification. Reconcile `social.post.result.created` per destination and parent post updates. Treat polling as fallback.

### Webhook controls

Use the webhook secret returned by the provider, validate authenticity according to current official signing documentation, deduplicate, acknowledge quickly, and process asynchronously. Provider result details may contain sensitive request/response logs and require restricted retention.

### Commercial decision

Choose Quickstart for fastest validation (provider branding/credentials) or White Label for Viralizer branding and credential ownership (platform approvals required). Pricing is volume-based according to provider materials but requires account confirmation.

## Google Analytics 4

### Verified capabilities

The GA4 Data API supports `runReport`, batch, pivot, realtime, metadata, and funnel reporting. Use OAuth with `analytics.readonly` for customer-managed properties; a service account is only suitable when the customer explicitly grants it property access. Standard-property Core quotas are token/concurrency based, including 10 concurrent requests per property and project/property hourly budgets documented by Google.

### MVP reports

Query campaign/source/medium/content dimensions and sessions, engaged sessions, key events/conversions, and revenue only where properly configured. Use compact batched reports, return quota metadata, cache results, and back off on 429/500/503. GA4 reporting identity, consent, thresholds, attribution, and data latency affect results.

## Shopify

### Verified capabilities

Use the GraphQL Admin API with an offline token for background sync. Request the minimum initial scopes: `read_products` and `read_orders`. `read_orders` normally covers the last 60 days; `read_all_orders` adds older history and can require approval. Customer Journey exposes first/last visits and moments in a documented 30-day attribution window but still reflects Shopify's attribution, not causal incrementality. Protected customer data is restricted and unnecessary for MVP reporting.

### MVP operations

Sync products and orders, ingest order/update and app-uninstalled webhooks, query order customer-journey fields where available, and match UTM/publication identifiers. Shopify is canonical for order totals. Avoid storing names, addresses, email, or other protected customer data.

### Rate limits

GraphQL Admin rate limits are calculated query-cost budgets per app/store. Record requested/actual cost and throttle per connection.

## Transactional email and in-app notifications

No primary transactional email provider is confirmed in the repository. Select one only when notification requirements are approved. Create a provider-neutral `NotificationProvider`; in-app notifications should be PostgreSQL records with read/dismiss state. Initial email events: generation completed/failed, approval requested, scheduled post failed, account disconnected.

## Existing direct social APIs

Retain Meta, LinkedIn, and YouTube code as disabled fallback adapters. Do not mix environment-wide accounts with customer-owned Post for Me connections. TikTok remains dependent on Post for Me or a later official integration.

## Integration acceptance checklist

- Official capability and permission reconfirmed immediately before coding.
- Sandbox/test account and non-production credentials available.
- Auth redirect, disconnect, expiry, and revoked-scope behavior tested.
- Rate limits and retry policy documented.
- Webhook authenticity and replay tests pass.
- Costs and data retention approved.
- Unsupported platform metrics display as unavailable, never zero.

## Official references

- Post for Me developer overview: https://www.postforme.dev/developers
- Post for Me first-post flow: https://www.postforme.dev/resources/your-first-post
- Post for Me analytics: https://www.postforme.dev/resources/getting-post-analytics
- Post for Me webhooks: https://www.postforme.dev/resources/real-time-updates-with-webhooks
- GA4 Data API: https://developers.google.com/analytics/devguides/reporting/data/v1
- GA4 quotas: https://developers.google.com/analytics/devguides/reporting/data/v1/quotas
- Shopify authentication: https://shopify.dev/docs/apps/build/authentication-authorization
- Shopify scopes: https://shopify.dev/docs/apps/build/authentication-authorization/manage-access-scopes
- Shopify GraphQL rate limits: https://shopify.dev/docs/apps/build/apis/graphql-admin/rate-limits
- Shopify CustomerJourney: https://shopify.dev/docs/api/admin-graphql/latest/objects/CustomerJourney

