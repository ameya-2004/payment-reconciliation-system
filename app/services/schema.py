"""Data dictionary: one place that describes every table. The CSV types, the SQL DDL and the docs come from it."""
from app.services.common import (CCY, EVENT_TYPES, ORDER_STATUS, ATTEMPT_STATUS, MATCH_LEVELS, MATCH_STATUS,
                                 EXC_TYPES, EXC_STATUS, RES_TYPES)

CCY_L = list(CCY)
TABLES = {}


def F(name, typ, req=True, allowed=None, unit="", uniq=False, rule=""):
    return dict(name=name, type=typ, required=req, allowed=allowed, unit=unit, unique=uniq, rule=rule)


def table(name, desc, pk, fields, fks=(), checks=(), card="", life=""):
    TABLES[name] = dict(desc=desc, pk=pk, fields=fields, fks=list(fks), checks=list(checks), card=card, life=life)


table("users", "Staff and system accounts that can resolve exceptions (synthetic labels, no real people).", "user_id", [
    F("user_id", "STRING", uniq=True, rule="USR-000 system, USR-0xx analysts, USR-1xx risk reviewers"),
    F("display_name", "STRING"),
    F("role", "STRING", allowed=["OPS_ANALYST", "RISK_REVIEWER", "SYSTEM"]),
], card="1:N resolutions (resolved_by); 1:N status_history (changed_by)")

table("merchants", "Merchants that accept payments. Fee terms are fixed per merchant.", "merchant_id", [
    F("merchant_id", "STRING", uniq=True, rule="MER-000001 pattern"),
    F("legal_name", "STRING", rule="invented name"),
    F("country", "STRING", allowed=[c["country"] for c in CCY.values()]),
    F("settlement_currency", "STRING", allowed=CCY_L, rule="every order of the merchant uses this currency"),
    F("fee_rate_bps", "INT", unit="basis points", rule="200..350"),
    F("fixed_fee_minor", "INT", unit="minor units", rule=">= 0, charged on every capture"),
    F("onboarded_date", "DATE", rule="effective date: before the first order"),
], card="1:N payment_orders", life="Active from onboarded_date.")

table("payment_orders", "One row per customer payment order.", "payment_id", [
    F("payment_id", "STRING", uniq=True, rule="PAY-2026-00000001 pattern, numbered by order_ts"),
    F("merchant_id", "STRING", rule="FK merchants"),
    F("customer_ref", "STRING", rule="opaque token, not personal data"),
    F("order_ts", "TIMESTAMP", rule="UTC, on or after the merchant's onboarded_date"),
    F("currency", "STRING", allowed=CCY_L, rule="equals the merchant's settlement_currency"),
    F("amount_minor", "INT", unit="minor units", rule="> 0"),
    F("payment_method", "STRING", allowed=["CARD_VISA", "CARD_MC", "WALLET", "UPI"]),
    F("status", "STRING", allowed=ORDER_STATUS, rule="derived from the canonical processor events"),
    F("captured_amount_minor", "INT", unit="minor units", rule="sum of canonical CAPTURED events"),
    F("refunded_amount_minor", "INT", unit="minor units", rule="sum of canonical REFUND_ISSUED events, <= captured"),
], fks=[("merchant_id", "merchants", "merchant_id")],
    card="1:N payment_attempts (1 or 2); 1:N processor_events; 1:0..N settlement_lines",
    life="FAILED (no capture), or CAPTURED -> PARTIALLY_REFUNDED -> REFUNDED. The state changes are the processor_events rows.")

table("payment_attempts", "Authorisation attempts for an order. A second attempt only follows a decline.", "attempt_id", [
    F("attempt_id", "STRING", uniq=True, rule="ATT-<payment_id>-01"),
    F("payment_id", "STRING", rule="FK payment_orders"),
    F("attempt_no", "INT", rule="1 or 2, consecutive"),
    F("attempt_ts", "TIMESTAMP", rule=">= order_ts"),
    F("amount_minor", "INT", unit="minor units", rule="equals the order amount"),
    F("status", "STRING", allowed=ATTEMPT_STATUS, rule="DECLINED, or CAPTURED when the attempt was captured"),
    F("decline_code", "STRING", req=False, rule="only when DECLINED"),
], fks=[("payment_id", "payment_orders", "payment_id")], card="N:1 payment_orders; 1:N processor_events")

