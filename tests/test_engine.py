"""
The matching rules, checked on tiny hand-made worlds (no generator involved).

Base world: one USD capture of 100.00, fee 3.00, so the batch nets 97.00 (9,700 minor units),
paid out on 2026-03-05. Each test changes one thing and looks at the engine's answer.
"""
from datetime import datetime

import pytest

from app.services.common import RES_MAP, CCY
from app.services.reconciliation import run_engine, simulate_resolutions

CFG = dict(tolerance_minor=2, window_after_days=3, sla_days=8, grace_days=7, as_of=datetime(2026, 10, 22), seed=7)
BATCH = "SET-2026-000001"
NET = 9700


def event(n, etype="CAPTURED", amount=10000, ccy="USD", at="2026-03-02T10:00:00Z", recv=None, key=None, delivery=None):
    pid = "PAY-2026-%08d" % n
    return dict(processor_event_id="EVT-2026-%08d" % n, payment_id=pid, attempt_id="ATT-%s-01" % pid,
                event_type=etype, event_ts=at, received_ts=recv or at, amount_minor=amount, currency=ccy,
                processor_ref="PSP%d" % n, webhook_event_id="wh%d" % n, delivery_id=delivery or "dlv%d" % n,
                idempotency_key=key or "IDEM%d" % n, source="WEBHOOK")


def line(ev, n=1, batch=BATCH, fee=300, gross=None):
    gross = gross if gross is not None else ev["amount_minor"]
    capture = ev["event_type"] == "CAPTURED"
    return dict(settlement_line_id="STL-%s-%03d" % (batch, n), batch_id=batch, payment_id=ev["payment_id"],
                processor_event_id=ev["processor_event_id"], line_type="CAPTURE" if capture else "REFUND",
                currency=ev["currency"], gross_amount_minor=gross, fee_minor=fee if capture else 0,
                net_amount_minor=gross - fee if capture else -gross, fee_rate_bps=0, fixed_fee_applied_minor=0,
                hold_reason=None)


def batch(lines, batch_id=BATCH, cutoff="2026-03-03T00:00:00Z", payout="2026-03-05"):
    cap = sum(l["gross_amount_minor"] for l in lines if l["line_type"] == "CAPTURE")
    ref = sum(l["gross_amount_minor"] for l in lines if l["line_type"] == "REFUND")
    fees = sum(l["fee_minor"] for l in lines)
    return dict(batch_id=batch_id, currency=lines[0]["currency"], cutoff_ts=cutoff, created_ts="2026-03-03T01:30:00Z",
                expected_payout_date=payout, status="PAYOUT_INITIATED", line_count=len(lines),
                gross_captured_minor=cap, gross_refunded_minor=ref, total_fees_minor=fees,
                net_payout_minor=cap - ref - fees)


def bank(n, amount=NET, ccy="USD", value="2026-03-05", ref=None):
    return dict(bank_line_id="BANK-2026-%06d" % n, statement_id="STM-x", value_date=value, booking_date=value,
                amount_minor=amount, currency=ccy, direction="CREDIT" if amount > 0 else "DEBIT",
                reference=ref or "PSP PAYOUT %s T1/1" % BATCH, counterparty_name="PSP", bank_account_ref="ACCT")


def world(bank_lines, events=None, lines=None, batches=None):
    ev = event(1)
    events = events if events is not None else [ev]
    lines = lines if lines is not None else [line(ev)]
    batches = batches if batches is not None else [batch(lines)]
    return dict(processor_events=events, settlement_lines=lines, settlement_batches=batches,
                bank_statement_lines=bank_lines, users=[
                    dict(user_id="USR-000", role="SYSTEM"), dict(user_id="USR-001", role="OPS_ANALYST"),
                    dict(user_id="USR-101", role="RISK_REVIEWER")])


def run(w, cfg=CFG):
    matches, exc, stats = run_engine(cfg, w)
    return matches, exc, stats


def types(exc):
    return sorted(x["exception_type"] for x in exc)


def bank_statuses(matches):
    return sorted(m["match_status"] for m in matches if m["match_level"] == "BANK_TO_BATCH")


def test_exact_payout_is_clean():
    matches, exc, _ = run(world([bank(1)]))
    assert exc == []
    assert bank_statuses(matches) == ["MATCHED"]


@pytest.mark.parametrize("diff,expected", [(0, []), (1, []), (2, []), (-2, []), (3, ["AMOUNT_MISMATCH"]), (-3, ["AMOUNT_MISMATCH"])])
def test_tolerance_boundary(diff, expected):
    _, exc, _ = run(world([bank(1, NET + diff)]))
    assert types(exc) == expected


