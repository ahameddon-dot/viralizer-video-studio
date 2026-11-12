CREATE TABLE IF NOT EXISTS hybrid_project_contexts (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  concept_id TEXT NOT NULL REFERENCES autopilot_creative_concepts(id) ON DELETE CASCADE,
  active_storyboard_revision_id TEXT,
  revision BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,concept_id)
);
CREATE INDEX IF NOT EXISTS idx_hybrid_projects_customer ON hybrid_project_contexts(customer_id,updated_at DESC);

CREATE TABLE IF NOT EXISTS hybrid_storyboard_revisions (
  id TEXT PRIMARY KEY,
  project_context_id TEXT NOT NULL REFERENCES hybrid_project_contexts(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  version BIGINT NOT NULL CHECK(version > 0),
  parent_revision_id TEXT REFERENCES hybrid_storyboard_revisions(id),
  storyboard_json TEXT NOT NULL,
  change_summary TEXT NOT NULL DEFAULT '',
  actor_type TEXT NOT NULL CHECK(actor_type IN ('user_ui','user_chat','system')),
  actor_id TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  UNIQUE(project_context_id,version)
);
CREATE INDEX IF NOT EXISTS idx_hybrid_storyboards_project ON hybrid_storyboard_revisions(project_context_id,version DESC);

CREATE TABLE IF NOT EXISTS hybrid_scene_revisions (
  id TEXT PRIMARY KEY,
  storyboard_revision_id TEXT NOT NULL REFERENCES hybrid_storyboard_revisions(id) ON DELETE CASCADE,
  project_context_id TEXT NOT NULL REFERENCES hybrid_project_contexts(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  scene_index BIGINT NOT NULL CHECK(scene_index >= 0),
  patch_json TEXT NOT NULL,
  actor_type TEXT NOT NULL CHECK(actor_type IN ('user_ui','user_chat','system')),
  actor_id TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_hybrid_scenes_project ON hybrid_scene_revisions(project_context_id,scene_index,created_at DESC);

CREATE TABLE IF NOT EXISTS hybrid_project_events (
  id TEXT PRIMARY KEY,
  project_context_id TEXT NOT NULL REFERENCES hybrid_project_contexts(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  sequence BIGINT NOT NULL CHECK(sequence > 0),
  event_type TEXT NOT NULL,
  payload_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  UNIQUE(project_context_id,sequence)
);
CREATE INDEX IF NOT EXISTS idx_hybrid_events_project ON hybrid_project_events(project_context_id,sequence);
