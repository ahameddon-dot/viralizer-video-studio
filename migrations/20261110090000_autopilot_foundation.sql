CREATE TABLE IF NOT EXISTS autopilot_workflow_runs (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  workflow_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','waiting_user','succeeded','failed','cancelled')),
  input_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_autopilot_runs_customer_updated ON autopilot_workflow_runs(customer_id,updated_at DESC);

CREATE TABLE IF NOT EXISTS autopilot_workflow_steps (
  id TEXT PRIMARY KEY,
  run_id TEXT NOT NULL REFERENCES autopilot_workflow_runs(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  agent_type TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'queued' CHECK(status IN ('queued','running','waiting_user','retry_wait','succeeded','failed','cancelled','dead_letter')),
  idempotency_key TEXT NOT NULL,
  input_json TEXT NOT NULL DEFAULT '{}',
  output_json TEXT NOT NULL DEFAULT '{}',
  error_json TEXT NOT NULL DEFAULT '{}',
  attempt BIGINT NOT NULL DEFAULT 0 CHECK(attempt >= 0),
  max_attempts BIGINT NOT NULL DEFAULT 3 CHECK(max_attempts > 0),
  next_attempt_at BIGINT NOT NULL DEFAULT 0,
  lease_until BIGINT NOT NULL DEFAULT 0,
  worker_id TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_steps_run ON autopilot_workflow_steps(run_id,created_at);
CREATE INDEX IF NOT EXISTS idx_autopilot_steps_customer ON autopilot_workflow_steps(customer_id,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_autopilot_steps_due ON autopilot_workflow_steps(status,next_attempt_at,lease_until) WHERE status IN ('queued','retry_wait');

CREATE TABLE IF NOT EXISTS autopilot_content_approvals (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  asset_version_id TEXT NOT NULL,
  asset_sha256 TEXT NOT NULL,
  destination_id TEXT NOT NULL,
  scheduled_at BIGINT NOT NULL DEFAULT 0,
  payload_hash TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'approved' CHECK(status IN ('approved','revoked','consumed')),
  approved_by TEXT NOT NULL,
  approved_at BIGINT NOT NULL,
  revoked_at BIGINT NOT NULL DEFAULT 0,
  consumed_at BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_autopilot_approvals_customer ON autopilot_content_approvals(customer_id,approved_at DESC);
CREATE INDEX IF NOT EXISTS idx_autopilot_approvals_payload ON autopilot_content_approvals(customer_id,payload_hash,status);

CREATE TABLE IF NOT EXISTS autopilot_webhook_events (
  id TEXT PRIMARY KEY,
  provider TEXT NOT NULL,
  provider_event_key TEXT NOT NULL,
  body_sha256 TEXT NOT NULL,
  signature_valid BIGINT NOT NULL CHECK(signature_valid IN (0,1)),
  status TEXT NOT NULL DEFAULT 'received' CHECK(status IN ('received','processing','processed','rejected','failed')),
  payload_json TEXT NOT NULL,
  error_json TEXT NOT NULL DEFAULT '{}',
  received_at BIGINT NOT NULL,
  processed_at BIGINT NOT NULL DEFAULT 0,
  UNIQUE(provider,provider_event_key)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_webhooks_status ON autopilot_webhook_events(status,received_at) WHERE status IN ('received','failed');

CREATE TABLE IF NOT EXISTS autopilot_provider_cost_events (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  workflow_step_id TEXT REFERENCES autopilot_workflow_steps(id) ON DELETE SET NULL,
  provider TEXT NOT NULL,
  operation TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  quantity TEXT NOT NULL DEFAULT '1',
  estimated_cost TEXT NOT NULL DEFAULT '0',
  currency TEXT NOT NULL DEFAULT 'USD',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  occurred_at BIGINT NOT NULL,
  UNIQUE(customer_id,provider,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_costs_customer_time ON autopilot_provider_cost_events(customer_id,occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_autopilot_costs_step ON autopilot_provider_cost_events(workflow_step_id);

