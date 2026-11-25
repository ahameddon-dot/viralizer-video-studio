# Viralizer Production V2 Migration

This migration is deliberately parallel. Applying `render.production-v2.yaml` creates new resources and does not modify the current live services.

## Target architecture

- Web API: 1 CPU / 2 GB RAM, Singapore
- Media worker: 4 CPU / 8 GB RAM, Singapore
- PostgreSQL: 1 GB instance, Singapore
- Permanent media: existing Cloudflare R2 bucket
- Durable queue: PostgreSQL-backed `creatorthon_media_jobs`
- Provider jobs: polled and resumed by the dedicated media worker

The media worker has the larger runtime because FFmpeg assembly, narration, branding, and multi-scene output are the memory- and CPU-heavy operations. Build Pipeline compute does not increase these runtime resources.

## Safety rules

1. Do not rename or delete the current Render services.
2. Do not point the production domain at V2 until every canary below passes.
3. Keep `autoDeployTrigger: off` during validation.
4. Never store provider secrets in Git. Enter every `sync: false` value in Render.
5. Keep the current service running for at least 48 hours after cutover so rollback remains immediate.

## Required secrets

Set the following on both the V2 web service and V2 worker:

- `APP_PASSWORD`
- `ADMIN_PASSWORD`
- `MCP_API_KEY`
- `PIXVERSE_API_KEY`
- `PIXVERSE_GROWTH_API_KEY`
- `OPENAI_API_KEY`
- `CLOUDFLARE_ACCOUNT_ID`
- `CLOUDFLARE_API_TOKEN`
- `R2_ACCOUNT_ID`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `POST_FOR_ME_API_KEY`
- `AUTOPILOT_PROVIDER_RELAY_SECRET`

`DATABASE_URL` is wired automatically from the new Render PostgreSQL database.

## Pre-cutover verification

Run these checks against the V2 URL:

1. `/health` returns HTTP 200 quickly.
2. `/health/storage` reports R2 ready.
3. `/health/media` reports a recent worker heartbeat.
4. Create a 15-second video and confirm its final MP4 downloads.
5. Create a 30-second multi-scene video.
6. Create one 5-minute canary using a non-production account and confirm:
   - scene progress survives a browser refresh;
   - completed scenes are not regenerated;
   - narration covers the approved duration;
   - final assembly completes;
   - the MP4 remains available after restarting both V2 services.
7. Publish one private/unlisted test and verify its saved tracking record.
8. Restart the V2 worker during a canary and confirm the job resumes from PostgreSQL/R2.

## Cutover

1. Temporarily stop new video submissions on the old service.
2. Let active old jobs finish.
3. Point the frontend/provider relay to the V2 URL.
4. Run a final 15-second smoke test.
5. Re-enable submissions.
6. Monitor error rate, memory, CPU, worker heartbeat, queue age, and provider failures.

## Rollback

If V2 fails, point the frontend/provider relay back to the current URL. Because this deployment is parallel, rollback does not require a database restore or code rollback. Do not delete V2 until the failure has been diagnosed and its job records and media have been preserved.

## Scaling after measurement

- Keep the web service at 1 CPU / 2 GB unless request latency or memory shows pressure.
- Keep the worker at 4 CPU / 8 GB for long-form production; reduce only after several 5-minute canaries pass with comfortable memory headroom.
- Add a second worker only after confirming the provider concurrency limits and database leasing behavior under parallel jobs.
- Increase PostgreSQL before its connection, CPU, or storage limits are approached; do not scale it based only on web traffic.
