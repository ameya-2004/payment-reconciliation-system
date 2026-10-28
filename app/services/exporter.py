"""Reading and writing the tables (CSV, JSON, SQL) and the generated report files."""
import csv
import gzip
import hashlib
import json
import os

from app.services.common import VERSION
from app.services.schema import TABLES, GT_COLS, ddl


# ---------------------------------------------------------------- csv
def write_csv(path, cols, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(cols)
        for r in rows:
            w.writerow(["" if r[c] is None else r[c] for c in cols])


def write_tables(out_dir, names, tables):
    os.makedirs(os.path.join(out_dir, "csv"), exist_ok=True)
    for name in names:
        cols = [f["name"] for f in TABLES[name]["fields"]]
        write_csv(os.path.join(out_dir, "csv", name + ".csv"), cols, tables[name])


def read_table(data_dir, name):
    """Read one CSV back with the types from the data dictionary (INT/BOOL become int, empty optional becomes None)."""
    fields = {f["name"]: f for f in TABLES[name]["fields"]}
    rows = []
    with open(os.path.join(data_dir, "csv", name + ".csv"), newline="", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = {}
            for col, value in raw.items():
                spec = fields[col]
                if value == "" and not spec["required"]:
                    row[col] = None
                elif spec["type"] in ("INT", "BOOL"):
                    row[col] = int(value)
                else:
                    row[col] = value
            rows.append(row)
    return rows


def read_tables(data_dir, names):
    return {n: read_table(data_dir, n) for n in names}


def read_ground_truth(data_dir):
    with open(os.path.join(data_dir, "ground_truth.csv"), newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------- ground truth, json, sql
def write_gt(out_dir, rows):
    write_csv(os.path.join(out_dir, "ground_truth.csv"), GT_COLS, rows)
    write_json(os.path.join(out_dir, "ground_truth.json"), rows, indent=None)


def write_json(path, obj, indent=1):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, indent=indent)
        f.write("\n")


def write_json_tables(out_dir, names, tables):
    os.makedirs(os.path.join(out_dir, "json"), exist_ok=True)
    for name in names:
        with open(os.path.join(out_dir, "json", name + ".json"), "w", encoding="utf-8", newline="\n") as f:
            json.dump(tables[name], f, separators=(",", ":"))
            f.write("\n")


def sql_val(v):
    if v is None:
        return "NULL"
    if isinstance(v, int):
        return str(v)
    return "'" + str(v).replace("'", "''") + "'"


def write_sql(path, tables):
    """DDL plus INSERTs, gzip with a fixed timestamp so the bytes are reproducible."""
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="", fileobj=raw, mode="wb", mtime=0) as gz:
            gz.write(("-- payment reconciliation seed data, generator version %s\n" % VERSION).encode())
            gz.write(ddl().encode())
            for name, meta in TABLES.items():
                cols = [f["name"] for f in meta["fields"]]
                rows = tables[name]
                for i in range(0, len(rows), 500):
                    vals = ",\n".join("(" + ",".join(sql_val(r[c]) for c in cols) + ")" for r in rows[i:i + 500])
                    gz.write(("INSERT INTO %s (%s) VALUES\n%s;\n" % (name, ",".join(cols), vals)).encode())


# ---------------------------------------------------------------- checksums
def sha(path):
    d = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            d.update(block)
    return d.hexdigest()


DATA_PATTERNS = ("csv", "json")
DATA_FILES = ("seed.sql.gz", "ground_truth.csv", "ground_truth.json", "params.json")


def data_checksums(out_dir):
    """sha256 of every data file (not of the report files, which carry no extra information)."""
    found = {}
    for sub in DATA_PATTERNS:
        folder = os.path.join(out_dir, sub)
        if os.path.isdir(folder):
            for name in sorted(os.listdir(folder)):
                found["%s/%s" % (sub, name)] = sha(os.path.join(folder, name))
    for name in DATA_FILES:
        path = os.path.join(out_dir, name)
        if os.path.exists(path):
            found[name] = sha(path)
    return found


# ---------------------------------------------------------------- reports
def data_dictionary_markdown():
    lines = ["# Data dictionary", "",
             "Generated from `app/services/schema.py`. Money is always integer minor units (cents, paise, yen). "
             "Timestamps are UTC ISO-8601, dates are YYYY-MM-DD.", ""]
    for name, m in TABLES.items():
        lines += ["## %s" % name, "", m["desc"], "",
                  "* Primary key: `%s`" % m["pk"],
                  "* Cardinality: %s" % m["card"]]
        if m["fks"]:
            lines.append("* Foreign keys: " + ", ".join("`%s` -> `%s.%s`" % x for x in m["fks"]))
        if m["life"]:
            lines.append("* Lifecycle / effective dates: %s" % m["life"])
        lines += ["", "| field | type | required | allowed values | unit | unique | validation rule |", "|---|---|---|---|---|---|---|"]
        for f in m["fields"]:
            lines.append("| %s | %s | %s | %s | %s | %s | %s |" % (
                f["name"], f["type"], "yes" if f["required"] else "no", ", ".join(f["allowed"]) if f["allowed"] else "",
                f["unit"], "yes" if f["unique"] else "", f["rule"]))
        lines.append("")
    lines += ["## ground_truth (separate file, never read by the engine)", "",
              "Columns: " + ", ".join("`%s`" % c for c in GT_COLS) + ". `origin` is EDGE_CASE for an injected fault and "
              "BASELINE_CONDITION for normal noise (webhook redeliveries, rounding exactly at the tolerance) "
              "or a late settlement found by rule. `expected_exception_type` is NONE where the right answer is no exception.", ""]
    return "\n".join(lines)


def validation_markdown(checks, metrics, cfg):
    passed = sum(1 for c in checks if c["status"] == "PASS")
    det = metrics["detection"]
    out = ["# Validation summary", "",
           "%d of %d checks passed." % (passed, len(checks)), "",
           "| check | result | detail |", "|---|---|---|"]
    out += ["| %s | %s | %s |" % (c["check"], c["status"], c["detail"]) for c in checks]
    out += ["", "## Engine vs ground truth", "",
            "Expected exceptions: %d, found: %d, missed: %d, extra: %d (precision %s, recall %s). "
            "Exceptions raised on records labelled normal: %d." % (
                det["overall_expected"], det["true_pos"], det["false_neg"], det["false_pos"], det["precision"],
                det["recall"], det["exceptions_raised_on_labelled_normal_records"]),
            "", "| exception type | expected | found | missed | extra |", "|---|---|---|---|---|"]
    for t, v in det["per_type"].items():
        out.append("| %s | %d | %d | %d | %d |" % (t, v["expected"], v["true_pos"], v["false_neg"], v["false_pos"]))
    out += ["", "Tolerance %d minor units, bank date window +%d days, settlement SLA %d days, as-of %s. "
            "The engine's rules mirror how faults are injected, so a perfect score shows the rules and the data agree; "
            "it does not prove the rules would catch faults nobody injected." % (
                cfg["tolerance_minor"], cfg["window_after_days"], cfg["sla_days"], cfg["as_of"].strftime("%Y-%m-%d")), ""]
    return "\n".join(out)


def write_reports(out_dir, cfg, checks, metrics, extra_dirs=()):
    write_json(os.path.join(out_dir, "data_dictionary.json"),
               {t: dict(description=m["desc"], primary_key=m["pk"], cardinality=m["card"], lifecycle=m["life"],
                        foreign_keys=[dict(column=c, references="%s.%s" % (rt, rc)) for c, rt, rc in m["fks"]],
                        fields=m["fields"]) for t, m in TABLES.items()})
    with open(os.path.join(out_dir, "schema.sql"), "w", encoding="utf-8", newline="\n") as f:
        f.write(ddl())
    dd = data_dictionary_markdown()
    vm = validation_markdown(checks, metrics, cfg)
    for folder, dd_name, vm_name in [(out_dir, "data_dictionary.md", "validation_summary.md")] + list(extra_dirs):
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, dd_name), "w", encoding="utf-8", newline="\n") as f:
            f.write(dd)
        with open(os.path.join(folder, vm_name), "w", encoding="utf-8", newline="\n") as f:
            f.write(vm + "\n")
    passed = sum(1 for c in checks if c["status"] == "PASS")
    write_json(os.path.join(out_dir, "validation_summary.json"), dict(passed=passed, total=len(checks), checks=checks))
    write_json(os.path.join(out_dir, "metrics.json"), metrics)
    write_json(os.path.join(out_dir, "source_manifest.json"), dict(
        external_data_used=False,
        note="Every value is produced by this repository's generator. Names, fees, FX rates and amounts are invented. "
             "No public dataset was downloaded, so there is no licence or attribution to record.",
        schema_inspiration="general payment-processor settlement report layouts (no data copied)"))
