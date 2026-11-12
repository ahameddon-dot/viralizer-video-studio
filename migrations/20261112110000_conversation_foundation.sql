CREATE TABLE IF NOT EXISTS conversation_threads (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
  active_project_context_id TEXT REFERENCES hybrid_project_contexts(id) ON DELETE SET NULL,
  created_by TEXT NOT NULL DEFAULT '',
  message_sequence BIGINT NOT NULL DEFAULT 0,
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_threads_customer ON conversation_threads(customer_id,updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  role TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool')),
  content_json TEXT NOT NULL,
  sequence BIGINT NOT NULL CHECK(sequence > 0),
  correlation_id TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  UNIQUE(conversation_id,sequence)
);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_thread ON conversation_messages(conversation_id,sequence);

CREATE TABLE IF NOT EXISTS conversation_memory_facts (
  id TEXT PRIMARY KEY,
  customer_id TEXT NOT NULL,
  conversation_id TEXT REFERENCES conversation_threads(id) ON DELETE SET NULL,
  fact_key TEXT NOT NULL,
  value_json TEXT NOT NULL,
  source_message_id TEXT REFERENCES conversation_messages(id) ON DELETE SET NULL,
  confidence TEXT NOT NULL DEFAULT '0',
  confirmation_status TEXT NOT NULL DEFAULT 'proposed' CHECK(confirmation_status IN ('proposed','confirmed','rejected','superseded')),
  confirmed_by TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversation_memory_customer ON conversation_memory_facts(customer_id,fact_key,updated_at DESC);

CREATE TABLE IF NOT EXISTS conversation_tool_executions (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  message_id TEXT REFERENCES conversation_messages(id) ON DELETE SET NULL,
  workflow_run_id TEXT REFERENCES autopilot_workflow_runs(id) ON DELETE SET NULL,
  project_context_id TEXT REFERENCES hybrid_project_contexts(id) ON DELETE SET NULL,
  tool_name TEXT NOT NULL,
  tool_version TEXT NOT NULL,
  arguments_json TEXT NOT NULL DEFAULT '{}',
  result_json TEXT NOT NULL DEFAULT '{}',
  authorization_json TEXT NOT NULL DEFAULT '{}',
  cost_class TEXT NOT NULL,
  approval_status TEXT NOT NULL DEFAULT 'not_required' CHECK(approval_status IN ('not_required','required','confirmed','rejected')),
  status TEXT NOT NULL DEFAULT 'proposed' CHECK(status IN ('proposed','blocked','authorized','running','succeeded','failed','cancelled')),
  idempotency_key TEXT NOT NULL,
  correlation_id TEXT NOT NULL,
  error_json TEXT NOT NULL DEFAULT '{}',
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  UNIQUE(customer_id,idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_conversation_tools_thread ON conversation_tool_executions(conversation_id,created_at DESC);

CREATE TABLE IF NOT EXISTS conversation_workflow_links (
  conversation_id TEXT NOT NULL REFERENCES conversation_threads(id) ON DELETE CASCADE,
  customer_id TEXT NOT NULL,
  project_context_id TEXT REFERENCES hybrid_project_contexts(id) ON DELETE SET NULL,
  workflow_run_id TEXT NOT NULL REFERENCES autopilot_workflow_runs(id) ON DELETE CASCADE,
  purpose TEXT NOT NULL DEFAULT '',
  created_at BIGINT NOT NULL,
  PRIMARY KEY(conversation_id,workflow_run_id)
);
CREATE INDEX IF NOT EXISTS idx_conversation_workflows_customer ON conversation_workflow_links(customer_id,workflow_run_id);
