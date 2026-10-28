"""
Run the reconciliation workflow on a dataset folder.

    python run_workflow.py                          # reconcile + validate the committed starter dataset (data/starter)
    python run_workflow.py --data data/full         # same for the full dataset (create it with --generate first)
    python run_workflow.py --generate --starter --data data/my_run
    python run_workflow.py --repro-check            # regenerate twice and compare checksums

Stages: (1) generate inputs + ground truth, (2) reconcile, (3) validate and score.
Stage 2 reads only the input tables. Exit code is 1 if a validation check fails or the engine's exceptions
differ from the ground truth, so the command can be used as a pass/fail test.
"""
import argparse
import json
import os
import platform
import shutil
import sys
import tempfile

from app.services import data_generator as gen
from app.services.common import PARAM_FILE, cfg_from_params, make_cfg
from app.services.exporter import (data_checksums, read_ground_truth, read_tables, write_json, write_json_tables,
                                   write_reports, write_sql, write_tables)
from app.services.reconciliation import reconcile
from app.services.schema import TABLES
from app.services.validation import evaluate, validate

OUTPUT_TABLES = ["reconciliation_matches", "exceptions", "resolutions", "status_history"]
VERSION_NOTE = "payment-reconciliation-system"


def load_cfg(data_dir, tolerance=None):
    with open(os.path.join(data_dir, PARAM_FILE), encoding="utf-8") as f:
        cfg = cfg_from_params(json.load(f))
    if tolerance is not None:
        cfg["tolerance_minor"] = tolerance
    return cfg


def clear_generated(data_dir):
    """Remove files this project writes, so an old run cannot leave stale files behind."""
    for sub in ("csv", "json"):
        shutil.rmtree(os.path.join(data_dir, sub), ignore_errors=True)
    for name in ("seed.sql.gz", "ground_truth.csv", "ground_truth.json", "reproducibility_check.json"):
        if os.path.exists(os.path.join(data_dir, name)):
            os.remove(os.path.join(data_dir, name))


def run_pipeline(data_dir, formats=("csv", "sql"), tolerance=None, docs_dir=None, command=""):
    cfg = load_cfg(data_dir, tolerance)
    tables = read_tables(data_dir, gen.INPUT_TABLES)
    gt_rows = read_ground_truth(data_dir)

    # stage 2: the engine sees input tables only
    outputs, stats = reconcile(cfg, tables)
    tables.update(outputs)

    # stage 3
    checks = validate(cfg, tables, gt_rows)
    metrics = evaluate(tables, gt_rows)
    metrics["engine_counters"] = dict(stats)
    metrics["tolerance_minor_used"] = cfg["tolerance_minor"]

    write_tables(data_dir, OUTPUT_TABLES, tables)
    if "json" in formats:
        write_json_tables(data_dir, list(TABLES), tables)
    else:
        shutil.rmtree(os.path.join(data_dir, "json"), ignore_errors=True)
    sql_path = os.path.join(data_dir, "seed.sql.gz")
    if "sql" in formats:
        write_sql(sql_path, tables)
    elif os.path.exists(sql_path):
        os.remove(sql_path)
    extra = [(docs_dir, "data_dictionary.md", "validation_report.md")] if docs_dir else []
    write_reports(data_dir, cfg, checks, metrics, extra_dirs=extra)
    write_json(os.path.join(data_dir, "manifest.json"), dict(
        project=VERSION_NOTE, seed=cfg["seed"], python=platform.python_version(), command=command,
        row_counts={t: len(tables[t]) for t in TABLES}, ground_truth_rows=len(gt_rows),
        sha256=data_checksums(data_dir)))

    det = metrics["detection"]
    ok = (all(c["status"] == "PASS" for c in checks) and det["false_neg"] == 0 and det["false_pos"] == 0
          and det["exceptions_raised_on_labelled_normal_records"] == 0)
    return dict(ok=ok, checks=checks, metrics=metrics, tables=tables, cfg=cfg)


