"""End to end on a freshly generated starter dataset (about a second)."""
import inspect
import os
import re
import sqlite3
import gzip

import pytest

from app.services import reconciliation
from app.services.common import canonical_events, div_half_even, bday_add
from app.services.exporter import data_checksums, read_table, read_ground_truth
from app.services.schema import TABLES
from tests.conftest import build

EDGE_CASES = ("DUPLICATE_SETTLEMENT_LINE", "BANK_AMOUNT_DIFFERS_BY_FEE", "REFUND_BEFORE_CAPTURE",
              "UNMATCHED_RECORD_SILENTLY_DROPPED", "CURRENCY_MISMATCH", "SAME_EVENT_INGESTED_TWICE")


def test_helpers():
    from datetime import date
    assert [div_half_even(n, 10) for n in (24, 25, 26, 35)] == [2, 2, 3, 4]  # half goes to the even neighbour
    assert bday_add(date(2026, 1, 2), 2) == date(2026, 1, 6)  # Friday + 2 business days = Tuesday


def test_workflow_passes_every_check(starter):
    _, res = starter
    failed = [c for c in res["checks"] if c["status"] != "PASS"]
    assert failed == []
    assert res["ok"]


def test_row_counts_match_the_request(starter):
    _, res = starter
    n = {t: len(r) for t, r in res["tables"].items()}
    assert (n["merchants"], n["payment_orders"], n["payment_attempts"], n["settlement_batches"],
            n["bank_statement_lines"]) == (40, 1000, 1100, 20, 100)


def test_same_seed_gives_identical_files_and_other_seed_does_not(starter, tmp_path):
    path, _ = starter
    again = tmp_path / "again"
    other = tmp_path / "other"
    build(again)
    build(other, seed=1)
    assert data_checksums(str(path)) == data_checksums(str(again))
    assert data_checksums(str(path)) != data_checksums(str(other))


def test_stage_two_can_be_run_again_on_the_same_folder(starter):
    path, _ = starter
    before = data_checksums(str(path))
    from run_workflow import run_pipeline
    again = run_pipeline(str(path), formats=("csv", "json", "sql"))
    assert again["ok"]
    assert data_checksums(str(path)) == before  # nothing duplicated, nothing lost


def test_each_required_edge_case_is_labelled_and_found(starter):
    path, res = starter
    gt = read_ground_truth(str(path))
    labelled = {g["issue_type"] for g in gt}
    assert set(EDGE_CASES) <= labelled
    found = {(x["exception_type"], x["entity_id"]) for x in res["tables"]["exceptions"]}
    for g in gt:
        if g["issue_type"] in EDGE_CASES:
            assert (g["expected_exception_type"], g["entity_id"]) in found, g


def test_normal_noise_is_labelled_and_not_flagged(starter):
    path, res = starter
    flagged = {x["entity_id"] for x in res["tables"]["exceptions"]}
    normal = [g for g in read_ground_truth(str(path)) if g["expected_exception_type"] == "NONE"]
    assert normal, "expected at least one labelled-normal record"
    assert not [g for g in normal if g["entity_id"] in flagged]


def test_tolerance_boundary_is_covered_on_both_sides(starter):
    path, res = starter
    gt = {g["issue_type"]: g for g in read_ground_truth(str(path))}
    flagged = {x["entity_id"] for x in res["tables"]["exceptions"]}
    assert gt["ROUNDING_AT_TOLERANCE"]["entity_id"] not in flagged
    assert gt["ROUNDING_OVER_TOLERANCE"]["entity_id"] in flagged


def test_ground_truth_is_kept_out_of_inputs_and_engine(starter):
    path, _ = starter
    for name in os.listdir(os.path.join(path, "csv")):
        with open(os.path.join(path, "csv", name)) as f:
            header = f.readline()
        assert "issue_type" not in header and "expected_exception" not in header
    assert "ground_truth" not in inspect.getsource(reconciliation)


def test_csv_round_trip_keeps_every_value(starter):
    path, res = starter
    for t in TABLES:
        assert read_table(str(path), t) == res["tables"][t], t


