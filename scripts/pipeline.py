#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Run configured checks and distinguish CLEAN, FIND and ERROR.

Exit 0 means every check ran; findings remain work to do. Exit 1 means an
execution/configuration/stamp error. A child exit 1 alone is NOT a finding.
FIND needs an allowed nonzero code (finding_codes, default [1]), no stderr,
and JSON selfcheck_protocol=1/status="FIND" or a standalone
ARTIFACT_SELFCHECK_FIND line. Legacy checks may explicitly configure their
own standalone finding_marker after reviewing the output contract.
Versioned JSON statuses must agree with the exit code: ERROR always fails,
FIND requires an allowed nonzero code, and CLEAN requires zero. Other JSON
without the reserved selfcheck_protocol key stays ordinary legacy output.
Scripts resolve relative to config; no basename substitution. Use
{skill}/scripts/... to deliberately select bundled checks.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import time

SKILL = str(Path(__file__).resolve().parent.parent)
FIND_MARKER = "ARTIFACT_SELFCHECK_FIND"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except (AttributeError, ValueError):
    pass


def expand(value, context):
    for key, replacement in context.items():
        value = value.replace("{%s}" % key, str(replacement))
    return value


def validate_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError("config must be a JSON object")
    checks = cfg.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ValueError("checks must be a nonempty list; empty pipeline did not run")
    for index, check in enumerate(checks, 1):
        if not isinstance(check, dict):
            raise ValueError("check %d must be an object" % index)
        if not isinstance(check.get("script"), str) or not check["script"].strip():
            raise ValueError("check %d needs a nonempty script path" % index)
        args = check.get("args", [])
        if not isinstance(args, list) or any(not isinstance(arg, str) for arg in args):
            raise ValueError("check %d args must be a list of strings" % index)
        codes = check.get("finding_codes", [1])
        if not isinstance(codes, list) or not codes or any(type(code) is not int or code <= 0 for code in codes):
            raise ValueError("check %d finding_codes must be positive integers" % index)
        marker = check.get("finding_marker", FIND_MARKER)
        if not isinstance(marker, str) or not marker.strip() or len(marker.splitlines()) != 1:
            raise ValueError("check %d finding_marker must be a nonempty single line" % index)
    return checks


def classify_check(check, rc, stdout, stderr):
    """Respect explicit protocol failures before applying legacy exit rules."""
    try:
        payload = json.loads(stdout)
    except (ValueError, TypeError):
        payload = None
    if isinstance(payload, dict) and "selfcheck_protocol" in payload:
        # The reserved key opts into this protocol. Invalid/unknown versions
        # and incomplete envelopes cannot silently become legacy successes.
        if type(payload["selfcheck_protocol"]) is not int or payload["selfcheck_protocol"] != 1:
            return "ERROR"
        status = payload.get("status")
        if status == "CLEAN" and rc == 0:
            return "CLEAN"
        if status == "FIND" and rc in check.get("finding_codes", [1]) and not stderr.strip():
            return "FIND"
        return "ERROR"
    if rc == 0:
        return "CLEAN"
    if rc not in check.get("finding_codes", [1]) or stderr.strip():
        return "ERROR"
    marker = check.get("finding_marker", FIND_MARKER).strip()
    return "FIND" if marker in (line.strip() for line in stdout.splitlines()) else "ERROR"


def finish(result):
    result["clean"] = sum(row["verdict"] == "CLEAN" for row in result["rows"])
    result["findings"] = sum(row["verdict"] == "FIND" for row in result["rows"])
    result["errors"] = sum(row["verdict"] == "ERROR" for row in result["rows"]) + int("config_error" in result) + int("stamp_error" in result)
    result["checks"] = len(result["rows"])
    result["status"] = "ERROR" if result["errors"] else ("FIND" if result["findings"] else "CLEAN")
    result["summary"] = "自检流水：通过 %d/%d（有发现 %d，错误 %d）" % (result["clean"], result["checks"], result["findings"], result["errors"])


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--config", required=True)
    ap.add_argument("--stamp", default="")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--timeout", type=int, default=900)
    args = ap.parse_args(argv)
    result = {"selfcheck_protocol": 1, "config": args.config, "rows": [], "at": time.strftime("%Y-%m-%d %H:%M:%S")}
    try:
        if args.timeout <= 0:
            raise ValueError("timeout must be positive")
        config_path = Path(args.config).resolve()
        cfg = json.loads(config_path.read_text(encoding="utf-8-sig"))
        checks = validate_config(cfg)
        context = dict(cfg)
        context["skill"] = str(cfg.get("skill") or SKILL)
        context.setdefault("seed", 40)
        for check in checks:
            script = Path(expand(check["script"], context))
            if not script.is_absolute():
                script = config_path.parent / script
            script = script.resolve()
            child_args = [expand(value, context) for value in check.get("args", [])]
            started = time.monotonic()
            rc, stdout, stderr = None, "", ""
            try:
                if not script.is_file():
                    raise FileNotFoundError("script not found: %s" % script)
                child = subprocess.run([sys.executable, str(script)] + child_args, capture_output=True, timeout=args.timeout)
                rc = child.returncode
                stdout = child.stdout.decode("utf-8", "replace")
                stderr = child.stderr.decode("utf-8", "replace")
            except (OSError, subprocess.SubprocessError) as error:
                stderr = str(error)
            verdict = classify_check(check, rc, stdout, stderr)
            lines = (stderr if verdict == "ERROR" and stderr.strip() else stdout).strip().splitlines()
            result["rows"].append({"name": str(check.get("name") or script.name), "script": str(script), "rc": rc,
                                   "verdict": verdict, "seconds": round(time.monotonic() - started, 3),
                                   "tail": lines[-1][:240] if lines else "", "stdout": stdout, "stderr": stderr})
    except (OSError, ValueError, TypeError) as error:
        result["config_error"] = str(error)
    finish(result)
    if args.stamp:
        try:
            Path(args.stamp).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as error:
            result["stamp_error"] = str(error)
            finish(result)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        for row in result["rows"]:
            print("%s %s rc=%s: %s" % (row["verdict"], row["name"], row["rc"], row["tail"]))
        for key in ("config_error", "stamp_error"):
            if key in result:
                print("ERROR %s: %s" % (key, result[key]))
        print(result["summary"])
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