def repro_check(data_dir, formats, tolerance):
    """Regenerate the dataset twice from its parameters and compare every data file's checksum."""
    cfg = load_cfg(data_dir, tolerance)
    runs = []
    for n in (1, 2):
        tmp = tempfile.mkdtemp(prefix="recon_repro%d_" % n)
        try:
            gen.generate_to(tmp, cfg)
            run_pipeline(tmp, formats, tolerance)
            runs.append(data_checksums(tmp))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    current = data_checksums(data_dir)
    result = dict(seed=cfg["seed"], regenerations=2, identical_to_each_other=runs[0] == runs[1],
                  identical_to_current_files=runs[0] == current, files_compared=len(current), sha256=current)
    write_json(os.path.join(data_dir, "reproducibility_check.json"), result)
    return result


def pick_formats(requested, data_dir, fresh):
    if requested:
        return tuple(f for f in requested.split(",") if f)
    if fresh:
        return ("csv", "sql")
    found = ["csv"]
    if os.path.isdir(os.path.join(data_dir, "json")):
        found.append("json")
    if os.path.exists(os.path.join(data_dir, "seed.sql.gz")):
        found.append("sql")
    return tuple(found)


def print_summary(res):
    checks, m = res["checks"], res["metrics"]
    failed = [c for c in checks if c["status"] != "PASS"]
    print("validation: %d/%d checks passed" % (len(checks) - len(failed), len(checks)))
    for c in failed:
        print("  FAIL:", c["check"], "-", c["detail"])
    d = m["detection"]
    print("engine vs ground truth: expected %d, found %d, missed %d, extra %d (precision %s, recall %s)" % (
        d["overall_expected"], d["true_pos"], d["false_neg"], d["false_pos"], d["precision"], d["recall"]))
    print("exceptions raised on records labelled normal:", d["exceptions_raised_on_labelled_normal_records"])
    print("%-28s %8s %6s %7s %6s" % ("exception type", "expected", "found", "missed", "extra"))
    for t, v in d["per_type"].items():
        print("%-28s %8d %6d %7d %6d" % (t, v["expected"], v["true_pos"], v["false_neg"], v["false_pos"]))
    print("status of exceptions:", m["workflow"]["exceptions_by_status"])


def main(argv=None):
    ap = argparse.ArgumentParser(description="Reconcile, validate and score a payment dataset")
    ap.add_argument("--data", default="data/starter", help="dataset folder (default data/starter)")
    ap.add_argument("--generate", action="store_true", help="run stage 1 first and overwrite the folder")
    gen.add_scale_args(ap)
    ap.add_argument("--formats", default=None,
                    help="comma list from csv,json,sql (csv is always written). Default: the formats the folder already has, "
                         "or csv,sql for a new one")
    ap.add_argument("--tolerance", type=int, default=None, help="match tolerance in minor units (default from params.json, 2)")
    ap.add_argument("--docs-dir", default=None, help="also write data_dictionary.md and validation_report.md here")
    ap.add_argument("--repro-check", action="store_true", help="regenerate twice and compare checksums")
    args = gen.apply_starter(ap.parse_args(argv))
    command = " ".join(["python run_workflow.py"] + (sys.argv[1:] if argv is None else list(argv)))

    if args.generate:
        clear_generated(args.data)
        gen.generate_to(args.data, make_cfg(args))
        print("generated input tables in", args.data)
    elif not os.path.exists(os.path.join(args.data, PARAM_FILE)):
        sys.exit("no dataset in %s. Run with --generate, or pass --data <folder>." % args.data)

    formats = pick_formats(args.formats, args.data, args.generate)
    res = run_pipeline(args.data, formats, args.tolerance, args.docs_dir, command)
    print_summary(res)
    ok = res["ok"]
    if args.repro_check:
        r = repro_check(args.data, formats, args.tolerance)
        same = r["identical_to_each_other"] and r["identical_to_current_files"]
        print("reproducibility: two regenerations identical to each other and to the current files: %s" % same)
        ok = ok and same
    print("RESULT:", "PASS" if ok else "FAIL")
    print("outputs in", args.data)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
