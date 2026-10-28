"""Stage 2: the reconciliation engine. It reads the input tables only, never the ground truth."""
import re
from collections import defaultdict, Counter
from datetime import datetime, timedelta

from app.services.common import CCY, RES_MAP, RISK_TYPES, SEVERITY, pts, ts, pdate, nightly, rng, number_history

# ---------------------------------------------------------------- reconciliation engine
REF_RE = re.compile(r"SET-\d{4}-\d{6}")
TR_RE = re.compile(r"T(\d+)/(\d+)")


def run_engine(cfg, T):
    """Matches and exceptions are worked out from the input tables only."""
    tol, sla, as_of = cfg["tolerance_minor"], cfg["sla_days"], cfg["as_of"]
    win = cfg["window_after_days"]
    batches = {b["batch_id"]: b for b in T["settlement_batches"]}

    def batch_ready(b):
        return pts(b["cutoff_ts"]) + timedelta(minutes=90)  # the settlement file is produced after the cut-off

    events = sorted(T["processor_events"], key=lambda e: (e["received_ts"], e["processor_event_id"]))
    stats = Counter()
    exc, matches = [], []

    def add_exc(etype, entity_type, entity_id, trigger, amount, ccy, **kw):
        exc.append(dict(exception_type=etype, entity_type=entity_type, entity_id=entity_id,
                        _trigger=trigger, amount_at_risk_minor=abs(amount), currency=ccy,
                        payment_id=kw.get("payment_id"), batch_id=kw.get("batch_id"),
                        bank_line_id=kw.get("bank_line_id"), processor_event_id=kw.get("event_id"),
                        settlement_line_id=kw.get("line_id"), _match_key=kw.get("match_key"),
                        rule_id=kw.get("rule", "R-" + etype), description=kw.get("desc", "")))

    # --- duplicates: group by idempotency key, first delivery is canonical
    groups = {}
    for e in events:
        groups.setdefault(e["idempotency_key"], []).append(e)
    canon = []
    for rows in groups.values():
        canon.append(rows[0])
        seen = {rows[0]["delivery_id"]}
        for row in rows[1:]:
            if row["delivery_id"] in seen:
                add_exc("DUPLICATE_EVENT", "PROCESSOR_EVENT", row["processor_event_id"], pts(row["received_ts"]),
                        row["amount_minor"], row["currency"], payment_id=row["payment_id"], event_id=row["processor_event_id"],
                        desc="same delivery ingested twice")
                stats["pipeline_duplicates"] += 1
            else:
                seen.add(row["delivery_id"])
                stats["webhook_redeliveries_deduped"] += 1
    canon.sort(key=lambda e: e["processor_event_id"])

    # --- lifecycle: a refund must not be stamped before its capture
    cap_by_pay, ref_by_pay = {}, defaultdict(list)
    for e in canon:
        if e["event_type"] == "CAPTURED":
            cap_by_pay[e["payment_id"]] = e
        elif e["event_type"] == "REFUND_ISSUED":
            ref_by_pay[e["payment_id"]].append(e)
    for pid in sorted(ref_by_pay):
        c = cap_by_pay.get(pid)
        if not c:
            continue
        bad = [x for x in ref_by_pay[pid] if x["event_ts"] < c["event_ts"]]
        if bad:
            x = min(bad, key=lambda z: z["event_ts"])
            add_exc("REFUND_BEFORE_CAPTURE", "PROCESSOR_EVENT", x["processor_event_id"],
                    max(pts(x["received_ts"]), pts(c["received_ts"])), x["amount_minor"], x["currency"],
                    payment_id=pid, event_id=x["processor_event_id"], desc="refund stamped before capture")

    # --- event -> settlement line
    lines_by_event = defaultdict(list)
    for l in sorted(T["settlement_lines"], key=lambda l: l["settlement_line_id"]):
        lines_by_event[l["processor_event_id"]].append(l)
    for e in canon:
        if e["event_type"] not in ("CAPTURED", "REFUND_ISSUED"):
            continue
        ls = lines_by_event.get(e["processor_event_id"])
        et = pts(e["event_ts"])
        if not ls:
            deadline = et + timedelta(days=sla)
            if deadline < as_of:
                add_exc("UNMATCHED_EVENT", "PROCESSOR_EVENT", e["processor_event_id"], deadline, e["amount_minor"],
                        e["currency"], payment_id=e["payment_id"], event_id=e["processor_event_id"],
                        desc="no settlement line within SLA")
            else:
                stats["not_yet_due"] += 1
            continue
        l = ls[0]
        b = batches[l["batch_id"]]
        cutoff = pts(b["cutoff_ts"])
        lag = (cutoff - et).total_seconds() / 86400.0
        same = l["gross_amount_minor"] == e["amount_minor"] and l["currency"] == e["currency"]
        status = "MATCHED" if same else "AMOUNT_MISMATCH"
        if same and lag > sla:
            status = "MATCHED_LATE"
        key = ("E", e["processor_event_id"])
        matches.append(dict(_key=key, match_level="EVENT_TO_LINE", bank_line_id=None, batch_id=None,
                            processor_event_id=e["processor_event_id"], settlement_line_id=l["settlement_line_id"],
                            currency=e["currency"], matched_amount_minor=l["gross_amount_minor"],
                            group_expected_amount_minor=e["amount_minor"],
                            group_diff_minor=l["gross_amount_minor"] - e["amount_minor"],
                            date_delta_days=(cutoff.date() - et.date()).days, rule_id="M1-EVENT-ID-AMOUNT-CCY",
                            match_status=status,
                            matched_at=nightly(max(pts(e["received_ts"]), batch_ready(b)))))
        if status == "AMOUNT_MISMATCH":
            add_exc("AMOUNT_MISMATCH", "SETTLEMENT_LINE", l["settlement_line_id"], batch_ready(b),
                    l["gross_amount_minor"] - e["amount_minor"], e["currency"], payment_id=e["payment_id"],
                    batch_id=b["batch_id"], event_id=e["processor_event_id"], line_id=l["settlement_line_id"],
                    match_key=key, rule="R-EVENT-LINE-AMOUNT", desc="settlement line differs from the processor event")
        if status == "MATCHED_LATE":
            add_exc("DELAYED_SETTLEMENT", "PROCESSOR_EVENT", e["processor_event_id"], batch_ready(b),
                    l["net_amount_minor"], e["currency"], payment_id=e["payment_id"], batch_id=b["batch_id"],
                    event_id=e["processor_event_id"], line_id=l["settlement_line_id"], match_key=key,
                    desc="settled %.1f days after capture" % lag)
        for extra in ls[1:]:
            add_exc("DUPLICATE_SETTLEMENT_LINE", "SETTLEMENT_LINE", extra["settlement_line_id"],
                    batch_ready(b), extra["net_amount_minor"], e["currency"], payment_id=e["payment_id"],
                    batch_id=b["batch_id"], event_id=e["processor_event_id"], line_id=extra["settlement_line_id"],
                    match_key=key, desc="event appears on more than one line")

    # --- bank line -> batch
    by_batch, orphans = defaultdict(list), []
    for bl in sorted(T["bank_statement_lines"], key=lambda x: x["bank_line_id"]):
        m = REF_RE.search(bl["reference"])
        if m and m.group(0) in batches:
            by_batch[m.group(0)].append(bl)
        else:
            orphans.append(bl)
    for bid in sorted(batches):
        b = batches[bid]
        expected = pdate(b["expected_payout_date"])
        bl = by_batch.get(bid)
        if not bl:
            due = datetime(expected.year, expected.month, expected.day) + timedelta(days=win + cfg["grace_days"])
            if due < as_of:
                add_exc("UNMATCHED_BATCH", "SETTLEMENT_BATCH", bid, due, b["net_payout_minor"], b["currency"],
                        batch_id=bid, desc="no bank payout found")
            continue
        den = max(int(TR_RE.search(x["reference"]).group(2)) for x in bl)
        net = b["net_payout_minor"]
        total = sum(x["amount_minor"] for x in bl)
        bad_ccy = [x for x in bl if x["currency"] != b["currency"]]
        last = max(pdate(x["value_date"]) for x in bl)
        trigger = datetime(last.year, last.month, last.day, 20, 0, 0)
        diff = total - net
        etype = None
        if bad_ccy:
            status, etype, amt, diff_out = "CURRENCY_MISMATCH", "CURRENCY_MISMATCH", net, None
        elif len(bl) < den:
            status, etype, amt, diff_out = "PARTIAL", "PARTIAL_PAYOUT", net - total, diff
        elif abs(diff) <= tol:
            status, amt, diff_out = ("MATCHED" if diff == 0 else "MATCHED_TOLERANCE"), 0, diff
        else:
            diff_out, amt = diff, abs(diff)
            fee_like = abs(diff - b["total_fees_minor"]) <= tol or abs(diff + CCY[b["currency"]]["wire"]) <= tol
            status, etype = ("FEE_DIFFERENCE", "FEE_DIFFERENCE") if fee_like else ("AMOUNT_MISMATCH", "AMOUNT_MISMATCH")
        is_late = any((pdate(x["value_date"]) - expected).days > win for x in bl)
        if is_late and etype is None:
            status = "MATCHED_LATE"
        first_key = None
        for x in bl:
            key = ("B", x["bank_line_id"], bid)
            first_key = first_key or key
            matches.append(dict(_key=key, match_level="BANK_TO_BATCH", bank_line_id=x["bank_line_id"], batch_id=bid,
                                processor_event_id=None, settlement_line_id=None, currency=x["currency"],
                                matched_amount_minor=x["amount_minor"], group_expected_amount_minor=net,
                                group_diff_minor=diff_out, date_delta_days=(pdate(x["value_date"]) - expected).days,
                                rule_id="M2-REF-AMOUNT-CCY-DATEWINDOW", match_status=status,
                                matched_at=nightly(datetime(pdate(x["value_date"]).year, pdate(x["value_date"]).month,
                                                            pdate(x["value_date"]).day, 20, 0, 0))))
        if etype:
            add_exc(etype, "SETTLEMENT_BATCH", bid, trigger, amt, b["currency"], batch_id=bid,
                    bank_line_id=bl[-1]["bank_line_id"], match_key=first_key, desc=etype.lower().replace("_", " "))
        if is_late and etype is None:
            add_exc("DELAYED_PAYOUT", "SETTLEMENT_BATCH", bid, trigger, net, b["currency"], batch_id=bid,
                    bank_line_id=bl[-1]["bank_line_id"], match_key=first_key,
                    desc="value date outside the %d day window" % win)
    for x in orphans:
        vd = pdate(x["value_date"])
        add_exc("UNMATCHED_BANK_LINE", "BANK_LINE", x["bank_line_id"], datetime(vd.year, vd.month, vd.day, 20, 0, 0),
                x["amount_minor"], x["currency"], bank_line_id=x["bank_line_id"], desc="no batch reference")

    # ids, in a stable order
    matches.sort(key=lambda m: (m["matched_at"], m["match_level"], m["_key"]))
    key_to_id = {}
    for i, m in enumerate(matches, 1):
        m["match_id"] = "REC-2026-%06d" % i
        key_to_id[m["_key"]] = m["match_id"]
        m["matched_at"] = ts(m["matched_at"])
    for x in exc:
        x["detected_at"] = nightly(x["_trigger"])
        x["match_id"] = key_to_id.get(x["_match_key"])
    exc.sort(key=lambda x: (x["detected_at"], x["exception_type"], x["entity_id"]))
    for i, x in enumerate(exc, 1):
        x["exception_id"] = "EXC-2026-%06d" % i
    return matches, exc, stats


