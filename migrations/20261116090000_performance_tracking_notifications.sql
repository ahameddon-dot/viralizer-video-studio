CREATE TABLE IF NOT EXISTS autopilot_performance_tracking (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  publication_id TEXT NOT NULL REFERENCES autopilot_publications(id) ON DELETE CASCADE,
  interval_hours INTEGER NOT NULL,
  due_at BIGINT NOT NULL,
  notified_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  UNIQUE(customer_id,publication_id,interval_hours)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_performance_tracking_due ON autopilot_performance_tracking(notified_at,due_at);
