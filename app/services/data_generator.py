"""Stage 1: build the input tables (clean baseline first, then labelled faults) and the ground truth."""
import argparse
import math
import os
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from app.services.common import (CCY, RES_MAP, GT_EXPECTED, EDGE_CASES, PARAM_FILE, ts, pts, dstr, pdate, h, rng,
                                 div_half_even, bday_add, convert, allocate, canonical_events, make_cfg,
                                 cfg_to_params)
from app.services.exporter import write_tables, write_json, write_gt

INPUT_TABLES = ["users", "merchants", "payment_orders", "payment_attempts", "processor_events",
                "settlement_batches", "settlement_lines", "bank_statement_lines"]


# ---------------------------------------------------------------- ground truth
class GroundTruth:
    """Every injected fault (and every normal-but-odd record) is written here at the moment it is created."""

    def __init__(self):
        self.items = []

    def add(self, issue, entity_type, entity_id, payment_id="", batch_id=""):
        self.items.append(dict(issue_type=issue, entity_type=entity_type, entity_id=entity_id,
                               payment_id=payment_id, batch_id=batch_id))

    def rows(self):
        notes = {
            "WEBHOOK_REDELIVERY": "same idempotency key, different delivery id: dedupe silently",
            "SAME_EVENT_INGESTED_TWICE": "same delivery id seen twice: dedupe and raise an exception",
            "ROUNDING_AT_TOLERANCE": "difference equals the tolerance, still a match",
            "ROUNDING_OVER_TOLERANCE": "one step over the tolerance, must be an exception",
        }
        out = []
        for i, x in enumerate(sorted(self.items, key=lambda x: (x["entity_id"], x["issue_type"])), 1):
            exp = GT_EXPECTED[x["issue_type"]]
            options = "|".join(name for name, _ in RES_MAP.get(exp, []))
            decision = "raise exception " + exp if exp != "NONE" else "no exception, treat as normal"
            out.append(dict(gt_id="GT-%06d" % i, issue_type=x["issue_type"],
                            origin="EDGE_CASE" if x["issue_type"] in EDGE_CASES else "BASELINE_CONDITION",
                            entity_type=x["entity_type"], entity_id=x["entity_id"], payment_id=x["payment_id"],
                            batch_id=x["batch_id"], expected_exception_type=exp,
                            expected_resolution_options=options, expected_decision=decision,
                            note=notes.get(x["issue_type"], "")))
        return out


# ---------------------------------------------------------------- 1. users and merchants
def gen_users():
    rows = [dict(user_id="USR-000", display_name="Recon Engine", role="SYSTEM")]
    rows += [dict(user_id="USR-%03d" % i, display_name="Ops Analyst %02d" % i, role="OPS_ANALYST") for i in range(1, 7)]
    rows += [dict(user_id="USR-%03d" % (100 + i), display_name="Risk Reviewer %02d" % i, role="RISK_REVIEWER")
             for i in range(1, 3)]
    return rows


def gen_merchants(cfg):
    r = rng(cfg, "merchants")
    first = ["Blue", "Prime", "Urban", "Nova", "Swift", "Green", "Atlas", "Summit", "Cedar", "Orbit", "Lumen", "Harbor"]
    second = ["Retail", "Foods", "Travel", "Digital", "Apparel", "Books", "Fitness", "Health", "Home", "Gadgets"]
    ccys = list(CCY)
    weights = [CCY[c]["w"] for c in ccys]
    rows, meta = [], {}
    for i in range(1, cfg["n_merchants"] + 1):
        mid = "MER-%06d" % i
        ccy = r.choices(ccys, weights)[0]
        bps = r.randint(200, 350)
        onboarded = cfg["start"] - timedelta(days=r.randint(30, 400))
        rows.append(dict(merchant_id=mid, legal_name="%s %s Ltd" % (r.choice(first), r.choice(second)),
                         country=CCY[ccy]["country"], settlement_currency=ccy, fee_rate_bps=bps,
                         fixed_fee_minor=CCY[ccy]["fixed"], onboarded_date=dstr(onboarded)))
        # size = how big this merchant's tickets are, weight = how many orders it gets (a few big merchants)
        meta[mid] = dict(ccy=ccy, bps=bps, fixed=CCY[ccy]["fixed"], size=r.lognormvariate(0, 0.5),
                         weight=min(r.paretovariate(1.2), 200))
    return rows, meta


