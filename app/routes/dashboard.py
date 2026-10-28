import json
import os
from collections import Counter, defaultdict

from flask import Blueprint, current_app, jsonify, request

from app.services.exporter import read_table

dashboard_bp = Blueprint("dashboard", __name__)

_cache = {}


def data_dir():
    return current_app.config["DATA_DIR"]


def load_table(name):
    """Read a table once per file version (keyed on the file's modified time)."""
    path = os.path.join(data_dir(), "csv", name + ".csv")
    if not os.path.exists(path):
        return None
    key = (path, os.stat(path).st_mtime_ns)
    if key not in _cache:
        if len(_cache) > 12:
            _cache.clear()
        _cache[key] = read_table(data_dir(), name)
    return _cache[key]


def load_json(name):
    path = os.path.join(data_dir(), name)
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def not_ready():
    return jsonify(status="not_ready",
                   message="Run `python run_workflow.py --data %s` to create the reconciliation outputs." % data_dir()), 503


@dashboard_bp.route("/")
def home():
    return jsonify(message="Payment Reconciliation System API", status="running",
                   endpoints=["/health", "/api/summary", "/api/exceptions", "/api/exceptions/<exception_id>",
                              "/api/validation", "/api/evaluation"])


@dashboard_bp.route("/health")
def health():
    return jsonify(status="healthy")


@dashboard_bp.route("/api/summary")
def summary():
    exceptions = load_table("exceptions")
    matches = load_table("reconciliation_matches")
    if exceptions is None or matches is None:
        return not_ready()
    at_risk = defaultdict(int)
    for x in exceptions:
        at_risk[x["currency"]] += x["amount_at_risk_minor"]
    manifest = load_json("manifest.json") or {}
    return jsonify(
        status="ready",
        row_counts=manifest.get("row_counts", {}),
        match_rows_by_status=dict(Counter(m["match_status"] for m in matches)),
        exceptions=len(exceptions),
        exceptions_by_type=dict(Counter(x["exception_type"] for x in exceptions)),
        exceptions_by_status=dict(Counter(x["status"] for x in exceptions)),
        exceptions_by_severity=dict(Counter(x["severity"] for x in exceptions)),
        amount_at_risk_minor_by_currency=dict(at_risk))


@dashboard_bp.route("/api/exceptions")
def list_exceptions():
    exceptions = load_table("exceptions")
    if exceptions is None:
        return not_ready()
    rows = exceptions
    for arg, col in (("type", "exception_type"), ("status", "status"), ("severity", "severity"),
                     ("batch_id", "batch_id"), ("payment_id", "payment_id")):
        wanted = request.args.get(arg)
        if wanted:
            rows = [x for x in rows if x[col] == wanted]
    try:
        limit = min(int(request.args.get("limit", 100)), 1000)
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        return jsonify(error="limit and offset must be integers"), 400
    return jsonify(count=len(rows), limit=limit, offset=offset, exceptions=rows[offset:offset + limit])


@dashboard_bp.route("/api/exceptions/<exception_id>")
def exception_detail(exception_id):
    """Everything connected to one exception: the match it came from, its resolution and its status history."""
    exceptions = load_table("exceptions")
    if exceptions is None:
        return not_ready()
    found = next((x for x in exceptions if x["exception_id"] == exception_id), None)
    if found is None:
        return jsonify(error="unknown exception_id", exception_id=exception_id), 404
    resolution = next((r for r in load_table("resolutions") if r["exception_id"] == exception_id), None)
    match = next((m for m in load_table("reconciliation_matches") if m["match_id"] == found["match_id"]), None) \
        if found["match_id"] else None
    history = [h for h in load_table("status_history")
               if h["entity_type"] == "EXCEPTION" and h["entity_id"] == exception_id]
    return jsonify(exception=found, resolution=resolution, match=match, status_history=history)


@dashboard_bp.route("/api/validation")
def validation():
    data = load_json("validation_summary.json")
    return jsonify(data) if data else not_ready()


@dashboard_bp.route("/api/evaluation")
def evaluation():
    """Engine output compared with the ground truth. The engine itself never reads the ground truth."""
    data = load_json("metrics.json")
    return jsonify(data) if data else not_ready()
