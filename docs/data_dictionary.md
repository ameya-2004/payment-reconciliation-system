# Data dictionary

Generated from `app/services/schema.py`. Money is always integer minor units (cents, paise, yen). Timestamps are UTC ISO-8601, dates are YYYY-MM-DD.

## users

Staff and system accounts that can resolve exceptions (synthetic labels, no real people).

* Primary key: `user_id`
* Cardinality: 1:N resolutions (resolved_by); 1:N status_history (changed_by)

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| user_id | STRING | yes |  |  | yes | USR-000 system, USR-0xx analysts, USR-1xx risk reviewers |
| display_name | STRING | yes |  |  |  |  |
| role | STRING | yes | OPS_ANALYST, RISK_REVIEWER, SYSTEM |  |  |  |

## merchants

Merchants that accept payments. Fee terms are fixed per merchant.

* Primary key: `merchant_id`
* Cardinality: 1:N payment_orders
* Lifecycle / effective dates: Active from onboarded_date.

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| merchant_id | STRING | yes |  |  | yes | MER-000001 pattern |
| legal_name | STRING | yes |  |  |  | invented name |
| country | STRING | yes | US, DE, GB, IN |  |  |  |
| settlement_currency | STRING | yes | USD, EUR, GBP, INR |  |  | every order of the merchant uses this currency |
| fee_rate_bps | INT | yes |  | basis points |  | 200..350 |
| fixed_fee_minor | INT | yes |  | minor units |  | >= 0, charged on every capture |
| onboarded_date | DATE | yes |  |  |  | effective date: before the first order |

## payment_orders

One row per customer payment order.

* Primary key: `payment_id`
* Cardinality: 1:N payment_attempts (1 or 2); 1:N processor_events; 1:0..N settlement_lines
* Foreign keys: `merchant_id` -> `merchants.merchant_id`
* Lifecycle / effective dates: FAILED (no capture), or CAPTURED -> PARTIALLY_REFUNDED -> REFUNDED. The state changes are the processor_events rows.

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| payment_id | STRING | yes |  |  | yes | PAY-2026-00000001 pattern, numbered by order_ts |
| merchant_id | STRING | yes |  |  |  | FK merchants |
| customer_ref | STRING | yes |  |  |  | opaque token, not personal data |
| order_ts | TIMESTAMP | yes |  |  |  | UTC, on or after the merchant's onboarded_date |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  | equals the merchant's settlement_currency |
| amount_minor | INT | yes |  | minor units |  | > 0 |
| payment_method | STRING | yes | CARD_VISA, CARD_MC, WALLET, UPI |  |  |  |
| status | STRING | yes | FAILED, CAPTURED, PARTIALLY_REFUNDED, REFUNDED |  |  | derived from the canonical processor events |
| captured_amount_minor | INT | yes |  | minor units |  | sum of canonical CAPTURED events |
| refunded_amount_minor | INT | yes |  | minor units |  | sum of canonical REFUND_ISSUED events, <= captured |

## payment_attempts

Authorisation attempts for an order. A second attempt only follows a decline.

* Primary key: `attempt_id`
* Cardinality: N:1 payment_orders; 1:N processor_events
* Foreign keys: `payment_id` -> `payment_orders.payment_id`

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| attempt_id | STRING | yes |  |  | yes | ATT-<payment_id>-01 |
| payment_id | STRING | yes |  |  |  | FK payment_orders |
| attempt_no | INT | yes |  |  |  | 1 or 2, consecutive |
| attempt_ts | TIMESTAMP | yes |  |  |  | >= order_ts |
| amount_minor | INT | yes |  | minor units |  | equals the order amount |
| status | STRING | yes | DECLINED, CAPTURED |  |  | DECLINED, or CAPTURED when the attempt was captured |
| decline_code | STRING | no |  |  |  | only when DECLINED |

## processor_events

Append-only processor webhook log. History is never overwritten.

