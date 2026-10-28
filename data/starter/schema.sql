CREATE TABLE users (
  user_id TEXT NOT NULL PRIMARY KEY,
  display_name TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('OPS_ANALYST', 'RISK_REVIEWER', 'SYSTEM'))
);

CREATE TABLE merchants (
  merchant_id TEXT NOT NULL PRIMARY KEY,
  legal_name TEXT NOT NULL,
  country TEXT NOT NULL CHECK (country IN ('US', 'DE', 'GB', 'IN')),
  settlement_currency TEXT NOT NULL CHECK (settlement_currency IN ('USD', 'EUR', 'GBP', 'INR')),
  fee_rate_bps INTEGER NOT NULL,
  fixed_fee_minor INTEGER NOT NULL,
  onboarded_date TEXT NOT NULL
);

CREATE TABLE payment_orders (
  payment_id TEXT NOT NULL PRIMARY KEY,
  merchant_id TEXT NOT NULL,
  customer_ref TEXT NOT NULL,
  order_ts TEXT NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  amount_minor INTEGER NOT NULL,
  payment_method TEXT NOT NULL CHECK (payment_method IN ('CARD_VISA', 'CARD_MC', 'WALLET', 'UPI')),
  status TEXT NOT NULL CHECK (status IN ('FAILED', 'CAPTURED', 'PARTIALLY_REFUNDED', 'REFUNDED')),
  captured_amount_minor INTEGER NOT NULL,
  refunded_amount_minor INTEGER NOT NULL,
  FOREIGN KEY (merchant_id) REFERENCES merchants(merchant_id)
);

CREATE TABLE payment_attempts (
  attempt_id TEXT NOT NULL PRIMARY KEY,
  payment_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL,
  attempt_ts TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('DECLINED', 'CAPTURED')),
  decline_code TEXT,
  FOREIGN KEY (payment_id) REFERENCES payment_orders(payment_id)
);

CREATE TABLE processor_events (
  processor_event_id TEXT NOT NULL PRIMARY KEY,
  payment_id TEXT NOT NULL,
  attempt_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IN ('AUTHORIZED', 'DECLINED', 'CAPTURED', 'REFUND_ISSUED')),
  event_ts TEXT NOT NULL,
  received_ts TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  webhook_event_id TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  idempotency_key TEXT NOT NULL,
  FOREIGN KEY (payment_id) REFERENCES payment_orders(payment_id),
  FOREIGN KEY (attempt_id) REFERENCES payment_attempts(attempt_id)
);

CREATE TABLE settlement_batches (
  batch_id TEXT NOT NULL PRIMARY KEY,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  cutoff_ts TEXT NOT NULL,
  expected_payout_date TEXT NOT NULL,
  line_count INTEGER NOT NULL,
  gross_captured_minor INTEGER NOT NULL,
  gross_refunded_minor INTEGER NOT NULL,
  total_fees_minor INTEGER NOT NULL,
  net_payout_minor INTEGER NOT NULL
);

CREATE TABLE settlement_lines (
  settlement_line_id TEXT NOT NULL PRIMARY KEY,
  batch_id TEXT NOT NULL,
  payment_id TEXT NOT NULL,
  processor_event_id TEXT NOT NULL,
  line_type TEXT NOT NULL CHECK (line_type IN ('CAPTURE', 'REFUND')),
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  gross_amount_minor INTEGER NOT NULL,
  fee_minor INTEGER NOT NULL,
  net_amount_minor INTEGER NOT NULL,
  FOREIGN KEY (batch_id) REFERENCES settlement_batches(batch_id),
  FOREIGN KEY (payment_id) REFERENCES payment_orders(payment_id),
  FOREIGN KEY (processor_event_id) REFERENCES processor_events(processor_event_id)
);

CREATE TABLE bank_statement_lines (
  bank_line_id TEXT NOT NULL PRIMARY KEY,
  value_date TEXT NOT NULL,
  booking_date TEXT NOT NULL,
  amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  reference TEXT NOT NULL,
  counterparty_name TEXT NOT NULL
);

