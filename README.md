# Payment Reconciliation System

Generates synthetic payments data, reconciles four sources against each other (payment orders, processor events,
settlement batches, bank statements), raises and resolves exceptions, and checks its own answers against a separate
ground-truth file. Everything is synthetic: no external data, no secrets, no database server needed.

* Standard library only for the core. Flask is used only for the optional local API; pytest only for the tests.
* Written for Python 3.9+. Tests pass on Python 3.11 and 3.13 (Linux), and both produce byte-identical starter data. Not run on 3.9 itself.
* Same seed gives byte-identical files (default seed `20261022`).
* A small dataset is committed in `data/starter/`. The full dataset, containing 50,000 payment orders, can be generated locally. Execution time depends on the machine and workload.

## Quick start

Windows (CMD):

```cmd
python -m venv venv
venv\Scripts\activate
python -m pip install -r requirements.txt
python -m pytest -q
python run_workflow.py
```

macOS / Linux:

```bash
python3 -m venv venv && source venv/bin/activate
python -m pip install -r requirements.txt
python -m pytest -q
python run_workflow.py
```

`python -m pytest -q` should report `52 passed, 1 skipped`.
`python run_workflow.py` reconciles the committed starter dataset and should end with `31/31 checks passed`,
`expected = found` for every exception type, and `RESULT: PASS` (exit code 0; any failure exits with 1).

### Generate the full dataset

```bash
python run_workflow.py --generate --data data/full --formats csv,sql --repro-check
```

2,000 merchants, 50,000 orders, 55,000 attempts, about 109,000 processor events, 1,000 settlement batches and
5,000 bank lines. `--repro-check` regenerates twice more and compares sha256 of every data file.
`data/full/` is git-ignored (about 52 MB); the command above recreates it exactly. Add `json` to `--formats` for JSON copies.

### Other commands

| command | what it does |
|---|---|
| `python -m app.services.data_generator --starter --out data/x` | stage 1 only: input tables, ground truth, parameters |
| `python run_workflow.py --data data/x` | stages 2 and 3 on an existing folder |
| `python run_workflow.py --generate --starter --data data/x` | all stages at small size |
| `python run_workflow.py --data data/try --tolerance 5` | change the match tolerance (minor units) without regenerating. It overwrites the outputs in that folder, so use a copy. The ground truth was built for 2, so other values report `FAIL` on purpose |
| `python run_workflow.py --docs-dir docs` | also write `data_dictionary.md` and `validation_report.md` into `docs/` |
|RECON_FULL_TEST=1 python -m pytest -q | also run the 50,000-order volume test; execution time depends on the machine and workload.|
| `python run.py` | start the local API |

Scale flags for `--generate`: `--seed --merchants --orders --attempts --batches --bank-lines`
(attempts must be between 1x and 2x orders; bank lines at least two per paid batch).

## How it works

```
stage 1  generate        users, merchants, orders, attempts, events, batches, lines, bank lines
                         + ground_truth.csv + params.json
stage 2  reconcile       reads ONLY the input tables -> matches, exceptions, resolutions, exception history
stage 3  validate/score  31 checks on the whole dataset; engine output compared with the ground truth
```

Matching rules (parameters in `params.json`; the tolerance can be overridden on the command line):

* **Bank line to batch:** the batch id in the bank reference, same currency, tranche amounts summed and compared with the
  batch net payout within **2 minor units**, value date from the expected payout date to **+3 days**.
* **Event to settlement line:** processor event id, amount and currency equal.
* **Duplicate events:** one idempotency key is one business event. A different delivery id is a webhook redelivery
  (normal, deduplicated silently). The same delivery id twice is a pipeline fault (deduplicated and raised).
* **Settlement SLA:** 8 days from capture. A late line is `DELAYED_SETTLEMENT`; no line at all is `UNMATCHED_EVENT`.
* **Fees:** `round_half_even(gross * bps / 10000) + fixed fee` on captures. Refund lines carry no fee.
  All money is integer minor units.

The six required edge cases (duplicate settlement line, bank amount differs by fee, refund before capture, unmatched record
silently dropped, currency mismatch, same processor event ingested twice) plus the other faults are listed with their
labels in [`docs/DESIGN.md`](docs/DESIGN.md).

## Where each step of the brief is done