* Primary key: `processor_event_id`
* Cardinality: N:1 payment_orders; N:1 payment_attempts; canonical event 1:0..1 settlement_lines (0 for declines, authorisations and dropped captures)
* Foreign keys: `payment_id` -> `payment_orders.payment_id`, `attempt_id` -> `payment_attempts.attempt_id`

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| processor_event_id | STRING | yes |  |  | yes | EVT-2026-00000001, numbered by received_ts |
| payment_id | STRING | yes |  |  |  | FK payment_orders |
| attempt_id | STRING | yes |  |  |  | FK payment_attempts |
| event_type | STRING | yes | AUTHORIZED, DECLINED, CAPTURED, REFUND_ISSUED |  |  |  |
| event_ts | TIMESTAMP | yes |  |  |  | processor clock |
| received_ts | TIMESTAMP | yes |  |  |  | >= event_ts |
| amount_minor | INT | yes |  | minor units |  | > 0 (declines carry the order amount) |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| webhook_event_id | STRING | yes |  |  |  | processor's own event id, shared by redeliveries |
| delivery_id | STRING | yes |  |  |  | one per HTTP delivery; a repeated value means our pipeline wrote the same delivery twice |
| idempotency_key | STRING | yes |  |  |  | same business event = same key (not unique on purpose) |

## settlement_batches

Processor settlement batch: one currency, one cut-off.

* Primary key: `batch_id`
* Cardinality: 1:N settlement_lines; N:M bank_statement_lines through reconciliation_matches (paid in several tranches)
* Lifecycle / effective dates: Effective date: expected_payout_date.

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| batch_id | STRING | yes |  |  | yes | SET-2026-000001 pattern, numbered by cutoff_ts |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| cutoff_ts | TIMESTAMP | yes |  |  |  |  |
| expected_payout_date | DATE | yes |  |  |  | cut-off date + 2 business days |
| line_count | INT | yes |  |  |  | count of settlement_lines |
| gross_captured_minor | INT | yes |  | minor units |  | sum of gross on CAPTURE lines |
| gross_refunded_minor | INT | yes |  | minor units |  | sum of gross on REFUND lines |
| total_fees_minor | INT | yes |  | minor units |  | sum of line fees |
| net_payout_minor | INT | yes |  | minor units |  | captured - refunded - fees |

## settlement_lines

One line per captured or refunded event inside a batch.

* Primary key: `settlement_line_id`
* Cardinality: N:1 settlement_batches; N:1 processor_events; 0..1 reconciliation_matches
* Foreign keys: `batch_id` -> `settlement_batches.batch_id`, `payment_id` -> `payment_orders.payment_id`, `processor_event_id` -> `processor_events.processor_event_id`

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| settlement_line_id | STRING | yes |  |  | yes | STL-<batch_id>-001 |
| batch_id | STRING | yes |  |  |  | FK settlement_batches |
| payment_id | STRING | yes |  |  |  | FK payment_orders |
| processor_event_id | STRING | yes |  |  |  | FK processor_events (the canonical event) |
| line_type | STRING | yes | CAPTURE, REFUND |  |  |  |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| gross_amount_minor | INT | yes |  | minor units |  | > 0, equals the event amount |
| fee_minor | INT | yes |  | minor units |  | capture: round_half_even(gross*bps/10000)+fixed; refund: 0 |
| net_amount_minor | INT | yes |  | minor units |  | capture: gross-fee; refund: -gross |

## bank_statement_lines

Bank statement entries for the processor funds account.

* Primary key: `bank_line_id`
* Cardinality: optional N:1 settlement_batches (an orphan line has no batch); 0..1 reconciliation_matches

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| bank_line_id | STRING | yes |  |  | yes | BANK-2026-000001 pattern, numbered by value_date |
| value_date | DATE | yes |  |  |  | effective date |
| booking_date | DATE | yes |  |  |  | >= value_date |
| amount_minor | INT | yes |  | minor units |  | signed: credit > 0, debit < 0 |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| reference | STRING | yes |  |  |  | free text; payouts look like 'PSP PAYOUT SET-2026-000123 T2/4' |
| counterparty_name | STRING | yes |  |  |  |  |

