-- Transactions database. Applied idempotently by db/ledger.py on every connect.
--
-- Two layers, named for who writes them, plus the view everything reads:
--   scraped_transactions   machine layer: the digested ledger, replaced in full on each import
--   transaction_overrides  human layer: sparse edits, kept forever
--   transactions           the ledger: scraped rows with overrides applied
--
-- Both tables are keyed on the ledger's dedup key, (date, abs(amount)), which is
-- unique per row after digest.consolidate_transactions.

CREATE TABLE IF NOT EXISTS scraped_transactions (
    txn_date     date          NOT NULL,
    abs_amount   numeric(12,2) NOT NULL,
    amount       numeric(12,2) NOT NULL,
    description  text          NOT NULL DEFAULT '',
    category     text,
    origin       text,
    sources      text[]        NOT NULL DEFAULT '{}',
    position     integer       NOT NULL,          -- index in the digested ledger (keeps its order)
    record       jsonb         NOT NULL,          -- the full digest row, so no field is lost
    imported_at  timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (txn_date, abs_amount)
);

-- Only the fields you changed are set; null falls through to the scraped value.
CREATE TABLE IF NOT EXISTS transaction_overrides (
    txn_date     date          NOT NULL,
    abs_amount   numeric(12,2) NOT NULL CHECK (abs_amount >= 0),
    category     text,
    note         text,
    excluded     boolean       NOT NULL DEFAULT false,   -- hidden from the ledger and every total
    created_at   timestamptz   NOT NULL DEFAULT now(),
    updated_at   timestamptz   NOT NULL DEFAULT now(),
    PRIMARY KEY (txn_date, abs_amount)
);

DROP VIEW IF EXISTS transactions;
CREATE VIEW transactions AS
SELECT s.txn_date,
       s.abs_amount,
       s.amount,
       s.description,
       COALESCE(o.category, s.category) AS category,
       s.category                       AS scraped_category,
       o.note,
       s.origin,
       s.sources,
       o.txn_date IS NOT NULL           AS overridden,
       s.position,
       s.record || jsonb_strip_nulls(jsonb_build_object(
           'category', o.category,
           'note',     o.note,
           'overridden', CASE WHEN o.txn_date IS NOT NULL THEN true END
       ))                               AS record
FROM scraped_transactions s
LEFT JOIN transaction_overrides o USING (txn_date, abs_amount)
WHERE NOT COALESCE(o.excluded, false);

-- Edits whose transaction no longer exists (a bank corrected its date or amount).
DROP VIEW IF EXISTS orphaned_overrides;
CREATE VIEW orphaned_overrides AS
SELECT o.*
FROM transaction_overrides o
LEFT JOIN scraped_transactions s USING (txn_date, abs_amount)
WHERE s.txn_date IS NULL;