def test_within_tolerance_is_flagged_as_tolerance_match():
    matches, _, _ = run(world([bank(1, NET + 2)]))
    assert bank_statuses(matches) == ["MATCHED_TOLERANCE"]


def test_tolerance_is_configurable():
    cfg = dict(CFG, tolerance_minor=5)
    _, exc, _ = run(world([bank(1, NET + 4)]), cfg)
    assert exc == []


def test_bank_paid_gross_so_difference_is_the_fee():
    matches, exc, _ = run(world([bank(1, NET + 300)]))
    assert types(exc) == ["FEE_DIFFERENCE"]
    assert bank_statuses(matches) == ["FEE_DIFFERENCE"]


def test_bank_wire_charge_is_also_a_fee_difference():
    _, exc, _ = run(world([bank(1, NET - CCY["USD"]["wire"])]))
    assert types(exc) == ["FEE_DIFFERENCE"]


def test_currency_mismatch():
    matches, exc, _ = run(world([bank(1, 8900, ccy="EUR")]))
    assert types(exc) == ["CURRENCY_MISMATCH"]
    assert bank_statuses(matches) == ["CURRENCY_MISMATCH"]
    bank_match = next(m for m in matches if m["match_level"] == "BANK_TO_BATCH")
    assert bank_match["group_diff_minor"] is None  # no meaningful difference across currencies


def test_partial_payout_when_a_tranche_never_arrives():
    _, exc, _ = run(world([bank(1, 4000, ref="PSP PAYOUT %s T1/2" % BATCH)]))
    assert types(exc) == ["PARTIAL_PAYOUT"]
    assert exc[0]["amount_at_risk_minor"] == NET - 4000


def test_all_tranches_adding_up_is_clean():
    ls = [bank(1, 4000, ref="PSP PAYOUT %s T1/2" % BATCH), bank(2, 5700, ref="PSP PAYOUT %s T2/2" % BATCH)]
    _, exc, _ = run(world(ls))
    assert exc == []


def test_missing_payout_is_exception_only_once_due():
    _, exc, _ = run(world([]))
    assert types(exc) == ["UNMATCHED_BATCH"]
    soon = batch([line(event(1))], payout="2026-10-20")  # window + grace has not run out yet
    _, exc, _ = run(world([], batches=[soon]))
    assert exc == []


def test_late_payout_inside_window_is_fine_outside_is_delayed():
    _, exc, _ = run(world([bank(1, value="2026-03-08")]))  # 3 days after expected
    assert exc == []
    _, exc, _ = run(world([bank(1, value="2026-03-09")]))  # 4 days after expected
    assert types(exc) == ["DELAYED_PAYOUT"]


def test_orphan_bank_line_is_an_exception():
    _, exc, _ = run(world([bank(1), bank(2, 12345, ref="INWARD REMITTANCE 998877")]))
    assert types(exc) == ["UNMATCHED_BANK_LINE"]
    assert exc[0]["bank_line_id"] == "BANK-2026-000002"


def test_unknown_batch_reference_is_orphan_not_a_match():
    _, exc, _ = run(world([bank(1), bank(2, 500, ref="PSP PAYOUT SET-2026-999999 T1/1")]))
    assert types(exc) == ["UNMATCHED_BANK_LINE"]


def test_same_delivery_twice_is_duplicate_event_and_redelivery_is_not():
    ev = event(1)
    twice = dict(ev, processor_event_id="EVT-2026-00000099", received_ts="2026-03-02T10:00:05Z")  # same delivery id
    _, exc, stats = run(world([bank(1)], events=[ev, twice], lines=[line(ev)]))
    assert types(exc) == ["DUPLICATE_EVENT"]
    redelivered = dict(ev, processor_event_id="EVT-2026-00000099", delivery_id="other-delivery",
                       received_ts="2026-03-02T11:00:00Z")
    _, exc, stats = run(world([bank(1)], events=[ev, redelivered], lines=[line(ev)]))
    assert exc == []
    assert stats["webhook_redeliveries_deduped"] == 1


def test_duplicate_events_never_double_count():
    """Ingesting an event twice must not change which settlement lines or batches are expected."""
    ev = event(1)
    twice = dict(ev, processor_event_id="EVT-2026-00000099", received_ts="2026-03-02T10:00:05Z")
    m1, _, _ = run(world([bank(1)]))
    m2, _, _ = run(world([bank(1)], events=[ev, twice], lines=[line(ev)]))
    assert [m["match_status"] for m in m1] == [m["match_status"] for m in m2]


