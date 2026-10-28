"""Constants, small helpers and run parameters shared by every stage."""
import hashlib
import random
from datetime import date, datetime, timedelta

VERSION = "1.0.0"
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
PARAM_FILE = "params.json"


def ts(d):
    return d.strftime(TS_FMT)


def pts(s):
    return datetime.strptime(s, TS_FMT)


def dstr(d):
    return d.strftime("%Y-%m-%d")


def pdate(s):
    return datetime.strptime(s, "%Y-%m-%d").date()


def h(*parts, n=12):
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:n]


# ---------------------------------------------------------------- reference data
# median = typical ticket, fixed = fixed fee per capture, wire = bank wire charge (all minor units),
# fx = value of one major unit in USD, w = share of merchants
CCY = {
    "USD": dict(country="US", median=4500, fixed=30, wire=1500, fx=1.00, w=0.35),
    "EUR": dict(country="DE", median=4000, fixed=25, wire=1500, fx=1.08, w=0.25),
    "GBP": dict(country="GB", median=3500, fixed=20, wire=1200, fx=1.27, w=0.20),
    "INR": dict(country="IN", median=180000, fixed=300, wire=50000, fx=0.012, w=0.20),
}
EVENT_TYPES = ["AUTHORIZED", "DECLINED", "CAPTURED", "REFUND_ISSUED"]
ORDER_STATUS = ["FAILED", "CAPTURED", "PARTIALLY_REFUNDED", "REFUNDED"]
ATTEMPT_STATUS = ["DECLINED", "CAPTURED"]
MATCH_LEVELS = ["BANK_TO_BATCH", "EVENT_TO_LINE"]
MATCH_STATUS = ["MATCHED", "MATCHED_TOLERANCE", "MATCHED_LATE", "PARTIAL",
                "AMOUNT_MISMATCH", "FEE_DIFFERENCE", "CURRENCY_MISMATCH"]
EXC_TYPES = ["DUPLICATE_EVENT", "REFUND_BEFORE_CAPTURE", "UNMATCHED_EVENT", "DUPLICATE_SETTLEMENT_LINE",
             "DELAYED_SETTLEMENT", "UNMATCHED_BATCH", "PARTIAL_PAYOUT", "CURRENCY_MISMATCH", "FEE_DIFFERENCE",
             "AMOUNT_MISMATCH", "DELAYED_PAYOUT", "UNMATCHED_BANK_LINE"]
EXC_STATUS = ["OPEN", "IN_REVIEW", "ESCALATED", "RESOLVED", "WRITTEN_OFF"]
RES_TYPES = ["AUTO_DEDUPED", "RESEQUENCED", "MANUAL_MATCH", "PROCESSOR_CLAIM_RECOVERED", "WRITTEN_OFF",
             "CLAWBACK_REQUESTED", "ADJUSTMENT_BOOKED", "LATE_SETTLEMENT_CONFIRMED", "FX_CONVERSION_CONFIRMED",
             "ROUNDING_ADJUSTMENT_BOOKED", "LATE_PAYOUT_CONFIRMED", "CLASSIFIED_NON_PSP", "RETURNED_TO_SENDER"]

# allowed exception lifecycle moves (None = the exception does not exist yet)
EXCEPTION_TRANSITIONS = {None: ["OPEN"], "OPEN": ["IN_REVIEW", "RESOLVED"],
                         "IN_REVIEW": ["ESCALATED", "RESOLVED", "WRITTEN_OFF"],
                         "ESCALATED": ["RESOLVED", "WRITTEN_OFF"]}