## reconciliation_matches

Bridge table: bank line <-> batch (N:M) and processor event <-> settlement line (1:1).

* Primary key: `match_id`
* Cardinality: the bridge: bank lines N:M batches; events 1:1 lines; 0..N exceptions point at a match
* Foreign keys: `bank_line_id` -> `bank_statement_lines.bank_line_id`, `batch_id` -> `settlement_batches.batch_id`, `processor_event_id` -> `processor_events.processor_event_id`, `settlement_line_id` -> `settlement_lines.settlement_line_id`

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| match_id | STRING | yes |  |  | yes | REC-2026-000001 pattern, numbered by matched_at |
| match_level | STRING | yes | BANK_TO_BATCH, EVENT_TO_LINE |  |  |  |
| bank_line_id | STRING | no |  |  |  | FK, set for BANK_TO_BATCH |
| batch_id | STRING | no |  |  |  | FK, set for BANK_TO_BATCH |
| processor_event_id | STRING | no |  |  |  | FK, set for EVENT_TO_LINE |
| settlement_line_id | STRING | no |  |  |  | FK, set for EVENT_TO_LINE |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| matched_amount_minor | INT | yes |  | minor units |  | the bank amount, or the settlement line gross |
| group_expected_amount_minor | INT | yes |  | minor units |  | batch net (bank level) or event amount |
| group_diff_minor | INT | no |  | minor units |  | sum matched - expected; empty when currencies differ |
| date_delta_days | INT | yes |  |  |  | bank value date - expected payout date, or batch cut-off date - event date |
| rule_id | STRING | yes |  |  |  | which matching rule fired |
| match_status | STRING | yes | MATCHED, MATCHED_TOLERANCE, MATCHED_LATE, PARTIAL, AMOUNT_MISMATCH, FEE_DIFFERENCE, CURRENCY_MISMATCH |  |  |  |
| matched_at | TIMESTAMP | yes |  |  |  | the nightly run |

## exceptions

Every unmatched, partial or inconsistent item found by the engine.

* Primary key: `exception_id`
* Cardinality: optional N:1 reconciliation_matches; 1:0..1 resolutions; 1:N status_history
* Foreign keys: `payment_id` -> `payment_orders.payment_id`, `batch_id` -> `settlement_batches.batch_id`, `bank_line_id` -> `bank_statement_lines.bank_line_id`, `processor_event_id` -> `processor_events.processor_event_id`, `settlement_line_id` -> `settlement_lines.settlement_line_id`, `match_id` -> `reconciliation_matches.match_id`
* Lifecycle / effective dates: OPEN -> IN_REVIEW -> ESCALATED -> RESOLVED or WRITTEN_OFF (OPEN -> RESOLVED for automatic dedupe). Effective dates: detected_at, sla_due_at.

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| exception_id | STRING | yes |  |  | yes | EXC-2026-000001 pattern |
| exception_type | STRING | yes | DUPLICATE_EVENT, REFUND_BEFORE_CAPTURE, UNMATCHED_EVENT, DUPLICATE_SETTLEMENT_LINE, DELAYED_SETTLEMENT, UNMATCHED_BATCH, PARTIAL_PAYOUT, CURRENCY_MISMATCH, FEE_DIFFERENCE, AMOUNT_MISMATCH, DELAYED_PAYOUT, UNMATCHED_BANK_LINE |  |  |  |
| severity | STRING | yes | LOW, MEDIUM, HIGH |  |  | fixed per exception type |
| status | STRING | yes | OPEN, IN_REVIEW, ESCALATED, RESOLVED, WRITTEN_OFF |  |  | state as of the as-of date; history in status_history |
| entity_type | STRING | yes | PROCESSOR_EVENT, SETTLEMENT_LINE, SETTLEMENT_BATCH, BANK_LINE |  |  |  |
| entity_id | STRING | yes |  |  |  | the main subject of the exception |
| payment_id | STRING | no |  |  |  |  |
| batch_id | STRING | no |  |  |  |  |
| bank_line_id | STRING | no |  |  |  |  |
| processor_event_id | STRING | no |  |  |  |  |
| settlement_line_id | STRING | no |  |  |  |  |
| match_id | STRING | no |  |  |  |  |
| amount_at_risk_minor | INT | yes |  | minor units |  | >= 0 |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| detected_at | TIMESTAMP | yes |  |  |  | nightly run, 02:00Z |
| sla_due_at | TIMESTAMP | yes |  |  |  | HIGH 2 days, MEDIUM 5, LOW 10 after detection |
| assigned_role | STRING | yes | OPS_ANALYST, RISK_REVIEWER, SYSTEM |  |  |  |
| rule_id | STRING | yes |  |  |  | the engine rule that raised it |
| description | STRING | yes |  |  |  |  |

