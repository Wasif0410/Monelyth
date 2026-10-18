-- Pairs of transactions the user said are not a transfer (DELETE /transfers/{group}), so
-- transfer detection (monelyth_engine.insights.transfers) never pairs them again. Rows go away
-- with either transaction.
CREATE TABLE transfer_unlinks (
  outgoing_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  incoming_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  PRIMARY KEY (outgoing_id, incoming_id)
) WITHOUT ROWID;