# how an analyst can close each exception type (with how often), and how serious each type is
RES_MAP = {
    "DUPLICATE_EVENT": [("AUTO_DEDUPED", 1.0)],
    "REFUND_BEFORE_CAPTURE": [("RESEQUENCED", 0.9), ("MANUAL_MATCH", 0.1)],
    "UNMATCHED_EVENT": [("PROCESSOR_CLAIM_RECOVERED", 0.7), ("WRITTEN_OFF", 0.15), ("MANUAL_MATCH", 0.15)],
    "DUPLICATE_SETTLEMENT_LINE": [("CLAWBACK_REQUESTED", 0.7), ("ADJUSTMENT_BOOKED", 0.3)],
    "DELAYED_SETTLEMENT": [("LATE_SETTLEMENT_CONFIRMED", 1.0)],
    "UNMATCHED_BATCH": [("PROCESSOR_CLAIM_RECOVERED", 0.8), ("WRITTEN_OFF", 0.2)],
    "PARTIAL_PAYOUT": [("PROCESSOR_CLAIM_RECOVERED", 0.85), ("WRITTEN_OFF", 0.15)],
    "CURRENCY_MISMATCH": [("FX_CONVERSION_CONFIRMED", 0.8), ("MANUAL_MATCH", 0.2)],
    "FEE_DIFFERENCE": [("ADJUSTMENT_BOOKED", 0.8), ("PROCESSOR_CLAIM_RECOVERED", 0.2)],
    "AMOUNT_MISMATCH": [("ROUNDING_ADJUSTMENT_BOOKED", 0.7), ("MANUAL_MATCH", 0.2), ("PROCESSOR_CLAIM_RECOVERED", 0.1)],
    "DELAYED_PAYOUT": [("LATE_PAYOUT_CONFIRMED", 1.0)],
    "UNMATCHED_BANK_LINE": [("CLASSIFIED_NON_PSP", 0.6), ("RETURNED_TO_SENDER", 0.2), ("MANUAL_MATCH", 0.2)],
}
SEVERITY = {
    "UNMATCHED_BATCH": "HIGH", "PARTIAL_PAYOUT": "HIGH", "CURRENCY_MISMATCH": "HIGH",
    "FEE_DIFFERENCE": "MEDIUM", "AMOUNT_MISMATCH": "MEDIUM", "DUPLICATE_SETTLEMENT_LINE": "MEDIUM",
    "UNMATCHED_EVENT": "MEDIUM", "UNMATCHED_BANK_LINE": "MEDIUM", "DELAYED_PAYOUT": "MEDIUM",
    "DUPLICATE_EVENT": "LOW", "REFUND_BEFORE_CAPTURE": "LOW", "DELAYED_SETTLEMENT": "LOW",
}

# what the engine should raise for each ground-truth label (NONE = it is normal, no exception)
GT_EXPECTED = {
    "DUPLICATE_SETTLEMENT_LINE": "DUPLICATE_SETTLEMENT_LINE",
    "BANK_AMOUNT_DIFFERS_BY_FEE": "FEE_DIFFERENCE",
    "REFUND_BEFORE_CAPTURE": "REFUND_BEFORE_CAPTURE",
    "UNMATCHED_RECORD_SILENTLY_DROPPED": "UNMATCHED_EVENT",
    "CURRENCY_MISMATCH": "CURRENCY_MISMATCH",
    "SAME_EVENT_INGESTED_TWICE": "DUPLICATE_EVENT",
    "PARTIAL_PAYOUT": "PARTIAL_PAYOUT",
    "MISSING_PAYOUT": "UNMATCHED_BATCH",
    "ROUNDING_OVER_TOLERANCE": "AMOUNT_MISMATCH",
    "ROUNDING_AT_TOLERANCE": "NONE",
    "DELAYED_PAYOUT": "DELAYED_PAYOUT",
    "DELAYED_SETTLEMENT": "DELAYED_SETTLEMENT",
    "WEBHOOK_REDELIVERY": "NONE",
    "ORPHAN_BANK_LINE": "UNMATCHED_BANK_LINE",
}
EDGE_CASES = ["DUPLICATE_SETTLEMENT_LINE", "BANK_AMOUNT_DIFFERS_BY_FEE", "REFUND_BEFORE_CAPTURE",
              "UNMATCHED_RECORD_SILENTLY_DROPPED", "CURRENCY_MISMATCH", "SAME_EVENT_INGESTED_TWICE",
              "PARTIAL_PAYOUT", "MISSING_PAYOUT", "ROUNDING_OVER_TOLERANCE", "DELAYED_PAYOUT", "ORPHAN_BANK_LINE"]
RISK_TYPES = ["CURRENCY_MISMATCH", "UNMATCHED_BANK_LINE", "UNMATCHED_BATCH", "PARTIAL_PAYOUT"]


# ---------------------------------------------------------------- small helpers
def rng(cfg, name):
    """One independent, reproducible random stream per stage."""
    return random.Random("%s:%s" % (cfg["seed"], name))


def div_half_even(n, d):
    """Integer n/d rounded half to even (banker's rounding), used for fees."""
    q, rem = divmod(n, d)
    if rem * 2 > d or (rem * 2 == d and q % 2 == 1):
        q += 1
    return q


def bday_add(d, n):
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def nightly(t):
    """The recon job runs at 02:00Z; anything seen later waits for the next run."""
    c = datetime(t.year, t.month, t.day, 2, 0, 0)
    return c if c > t else c + timedelta(days=1)


