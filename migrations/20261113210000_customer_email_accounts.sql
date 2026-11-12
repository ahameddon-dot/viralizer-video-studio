CREATE TABLE IF NOT EXISTS customer_accounts (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','disabled')),
  created_at BIGINT NOT NULL,
  updated_at BIGINT NOT NULL,
  last_login_at BIGINT NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_customer_accounts_status ON customer_accounts(status,updated_at DESC);