table("processor_events", "Append-only processor webhook log. History is never overwritten.", "processor_event_id", [
    F("processor_event_id", "STRING", uniq=True, rule="EVT-2026-00000001, numbered by received_ts"),
    F("payment_id", "STRING", rule="FK payment_orders"),
    F("attempt_id", "STRING", rule="FK payment_attempts"),
    F("event_type", "STRING", allowed=EVENT_TYPES),
    F("event_ts", "TIMESTAMP", rule="processor clock"),
    F("received_ts", "TIMESTAMP", rule=">= event_ts"),
    F("amount_minor", "INT", unit="minor units", rule="> 0 (declines carry the order amount)"),
    F("currency", "STRING", allowed=CCY_L),
    F("webhook_event_id", "STRING", rule="processor's own event id, shared by redeliveries"),
    F("delivery_id", "STRING", rule="one per HTTP delivery; a repeated value means our pipeline wrote the same delivery twice"),
    F("idempotency_key", "STRING", rule="same business event = same key (not unique on purpose)"),
], fks=[("payment_id", "payment_orders", "payment_id"), ("attempt_id", "payment_attempts", "attempt_id")],
    card="N:1 payment_orders; N:1 payment_attempts; canonical event 1:0..1 settlement_lines (0 for declines, authorisations and dropped captures)")

table("settlement_batches", "Processor settlement batch: one currency, one cut-off.", "batch_id", [
    F("batch_id", "STRING", uniq=True, rule="SET-2026-000001 pattern, numbered by cutoff_ts"),
    F("currency", "STRING", allowed=CCY_L),
    F("cutoff_ts", "TIMESTAMP"),
    F("expected_payout_date", "DATE", rule="cut-off date + 2 business days"),
    F("line_count", "INT", rule="count of settlement_lines"),
    F("gross_captured_minor", "INT", unit="minor units", rule="sum of gross on CAPTURE lines"),
    F("gross_refunded_minor", "INT", unit="minor units", rule="sum of gross on REFUND lines"),
    F("total_fees_minor", "INT", unit="minor units", rule="sum of line fees"),
    F("net_payout_minor", "INT", unit="minor units", rule="captured - refunded - fees"),
], card="1:N settlement_lines; N:M bank_statement_lines through reconciliation_matches (paid in several tranches)",
    life="Effective date: expected_payout_date.")

table("settlement_lines", "One line per captured or refunded event inside a batch.", "settlement_line_id", [
    F("settlement_line_id", "STRING", uniq=True, rule="STL-<batch_id>-001"),
    F("batch_id", "STRING", rule="FK settlement_batches"),
    F("payment_id", "STRING", rule="FK payment_orders"),
    F("processor_event_id", "STRING", rule="FK processor_events (the canonical event)"),
    F("line_type", "STRING", allowed=["CAPTURE", "REFUND"]),
    F("currency", "STRING", allowed=CCY_L),
    F("gross_amount_minor", "INT", unit="minor units", rule="> 0, equals the event amount"),
    F("fee_minor", "INT", unit="minor units", rule="capture: round_half_even(gross*bps/10000)+fixed; refund: 0"),
    F("net_amount_minor", "INT", unit="minor units", rule="capture: gross-fee; refund: -gross"),
], fks=[("batch_id", "settlement_batches", "batch_id"), ("payment_id", "payment_orders", "payment_id"),
        ("processor_event_id", "processor_events", "processor_event_id")],
    card="N:1 settlement_batches; N:1 processor_events; 0..1 reconciliation_matches")

