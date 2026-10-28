# Validation summary

31 of 31 checks passed.

| check | result | detail |
|---|---|---|
| primary keys unique + enums + NOT NULL + CHECKs (sqlite load) | PASS | all tables loaded |
| foreign key integrity (PRAGMA foreign_key_check) | PASS | 0 violations |
| ID formats follow the naming convention | PASS | 0 bad ids |
| child ids embed their parent id | PASS |  |
| row counts match requested volume | PASS | merchants=2000 orders=50000 attempts=55000 batches=1000 bank=5000 |
| attempt_ts >= order_ts | PASS | 0 violations |
| received_ts >= event_ts | PASS | 0 violations |
| orders are not earlier than the merchant's onboarded_date | PASS | 0 violations |
| order currency equals merchant settlement currency | PASS |  |
| expected payout date >= cutoff date | PASS |  |
| refund never before capture unless labelled REFUND_BEFORE_CAPTURE | PASS | 0 unlabelled |
| refunded <= captured for every order | PASS |  |
| order status and totals are derived from the canonical events | PASS | 0 orders off |
| at most one capture per order | PASS |  |
| attempt status matches the events (CAPTURED only if a capture event exists) | PASS | 0 attempts off |
| decline_code is set exactly on declined attempts | PASS |  |
| fee and refund treatment consistent (fee formula, refunds carry no fee) | PASS | 0 lines off |
| batch totals equal the sum of their lines | PASS | 0 batches off |
| settlement line amount/currency equals its processor event and batch | PASS |  |
| duplicate settlement lines are exactly the labelled ones | PASS | 12 duplicates, 12 labelled |
| no settlement line points at a non-canonical event copy | PASS |  |
| matched amounts reconcile within tolerance (2 minor units) | PASS |  |
| every settleable event without a line is an exception | PASS | 0 missing |
| every batch without a bank payout is an exception | PASS | 0 missing |
| every unmatched bank line is an exception | PASS | 0 missing |
| every partial or mismatched match row has an exception | PASS | 0 without |
| resolution exists exactly for closed exceptions | PASS |  |
| resolved_ts >= detected_at | PASS |  |
| exception history starts at creation, follows the allowed moves in time order and ends at the current status | PASS | 0 violations |
| every resolution type is allowed for its exception type | PASS | 0 not allowed |
| ground truth is not referenced by any input table column | PASS |  |

## Engine vs ground truth

Expected exceptions: 849, found: 849, missed: 0, extra: 0 (precision 1.0, recall 1.0). Exceptions raised on records labelled normal: 0.

| exception type | expected | found | missed | extra |
|---|---|---|---|---|
| DUPLICATE_EVENT | 30 | 30 | 0 | 0 |
| REFUND_BEFORE_CAPTURE | 40 | 40 | 0 | 0 |
| UNMATCHED_EVENT | 25 | 25 | 0 | 0 |
| DUPLICATE_SETTLEMENT_LINE | 12 | 12 | 0 | 0 |
| DELAYED_SETTLEMENT | 601 | 601 | 0 | 0 |
| UNMATCHED_BATCH | 8 | 8 | 0 | 0 |
| PARTIAL_PAYOUT | 8 | 8 | 0 | 0 |
| CURRENCY_MISMATCH | 10 | 10 | 0 | 0 |
| FEE_DIFFERENCE | 15 | 15 | 0 | 0 |
| AMOUNT_MISMATCH | 10 | 10 | 0 | 0 |
| DELAYED_PAYOUT | 30 | 30 | 0 | 0 |
| UNMATCHED_BANK_LINE | 60 | 60 | 0 | 0 |

Validation configuration: Amount tolerance of 2 minor currency units, bank-statement date window of 3 days, settlement SLA of 8 days, and simulation date of 22 October 2026.

Validation limitation: The reconciliation rules and injected test scenarios are designed to be consistent with one another. The perfect validation score confirms that all included scenarios were handled as expected; it does not guarantee detection of every possible real-world anomaly.
