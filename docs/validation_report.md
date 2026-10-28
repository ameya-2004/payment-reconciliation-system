# Validation summary

31 of 31 checks passed.

| check | result | detail |
|---|---|---|
| primary keys unique + enums + NOT NULL + CHECKs (sqlite load) | PASS | all tables loaded |
| foreign key integrity (PRAGMA foreign_key_check) | PASS | 0 violations |
| ID formats follow the naming convention | PASS | 0 bad ids |
| child ids embed their parent id | PASS |  |
| row counts match requested volume | PASS | merchants=40 orders=1000 attempts=1100 batches=20 bank=100 |
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
| duplicate settlement lines are exactly the labelled ones | PASS | 1 duplicates, 1 labelled |
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

Expected exceptions: 114, found: 114, missed: 0, extra: 0 (precision 1.0, recall 1.0). Exceptions raised on records labelled normal: 0.

| exception type | expected | found | missed | extra |
|---|---|---|---|---|
| DUPLICATE_EVENT | 1 | 1 | 0 | 0 |
| REFUND_BEFORE_CAPTURE | 1 | 1 | 0 | 0 |
| UNMATCHED_EVENT | 1 | 1 | 0 | 0 |
| DUPLICATE_SETTLEMENT_LINE | 1 | 1 | 0 | 0 |
| DELAYED_SETTLEMENT | 103 | 103 | 0 | 0 |
| UNMATCHED_BATCH | 1 | 1 | 0 | 0 |
| PARTIAL_PAYOUT | 1 | 1 | 0 | 0 |
| CURRENCY_MISMATCH | 1 | 1 | 0 | 0 |
| FEE_DIFFERENCE | 1 | 1 | 0 | 0 |
| AMOUNT_MISMATCH | 1 | 1 | 0 | 0 |
| DELAYED_PAYOUT | 1 | 1 | 0 | 0 |
| UNMATCHED_BANK_LINE | 1 | 1 | 0 | 0 |

Tolerance 2 minor units, bank date window +3 days, settlement SLA 8 days, as-of 2026-10-22. The engine's rules mirror how faults are injected, so a perfect score shows the rules and the data agree; it does not prove the rules would catch faults nobody injected.
