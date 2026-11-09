CREATE TABLE IF NOT EXISTS autopilot_asset_versions (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  workflow_run_id TEXT NOT NULL REFERENCES autopilot_workflow_runs(id) ON DELETE CASCADE,
  concept_id TEXT NOT NULL,
  version BIGINT NOT NULL DEFAULT 1,
  media_url TEXT NOT NULL,
  media_sha256 TEXT NOT NULL CHECK(length(media_sha256)=64),
  duration_seconds TEXT NOT NULL DEFAULT '15',
  aspect_ratio TEXT NOT NULL DEFAULT '9:16',
  caption TEXT NOT NULL DEFAULT '',
  title TEXT NOT NULL DEFAULT '',
  hashtags_json TEXT NOT NULL DEFAULT '[]',
  qc_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'ready_review' CHECK(status IN ('processing','ready_review','superseded','rejected')),
  created_at BIGINT NOT NULL,
  UNIQUE(customer_id,concept_id,version)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_assets_customer ON autopilot_asset_versions(customer_id,created_at DESC);

CREATE TABLE IF NOT EXISTS autopilot_publications (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  workflow_run_id TEXT NOT NULL REFERENCES autopilot_workflow_runs(id) ON DELETE CASCADE,
  approval_id TEXT NOT NULL REFERENCES autopilot_content_approvals(id),
  asset_version_id TEXT NOT NULL REFERENCES autopilot_asset_versions(id),
  destination_id TEXT NOT NULL,
  provider TEXT NOT NULL DEFAULT 'post_for_me',
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','scheduled','submitting','processing','published','failed','cancelled')),
  scheduled_at BIGINT NOT NULL DEFAULT 0,
  provider_post_id TEXT NOT NULL DEFAULT '',
  native_post_id TEXT NOT NULL DEFAULT '',
  native_url TEXT NOT NULL DEFAULT '',
  payload_json TEXT NOT NULL,
  result_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  published_at BIGINT NOT NULL DEFAULT 0,
  next_metrics_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,approval_id,destination_id)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_publications_due ON autopilot_publications(status,next_metrics_at);

CREATE TABLE IF NOT EXISTS autopilot_metric_snapshots (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  publication_id TEXT NOT NULL REFERENCES autopilot_publications(id) ON DELETE CASCADE,
  captured_at BIGINT NOT NULL,
  metrics_json TEXT NOT NULL DEFAULT '{}',
  deltas_json TEXT NOT NULL DEFAULT '{}',
  unavailable_json TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL DEFAULT '{}',
  UNIQUE(publication_id,captured_at)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_metrics_publication ON autopilot_metric_snapshots(publication_id,captured_at DESC);

CREATE TABLE IF NOT EXISTS autopilot_recommendations (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  publication_id TEXT NOT NULL REFERENCES autopilot_publications(id) ON DELETE CASCADE,
  recommendation_type TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  evidence_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','accepted','dismissed')),
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_autopilot_recommendations_customer ON autopilot_recommendations(customer_id,created_at DESC);