table("bank_statement_lines", "Bank statement entries for the processor funds account.", "bank_line_id", [
    F("bank_line_id", "STRING", uniq=True, rule="BANK-2026-000001 pattern, numbered by value_date"),
    F("value_date", "DATE", rule="effective date"),
    F("booking_date", "DATE", rule=">= value_date"),
    F("amount_minor", "INT", unit="minor units", rule="signed: credit > 0, debit < 0"),
    F("currency", "STRING", allowed=CCY_L),
    F("reference", "STRING", rule="free text; payouts look like 'PSP PAYOUT SET-2026-000123 T2/4'"),
    F("counterparty_name", "STRING"),
], card="optional N:1 settlement_batches (an orphan line has no batch); 0..1 reconciliation_matches")

table("reconciliation_matches", "Bridge table: bank line <-> batch (N:M) and processor event <-> settlement line (1:1).", "match_id", [
    F("match_id", "STRING", uniq=True, rule="REC-2026-000001 pattern, numbered by matched_at"),
    F("match_level", "STRING", allowed=MATCH_LEVELS),
    F("bank_line_id", "STRING", req=False, rule="FK, set for BANK_TO_BATCH"),
    F("batch_id", "STRING", req=False, rule="FK, set for BANK_TO_BATCH"),
    F("processor_event_id", "STRING", req=False, rule="FK, set for EVENT_TO_LINE"),
    F("settlement_line_id", "STRING", req=False, rule="FK, set for EVENT_TO_LINE"),
    F("currency", "STRING", allowed=CCY_L),
    F("matched_amount_minor", "INT", unit="minor units", rule="the bank amount, or the settlement line gross"),
    F("group_expected_amount_minor", "INT", unit="minor units", rule="batch net (bank level) or event amount"),
    F("group_diff_minor", "INT", req=False, unit="minor units", rule="sum matched - expected; empty when currencies differ"),
    F("date_delta_days", "INT", rule="bank value date - expected payout date, or batch cut-off date - event date"),
    F("rule_id", "STRING", rule="which matching rule fired"),
    F("match_status", "STRING", allowed=MATCH_STATUS),
    F("matched_at", "TIMESTAMP", rule="the nightly run"),
], fks=[("bank_line_id", "bank_statement_lines", "bank_line_id"), ("batch_id", "settlement_batches", "batch_id"),
        ("processor_event_id", "processor_events", "processor_event_id"),
        ("settlement_line_id", "settlement_lines", "settlement_line_id")],
    checks=["(match_level='BANK_TO_BATCH' AND bank_line_id IS NOT NULL AND batch_id IS NOT NULL) OR "
            "(match_level='EVENT_TO_LINE' AND processor_event_id IS NOT NULL AND settlement_line_id IS NOT NULL)"],
    card="the bridge: bank lines N:M batches; events 1:1 lines; 0..N exceptions point at a match")

table("exceptions", "Every unmatched, partial or inconsistent item found by the engine.", "exception_id", [
    F("exception_id", "STRING", uniq=True, rule="EXC-2026-000001 pattern"),
    F("exception_type", "STRING", allowed=EXC_TYPES),
    F("severity", "STRING", allowed=["LOW", "MEDIUM", "HIGH"], rule="fixed per exception type"),
    F("status", "STRING", allowed=EXC_STATUS, rule="state as of the as-of date; history in status_history"),
    F("entity_type", "STRING", allowed=["PROCESSOR_EVENT", "SETTLEMENT_LINE", "SETTLEMENT_BATCH", "BANK_LINE"]),
    F("entity_id", "STRING", rule="the main subject of the exception"),
    F("payment_id", "STRING", req=False),
    F("batch_id", "STRING", req=False),
    F("bank_line_id", "STRING", req=False),
    F("processor_event_id", "STRING", req=False),
    F("settlement_line_id", "STRING", req=False),
    F("match_id", "STRING", req=False),
    F("amount_at_risk_minor", "INT", unit="minor units", rule=">= 0"),
    F("currency", "STRING", allowed=CCY_L),
    F("detected_at", "TIMESTAMP", rule="nightly run, 02:00Z"),
    F("sla_due_at", "TIMESTAMP", rule="HIGH 2 days, MEDIUM 5, LOW 10 after detection"),
    F("assigned_role", "STRING", allowed=["OPS_ANALYST", "RISK_REVIEWER", "SYSTEM"]),
    F("rule_id", "STRING", rule="the engine rule that raised it"),
    F("description", "STRING"),
], fks=[("payment_id", "payment_orders", "payment_id"), ("batch_id", "settlement_batches", "batch_id"),
        ("bank_line_id", "bank_statement_lines", "bank_line_id"),
        ("processor_event_id", "processor_events", "processor_event_id"),
        ("settlement_line_id", "settlement_lines", "settlement_line_id"),
        ("match_id", "reconciliation_matches", "match_id")],
    card="optional N:1 reconciliation_matches; 1:0..1 resolutions; 1:N status_history",
    life="OPEN -> IN_REVIEW -> ESCALATED -> RESOLVED or WRITTEN_OFF (OPEN -> RESOLVED for automatic dedupe). "
         "Effective dates: detected_at, sla_due_at.")