# ---------------------------------------------------------------- 2. orders
def gen_orders(cfg, meta):
    r = rng(cfg, "orders")
    ids = list(meta)
    cum, run = [], 0.0
    for m in ids:
        run += meta[m]["weight"]
        cum.append(run)
    picks = r.choices(range(len(ids)), cum_weights=cum, k=cfg["n_orders"])
    weekday_weight = [0.9, 0.95, 1.0, 1.0, 1.0, 0.75, 0.6]
    hour_weight = [1, 1, 1, 1, 1, 2, 3, 4, 6, 8, 9, 9, 9, 9, 9, 9, 8, 8, 8, 7, 6, 4, 3, 2]
    span = (cfg["end"] - cfg["start"]).days
    raw = []
    for mi in picks:
        mid = ids[mi]
        m = meta[mid]
        while True:  # fewer orders at the weekend
            day = cfg["start"] + timedelta(days=r.randint(0, span))
            if r.random() < weekday_weight[day.weekday()]:
                break
        when = datetime(day.year, day.month, day.day, r.choices(range(24), hour_weight)[0],
                        r.randint(0, 59), r.randint(0, 59))
        median = CCY[m["ccy"]]["median"]
        amount = int(round(median * m["size"] * math.exp(r.gauss(0, 0.9))))
        amount = min(max(amount, median // 20), median * 60)
        if amount >= 200 and r.random() < 0.5:
            amount = (amount // 100) * 100 + 99  # 12.99 style prices
        method = "UPI" if m["ccy"] == "INR" and r.random() < 0.4 else r.choices(["CARD_VISA", "CARD_MC", "WALLET"], [0.55, 0.35, 0.10])[0]
        raw.append((when, mid, m["ccy"], amount, method, r.randint(1, 400000)))
    raw.sort(key=lambda x: (x[0], x[1]))
    return [dict(payment_id="PAY-2026-%08d" % i, merchant_id=mid, customer_ref="CUS-%07d" % cust, order_ts=ts(when),
                 currency=ccy, amount_minor=amount, payment_method=method, status="FAILED",
                 captured_amount_minor=0, refunded_amount_minor=0)
            for i, (when, mid, ccy, amount, method, cust) in enumerate(raw, 1)]


# ---------------------------------------------------------------- 3. attempts and events
DECLINES = ["INSUFFICIENT_FUNDS", "DO_NOT_HONOR", "EXPIRED_CARD", "SUSPECTED_FRAUD", "ISSUER_UNAVAILABLE"]


def latency(r):
    """How long the webhook takes to reach us (mostly seconds, sometimes minutes)."""
    return timedelta(seconds=r.randint(30, 900) if r.random() < 0.02 else r.randint(1, 15))


def gen_flow(cfg, orders, gt):
    r = rng(cfg, "flow")
    n = len(orders)
    k_retry = cfg["n_attempts"] - n
    if not 0 <= k_retry <= n:
        sys.exit("attempts must be between orders and 2 x orders")
    # Rule, not a coin flip: the orders with the largest (noisy) ticket sizes are the ones declined first.
    score = sorted(((math.log(o["amount_minor"] / CCY[o["currency"]]["median"]) + r.gauss(0, 0.6), i)
                    for i, o in enumerate(orders)), reverse=True)
    declined_first = set(i for _, i in score[:k_retry])

    attempts, events = [], []
    seq = 0

    def event(pid, aid, etype, when, amount, ccy, k=1):
        nonlocal seq
        seq += 1
        e = dict(payment_id=pid, attempt_id=aid, event_type=etype, event_ts=when, received_ts=when + latency(r),
                 amount_minor=amount, currency=ccy, k=k, _order=seq, _copy=0, _label=None)
        events.append(e)
        return e

    captures, refunds = {}, defaultdict(list)
    refund_cutoff = datetime(cfg["end"].year, cfg["end"].month, cfg["end"].day) + timedelta(days=3)
    for i, o in enumerate(orders):
        pid, ccy, amount = o["payment_id"], o["currency"], o["amount_minor"]
        when = pts(o["order_ts"]) + timedelta(seconds=r.randint(1, 5))
        if i in declined_first:
            code = r.choice(DECLINES)
            second_ok = r.random() < (0.9 if code == "ISSUER_UNAVAILABLE" else 0.65)
            plan = [("DECLINED", code), ("AUTHORIZED", None) if second_ok else ("DECLINED", r.choice(DECLINES[:3]))]
        else:
            plan = [("AUTHORIZED", None)]
        for k, (status, code) in enumerate(plan, 1):
            if k > 1:
                when += timedelta(seconds=r.randint(60, 1800))
            aid = "ATT-%s-%02d" % (pid, k)
            attempts.append(dict(attempt_id=aid, payment_id=pid, attempt_no=k, attempt_ts=ts(when),
                                 amount_minor=amount, status=status, decline_code=code))
            if status == "DECLINED":
                event(pid, aid, "DECLINED", when + timedelta(seconds=1), amount, ccy)
                continue
            authorised = when + timedelta(seconds=1)
            event(pid, aid, "AUTHORIZED", authorised, amount, ccy)
            if r.random() < 0.7:
                captured = authorised + timedelta(seconds=r.randint(0, 120))
            else:
                captured = authorised + timedelta(seconds=r.randint(4 * 3600, 48 * 3600))
            captures[pid] = event(pid, aid, "CAPTURED", captured, amount, ccy)
            if r.random() < cfg["refund_rate"]:  # partial or full, sometimes two partial refunds
                left, when_refund = amount, captured
                parts = 2 if r.random() < 0.12 else 1
                for j in range(1, parts + 1):
                    when_refund += timedelta(seconds=int(r.uniform(0.5, 30) * 86400))
                    if when_refund > refund_cutoff:
                        break
                    full = j == 1 and parts == 1 and r.random() < 0.4
                    refund = left if full else min(max(int(round(left * r.uniform(0.1, 0.7))), 1), left)
                    left -= refund
                    refunds[pid].append(event(pid, aid, "REFUND_ISSUED", when_refund, refund, ccy, k=j))
                    if left == 0:
                        break

    # EDGE CASE: a refund shows up before its capture (the capture is stamped and delivered later)
    both = [p for p in captures if refunds.get(p)]
    for p in r.sample(both, min(cfg["inj"]["refund_before_capture"], len(both))):
        cap, ref = captures[p], refunds[p][0]
        cap["event_ts"] = ref["event_ts"] + timedelta(seconds=r.randint(60, 3600))
        cap["received_ts"] = cap["event_ts"] + latency(r)
        ref["_label"] = "REFUND_BEFORE_CAPTURE"

    # NORMAL NOISE: the processor retries a webhook (same webhook id, new delivery id)
    extra = []
    for e in events:
        if r.random() < cfg["redelivery_rate"]:
            copy = dict(e, _copy=1, _label="WEBHOOK_REDELIVERY", _delivery=1,
                        received_ts=e["received_ts"] + timedelta(seconds=r.randint(30, 3600)))
            extra.append(copy)
            e["_has_copy"] = True
    # EDGE CASE: our own pipeline wrote the identical delivery twice
    pool = [e for e in events if e["event_type"] in ("CAPTURED", "REFUND_ISSUED") and not e.get("_has_copy")]
    for e in r.sample(pool, min(cfg["inj"]["ingested_twice"], len(pool))):
        extra.append(dict(e, _copy=1, _label="SAME_EVENT_INGESTED_TWICE", _delivery=0))
    events.extend(extra)

    # final ids follow the order the events reached us
    events.sort(key=lambda e: (e["received_ts"], e["_order"], e["_copy"]))
    final = []
    for i, e in enumerate(events, 1):
        key = "%s:%s:%s:%d" % (e["payment_id"], e["attempt_id"], e["event_type"], e["k"])
        eid = "EVT-2026-%08d" % i
        final.append(dict(processor_event_id=eid, payment_id=e["payment_id"], attempt_id=e["attempt_id"],
                          event_type=e["event_type"], event_ts=ts(e["event_ts"]), received_ts=ts(e["received_ts"]),
                          amount_minor=e["amount_minor"], currency=e["currency"], webhook_event_id="wh_" + h(key, n=14),
                          delivery_id="dlv_" + h(key, "d%d" % e.get("_delivery", 0)),
                          idempotency_key="IDEM-" + h(key, n=16)))
        if e["_label"]:
            gt.add(e["_label"], "PROCESSOR_EVENT", eid, payment_id=e["payment_id"])
    return attempts, final


def derive_orders(orders, attempts, events):
    """Order and attempt status and totals come from the canonical events, never from a random draw."""
    canon = canonical_events(events)
    cap, ref = defaultdict(int), defaultdict(int)
    captured_attempts = set()
    for e in canon:
        if e["event_type"] == "CAPTURED":
            cap[e["payment_id"]] += e["amount_minor"]
            captured_attempts.add(e["attempt_id"])
        elif e["event_type"] == "REFUND_ISSUED":
            ref[e["payment_id"]] += e["amount_minor"]
    for a in attempts:
        if a["attempt_id"] in captured_attempts:
            a["status"] = "CAPTURED"
    for o in orders:
        c, f = cap[o["payment_id"]], ref[o["payment_id"]]
        o["captured_amount_minor"], o["refunded_amount_minor"] = c, f
        o["status"] = "FAILED" if c == 0 else "CAPTURED" if f == 0 else "PARTIALLY_REFUNDED" if f < c else "REFUNDED"


# ---------------------------------------------------------------- 4. settlement
BATCH_FAULTS = ["dup_settlement_line", "missing_payout", "partial_payout", "currency_mismatch", "fee_diff",
                "rounding_over", "rounding_at_tol", "delayed_payout"]


def plan_batch_faults(cfg, eligible):
    """Pick which batches get which bank-side fault. Only batches old enough to be judged at the as-of date."""
    r = rng(cfg, "batchplan")
    total = sum(cfg["inj"][k] for k in BATCH_FAULTS)
    if total > len(eligible):
        sys.exit("not enough batches for the requested faults, use more batches")
    chosen = r.sample(eligible, total)
    plan, pos = {}, 0
    for k in BATCH_FAULTS:
        plan[k] = chosen[pos:pos + cfg["inj"][k]]
        pos += cfg["inj"][k]
    return plan


def gen_settlement(cfg, meta, pay_merchant, events, gt):
    r = rng(cfg, "settle")
    canon = [e for e in canonical_events(events) if e["event_type"] in ("CAPTURED", "REFUND_ISSUED")]
    # the processor holds a few lines for 9-14 days (longer than the 8 day SLA)
    held = {e["processor_event_id"]: (r.randint(9, 14) if r.random() < cfg["delayed_rate"] else 0) for e in canon}
    # EDGE CASE: the processor quietly leaves a capture out of every batch
    candidates = [e for e in canon if e["event_type"] == "CAPTURED" and not held[e["processor_event_id"]]]
    dropped = r.sample(candidates, min(cfg["inj"]["silently_dropped"], len(candidates)))
    for e in dropped:
        gt.add("UNMATCHED_RECORD_SILENTLY_DROPPED", "PROCESSOR_EVENT", e["processor_event_id"], payment_id=e["payment_id"])
    dropped_ids = set(e["processor_event_id"] for e in dropped)
    live = [e for e in canon if e["processor_event_id"] not in dropped_ids]

    def release(e):  # when the processor can put the line into a batch
        return pts(e["event_ts"]) + timedelta(days=held[e["processor_event_id"]])

    # each currency gets batches in proportion to its volume; its events, in release order, are cut into
    # consecutive groups, one group per batch. The cut-off is the latest release time in the group.
    volume = defaultdict(int)
    for e in live:
        volume[e["currency"]] += 1
    batches_per_ccy = allocate(cfg["n_batches"], dict(volume))
    groups = []
    for ccy, n in batches_per_ccy.items():
        mine = sorted((e for e in live if e["currency"] == ccy), key=lambda e: (release(e), e["processor_event_id"]))
        if n > len(mine):
            sys.exit("%s has only %d lines for %d batches, use fewer batches" % (ccy, len(mine), n))
        previous = None
        for i in range(n):
            part = mine[i * len(mine) // n:(i + 1) * len(mine) // n]
            cutoff = (max(release(e) for e in part) + timedelta(seconds=59)).replace(second=0)
            if previous and cutoff <= previous:
                cutoff = previous + timedelta(minutes=1)
            previous = cutoff
            groups.append((cutoff, ccy, part))
    groups.sort(key=lambda g: (g[0], g[1]))

    old_enough = cfg["as_of"] - timedelta(days=25)
    plan = plan_batch_faults(cfg, [i for i, g in enumerate(groups) if g[0] <= old_enough])
    duplicate_in = set(plan["dup_settlement_line"])

    batches, lines = [], []
    for bi, (cutoff, ccy, part) in enumerate(groups):
        batch_id = "SET-2026-%06d" % (bi + 1)
        entries = []
        for e in sorted(part, key=lambda e: (e["event_ts"], e["processor_event_id"])):
            m = meta[pay_merchant[e["payment_id"]]]
            gross = e["amount_minor"]
            if e["event_type"] == "CAPTURED":
                fee = div_half_even(gross * m["bps"], 10000) + m["fixed"]
                entries.append((e, "CAPTURE", gross, fee, gross - fee))
            else:  # the processor keeps the fee on refunds, so refund lines carry no fee
                entries.append((e, "REFUND", gross, 0, -gross))
            lag_days = (cutoff - pts(e["event_ts"])).total_seconds() / 86400.0
            if lag_days > cfg["sla_days"]:
                gt.add("DELAYED_SETTLEMENT", "PROCESSOR_EVENT", e["processor_event_id"], payment_id=e["payment_id"], batch_id=batch_id)
        dup_position = None
        if bi in duplicate_in:  # EDGE CASE: the same capture is listed twice in one batch
            pick = r.choice([i for i, x in enumerate(entries) if x[1] == "CAPTURE"])
            entries.insert(pick + 1, entries[pick])
            dup_position = pick + 2
        cap = ref = fees = 0
        for n, (e, kind, gross, fee, net) in enumerate(entries, 1):
            line_id = "STL-%s-%03d" % (batch_id, n)
            lines.append(dict(settlement_line_id=line_id, batch_id=batch_id, payment_id=e["payment_id"],
                              processor_event_id=e["processor_event_id"], line_type=kind, currency=ccy,
                              gross_amount_minor=gross, fee_minor=fee, net_amount_minor=net))
            cap += gross if kind == "CAPTURE" else 0
            ref += gross if kind == "REFUND" else 0
            fees += fee
            if dup_position == n:
                gt.add("DUPLICATE_SETTLEMENT_LINE", "SETTLEMENT_LINE", line_id, payment_id=e["payment_id"], batch_id=batch_id)
        # batch totals are summed from the lines, never generated on their own
        batches.append(dict(batch_id=batch_id, currency=ccy, cutoff_ts=ts(cutoff),
                            expected_payout_date=dstr(bday_add(cutoff.date(), cfg["payout_lag_bdays"])),
                            line_count=len(entries), gross_captured_minor=cap, gross_refunded_minor=ref,
                            total_fees_minor=fees, net_payout_minor=cap - ref - fees))
    return batches, lines, plan


# ---------------------------------------------------------------- 5. bank lines
def gen_bank(cfg, batches, plan, gt):
    r = rng(cfg, "bank")
    tol = cfg["tolerance_minor"]
    missing, partial = set(plan["missing_payout"]), set(plan["partial_payout"])
    which = {k: set(plan[k]) for k in plan}
    paid = [i for i in range(len(batches)) if i not in missing]

    # How many tranches does each batch get? Spread the requested bank-line count over the paid batches;
    # a partial batch has one tranche that is allocated but never written to the statement.
    n_orphans = cfg["inj"]["orphans"]
    to_spread = cfg["n_bank"] - n_orphans + len(partial)
    if to_spread < 2 * len(paid):
        sys.exit("--bank-lines is too small: need at least two per paid batch")
    tranches = {i: to_spread // len(paid) + (1 if n < to_spread % len(paid) else 0) for n, i in enumerate(paid)}

    for i in sorted(missing):
        gt.add("MISSING_PAYOUT", "SETTLEMENT_BATCH", batches[i]["batch_id"], batch_id=batches[i]["batch_id"])
    raw = []
    for i in paid:
        b = batches[i]
        net, ccy, k = b["net_payout_minor"], b["currency"], tranches[i]
        if net <= k:
            sys.exit("batch %s is too small to split into %d tranches" % (b["batch_id"], k))
        weights = [r.uniform(0.5, 1.5) for _ in range(k)]
        parts = [max(1, int(net * w / sum(weights))) for w in weights[:-1]]
        parts.append(net - sum(parts))
        biggest = max(range(k), key=lambda j: parts[j])
        bank_ccy = [ccy] * k
        label = None
        if i in which["fee_diff"]:  # the bank paid gross (net + fees), or net minus a wire charge
            pays_gross = plan["fee_diff"].index(i) % 2 == 0  # alternate the two kinds of fee difference
            parts[biggest] += b["total_fees_minor"] if pays_gross else -CCY[ccy]["wire"]
            label = "BANK_AMOUNT_DIFFERS_BY_FEE"
        elif i in which["rounding_over"]:  # one step or more over the tolerance
            parts[biggest] += r.choice([-1, 1]) * (tol + 1 + r.randint(0, 5))
            label = "ROUNDING_OVER_TOLERANCE"
        elif i in which["rounding_at_tol"]:  # exactly at the tolerance: still a match
            parts[biggest] += r.choice([-1, 1]) * tol
            label = "ROUNDING_AT_TOLERANCE"
        elif i in which["currency_mismatch"]:  # the last tranche arrives in another currency
            other = r.choice([c for c in CCY if c != ccy])
            bank_ccy[-1] = other
            parts[-1] = convert(parts[-1], ccy, other)
            label = "CURRENCY_MISMATCH"
        elif i in partial:
            label = "PARTIAL_PAYOUT"
        late = i in which["delayed_payout"]
        if late:
            label = "DELAYED_PAYOUT"
        if label:
            gt.add(label, "SETTLEMENT_BATCH", b["batch_id"], batch_id=b["batch_id"])
        expected = pdate(b["expected_payout_date"])
        base = r.randint(4, 10) if late else r.choices([0, 1, 2, 3], [0.6, 0.25, 0.1, 0.05])[0]
        for j in range(k):
            if i in partial and j == k - 1:
                continue  # the last tranche never arrives
            offset = base if late else min(3, base + (0 if j == 0 else r.choice([0, 0, 1])))
            value = expected + timedelta(days=offset)
            booking = value + timedelta(days=1) if r.random() < 0.1 else value
            raw.append(dict(value=value, booking=booking, amount=parts[j], ccy=bank_ccy[j],
                            ref="PSP PAYOUT %s T%d/%d" % (b["batch_id"], j + 1, k), name="ACQUIRING PSP (SYNTHETIC)", label=None))

    # bank lines that no batch explains: unknown batch reference, unexplained credits, bank charges
    ccys = list(CCY)
    for n in range(n_orphans):
        ccy = r.choices(ccys, [CCY[c]["w"] for c in ccys])[0]
        value = cfg["start"] + timedelta(days=r.randint(20, max(21, (cfg["end"] - cfg["start"]).days - 10)))
        kind = n % 3
        if kind == 0:
            amount, ref, name = int(CCY[ccy]["median"] * r.uniform(2, 80)), "PSP PAYOUT SET-2026-9%05d T1/1" % r.randint(0, 99999), "ACQUIRING PSP (SYNTHETIC)"
        elif kind == 1:
            amount, ref, name = int(CCY[ccy]["median"] * r.uniform(2, 80)), "INWARD REMITTANCE REF %d" % r.randint(10000, 99999), "UNKNOWN REMITTER"
        else:
            amount, ref, name = -int(CCY[ccy]["wire"] * r.uniform(0.1, 1.5)) - 1, "BANK CHARGES %s" % value.strftime("%b %Y").upper(), "BANK"
        raw.append(dict(value=value, booking=value, amount=amount, ccy=ccy, ref=ref, name=name, label="ORPHAN_BANK_LINE"))

    raw.sort(key=lambda x: (x["value"], x["ccy"], x["ref"], x["amount"]))
    rows = []
    for n, x in enumerate(raw, 1):
        bank_id = "BANK-2026-%06d" % n
        rows.append(dict(bank_line_id=bank_id, value_date=dstr(x["value"]), booking_date=dstr(x["booking"]),
                         amount_minor=x["amount"], currency=x["ccy"], reference=x["ref"], counterparty_name=x["name"]))
        if x["label"]:
            gt.add(x["label"], "BANK_LINE", bank_id)
    return rows


# ---------------------------------------------------------------- orchestration
def generate(cfg):
    """Build every input table. Returns (tables, ground_truth_rows)."""
    gt = GroundTruth()
    users = gen_users()
    merchants, meta = gen_merchants(cfg)
    orders = gen_orders(cfg, meta)
    pay_merchant = {o["payment_id"]: o["merchant_id"] for o in orders}
    attempts, events = gen_flow(cfg, orders, gt)
    derive_orders(orders, attempts, events)
    batches, lines, plan = gen_settlement(cfg, meta, pay_merchant, events, gt)
    bank = gen_bank(cfg, batches, plan, gt)
    tables = dict(users=users, merchants=merchants, payment_orders=orders, payment_attempts=attempts,
                  processor_events=events, settlement_batches=batches, settlement_lines=lines,
                  bank_statement_lines=bank)
    return tables, gt.rows()


def generate_to(out_dir, cfg):
    """Stage 1 on disk: input tables, ground truth and the parameters later stages need."""
    os.makedirs(out_dir, exist_ok=True)
    tables, gt_rows = generate(cfg)
    write_tables(out_dir, INPUT_TABLES, tables)
    write_gt(out_dir, gt_rows)
    write_json(os.path.join(out_dir, PARAM_FILE), cfg_to_params(cfg))
    return tables, gt_rows


def add_scale_args(ap):
    ap.add_argument("--seed", type=int, default=20261022)
    ap.add_argument("--merchants", type=int, default=2000)
    ap.add_argument("--orders", type=int, default=50000)
    ap.add_argument("--attempts", type=int, default=55000)
    ap.add_argument("--batches", type=int, default=1000)
    ap.add_argument("--bank-lines", type=int, default=5000)
    ap.add_argument("--starter", action="store_true",
                    help="small dataset: 40 merchants, 1,000 orders, 1,100 attempts, 20 batches, 100 bank lines")


def apply_starter(args):
    if args.starter:
        args.merchants, args.orders, args.attempts, args.batches, args.bank_lines = 40, 1000, 1100, 20, 100
    return args


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage 1: generate the synthetic input tables and ground truth")
    add_scale_args(ap)
    ap.add_argument("--out", default="data/full")
    args = apply_starter(ap.parse_args(argv))
    tables, gt_rows = generate_to(args.out, make_cfg(args))
    print("wrote input tables to", args.out)
    print({t: len(rows) for t, rows in tables.items()}, "ground truth rows:", len(gt_rows))
    print("next: python run_workflow.py --data %s" % args.out)


if __name__ == "__main__":
    main()
