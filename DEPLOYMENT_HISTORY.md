# Deployment history

| Version | Environment | Branch | Commit | Date | Status |
|---|---|---|---|---|---|
| v1.1.0-beta.43 | Private beta | `develop` | Assigned when committed | 2026-08-28 | Replaced generic video prompts with concise duration-aware shot sequences |
| v1.1.0-beta.42 | Private beta | `develop` | Assigned when committed | 2026-08-26 | Added server-side PixVerse Growth Studio product-marketing creation, polling, editing and history workflow |
| v1.0.0 | Production | `main` | `1d530df` | 2026-08-16 | Published baseline |
| v1.1.0-beta.1 | Private beta | `develop` | `d386f35` | 2026-08-17 | Superseded before deployment |
| v1.1.0-beta.2 | Private beta | `develop` | Assigned when committed | 2026-08-17 | Testing — free ephemeral storage |
| v1.1.0-beta.12 | Private beta | `develop` | Assigned when committed | 2026-08-21 | MCP creation-flow UI sent for testing |
| v1.1.0-beta.13 | Private beta | `develop` | Assigned when committed | 2026-08-21 | Creation Hub corrected to match approved visual |
| v1.1.0-beta.14 | Private beta | `develop` | Assigned when committed | 2026-08-21 | MCP report and creation order aligned with approved visual |
| v1.1.0-beta.15 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Manual studio isolated from MCP and sample prompt content |
| v1.1.0-beta.16 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Restored infographic confirmation and generation action |
| v1.1.0-beta.17 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Added staged MCP format, prompt preparation and generation flow |
| v1.1.0-beta.18 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Restored full Viralizer generator-content fields before creation |
| v1.1.0-beta.19 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Added incomplete-media refetch and corrected empty thumbnail previews |
| v1.1.0-beta.20 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Added visible search topic, entity type and category labels |
| v1.1.0-beta.21 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Kept dates and times inside topic-result columns |
| v1.1.0-beta.22 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Corrected Daily trend Published-cell date and time layout |
| v1.1.0-beta.23 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Added source topic images to Daily trend discovery rows |
| v1.1.0-beta.24 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Removed No image placeholders and empty media space |
| v1.1.0-beta.25 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Added instant cached Daily trend display and background refresh |
| v1.1.0-beta.26 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Removed topic images while preserving caching and text-only table |
| v1.1.0-beta.27 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Restored seven-column Daily trend alignment with controlled wrapping |
| v1.1.0-beta.28 | Private beta | `develop` | Assigned when committed | 2026-08-22 | Shared cached Viralizer reports between video and PDF; removed redundant MCP retries |
| v1.1.0-beta.29 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Separated Image to Video reference assets from text-to-video workflow |
| v1.1.0-beta.30 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Added safe PixVerse authentication health check and trimmed pasted credentials |
| v1.1.0-beta.31 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Stopped the beta Blueprint from resetting the manually configured PixVerse API secret |
| v1.1.0-beta.32 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Added a manually owned PixVerse runtime-key override for beta |
| v1.1.0-beta.33 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Reorganized only the Viralizer-report creation flow into four clear stages |
| v1.1.0-beta.34 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Moved category intelligence into a dedicated Topic Intelligence navigation view |
| v1.1.0-beta.41 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Added cached dynamic Wikidata entity and relationship resolution across the full Topic Intelligence taxonomy |
| v1.1.0-beta.40 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Removed misleading category-wide competitor fallbacks; landscapes now require a verified topic entity |
| v1.1.0-beta.39 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Extended verified market and competitor landscapes across all Topic Intelligence super-categories |
| v1.1.0-beta.38 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Added expandable verified competitors and relationship explanations to Topic Intelligence |
| v1.1.0-beta.37 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Added verified logos for the company and organization entities visible in Topic Intelligence testing |
| v1.1.0-beta.36 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Verified Topic Intelligence entities and real logo/source-image handling; removed invented phrase entities |
| v1.1.0-beta.35 | Private beta | `develop` | Assigned when committed | 2026-08-25 | Added key company and brand metadata, logos and actions to Topic Intelligence results |

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
