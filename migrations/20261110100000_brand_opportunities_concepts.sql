CREATE TABLE IF NOT EXISTS autopilot_brand_profiles (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  version BIGINT NOT NULL CHECK(version > 0),
  customer_type TEXT NOT NULL CHECK(customer_type IN ('creator','business')),
  status TEXT NOT NULL DEFAULT 'draft' CHECK(status IN ('draft','confirmed','archived')),
  website_url TEXT NOT NULL DEFAULT '',
  profile_json TEXT NOT NULL DEFAULT '{}',
  evidence_json TEXT NOT NULL DEFAULT '[]',
  confirmed_at BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,version)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_brand_customer_version ON autopilot_brand_profiles(customer_id,version DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_autopilot_brand_current ON autopilot_brand_profiles(customer_id) WHERE status IN ('draft','confirmed');

CREATE TABLE IF NOT EXISTS autopilot_opportunities (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  brand_profile_id TEXT REFERENCES autopilot_brand_profiles(id) ON DELETE SET NULL,
  trend_key TEXT NOT NULL,
  title TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT '',
  model_version TEXT NOT NULL,
  score TEXT NOT NULL,
  components_json TEXT NOT NULL DEFAULT '{}',
  rationale TEXT NOT NULL DEFAULT '',
  source_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'recommended' CHECK(status IN ('recommended','selected','dismissed','archived')),
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,trend_key,model_version)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_opportunities_customer_score ON autopilot_opportunities(customer_id,status,score DESC,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_autopilot_opportunities_brand ON autopilot_opportunities(brand_profile_id);

CREATE TABLE IF NOT EXISTS autopilot_creative_concepts (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  opportunity_id TEXT NOT NULL REFERENCES autopilot_opportunities(id) ON DELETE CASCADE,
  variant_number BIGINT NOT NULL CHECK(variant_number BETWEEN 1 AND 3),
  concept_version TEXT NOT NULL,
  name TEXT NOT NULL,
  content_json TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','selected','rejected','archived')),
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(opportunity_id,variant_number,concept_version)
);
CREATE INDEX IF NOT EXISTS idx_autopilot_concepts_customer ON autopilot_creative_concepts(customer_id,updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_autopilot_concepts_opportunity ON autopilot_creative_concepts(opportunity_id,variant_number);

