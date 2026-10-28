"""Stage 3: validation of the whole dataset and scoring of the engine against the ground truth."""
import re
import sqlite3
from collections import defaultdict, Counter
from datetime import timedelta

from app.services.common import EXC_TYPES, EXCEPTION_TRANSITIONS, RES_MAP, pts, div_half_even, canonical_events
from app.services.schema import TABLES, ddl
from app.services.reconciliation import REF_RE


def validate(cfg, T, gt_rows):
    checks = []

    def rec(name, ok, detail=""):
        checks.append(dict(check=name, status="PASS" if ok else "FAIL", detail=detail))

    # sqlite: PK uniqueness, enums/CHECKs, FK integrity
    con = sqlite3.connect(":memory:")
    con.executescript(ddl())
    try:
        for t, m in TABLES.items():
            cols = [f["name"] for f in m["fields"]]
            con.executemany("INSERT INTO %s (%s) VALUES (%s)" % (t, ",".join(cols), ",".join("?" * len(cols))),
                            [[row[c] for c in cols] for row in T[t]])
        rec("primary keys unique + enums + NOT NULL + CHECKs (sqlite load)", True, "all tables loaded")
    except sqlite3.IntegrityError as e:
        rec("primary keys unique + enums + NOT NULL + CHECKs (sqlite load)", False, str(e))
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    rec("foreign key integrity (PRAGMA foreign_key_check)", not bad, "%d violations" % len(bad))
    con.close()

    pat = {"payment_orders": ("payment_id", r"^PAY-2026-\d{8}$"), "settlement_batches": ("batch_id", r"^SET-2026-\d{6}$"),
           "bank_statement_lines": ("bank_line_id", r"^BANK-2026-\d{6}$"),
           "reconciliation_matches": ("match_id", r"^REC-2026-\d{6}$"),
           "payment_attempts": ("attempt_id", r"^ATT-PAY-2026-\d{8}-\d{2}$"),
           "settlement_lines": ("settlement_line_id", r"^STL-SET-2026-\d{6}-\d{3,}$")}
    bad = sum(1 for t, (c, p) in pat.items() for row in T[t] if not re.match(p, row[c]))
    rec("ID formats follow the naming convention", bad == 0, "%d bad ids" % bad)
    ok = all(a["attempt_id"] == "ATT-%s-%02d" % (a["payment_id"], a["attempt_no"]) for a in T["payment_attempts"])
    ok2 = all(l["settlement_line_id"].startswith("STL-" + l["batch_id"] + "-") for l in T["settlement_lines"])
    rec("child ids embed their parent id", ok and ok2)

    rec("row counts match requested volume",
        len(T["merchants"]) == cfg["n_merchants"] and len(T["payment_orders"]) == cfg["n_orders"]
        and len(T["payment_attempts"]) == cfg["n_attempts"] and len(T["settlement_batches"]) == cfg["n_batches"]
        and len(T["bank_statement_lines"]) == cfg["n_bank"],
        "merchants=%d orders=%d attempts=%d batches=%d bank=%d" % (
            len(T["merchants"]), len(T["payment_orders"]), len(T["payment_attempts"]),
            len(T["settlement_batches"]), len(T["bank_statement_lines"])))

    # dates
    gt_by_type = defaultdict(set)
    for g in gt_rows:
        gt_by_type[g["issue_type"]].add(g["entity_id"])
    ords = {o["payment_id"]: o for o in T["payment_orders"]}
    mer = {m["merchant_id"]: m for m in T["merchants"]}
    bad = sum(1 for a in T["payment_attempts"] if a["attempt_ts"] < ords[a["payment_id"]]["order_ts"])
    rec("attempt_ts >= order_ts", bad == 0, "%d violations" % bad)
    bad = sum(1 for e in T["processor_events"] if e["received_ts"] < e["event_ts"])
    rec("received_ts >= event_ts", bad == 0, "%d violations" % bad)
    bad = sum(1 for o in T["payment_orders"] if o["order_ts"][:10] < mer[o["merchant_id"]]["onboarded_date"])
    rec("orders are not earlier than the merchant's onboarded_date", bad == 0, "%d violations" % bad)
    bad = sum(1 for o in T["payment_orders"] if o["currency"] != mer[o["merchant_id"]]["settlement_currency"])
    rec("order currency equals merchant settlement currency", bad == 0)
    batches = {b["batch_id"]: b for b in T["settlement_batches"]}
    bad = sum(1 for b in batches.values() if not (b["cutoff_ts"][:10] <= b["expected_payout_date"]))
    rec("expected payout date >= cutoff date", bad == 0)

    # capture/refund ordering, except the labelled edge case
    canon = canonical_events(T["processor_events"])
    cap, bad = {}, 0
    for e in canon:
        if e["event_type"] == "CAPTURED":
            cap[e["payment_id"]] = e
    for e in canon:
        if e["event_type"] == "REFUND_ISSUED" and e["payment_id"] in cap:
            if e["event_ts"] < cap[e["payment_id"]]["event_ts"] and e["processor_event_id"] not in gt_by_type["REFUND_BEFORE_CAPTURE"]:
                bad += 1
    rec("refund never before capture unless labelled REFUND_BEFORE_CAPTURE", bad == 0, "%d unlabelled" % bad)
    bad = sum(1 for o in T["payment_orders"] if o["refunded_amount_minor"] > o["captured_amount_minor"])
    rec("refunded <= captured for every order", bad == 0)
    cap_sum, ref_sum, n_cap = defaultdict(int), defaultdict(int), Counter()
    for e in canon:
        if e["event_type"] == "CAPTURED":
            cap_sum[e["payment_id"]] += e["amount_minor"]
            n_cap[e["payment_id"]] += 1
        elif e["event_type"] == "REFUND_ISSUED":
            ref_sum[e["payment_id"]] += e["amount_minor"]
    bad = 0
    for o in T["payment_orders"]:
        c, f = cap_sum[o["payment_id"]], ref_sum[o["payment_id"]]
        status = "FAILED" if c == 0 else "CAPTURED" if f == 0 else "PARTIALLY_REFUNDED" if f < c else "REFUNDED"
        bad += (o["status"], o["captured_amount_minor"], o["refunded_amount_minor"]) != (status, c, f)
    rec("order status and totals are derived from the canonical events", bad == 0, "%d orders off" % bad)
    rec("at most one capture per order", max(n_cap.values(), default=0) <= 1)
    captured_attempts = set(e["attempt_id"] for e in canon if e["event_type"] == "CAPTURED")
    bad = sum(1 for a in T["payment_attempts"] if (a["status"] == "CAPTURED") != (a["attempt_id"] in captured_attempts))
    rec("attempt status matches the events (CAPTURED only if a capture event exists)", bad == 0, "%d attempts off" % bad)
    bad = sum(1 for a in T["payment_attempts"] if (a["status"] == "DECLINED") != (a["decline_code"] is not None))
    rec("decline_code is set exactly on declined attempts", bad == 0)

    # settlement arithmetic
    bad = 0
    for l in T["settlement_lines"]:
        if l["line_type"] == "CAPTURE":
            m = mer[ords[l["payment_id"]]["merchant_id"]]
            fee = div_half_even(l["gross_amount_minor"] * m["fee_rate_bps"], 10000) + m["fixed_fee_minor"]
            if l["fee_minor"] != fee or l["net_amount_minor"] != l["gross_amount_minor"] - fee:
                bad += 1
        elif l["fee_minor"] != 0 or l["net_amount_minor"] != -l["gross_amount_minor"]:
            bad += 1
    rec("fee and refund treatment consistent (fee formula, refunds carry no fee)", bad == 0, "%d lines off" % bad)
    tot = defaultdict(lambda: [0, 0, 0, 0, 0])
    for l in T["settlement_lines"]:
        t = tot[l["batch_id"]]
        t[0] += 1
        t[3] += l["fee_minor"]
        t[4] += l["net_amount_minor"]
        t[1 if l["line_type"] == "CAPTURE" else 2] += l["gross_amount_minor"]
    bad = sum(1 for b in batches.values() if [b["line_count"], b["gross_captured_minor"], b["gross_refunded_minor"],
                                              b["total_fees_minor"], b["net_payout_minor"]] != tot[b["batch_id"]]
              or b["net_payout_minor"] != b["gross_captured_minor"] - b["gross_refunded_minor"] - b["total_fees_minor"])
    rec("batch totals equal the sum of their lines", bad == 0, "%d batches off" % bad)
    evs = {e["processor_event_id"]: e for e in T["processor_events"]}
    bad = sum(1 for l in T["settlement_lines"] if evs[l["processor_event_id"]]["amount_minor"] != l["gross_amount_minor"]
              or evs[l["processor_event_id"]]["currency"] != l["currency"] or batches[l["batch_id"]]["currency"] != l["currency"])
    rec("settlement line amount/currency equals its processor event and batch", bad == 0)

    # duplicates
    pair = Counter((l["processor_event_id"], l["line_type"]) for l in T["settlement_lines"])
    extra = sum(v - 1 for v in pair.values() if v > 1)
    rec("duplicate settlement lines are exactly the labelled ones", extra == len(gt_by_type["DUPLICATE_SETTLEMENT_LINE"]),
        "%d duplicates, %d labelled" % (extra, len(gt_by_type["DUPLICATE_SETTLEMENT_LINE"])))
    canon_ids = set(e["processor_event_id"] for e in canon)
    rec("no settlement line points at a non-canonical event copy",
        all(l["processor_event_id"] in canon_ids for l in T["settlement_lines"]))

    # matches and exceptions
    bad = sum(1 for m in T["reconciliation_matches"] if m["match_status"] in ("MATCHED", "MATCHED_TOLERANCE", "MATCHED_LATE")
              and m["group_diff_minor"] is not None and abs(m["group_diff_minor"]) > cfg["tolerance_minor"])
    rec("matched amounts reconcile within tolerance (%d minor units)" % cfg["tolerance_minor"], bad == 0)
    exc_ent = set((x["exception_type"], x["entity_id"]) for x in T["exceptions"])
    line_events = set(l["processor_event_id"] for l in T["settlement_lines"])
    miss = 0
    for e in canon:
        if e["event_type"] in ("CAPTURED", "REFUND_ISSUED") and e["processor_event_id"] not in line_events \
                and pts(e["event_ts"]) + timedelta(days=cfg["sla_days"]) < cfg["as_of"] \
                and ("UNMATCHED_EVENT", e["processor_event_id"]) not in exc_ent:
            miss += 1
    rec("every settleable event without a line is an exception", miss == 0, "%d missing" % miss)
    paid = set(REF_RE.search(b["reference"]).group(0) for b in T["bank_statement_lines"] if REF_RE.search(b["reference"]))
    miss = sum(1 for b in batches if b not in paid and ("UNMATCHED_BATCH", b) not in exc_ent)
    rec("every batch without a bank payout is an exception", miss == 0, "%d missing" % miss)
    matched_bank = set(m["bank_line_id"] for m in T["reconciliation_matches"] if m["bank_line_id"])
    miss = sum(1 for b in T["bank_statement_lines"] if b["bank_line_id"] not in matched_bank
               and ("UNMATCHED_BANK_LINE", b["bank_line_id"]) not in exc_ent)
    rec("every unmatched bank line is an exception", miss == 0, "%d missing" % miss)
    bad_status = ("PARTIAL", "AMOUNT_MISMATCH", "FEE_DIFFERENCE", "CURRENCY_MISMATCH")
    by_batch = set(x["batch_id"] for x in T["exceptions"] if x["entity_type"] == "SETTLEMENT_BATCH")
    by_line = set(x["settlement_line_id"] for x in T["exceptions"] if x["settlement_line_id"])
    miss = sum(1 for m in T["reconciliation_matches"] if m["match_status"] in bad_status
               and ((m["match_level"] == "BANK_TO_BATCH" and m["batch_id"] not in by_batch)
                    or (m["match_level"] == "EVENT_TO_LINE" and m["settlement_line_id"] not in by_line)))
    rec("every partial or mismatched match row has an exception", miss == 0, "%d without" % miss)
    done = set(r["exception_id"] for r in T["resolutions"])
    bad = sum(1 for x in T["exceptions"] if (x["status"] in ("RESOLVED", "WRITTEN_OFF")) != (x["exception_id"] in done))
    rec("resolution exists exactly for closed exceptions", bad == 0)
    det = {x["exception_id"]: x["detected_at"] for x in T["exceptions"]}
    bad = sum(1 for r in T["resolutions"] if r["resolved_ts"] < det[r["exception_id"]])
    rec("resolved_ts >= detected_at", bad == 0)

    # lifecycle: every exception has a history that follows the allowed moves, in time order, ending at its status
    chain = defaultdict(list)
    for row in T["status_history"]:
        chain[row["entity_id"]].append(row)
    bad = 0
    for rows in chain.values():
        rows.sort(key=lambda z: z["history_id"])
        prev, prev_at = None, ""
        for z in rows:
            if z["from_status"] != prev or z["to_status"] not in EXCEPTION_TRANSITIONS.get(prev, []) or z["changed_at"] < prev_at:
                bad += 1
            prev, prev_at = z["to_status"], z["changed_at"]
    for x in T["exceptions"]:
        rows = chain.get(x["exception_id"])
        if not rows or rows[0]["from_status"] is not None or rows[-1]["to_status"] != x["status"]:
            bad += 1
    rec("exception history starts at creation, follows the allowed moves in time order and ends at the current status",
        bad == 0, "%d violations" % bad)
    allowed = {x["exception_id"]: x["exception_type"] for x in T["exceptions"]}
    bad = sum(1 for r in T["resolutions"] if r["resolution_type"] not in [name for name, _ in RES_MAP[allowed[r["exception_id"]]]])
    rec("every resolution type is allowed for its exception type", bad == 0, "%d not allowed" % bad)

    rec("ground truth is not referenced by any input table column",
        not any("gt_" in f["name"] or "issue_type" in f["name"] for m in TABLES.values() for f in m["fields"]))
    return checks


