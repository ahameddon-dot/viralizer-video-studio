CREATE TABLE IF NOT EXISTS autopilot_provider_connections (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  provider TEXT NOT NULL CHECK(provider IN ('post_for_me','ga4','shopify')),
  external_account_id TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','connected','expired','revoked','error')),
  capabilities_json TEXT NOT NULL DEFAULT '[]',
  secret_reference TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  connected_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,provider,external_account_id)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_connections_customer ON autopilot_provider_connections(customer_id,provider,status);

CREATE TABLE IF NOT EXISTS autopilot_attribution_events (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  publication_id TEXT REFERENCES autopilot_publications(id) ON DELETE SET NULL,
  provider TEXT NOT NULL CHECK(provider IN ('ga4','shopify')),
  event_key TEXT NOT NULL,
  occurred_at BIGINT NOT NULL,
  campaign_id TEXT NOT NULL DEFAULT '',
  source TEXT NOT NULL DEFAULT '',
  medium TEXT NOT NULL DEFAULT '',
  content TEXT NOT NULL DEFAULT '',
  sessions TEXT NOT NULL DEFAULT '0',
  conversions TEXT NOT NULL DEFAULT '0',
  revenue TEXT NOT NULL DEFAULT '0',
  currency TEXT NOT NULL DEFAULT '',
  attribution_status TEXT NOT NULL DEFAULT 'unattributed' CHECK(attribution_status IN ('attributed','unattributed','ambiguous')),
  raw_json TEXT NOT NULL DEFAULT '{}',
  created_at BIGINT NOT NULL,
  UNIQUE(customer_id,provider,event_key)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_attribution_customer ON autopilot_attribution_events(customer_id,occurred_at DESC);
