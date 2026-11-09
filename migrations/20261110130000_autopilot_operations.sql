CREATE TABLE IF NOT EXISTS autopilot_notifications (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  notification_type TEXT NOT NULL,
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  action_url TEXT NOT NULL DEFAULT '',
  entity_type TEXT NOT NULL DEFAULT '',
  entity_id TEXT NOT NULL DEFAULT '',
  read_at BIGINT NOT NULL DEFAULT 0,
  dismissed_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  UNIQUE(customer_id,notification_type,entity_type,entity_id)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_notifications_customer ON autopilot_notifications(customer_id,created_at DESC);

CREATE TABLE IF NOT EXISTS autopilot_audit_events (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  event_type TEXT NOT NULL,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  correlation_id TEXT NOT NULL DEFAULT '',
  detail_json TEXT NOT NULL DEFAULT '{}',
  created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_autopilot_audit_customer ON autopilot_audit_events(customer_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_autopilot_audit_entity ON autopilot_audit_events(entity_type,entity_id,created_at DESC);