def test_refund_stamped_before_its_capture():
    cap = event(1, at="2026-03-02T12:00:00Z", recv="2026-03-02T12:00:09Z")
    refund = dict(event(1, "REFUND_ISSUED", amount=2000, at="2026-03-02T11:00:00Z"), processor_event_id="EVT-2026-00000002",
                  delivery_id="dlvr", idempotency_key="IDEM-REF")
    ls = [line(cap), line(refund, 2)]
    _, exc, _ = run(world([bank(1, NET - 2000)], events=[cap, refund], lines=ls, batches=[batch(ls)]))
    assert types(exc) == ["REFUND_BEFORE_CAPTURE"]


def test_refund_after_capture_is_fine_and_carries_no_fee():
    cap = event(1)
    refund = dict(event(1, "REFUND_ISSUED", amount=2000, at="2026-03-02T15:00:00Z"), processor_event_id="EVT-2026-00000002",
                  delivery_id="dlvr", idempotency_key="IDEM-REF")
    ls = [line(cap), line(refund, 2)]
    b = batch(ls)
    assert b["net_payout_minor"] == 10000 - 2000 - 300
    _, exc, _ = run(world([bank(1, b["net_payout_minor"])], events=[cap, refund], lines=ls, batches=[b]))
    assert exc == []


def test_captured_event_with_no_settlement_line():
    old = event(2, at="2026-03-02T10:00:00Z")  # far older than the 8 day SLA
    _, exc, _ = run(world([bank(1)], events=[event(1), old]))
    assert types(exc) == ["UNMATCHED_EVENT"]
    assert exc[0]["processor_event_id"] == old["processor_event_id"]


def test_recent_unsettled_event_is_not_yet_an_exception():
    recent = event(2, at="2026-10-20T10:00:00Z")
    _, exc, stats = run(world([bank(1)], events=[event(1), recent]))
    assert exc == []
    assert stats["not_yet_due"] == 1


def test_authorisations_and_declines_never_need_settlement():
    declined = event(2, "DECLINED")
    auth = event(3, "AUTHORIZED")
    _, exc, _ = run(world([bank(1)], events=[event(1), declined, auth]))
    assert exc == []


def test_duplicate_settlement_line():
    ev = event(1)
    ls = [line(ev, 1), line(ev, 2)]
    _, exc, _ = run(world([bank(1, batch(ls)["net_payout_minor"])], lines=ls, batches=[batch(ls)]))
    assert types(exc) == ["DUPLICATE_SETTLEMENT_LINE"]
    assert exc[0]["settlement_line_id"] == ls[1]["settlement_line_id"]


def test_settlement_much_later_than_capture_is_delayed_settlement():
    ev = event(1, at="2026-02-10T10:00:00Z")  # batch cut-off 2026-03-03, 21 days later
    ls = [line(ev)]
    _, exc, _ = run(world([bank(1)], events=[ev], lines=ls, batches=[batch(ls)]))
    assert types(exc) == ["DELAYED_SETTLEMENT"]


def test_line_that_disagrees_with_its_event_is_an_exception():
    ev = event(1)
    ls = [line(ev, gross=9900)]
    _, exc, _ = run(world([bank(1, batch(ls)["net_payout_minor"])], lines=ls, batches=[batch(ls)]))
    assert types(exc) == ["AMOUNT_MISMATCH"]
    assert exc[0]["amount_at_risk_minor"] == 100


def test_every_exception_gets_a_valid_workflow_record():
    w = world([bank(1, NET + 300), bank(2, 50, ref="INWARD 1")], events=[event(1), event(2, at="2026-03-02T10:00:00Z")])
    _, exc, _ = run(w)
    exc_rows, res_rows, hist = simulate_resolutions(CFG, exc, w["users"])
    assert len(exc_rows) == len(exc) >= 3
    by_id = {x["exception_id"] for x in exc_rows} if exc_rows and "exception_id" in exc_rows[0] else set()
    for x in exc_rows:
        assert x["sla_due_at"] > x["detected_at"]
    for r in res_rows:
        etype = next(x["exception_type"] for x in exc_rows if x["exception_id"] == r["exception_id"])
        assert r["resolution_type"] in [name for name, _ in RES_MAP[etype]]
    assert by_id
    # history: first row of every exception is OPEN created by the system, nothing is overwritten
    firsts = [h for h in hist if h[2] is None]
    assert len(firsts) == len(exc_rows) and all(h[3] == "OPEN" for h in firsts)
