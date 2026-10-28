# Walkthrough: how to read and explain this project

The code is about 1,900 lines, but it is four ideas repeated across a few files. Read it in the order below.

## The four ideas

1. **Generate clean data, then break it on purpose and write down what you broke.**
   Orders -> attempts -> events -> settlement batches -> bank lines are all valid first. Then a fault is injected
   (for example a capture is left out of every batch), and at that moment a row is added to `ground_truth.csv`.
2. **Reconcile by matching.** Bank lines are matched to batches (reference, currency, summed amount, date window).
   Processor events are matched to settlement lines (event id, amount, currency). Anything that does not match, or matches
   badly, becomes an exception.
3. **Parameters decide the grey areas.** Tolerance (2 minor units), the date window (+3 days), the settlement SLA
   (8 days) and the grace period (7 days) decide what is a match and what is an exception. They are in `params.json`.
4. **Score yourself against the answer key.** The engine never reads `ground_truth.csv`. Stage 3 compares what the engine
   raised with what was injected: expected, found, missed, extra.

## Reading order (about two hours)

| step | file | what to look for |
|---|---|---|
| 1 | `README.md`, then run the quick start | the three stages and what the output looks like |
| 2 | `docs/DESIGN.md`, the fault table | each fault: how it is produced, its label, what the engine should raise |
| 3 | `run_workflow.py`: `run_pipeline()` | the whole flow in about 40 lines: read inputs, `reconcile()`, `validate()`, write outputs |
| 4 | `app/services/reconciliation.py`: `run_engine()` | in order: duplicates, refund before capture, event -> line, bank -> batch, orphans |
| 5 | `app/services/data_generator.py`: `gen_flow()`, `gen_settlement()`, `gen_bank()` | where each fault is injected and labelled |
| 6 | `app/services/validation.py` | the 31 checks, each one a sentence |
| 7 | `tests/test_engine.py` | small hand-made worlds; the quickest way to see each rule |

`schema.py` (the data dictionary), `exporter.py` (file IO) and `common.py` (constants) are support. Skim them.

## A worked example you can check by hand (starter data)

* **Fee:** line `STL-SET-2026-000003-012`, payment `PAY-2026-00000037`, merchant `MER-000006` (296 bps, fixed fee 30).
  Gross 7,913. 7,913 x 296 / 10,000 = 234.22, rounded half-even to 234. Plus 30 fixed = **264**. Net = 7,913 - 264 = **7,649**.
* **Batch total:** `SET-2026-000016` (GBP): captured 529,104 - refunded 69,078 - fees 16,090 = **443,936** net payout.
* **Bank side:** its five bank tranches (`T1/5` to `T5/5`) are 79,877 + 95,915 + 86,389 + 87,649 + 94,106 = **443,936**.
  Same total, same currency, value dates 23-24 Jan against an expected payout of 22 Jan (+1 and +2 days, inside the window).
  So the batch is a clean match and raises nothing.

## Questions you are likely to be asked, and the short answers

**Why integer minor units?** Floats cannot represent most decimal amounts exactly, so totals drift and equality checks
become unreliable. Integers make "do these add up" an exact question. Fees use half-even rounding so rounding errors do not
all lean one way.

**What is a webhook redelivery, and why is it not an exception?** The processor did not get our acknowledgement and sent the
same event again. Same webhook event id and idempotency key, but a new delivery id. We deduplicate it silently. If the *same
delivery id* appears twice, our own pipeline wrote it twice, which is a fault, so we deduplicate and raise `DUPLICATE_EVENT`.

**What does the idempotency key do?** It names the business event (payment, attempt, event type, sequence). The first row with a
key is canonical; later rows with the same key are copies. Everything downstream (orders, settlement, matching) uses only the
canonical rows, so an event cannot be counted twice.

**How is a batch's net payout calculated?** Sum of capture gross, minus refund gross, minus fees. Refund lines carry no fee
because the processor keeps the fee on refunds. The batch total is summed from its lines, never generated separately.

**How does the bank-to-batch match work, and what is the tolerance for?** The bank reference names the batch and the tranche
(`... T2/5`). We sum the tranches, compare with the batch net payout, and require the same currency and a value date from the
expected payout date to 3 days later. A difference of up to 2 minor units is still a match (rounding); 3 or more is an
`AMOUNT_MISMATCH`. The data has a case exactly at 2 and cases above it, so the boundary is tested on both sides.

**Why is a missing payout not flagged immediately?** The payout may simply not be due yet. It becomes `UNMATCHED_BATCH` only
after the expected date + the 3 day window + 7 days grace has passed relative to the as-of date. The same idea applies to
captures with no settlement line (8 day SLA).

**Why does the engine never read the ground truth?** Otherwise the score would be meaningless. A test checks that
`reconciliation.py` does not mention it, and a validation check checks that no input table has a ground-truth column.

**Why is 100 % detection not impressive?** Because the engine's rules were written next to the code that injects the faults.
It shows the rules and the data agree, and that nothing was missed or flagged wrongly in this dataset. It does not show the
rules would catch a fault nobody thought of, or cope with real bank formats.

**How do you know the tests are not empty?** I broke the engine on purpose three ways (tolerance off by one, redeliveries
treated as duplicates, refund-before-capture check disabled) and each made several tests fail.

**How is the data reproducible?** Every stage has its own random stream seeded from `seed` plus a stage name; nothing depends
on the clock; files are written with fixed line endings and a fixed gzip timestamp. `--repro-check` regenerates twice and
compares sha256 of every data file. On the starter dataset, Python 3.11 and 3.13 produce identical files.

**What are the limitations?** One processor and one funds account per currency, four currencies with invented FX rates, no
chargebacks or reserves, resolutions are a seeded simulation, and the late-settlement count is high because the last batch of
each currency waits for lines held 9-14 days.

**What would you do next?** Per-currency tolerance, chargebacks, several processors, an engine that proposes resolutions and
is scored on them, and a real database load.

## Exercises (do at least two before the interview)

1. Copy `data/starter` to `data/try`, then run `python run_workflow.py --data data/try --tolerance 5` and again with
   `--tolerance 1`. On the starter data, tolerance 5 misses the one `AMOUNT_MISMATCH` (now inside tolerance) and tolerance 1
   raises one extra `AMOUNT_MISMATCH` (the case exactly at 2). Both print `RESULT: FAIL`, which is correct: the ground truth was
   built for tolerance 2. Why does the boundary case behave differently at each setting?
2. In `common.py`, inside `make_cfg`, change `redelivery_rate` to `0.05` and regenerate. Which numbers move? Which do not?
3. Open `data/starter/csv/exceptions.csv`, pick an exception, and trace it by hand: its match row, its batch or event, its
   resolution, and its `status_history` rows. The API endpoint `/api/exceptions/<id>` does the same.
4. In `reconciliation.py`, delete the rule that raises `DUPLICATE_SETTLEMENT_LINE`. Which tests fail, and what does the
   `missed` column of the engine-versus-truth table show?
5. Pick one validation check and break its data by hand in a copy of `data/starter/csv`; confirm the check fails.
