# Deployment history

| Version | Environment | Branch | Commit | Date | Status |
|---|---|---|---|---|---|
| v1.0.0 | Production | `main` | `1d530df` | 2026-08-16 | Published baseline |
| v1.1.0-beta.1 | Private beta | `develop` | `d386f35` | 2026-08-17 | Superseded before deployment |
| v1.1.0-beta.2 | Private beta | `develop` | Assigned when committed | 2026-08-17 | Testing — free ephemeral storage |
| v1.1.0-beta.12 | Private beta | `develop` | Assigned when committed | 2026-08-21 | MCP creation-flow UI sent for testing |
| v1.1.0-beta.13 | Private beta | `develop` | Assigned when committed | 2026-08-21 | Creation Hub corrected to match approved visual |
| v1.1.0-beta.14 | Private beta | `develop` | Assigned when committed | 2026-08-21 | MCP report and creation order aligned with approved visual |

## Deployment rules

1. Development work is committed to `develop` and deployed only to the private beta service.
2. Marking a version **Approved** does not publish it.
3. Production requires a separate explicit publication decision.
4. Every production version receives a permanent version tag and change record.
5. A rollback creates a new traceable deployment event; Git history is never deleted.
6. Data compatibility and environment-variable differences must be reviewed before rollback.

## Pending infrastructure

- Create the `viralizer-video-studio-beta` Render service from `render-beta.yaml`.
- Configure separate beta `APP_PASSWORD` and `ADMIN_PASSWORD` values.
- Configure beta API keys and limits independently where practical.
- Test dashboard accuracy in preview-only mode.
- Add controlled production deployment automation only after preview records are approved.
