# Changes from the first version

The first version generated the right volumes and ran, but covered only part of the brief. This version keeps its layout
(`app/services/`, `run_workflow.py`, Flask routes, `tests/`, `docs/`) and changes the following.

| area | first version | now |
|---|---|---|
| required edge cases | 1 of 6 (currency mismatch) | all 6, plus partial, missing and late payouts, tolerance boundary, bank noise |
| refunds, partial refunds, duplicate webhooks, delayed settlement, fees, rounding | flat 2 % fee only | all of them; fee per merchant, half-even rounding |
| data consistency | settlements dated before captures; several captures per order; orders before the merchant existed; every order `CREATED` | none of these; order status derived from events; checked by validation and tests |
| IDs | `ATT-00000001`, `STL-000001-0001`, no match or exception ids | exactly the brief's patterns, plus ids for matches, exceptions, resolutions, history |
| resolutions and history | none | exceptions with severity, SLA, assignment, resolutions and append-only status history |
| matching | bank lines vs batch totals, exact amounts | bank vs batch (reference, currency, amount within a tolerance, date window) and event vs settlement line |
| ground truth | 6 rows, one per scenario | one row per injected fault and per labelled-normal record, with expected exception and resolution options |
| validation | counts in a document | 31 checks on every dataset, written to a report |
| data dictionary | table level | every field: type, required, allowed values, unit, uniqueness, rule; cardinalities and lifecycles |
| exports | CSV | CSV, JSON, SQL seed, manifest with checksums, source manifest |
| scale | fixed in code | one generator for every size; `--starter` and scale flags |
| reproducibility | deterministic, not demonstrated | `--repro-check`, two regenerations compared by checksum |
| tests | 3 | 52 (engine rules, whole pipeline, API) |
| dependencies | Flask, pandas, numpy, MySQL connector and more | Flask and pytest; standard library otherwise |
| MySQL loaders | included, untested | removed (could not be tested, and no longer matched the schema); the SQL seed is tested on SQLite |
| API | 4 endpoints | summary, filterable exception list, per-exception trace, validation, evaluation |

## Kept simple on purpose

To make the project easier to understand and explain, these were left out although a bigger version could have them:
merchant risk tiers and status changes, order status history, voided payments, a fifth currency (JPY, which has no minor
unit), exception severity from the amount in USD (it is a fixed table per exception type), and extra labelled-normal cases.
Everything the brief requires is still covered. The code is about 1,900 lines because the brief itself demands most of it.