CREATE TABLE reconciliation_matches (
  match_id TEXT NOT NULL PRIMARY KEY,
  match_level TEXT NOT NULL CHECK (match_level IN ('BANK_TO_BATCH', 'EVENT_TO_LINE')),
  bank_line_id TEXT,
  batch_id TEXT,
  processor_event_id TEXT,
  settlement_line_id TEXT,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  matched_amount_minor INTEGER NOT NULL,
  group_expected_amount_minor INTEGER NOT NULL,
  group_diff_minor INTEGER,
  date_delta_days INTEGER NOT NULL,
  rule_id TEXT NOT NULL,
  match_status TEXT NOT NULL CHECK (match_status IN ('MATCHED', 'MATCHED_TOLERANCE', 'MATCHED_LATE', 'PARTIAL', 'AMOUNT_MISMATCH', 'FEE_DIFFERENCE', 'CURRENCY_MISMATCH')),
  matched_at TEXT NOT NULL,
  FOREIGN KEY (bank_line_id) REFERENCES bank_statement_lines(bank_line_id),
  FOREIGN KEY (batch_id) REFERENCES settlement_batches(batch_id),
  FOREIGN KEY (processor_event_id) REFERENCES processor_events(processor_event_id),
  FOREIGN KEY (settlement_line_id) REFERENCES settlement_lines(settlement_line_id),
  CHECK ((match_level='BANK_TO_BATCH' AND bank_line_id IS NOT NULL AND batch_id IS NOT NULL) OR (match_level='EVENT_TO_LINE' AND processor_event_id IS NOT NULL AND settlement_line_id IS NOT NULL))
);

CREATE TABLE exceptions (
  exception_id TEXT NOT NULL PRIMARY KEY,
  exception_type TEXT NOT NULL CHECK (exception_type IN ('DUPLICATE_EVENT', 'REFUND_BEFORE_CAPTURE', 'UNMATCHED_EVENT', 'DUPLICATE_SETTLEMENT_LINE', 'DELAYED_SETTLEMENT', 'UNMATCHED_BATCH', 'PARTIAL_PAYOUT', 'CURRENCY_MISMATCH', 'FEE_DIFFERENCE', 'AMOUNT_MISMATCH', 'DELAYED_PAYOUT', 'UNMATCHED_BANK_LINE')),
  severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')),
  status TEXT NOT NULL CHECK (status IN ('OPEN', 'IN_REVIEW', 'ESCALATED', 'RESOLVED', 'WRITTEN_OFF')),
  entity_type TEXT NOT NULL CHECK (entity_type IN ('PROCESSOR_EVENT', 'SETTLEMENT_LINE', 'SETTLEMENT_BATCH', 'BANK_LINE')),
  entity_id TEXT NOT NULL,
  payment_id TEXT,
  batch_id TEXT,
  bank_line_id TEXT,
  processor_event_id TEXT,
  settlement_line_id TEXT,
  match_id TEXT,
  amount_at_risk_minor INTEGER NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  detected_at TEXT NOT NULL,
  sla_due_at TEXT NOT NULL,
  assigned_role TEXT NOT NULL CHECK (assigned_role IN ('OPS_ANALYST', 'RISK_REVIEWER', 'SYSTEM')),
  rule_id TEXT NOT NULL,
  description TEXT NOT NULL,
  FOREIGN KEY (payment_id) REFERENCES payment_orders(payment_id),
  FOREIGN KEY (batch_id) REFERENCES settlement_batches(batch_id),
  FOREIGN KEY (bank_line_id) REFERENCES bank_statement_lines(bank_line_id),
  FOREIGN KEY (processor_event_id) REFERENCES processor_events(processor_event_id),
  FOREIGN KEY (settlement_line_id) REFERENCES settlement_lines(settlement_line_id),
  FOREIGN KEY (match_id) REFERENCES reconciliation_matches(match_id)
);

CREATE TABLE resolutions (
  resolution_id TEXT NOT NULL PRIMARY KEY,
  exception_id TEXT NOT NULL,
  resolution_type TEXT NOT NULL CHECK (resolution_type IN ('AUTO_DEDUPED', 'RESEQUENCED', 'MANUAL_MATCH', 'PROCESSOR_CLAIM_RECOVERED', 'WRITTEN_OFF', 'CLAWBACK_REQUESTED', 'ADJUSTMENT_BOOKED', 'LATE_SETTLEMENT_CONFIRMED', 'FX_CONVERSION_CONFIRMED', 'ROUNDING_ADJUSTMENT_BOOKED', 'LATE_PAYOUT_CONFIRMED', 'CLASSIFIED_NON_PSP', 'RETURNED_TO_SENDER')),
  resolved_by TEXT NOT NULL,
  resolved_ts TEXT NOT NULL,
  adjustment_amount_minor INTEGER NOT NULL,
  currency TEXT NOT NULL CHECK (currency IN ('USD', 'EUR', 'GBP', 'INR')),
  notes TEXT NOT NULL,
  FOREIGN KEY (exception_id) REFERENCES exceptions(exception_id),
  FOREIGN KEY (resolved_by) REFERENCES users(user_id)
);

CREATE TABLE status_history (
  history_id TEXT NOT NULL PRIMARY KEY,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('EXCEPTION')),
  entity_id TEXT NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL CHECK (to_status IN ('OPEN', 'IN_REVIEW', 'ESCALATED', 'RESOLVED', 'WRITTEN_OFF')),
  changed_at TEXT NOT NULL,
  changed_by TEXT NOT NULL,
  FOREIGN KEY (changed_by) REFERENCES users(user_id)
);