def convert(amount, c_from, c_to):
    """Convert minor units between currencies with the fixed invented rates."""
    usd = amount / 100 * CCY[c_from]["fx"]
    return int(round(usd / CCY[c_to]["fx"] * 100))


def allocate(total, weights):
    """Split `total` across keys by weight (largest remainder, at least 1 each)."""
    keys = list(weights)
    s = sum(weights.values())
    raw = {k: weights[k] * total / s for k in keys}
    out = {k: max(1, int(raw[k])) for k in keys}
    while sum(out.values()) < total:
        k = max(keys, key=lambda x: (raw[x] - out[x], -keys.index(x)))
        out[k] += 1
    while sum(out.values()) > total:
        k = max(keys, key=lambda x: (out[x], -keys.index(x)))
        out[k] -= 1
    return out


def canonical_events(events):
    """First delivery of each idempotency key wins. Input must be in id order."""
    seen, out = set(), []
    for e in events:
        if e["idempotency_key"] not in seen:
            seen.add(e["idempotency_key"])
            out.append(e)
    return out


def number_history(rows, start=1):
    """rows: (entity_type, entity_id, from_status, to_status, when, who). Numbered in time order;
    ties keep the order given, so one entity's chain stays valid."""
    order = sorted(range(len(rows)), key=lambda i: (rows[i][4], rows[i][0], rows[i][1], i))
    out = []
    for n, i in enumerate(order, start):
        a, b, c, d, e, f = rows[i]
        out.append(dict(history_id="HIS-%07d" % n, entity_type=a, entity_id=b, from_status=c, to_status=d,
                        changed_at=ts(e), changed_by=f))
    return out


# ---------------------------------------------------------------- run parameters
def make_cfg(a):
    """All parameters of a run. Fault counts scale with the dataset size; `a` holds the size flags."""
    sc, bs = a.orders / 50000.0, a.batches / 1000.0
    inj = dict(
        dup_settlement_line=max(1, round(12 * bs)), missing_payout=max(1, round(8 * bs)),
        partial_payout=max(1, round(8 * bs)), currency_mismatch=max(1, round(10 * bs)),
        fee_diff=max(1, round(15 * bs)), rounding_over=max(1, round(10 * bs)),
        rounding_at_tol=max(1, round(12 * bs)), delayed_payout=max(1, round(30 * bs)),
        refund_before_capture=max(1, round(40 * sc)), silently_dropped=max(1, round(25 * sc)),
        ingested_twice=max(1, round(30 * sc)), orphans=max(1, round(0.012 * a.bank_lines)),
    )
    batch_keys = ["dup_settlement_line", "missing_payout", "partial_payout", "currency_mismatch", "fee_diff",
                  "rounding_over", "rounding_at_tol", "delayed_payout"]
    total = sum(inj[k] for k in batch_keys)
    if total > 0.7 * a.batches:  # small datasets: shrink so most batches stay clean
        f = 0.7 * a.batches / total
        for k in batch_keys:
            inj[k] = max(1, int(inj[k] * f))
    start = date(2026, 1, 1)
    return dict(
        seed=a.seed, n_merchants=a.merchants, n_orders=a.orders, n_attempts=a.attempts,
        n_batches=a.batches, n_bank=a.bank_lines,
        start=start, end=start + timedelta(days=min(272, max(21, round(272 * bs)))),
        as_of=datetime(2026, 10, 22, 0, 0, 0),
        tolerance_minor=2,       # bank vs batch amount may differ by this much (minor units)
        window_after_days=3,     # bank value date may be this many days after the expected payout date
        sla_days=8,              # a capture should be on a settlement line within this many days
        payout_lag_bdays=2,      # expected payout = batch cut-off + 2 business days
        grace_days=7,            # extra days before a missing payout becomes an exception
        refund_rate=0.085, redelivery_rate=0.01, delayed_rate=0.008, inj=inj,
    )


def cfg_to_params(cfg):
    out = dict(cfg)
    out["start"], out["end"] = cfg["start"].isoformat(), cfg["end"].isoformat()
    out["as_of"] = ts(cfg["as_of"])
    return out


def cfg_from_params(p):
    cfg = dict(p)
    cfg["start"], cfg["end"] = date.fromisoformat(p["start"]), date.fromisoformat(p["end"])
    cfg["as_of"] = pts(p["as_of"])
    return cfg
