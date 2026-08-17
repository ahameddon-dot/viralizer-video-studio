# Release and rollback process

## Statuses

- **Draft:** incomplete work.
- **Testing:** deployed only to private beta.
- **Approved:** accepted but not published.
- **Published:** active production version.
- **Withdrawn:** intentionally not published or removed from production.
- **Archived:** retained as historical evidence.
- **Failed:** deployment or critical verification failed.

## Required record for every change

Each change must document its identifier, type, risk, before state, after state, reason, user impact, files, endpoints, configuration names, data impact, tests and rollback effect.

## Publishing

1. Test the version on the `develop` branch and beta Render service.
2. Review its dashboard comparison against current production.
3. Mark the release approved.
4. Obtain a separate explicit instruction to publish.
5. Tag the approved Git commit.
6. Merge the approved change set into `main`.
7. Verify the production health check and record the deployment.

## Rollback

1. Select a target version in the dashboard.
2. Review every feature, file, endpoint and configuration difference that will be removed.
3. Confirm stored-data compatibility and backups.
4. Create a traceable rollback commit or controlled deployment to the selected tag.
5. Verify production health.
6. Mark the removed version Withdrawn and record the reason.

Never rewrite or delete release history. Never display secret values in dashboard comparisons.