def test_exception_history_is_append_only_and_complete(starter):
    _, res = starter
    t = res["tables"]
    history = t["status_history"]
    ids = [h["history_id"] for h in history]
    assert ids == ["HIS-%07d" % i for i in range(1, len(ids) + 1)]  # no gaps, no renumbering
    assert {h["entity_type"] for h in history} == {"EXCEPTION"}
    first = {}
    for h in history:
        first.setdefault(h["entity_id"], h)
    assert set(first) == {x["exception_id"] for x in t["exceptions"]}  # every exception has a history
    assert all(h["from_status"] is None and h["to_status"] == "OPEN" for h in first.values())


def test_order_status_is_derived_from_the_events(starter):
    _, res = starter
    t = res["tables"]
    captured, refunded = {}, {}
    for e in canonical_events(t["processor_events"]):
        if e["event_type"] == "CAPTURED":
            captured[e["payment_id"]] = captured.get(e["payment_id"], 0) + e["amount_minor"]
        elif e["event_type"] == "REFUND_ISSUED":
            refunded[e["payment_id"]] = refunded.get(e["payment_id"], 0) + e["amount_minor"]
    for o in t["payment_orders"]:
        c, r = captured.get(o["payment_id"], 0), refunded.get(o["payment_id"], 0)
        expected = "FAILED" if c == 0 else "CAPTURED" if r == 0 else "PARTIALLY_REFUNDED" if r < c else "REFUNDED"
        assert (o["status"], o["captured_amount_minor"], o["refunded_amount_minor"]) == (expected, c, r)


def test_one_capture_per_order(starter):
    _, res = starter
    caps = [e["payment_id"] for e in canonical_events(res["tables"]["processor_events"]) if e["event_type"] == "CAPTURED"]
    assert len(caps) == len(set(caps))


def test_settlement_never_happens_before_capture_except_labelled(starter):
    _, res = starter
    t = res["tables"]
    batches = {b["batch_id"]: b for b in t["settlement_batches"]}
    events = {e["processor_event_id"]: e for e in t["processor_events"]}
    early = [l for l in t["settlement_lines"] if batches[l["batch_id"]]["cutoff_ts"] < events[l["processor_event_id"]]["event_ts"]]
    assert early == []


def test_orders_are_never_before_their_merchant_exists(starter):
    _, res = starter
    t = res["tables"]
    onboarded = {m["merchant_id"]: m["onboarded_date"] for m in t["merchants"]}
    assert not [o for o in t["payment_orders"] if o["order_ts"][:10] < onboarded[o["merchant_id"]]]


def test_sql_seed_loads_and_matches_the_csv(starter):
    path, res = starter
    con = sqlite3.connect(":memory:")
    con.execute("PRAGMA foreign_keys = ON")
    with gzip.open(os.path.join(path, "seed.sql.gz"), "rt") as f:
        con.executescript(f.read())
    for t in TABLES:
        assert con.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0] == len(res["tables"][t]), t
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_id_conventions(starter):
    _, res = starter
    t = res["tables"]
    pat = {"payment_orders": ("payment_id", r"PAY-2026-\d{8}"), "settlement_batches": ("batch_id", r"SET-2026-\d{6}"),
           "bank_statement_lines": ("bank_line_id", r"BANK-2026-\d{6}"),
           "reconciliation_matches": ("match_id", r"REC-2026-\d{6}")}
    for table, (col, rx) in pat.items():
        assert all(re.fullmatch(rx, r[col]) for r in t[table]), table
    assert all(a["attempt_id"] == "ATT-%s-%02d" % (a["payment_id"], a["attempt_no"]) for a in t["payment_attempts"])
    assert all(l["settlement_line_id"].startswith("STL-%s-" % l["batch_id"]) for l in t["settlement_lines"])


@pytest.mark.skipif(not os.getenv("RECON_FULL_TEST"), reason="set RECON_FULL_TEST=1 to generate the 50,000-order dataset (about 20 s)")
def test_full_volume(tmp_path):
    from app.services import data_generator as gen
    from app.services.common import make_cfg
    from types import SimpleNamespace
    from run_workflow import run_pipeline
    a = SimpleNamespace(seed=20261022, merchants=2000, orders=50000, attempts=55000, batches=1000, bank_lines=5000)
    gen.generate_to(str(tmp_path), make_cfg(a))
    res = run_pipeline(str(tmp_path), formats=("csv",))
    n = {t: len(r) for t, r in res["tables"].items()}
    assert (n["merchants"], n["payment_orders"], n["payment_attempts"], n["settlement_batches"],
            n["bank_statement_lines"]) == (2000, 50000, 55000, 1000, 5000)
    assert res["ok"]
