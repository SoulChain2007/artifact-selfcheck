#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Validate the external-method intake JSONL ledger.

Each non-comment line is an object with nonempty text fields: source, surface,
reading, quote, counter, target, verdict, detector. Verdict is adopt/weak/reject.
This verifies record structure, not the truth or quality of source evidence.
Exit 0: valid nonempty ledger; 1: content findings; 2: unreadable input.
JSON outputs use selfcheck_protocol=1 and status=CLEAN/FIND/ERROR. Text findings
include the standalone ARTIFACT_SELFCHECK_FIND marker for pipeline integration.
"""
import argparse
import json
from pathlib import Path
import sys

REQUIRED = ("source", "surface", "reading", "quote", "counter", "target", "verdict", "detector")
VERDICTS = {"adopt", "weak", "reject"}
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def audit(text):
    rows, violations = [], []
    for number, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            record = json.loads(line)
        except ValueError as error:
            violations.append({"line": number, "why": "invalid JSON: %s" % error})
            continue
        if not isinstance(record, dict):
            violations.append({"line": number, "why": "record must be a JSON object"})
            continue
        rows.append(record)
        for key in REQUIRED:
            value = record.get(key)
            if not isinstance(value, str) or not value.strip():
                violations.append({"line": number, "field": key, "why": "required nonempty text field: %s" % key})
        verdict = record.get("verdict")
        if isinstance(verdict, str) and verdict.strip().lower() not in VERDICTS:
            violations.append({"line": number, "field": "verdict", "why": "verdict must be adopt, weak or reject"})
        for key, empty_markers in (("quote", {"-", "无", "n/a"}), ("counter", {"-", "无"})):
            value = record.get(key)
            if isinstance(value, str) and value.strip().lower() in empty_markers:
                violations.append({"line": number, "field": key, "why": "%s is a placeholder, not evidence" % key})
    if not rows:
        violations.append({"why": "ledger has no object records; no intake evidence was checked"})
    return rows, violations


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = {"selfcheck_protocol": 1, "ledger": args.ledger, "rows": 0, "violations": [], "adopted": 0, "rejected": 0}
    try:
        rows, violations = audit(Path(args.ledger).read_text(encoding="utf-8-sig"))
        result.update(rows=len(rows), violations=violations,
                      adopted=sum(isinstance(row.get("verdict"), str) and row["verdict"].strip().lower() == "adopt" for row in rows),
                      rejected=sum(isinstance(row.get("verdict"), str) and row["verdict"].strip().lower() == "reject" for row in rows))
        result["status"] = "FIND" if violations else "CLEAN"
        rc = 1 if violations else 0
    except (OSError, UnicodeError) as error:
        result.update(status="ERROR", error=str(error))
        rc = 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print("外部方法准入结构检查：%s，记录 %d，违规 %d" % (result["status"], result["rows"], len(result["violations"])))
        for violation in result["violations"]:
            print("line %s: %s" % (violation.get("line", "-"), violation["why"]))
        if "error" in result:
            print(result["error"])
        if result["status"] == "FIND":
            print("ARTIFACT_SELFCHECK_FIND")
    return rc


if __name__ == "__main__":
    sys.exit(main())