# ---------------------------------------------------------------- analyst workflow (a seeded simulation)
def simulate_resolutions(cfg, exc, users):
    r = rng(cfg, "workflow")
    as_of = cfg["as_of"]
    by_role = defaultdict(list)
    for u in users:
        by_role[u["role"]].append(u["user_id"])
    sla_days = {"HIGH": 2, "MEDIUM": 5, "LOW": 10}
    median_h = {"HIGH": 96, "MEDIUM": 48, "LOW": 24}
    exc_rows, res_rows, hist = [], [], []
    for x in exc:
        t = x["exception_type"]
        sev_name = SEVERITY[t]
        opts = RES_MAP[t]
        rtype = r.choices([o for o, _ in opts], [w for _, w in opts])[0]
        risk = t in RISK_TYPES or sev_name == "HIGH" or rtype == "WRITTEN_OFF"
        det = x["detected_at"]
        if rtype == "AUTO_DEDUPED":
            hours = r.uniform(0.01, 0.2)
        else:
            hours = median_h[sev_name] * r.lognormvariate(0, 0.8) + (24 if risk else 0)
            if r.random() < 0.03:
                hours *= 8  # the occasional one that sits around
        done = det + timedelta(seconds=int(hours * 3600))
        analyst = r.choice(by_role["OPS_ANALYST"])
        steps = [(None, "OPEN", det, "USR-000")]
        if rtype == "AUTO_DEDUPED":
            final_by = "USR-000"
            steps.append(("OPEN", "RESOLVED", done, final_by))
            role = "SYSTEM"
        else:
            t_rev = det + timedelta(seconds=int(hours * 3600 * r.uniform(0.05, 0.3)))
            steps.append(("OPEN", "IN_REVIEW", t_rev, analyst))
            if risk:
                t_esc = t_rev + timedelta(seconds=int(hours * 3600 * r.uniform(0.1, 0.3)))
                steps.append(("IN_REVIEW", "ESCALATED", t_esc, analyst))
                final_by = r.choice(by_role["RISK_REVIEWER"])
                role = "RISK_REVIEWER"
            else:
                final_by = analyst
                role = "OPS_ANALYST"
            last_from = steps[-1][1]
            steps.append((last_from, "WRITTEN_OFF" if rtype == "WRITTEN_OFF" else "RESOLVED", done, final_by))
        steps = [s for s in steps if s[2] <= as_of]
        status = steps[-1][1]
        closed = status in ("RESOLVED", "WRITTEN_OFF")
        for fr, to, when, who in steps:
            hist.append(("EXCEPTION", x["exception_id"], fr, to, when, who))
        money_types = ("PROCESSOR_CLAIM_RECOVERED", "WRITTEN_OFF", "CLAWBACK_REQUESTED",
                       "ADJUSTMENT_BOOKED", "ROUNDING_ADJUSTMENT_BOOKED")
        if closed:
            res_rows.append(dict(
                resolution_id="", exception_id=x["exception_id"], resolution_type=rtype, resolved_by=final_by,
                resolved_ts=ts(done), adjustment_amount_minor=x["amount_at_risk_minor"] if rtype in money_types else 0,
                currency=x["currency"], notes="%s -> %s" % (t, rtype)))
        exc_rows.append(dict(
            exception_id=x["exception_id"], exception_type=t, severity=sev_name, status=status,
            entity_type=x["entity_type"], entity_id=x["entity_id"], payment_id=x["payment_id"], batch_id=x["batch_id"],
            bank_line_id=x["bank_line_id"], processor_event_id=x["processor_event_id"],
            settlement_line_id=x["settlement_line_id"], match_id=x["match_id"],
            amount_at_risk_minor=x["amount_at_risk_minor"], currency=x["currency"], detected_at=ts(det),
            sla_due_at=ts(det + timedelta(days=sla_days[sev_name])), assigned_role=role,
            rule_id=x["rule_id"], description=x["description"]))
    res_rows.sort(key=lambda z: (z["resolved_ts"], z["exception_id"]))
    for i, z in enumerate(res_rows, 1):
        z["resolution_id"] = "RES-2026-%06d" % i
    return exc_rows, res_rows, hist


def reconcile(cfg, T):
    """Run the whole second stage on the input tables. Returns the four output tables and the engine counters."""
    matches, exc, stats = run_engine(cfg, T)
    exc_rows, res_rows, exc_hist = simulate_resolutions(cfg, exc, T["users"])
    for m in matches:
        m.pop("_key", None)
    history = number_history(exc_hist)
    return dict(reconciliation_matches=matches, exceptions=exc_rows, resolutions=res_rows, status_history=history), stats
