# Growth Autopilot release and rollback runbook

## Release gates

1. Run the complete Autopilot unit/contract suite and JavaScript parse check.
2. Exercise all migrations against a disposable PostgreSQL database using the production major version.
3. Confirm `AUTOPILOT_PROVIDER_MODE=disabled` for schema-only rollout.
4. Back up PostgreSQL and record the application release identifier.
5. Apply migrations once through the reviewed migration runner.
6. Deploy the web application, then the Autopilot worker with provider mode disabled.
7. Verify `/health`, `/api/admin/autopilot/operations`, queue counts, and webhook receipt.
8. Enable `fake` only in staging. Run brand → opportunity → concept → asset → approval → publication → monitoring.
9. Configure sandbox secret references and set `AUTOPILOT_PROVIDER_CALLS_ENABLED=true` only in staging.
10. Promote one provider at a time after its sandbox acceptance evidence is approved.

## Rollback

- Disable worker execution first by setting `AUTOPILOT_PROVIDER_MODE=disabled`.
- Do not reverse schema migrations that have accepted customer data. Roll application code back while retaining additive tables.
- Revoke provider credentials if a provider boundary is implicated.
- Inspect dead letters and webhook inbox before retrying anything.
- Exact approvals are never recreated automatically. Payload changes require new approval.
- Restore the database only for confirmed data corruption, using the pre-release backup and an incident-approved recovery window.

## Incident checks

- Duplicate publication: disable provider execution, inspect approval ID and idempotency key, reconcile native post before retry.
- Queue backlog: verify worker heartbeat/process, database leases, and provider rate limits; do not increase concurrency blindly.
- Webhook failures: validate secret rotation, raw-body handling, and replay identifiers.
- Metrics stale: keep the prior snapshot visible and mark data stale; publishing must remain available.
- Account disconnected: pause future publication and request reconnection without altering approved content.

## Data lifecycle

- Webhook receipts: 30 days after processed/rejected by default.
- Audit events: 365 days by default, subject to approved legal policy.
- Retention is previewed before execution and requires exact `APPLY RETENTION` confirmation.
- Customer deletion is scoped to Autopilot-owned records and requires `DELETE <customer_id>` confirmation.
- Export never includes secret references or provider credentials.