table("resolutions", "How an exception was closed. Exists only once the exception is closed.", "resolution_id", [
    F("resolution_id", "STRING", uniq=True, rule="RES-2026-000001 pattern"),
    F("exception_id", "STRING", rule="FK exceptions"),
    F("resolution_type", "STRING", allowed=RES_TYPES, rule="must be allowed for the exception type"),
    F("resolved_by", "STRING", rule="FK users"),
    F("resolved_ts", "TIMESTAMP", rule=">= detected_at, <= as-of"),
    F("adjustment_amount_minor", "INT", unit="minor units", rule=">= 0"),
    F("currency", "STRING", allowed=CCY_L),
    F("notes", "STRING"),
], fks=[("exception_id", "exceptions", "exception_id"), ("resolved_by", "users", "user_id")],
    card="N:1 exceptions (at most one here); N:1 users")

table("status_history", "Append-only status changes of exceptions: who and when. Rows are never updated.", "history_id", [
    F("history_id", "STRING", uniq=True, rule="HIS-0000001 pattern"),
    F("entity_type", "STRING", allowed=["EXCEPTION"]),
    F("entity_id", "STRING", rule="exception_id"),
    F("from_status", "STRING", req=False, rule="empty on creation"),
    F("to_status", "STRING", allowed=EXC_STATUS),
    F("changed_at", "TIMESTAMP"),
    F("changed_by", "STRING", rule="FK users"),
], fks=[("changed_by", "users", "user_id")], card="N:1 exceptions; N:1 users")

GT_COLS = ["gt_id", "issue_type", "origin", "entity_type", "entity_id", "payment_id", "batch_id",
           "expected_exception_type", "expected_resolution_options", "expected_decision", "note"]


def ddl():
    """CREATE TABLE statements (SQLite/ANSI) with primary keys, foreign keys, enums and CHECKs."""
    out = []
    for t, m in TABLES.items():
        cols = []
        for f in m["fields"]:
            sql_type = {"STRING": "TEXT", "INT": "INTEGER", "DATE": "TEXT", "TIMESTAMP": "TEXT"}[f["type"]]
            c = "  %s %s" % (f["name"], sql_type)
            if f["required"]:
                c += " NOT NULL"
            if f["name"] == m["pk"]:
                c += " PRIMARY KEY"
            if f["allowed"]:
                c += " CHECK (%s IN (%s))" % (f["name"], ", ".join("'%s'" % v for v in f["allowed"]))
            cols.append(c)
        cols += ["  FOREIGN KEY (%s) REFERENCES %s(%s)" % x for x in m["fks"]]
        cols += ["  CHECK (%s)" % chk for chk in m["checks"]]
        out.append("CREATE TABLE %s (\n%s\n);" % (t, ",\n".join(cols)))
    return "\n\n".join(out) + "\n"
