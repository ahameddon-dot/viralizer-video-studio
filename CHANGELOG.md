# Viralizer Video Studio changelog

## v1.1.0-beta.1 — 2026-08-17 — Private testing

### Added

- Separate administrator authentication using `ADMIN_PASSWORD`.
- Private release dashboard at `/admin`.
- Detailed version history with before-and-after explanations.
- Version comparison across files, endpoints, configuration names, data impact and tests.
- Rollback impact preview that does not change production.
- Separate Render beta blueprint targeting the `develop` branch.

### Safety

- Production publishing and rollback execution remain locked.
- The dashboard is not visible to regular users without the separate administrator password.
- The existing `main` branch remains the production branch.

## v1.0.0 — 2026-08-16 — Production baseline

- Added dated extended-news details and original-source links.
- Sorted Category Intelligence topics by freshness.
- Expanded good and bad reputation discovery queries.
- Added five-word entity-led YouTube search terms.
- Added full-content infographic generation.
- Added actual uploaded-image reference generation.

The complete change-by-change record is stored in `data/release_catalog.json` and displayed in the private dashboard.
