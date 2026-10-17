-- Initial schema (PLAN.md section 4) and the default categories.
--
-- Tables are STRICT so SQLite rejects a value of the wrong type instead of silently storing
-- it; most importantly, amount_cents can only ever hold an integer.
-- The migration runner wraps this file in a transaction; do not add BEGIN or COMMIT here.

-- Bank accounts and cards the user has added
CREATE TABLE accounts (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL,
  institution   TEXT,
  type          TEXT NOT NULL CHECK (type IN ('checking','savings','credit_card','other')),
  currency      TEXT NOT NULL
) STRICT;

-- Spending/income categories (seeded with defaults, user can add more later)
CREATE TABLE categories (
  id            INTEGER PRIMARY KEY,
  name          TEXT NOT NULL UNIQUE,
  kind          TEXT NOT NULL CHECK (kind IN ('income','expense','transfer')),
  parent_id     INTEGER REFERENCES categories(id)
) STRICT;

-- One row per file the user imported
CREATE TABLE imports (
  id            INTEGER PRIMARY KEY,
  account_id    INTEGER NOT NULL REFERENCES accounts(id),
  file_name     TEXT NOT NULL,
  file_sha256   TEXT NOT NULL UNIQUE,
  format        TEXT NOT NULL CHECK (format IN ('csv','ofx','pdf')),
  imported_at   TEXT NOT NULL,
  row_count     INTEGER NOT NULL
) STRICT;

-- The core table
CREATE TABLE transactions (
  id               INTEGER PRIMARY KEY,
  account_id       INTEGER NOT NULL REFERENCES accounts(id),
  import_id        INTEGER REFERENCES imports(id),
  posted_date      TEXT NOT NULL,
  amount_cents     INTEGER NOT NULL,
  description_raw  TEXT NOT NULL,
  merchant         TEXT,
  category_id      INTEGER REFERENCES categories(id),
  category_source  TEXT CHECK (category_source IN ('memory','rule','classifier','llm','user')),
  confidence       REAL CHECK (confidence BETWEEN 0 AND 1),
  needs_review     INTEGER NOT NULL DEFAULT 0 CHECK (needs_review IN (0, 1)),
  transfer_group   TEXT,
  fingerprint      TEXT NOT NULL UNIQUE
) STRICT;
CREATE INDEX ix_tx_account_date  ON transactions(account_id, posted_date);
CREATE INDEX ix_tx_category_date ON transactions(category_id, posted_date);

-- "This merchant is always this category", learned from the user's corrections
CREATE TABLE merchant_memory (
  merchant      TEXT PRIMARY KEY,
  category_id   INTEGER NOT NULL REFERENCES categories(id),
  source        TEXT NOT NULL CHECK (source IN ('user','llm','classifier')),
  updated_at    TEXT NOT NULL
) STRICT;

-- Keyword/regex rules: shipped defaults plus user-made ones
CREATE TABLE rules (
  id            INTEGER PRIMARY KEY,
  pattern       TEXT NOT NULL,
  match_type    TEXT NOT NULL CHECK (match_type IN ('contains','regex')),
  category_id   INTEGER NOT NULL REFERENCES categories(id),
  priority      INTEGER NOT NULL DEFAULT 0,
  created_by    TEXT NOT NULL CHECK (created_by IN ('system','user'))
) STRICT;

-- Remembers how each bank's CSV is laid out so the user only maps columns once
CREATE TABLE csv_profiles (
  header_signature TEXT PRIMARY KEY,
  mapping_json     TEXT NOT NULL
) STRICT;

-- Chat history
CREATE TABLE chat_messages (
  id               INTEGER PRIMARY KEY,
  conversation_id  TEXT NOT NULL,
  role             TEXT NOT NULL CHECK (role IN ('user','assistant','tool')),
  content          TEXT NOT NULL,
  tool_calls_json  TEXT,
  created_at       TEXT NOT NULL
) STRICT;

-- Default categories, in the order the UI lists them. ON CONFLICT keeps the seed idempotent.
INSERT INTO categories (name, kind) VALUES
  ('Salary',             'income'),
  ('Other Income',       'income'),
  ('Rent/Mortgage',      'expense'),
  ('Utilities',          'expense'),
  ('Groceries',          'expense'),
  ('Dining Out',         'expense'),
  ('Coffee',             'expense'),
  ('Transport',          'expense'),
  ('Gas',                'expense'),
  ('Rideshare',          'expense'),
  ('Shopping',           'expense'),
  ('Subscriptions',      'expense'),
  ('Entertainment',      'expense'),
  ('Health',             'expense'),
  ('Education',          'expense'),
  ('Travel',             'expense'),
  ('Fees & Interest',    'expense'),
  ('Gifts & Donations',  'expense'),
  ('Transfers',          'transfer'),
  ('Other',              'expense')
ON CONFLICT (name) DO NOTHING;