| brief step | where |
|---|---|
| 1 data dictionary | [`docs/data_dictionary.md`](docs/data_dictionary.md), generated from `app/services/schema.py` |
| 2 parents first, then children and events | `generate()` in `app/services/data_generator.py` |
| 3 deterministic IDs | `PAY-2026-00000001`, `ATT-<payment-id>-01`, `SET-2026-000001`, `STL-<batch-id>-001`, `BANK-2026-000001`, `REC-2026-000001`; checked by validation and tests |
| 4 volume, fixed seed, parameterised scale | defaults are the brief's volumes; `--starter` and the scale flags use the same generator |
| 5 clean baseline first, then labelled faults | `gen_flow`, `gen_settlement`, `gen_bank`; each fault writes its label where it is injected |
| 6 derived values calculated | order status and totals from events, batch totals from lines, exception status from its history |
| 7 separate ground truth | `ground_truth.csv/json`; `app/services/reconciliation.py` never reads it (a test checks this) |
| 8 validation | `app/services/validation.py`, 31 checks, report in `docs/validation_report.md` |
| 9 exports | CSV, JSON, SQL seed (`seed.sql.gz`), README, schema, generator command and seed in `manifest.json`, source manifest, validation summary |
| 10 reproducibility | `--repro-check`, result in `reproducibility_check.json` |

## Outputs (in each dataset folder)

| file | content |
|---|---|
| `csv/` | 12 tables: users, merchants, payment_orders, payment_attempts, processor_events, settlement_batches, settlement_lines, bank_statement_lines, reconciliation_matches, exceptions, resolutions, status_history |
| `json/` | the same tables as JSON (when requested) |
| `seed.sql.gz` | DDL with primary keys, foreign keys and CHECKs, plus INSERTs. Loads into SQLite as is |
| `ground_truth.csv/json` | labelled faults and labelled-normal records |
| `validation_summary.md/json`, `metrics.json` | checks and engine-versus-truth numbers |
| `manifest.json`, `reproducibility_check.json`, `params.json`, `source_manifest.json` | counts, checksums, parameters, provenance |

Files are written with LF line endings on every OS. If Git rewrites line endings (`core.autocrlf`), checksums on your
checkout can differ although the content is the same.

Load the SQL seed into SQLite (no server needed):

```python
import gzip, sqlite3
con = sqlite3.connect("recon.db")
con.executescript(gzip.open("data/starter/seed.sql.gz", "rt").read())
print(con.execute("select exception_type, count(*) from exceptions group by 1").fetchall())
```

## Local API

```bash
python run_workflow.py        # make sure outputs exist
python run.py                 # http://127.0.0.1:5000
```

Set `RECON_DATA_DIR=data/full` to serve the full dataset. Read-only endpoints: `/health`, `/api/summary`,
`/api/exceptions` (filters `type`, `status`, `severity`, `batch_id`, `payment_id`, `limit`, `offset`),
`/api/exceptions/<exception_id>` (the exception with its match, resolution and status history), `/api/validation`,
`/api/evaluation`. The built-in Flask server is for local use only.

## Tests

python -m pytest -q runs the automated test suite. The verified result was 52 passed and 1 skipped; execution time depends on the environment.

* `tests/test_engine.py`: the matching rules on tiny hand-made worlds, including both sides of the tolerance boundary.
* `tests/test_pipeline.py`: a freshly generated starter dataset: determinism, all checks, ground truth kept apart,
  history append-only, CSV round trip, the SQL seed loads, ID formats, lifecycle consistency.
* `tests/test_api.py`: the API endpoints.

I also broke the engine on purpose (tolerance off by one, redeliveries treated as duplicates, refund-before-capture check
disabled) and confirmed the tests fail each time.

## Limitations

* The engine's rules mirror how faults are injected, so finding 100 % of the labelled faults shows that the rules and
  the data agree. It does not show that the approach would catch faults nobody thought of.
* One processor, one funds account per currency, one currency per merchant, four currencies. FX appears only in the
  currency-mismatch fault, with fixed invented rates.
* No chargebacks, disputes, voids or reserves.
* Some lines are held 9-14 days, so the last batch of each currency waits for them and many lines in it count as
  late settlements. This is correct under the rule, but it makes the late-settlement count high (601 in the full set, 103 in
  the starter set).
* The step that creates resolutions is a seeded simulation of analyst behaviour, not real analyst data.
* `as_of` is fixed at 2026-10-22, so a few of the newest exceptions are still open or in review.
* The SQL seed is tested on SQLite only; no MySQL or PostgreSQL.

## Documents

* [`docs/WALKTHROUGH.md`](docs/WALKTHROUGH.md): reading order and the questions you are likely to be asked
* [`docs/DESIGN.md`](docs/DESIGN.md): problem, assumptions, decisions, fault table, verification
* [`docs/ENTITY_RELATIONSHIPS.md`](docs/ENTITY_RELATIONSHIPS.md): diagram, cardinalities, lifecycles
* [`docs/ai_usage_and_prompt_history.md`](docs/ai_usage_and_prompt_history.md): AI use and prompts
* [`docs/CHANGELOG.md`](docs/CHANGELOG.md): what changed from the first version of this project

## Safety

No credentials are needed or used. `.gitignore` excludes virtual environments, caches and `.env` files.
Names, amounts, fees and FX rates are invented; there is no personal or confidential data.