## resolutions

How an exception was closed. Exists only once the exception is closed.

* Primary key: `resolution_id`
* Cardinality: N:1 exceptions (at most one here); N:1 users
* Foreign keys: `exception_id` -> `exceptions.exception_id`, `resolved_by` -> `users.user_id`

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| resolution_id | STRING | yes |  |  | yes | RES-2026-000001 pattern |
| exception_id | STRING | yes |  |  |  | FK exceptions |
| resolution_type | STRING | yes | AUTO_DEDUPED, RESEQUENCED, MANUAL_MATCH, PROCESSOR_CLAIM_RECOVERED, WRITTEN_OFF, CLAWBACK_REQUESTED, ADJUSTMENT_BOOKED, LATE_SETTLEMENT_CONFIRMED, FX_CONVERSION_CONFIRMED, ROUNDING_ADJUSTMENT_BOOKED, LATE_PAYOUT_CONFIRMED, CLASSIFIED_NON_PSP, RETURNED_TO_SENDER |  |  | must be allowed for the exception type |
| resolved_by | STRING | yes |  |  |  | FK users |
| resolved_ts | TIMESTAMP | yes |  |  |  | >= detected_at, <= as-of |
| adjustment_amount_minor | INT | yes |  | minor units |  | >= 0 |
| currency | STRING | yes | USD, EUR, GBP, INR |  |  |  |
| notes | STRING | yes |  |  |  |  |

## status_history

Append-only status changes of exceptions: who and when. Rows are never updated.

* Primary key: `history_id`
* Cardinality: N:1 exceptions; N:1 users
* Foreign keys: `changed_by` -> `users.user_id`

| field | type | required | allowed values | unit | unique | validation rule |
|---|---|---|---|---|---|---|
| history_id | STRING | yes |  |  | yes | HIS-0000001 pattern |
| entity_type | STRING | yes | EXCEPTION |  |  |  |
| entity_id | STRING | yes |  |  |  | exception_id |
| from_status | STRING | no |  |  |  | empty on creation |
| to_status | STRING | yes | OPEN, IN_REVIEW, ESCALATED, RESOLVED, WRITTEN_OFF |  |  |  |
| changed_at | TIMESTAMP | yes |  |  |  |  |
| changed_by | STRING | yes |  |  |  | FK users |

## ground_truth (separate file, never read by the engine)

Columns: `gt_id`, `issue_type`, `origin`, `entity_type`, `entity_id`, `payment_id`, `batch_id`, `expected_exception_type`, `expected_resolution_options`, `expected_decision`, `note`. `origin` is EDGE_CASE for an injected fault and BASELINE_CONDITION for normal noise (webhook redeliveries, rounding exactly at the tolerance) or a late settlement found by rule. `expected_exception_type` is NONE where the right answer is no exception.