def evaluate(T, gt_rows):
    exc = [(x["exception_type"], x["entity_id"]) for x in T["exceptions"]]
    exc_set = set(exc)
    expected = set((g["expected_exception_type"], g["entity_id"]) for g in gt_rows if g["expected_exception_type"] != "NONE")
    none_rows = [(g["issue_type"], g["entity_id"]) for g in gt_rows if g["expected_exception_type"] == "NONE"]
    per = {}
    for t in EXC_TYPES:
        exp_t = set(e for e in expected if e[0] == t)
        got_t = set(e for e in exc_set if e[0] == t)
        tp = len(exp_t & got_t)
        fn = len(exp_t - got_t)
        fp = len(got_t - exp_t)
        per[t] = dict(expected=len(exp_t), detected=len(got_t), true_pos=tp, false_neg=fn, false_pos=fp,
                      precision=round(tp / (tp + fp), 4) if tp + fp else None,
                      recall=round(tp / (tp + fn), 4) if tp + fn else None)
    tp = len(expected & exc_set)
    fp = len(exc_set - expected)
    fn = len(expected - exc_set)
    ents = set(e[1] for e in exc_set)
    fp_on_normal = sum(1 for _, eid in none_rows if eid in ents)
    # money
    by_lvl = Counter((m["match_level"], m["match_status"]) for m in T["reconciliation_matches"])
    lag = defaultdict(list)
    det = {x["exception_id"]: (pts(x["detected_at"]), x["exception_type"]) for x in T["exceptions"]}
    for r in T["resolutions"]:
        d, t = det[r["exception_id"]]
        lag[t].append((pts(r["resolved_ts"]) - d).total_seconds() / 3600.0)
    mean_h = {t: round(sum(v) / len(v), 1) for t, v in sorted(lag.items())}
    status = Counter(x["status"] for x in T["exceptions"])
    at_risk = defaultdict(int)
    for x in T["exceptions"]:
        at_risk[x["currency"]] += x["amount_at_risk_minor"]
    batches = len(T["settlement_batches"])
    paid_ok = set(m["batch_id"] for m in T["reconciliation_matches"]
                  if m["batch_id"] and m["match_status"] in ("MATCHED", "MATCHED_TOLERANCE"))
    return dict(
        detection=dict(overall_expected=len(expected), true_pos=tp, false_neg=fn, false_pos=fp,
                       precision=round(tp / (tp + fp), 4) if tp + fp else None,
                       recall=round(tp / (tp + fn), 4) if tp + fn else None,
                       exceptions_raised_on_labelled_normal_records=fp_on_normal, per_type=per),
        matching=dict(match_rows_by_level_and_status={"%s/%s" % k: v for k, v in sorted(by_lvl.items())}),
        workflow=dict(exceptions_by_status=dict(status), mean_hours_to_resolve_by_type=mean_h,
                      exceptions_by_type=dict(Counter(x["exception_type"] for x in T["exceptions"])),
                      amount_at_risk_minor_by_currency=dict(at_risk)),
        batches_fully_matched_to_bank=len(paid_ok), batches_total=batches)
