# Design notes

## The problem

Payments data sits in four places that rarely agree: what the merchant asked for (orders and attempts), what the
processor says happened (events), what the processor says it will pay (settlement batches and lines), and what the bank
received (statement lines). Reconciliation finds where they disagree, records why, and records how each case was closed.
This project generates a realistic, fully labelled version of that data and a reconciliation engine to run on it.

## Pipeline

| stage | module | what it does |
|---|---|---|
| 1 generate | `app/services/data_generator.py` | clean baseline first (merchants, orders, attempts, events, settlement, bank lines), faults injected on top, ground truth written at the moment of injection |
| 2 reconcile | `app/services/reconciliation.py` | reads the input tables only: matches, exceptions, then a seeded analyst workflow: resolutions and exception history |
| 3 validate and score | `app/services/validation.py` | 31 checks over every table; engine output compared with the ground truth |
| support | `common.py`, `schema.py`, `exporter.py` | constants and helpers, the data dictionary (types, enums, rules, cardinalities), CSV/JSON/SQL IO and reports |

Stage 1 writes CSV; stage 2 reads that CSV back with the types from the data dictionary, so the engine can run on any
saved dataset. A test checks that the CSV round trip keeps every value.

## Faults and conditions

Each row says what is injected, how, the label in `ground_truth.csv`, and what the engine should raise.

| required case or condition | how it is produced | ground-truth label | expected exception |
|---|---|---|---|
| duplicate settlement line | processor lists one capture twice in a batch | DUPLICATE_SETTLEMENT_LINE | DUPLICATE_SETTLEMENT_LINE |
| bank amount differs by fee | bank pays gross (net + fees) or net minus a wire charge | BANK_AMOUNT_DIFFERS_BY_FEE | FEE_DIFFERENCE |
| refund appears before capture | capture is stamped and delivered after its refund | REFUND_BEFORE_CAPTURE | REFUND_BEFORE_CAPTURE |
| unmatched record silently dropped | a capture is left out of every batch | UNMATCHED_RECORD_SILENTLY_DROPPED | UNMATCHED_EVENT (after the 8 day SLA) |
| currency mismatch | last payout tranche arrives in another currency, converted | CURRENCY_MISMATCH | CURRENCY_MISMATCH |
| same processor event ingested twice | identical delivery id written twice | SAME_EVENT_INGESTED_TWICE | DUPLICATE_EVENT |
| partial payout | last tranche never arrives | PARTIAL_PAYOUT | PARTIAL_PAYOUT |
| missing payout | batch is never paid | MISSING_PAYOUT | UNMATCHED_BATCH (once payout + window + grace has passed) |
| rounding over tolerance | bank amount off by tolerance + 1..6 | ROUNDING_OVER_TOLERANCE | AMOUNT_MISMATCH |
| delayed payout | value date 4..10 days after expected | DELAYED_PAYOUT | DELAYED_PAYOUT |
| bank noise | credits with unknown reference, bank charges | ORPHAN_BANK_LINE | UNMATCHED_BANK_LINE |
| delayed settlement | line held 9-14 days, or waiting for a held line in its batch | DELAYED_SETTLEMENT (by rule: more than 8 days from capture to cut-off) | DELAYED_SETTLEMENT |
| rounding exactly at tolerance | bank amount off by exactly 2 | ROUNDING_AT_TOLERANCE | none (still a match) |
| webhook redelivery | same event id, new delivery id | WEBHOOK_REDELIVERY | none (deduplicated silently) |

Labelled-normal rows are in the ground truth on purpose, so false positives can be counted.
`expected_resolution_options` lists which resolutions an analyst may use for that exception type.

## Key decisions and why

* **Integer minor units for all money.** No floats, so arithmetic checks are exact. Fees use half-even rounding.
* **Derived values are computed.** Order status and captured/refunded totals come from the canonical events, batch totals
  from lines, bank amounts from batch nets, exception status from its history. Nothing is generated and then "fixed".
* **State changes are rows.** `processor_events` is append-only and is the history of every order. `status_history` holds
  every exception transition (never updated). Validation checks each exception chain is allowed, in time order, and ends at
  its current status.
* **Two kinds of duplicate.** A webhook redelivery and a pipeline double-write share an idempotency key but differ in delivery
  id. Deduplicating on the key makes ingestion idempotent; the delivery id decides whether it is an exception.
* **Ground truth is written where the fault is injected**, not inferred later, and the engine never reads it.
* **Time is deterministic.** The nightly job runs at 02:00Z, so `detected_at` and `matched_at` follow the data.
* **Tolerance is a parameter** (default 2 minor units). The data has bank amounts exactly at it and one or more over it, so
  the boundary is tested on both sides.
* **One generator for every size.** The date span shrinks with the batch count so batch cadence stays comparable.
* **Severity is fixed per exception type** (`SEVERITY` in `common.py`), which keeps the rule easy to explain.

## Assumptions

Tolerance 2 minor units; bank date window 0..+3 days after the expected payout date (cut-off + 2 business days);
settlement SLA 8 days; 7 days grace after the window before a missing payout becomes an exception; `as_of` 2026-10-22;
currencies USD, EUR, GBP, INR with fixed invented FX rates; each merchant has one settlement currency;
fee rate 200-350 bps per merchant plus a fixed fee per capture; the processor keeps fees on refunds (refund lines carry no fee);
about 8.5 % of captured orders are refunded, 12 % of those in two parts; about 0.8 % of lines are held 9-14 days.
Exception SLAs (2, 5 and 10 days for HIGH, MEDIUM and LOW) and the users are invented. IDs the brief did not specify
(`EVT-`, `EXC-`, `RES-`, `HIS-`, `USR-`, `MER-`) follow the same zero-padded pattern.

## How it is verified

* 31 checks in every run: primary keys, enums, NOT NULL and CHECKs (by loading all tables into SQLite), foreign keys, ID
  formats, row counts, date ordering, order status derived from events, one capture per order, fee formula, refunds carrying
  no fee, batch totals equal their lines, lines equal their events, duplicates, tolerance, "every unmatched item is an
  exception", exception lifecycle, allowed resolution types, ground truth kept out of the inputs.
* 52 tests (plus 18 more at full volume): the engine's rules on hand-made worlds, a whole starter dataset, the API.
* Reproducibility: `--repro-check` regenerates twice and compares sha256 of every data file with each other and the current
  files. On the starter dataset, Python 3.11 and 3.13 produce identical files.
* Breaking the engine on purpose (tolerance off by one, redeliveries flagged as duplicates, refund-before-capture check off)
  makes tests fail each time.

## Limitations and next steps

See the README. The main limitation: the engine's rules mirror how faults are injected, so a perfect score shows
consistency, not that the approach generalises to real processor and bank formats.
Next steps: chargebacks and reserves, several processors, per-currency tolerance, an engine that suggests resolutions and is
scored on them, and loading the seed into MySQL or PostgreSQL.
