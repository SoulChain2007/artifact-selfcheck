"""Standard-library CLI regressions; run: python -m unittest discover -s tests -p test_runtime.py -v."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        # Keep scratch under the chosen working directory: sandboxed Windows
        # hosts may advertise a redirected TEMP which cannot actually be written.
        self.tmp = tempfile.TemporaryDirectory(prefix="selfcheck-runtime-", dir=Path.cwd())
        self.assertEqual(Path.cwd().resolve(), Path(self.tmp.name).resolve().parent)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def invoke(self, script, *args):
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        child = subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)],
                               capture_output=True, encoding="utf-8", env=env, timeout=10)
        self.assertEqual("", child.stderr, child.stderr)
        return child.returncode, json.loads(child.stdout)

    def pipeline(self, checks, extra=()):
        config = self.write("config.json", json.dumps({"checks": checks}))
        return self.invoke("pipeline.py", "--config", config, "--json", *extra)

    def intake(self, text):
        ledger = self.write("intake.jsonl", text)
        return self.invoke("source_intake.py", "--ledger", ledger, "--json")

    def valid_record(self):
        return {"source": "Author, primary source, 2026", "surface": "official docs",
                "reading": "version 1", "quote": "The supported statement.",
                "counter": "Checked limitations; limited to this scope.",
                "target": "references/lenses.md:L5", "verdict": "adopt", "detector": "test_runtime.py"}

    def test_valid_intake_clean(self):
        rc, result = self.intake(json.dumps(self.valid_record()))
        self.assertEqual((0, "CLEAN", 1, 1), (rc, result["status"], result["rows"], result["adopted"]))

    def test_empty_and_comment_only_intake_findings(self):
        for text in ("", " \n# no evidence\n"):
            with self.subTest(text=text):
                rc, result = self.intake(text)
                self.assertEqual((1, "FIND", 0), (rc, result["status"], result["rows"]))
                self.assertTrue(result["violations"])

    def test_intake_nonobjects_and_malformed_json_do_not_crash(self):
        for text in ('null', '[]', '4', '"text"', '{oops'):
            with self.subTest(text=text):
                rc, result = self.intake(text)
                self.assertEqual((1, "FIND"), (rc, result["status"]))
                self.assertEqual(1, result["violations"][0]["line"])

    def test_intake_null_blank_and_nontext_required_fields(self):
        for field in self.valid_record():
            for value in (None, " ", [], 0):
                with self.subTest(field=field, value=value):
                    record = self.valid_record()
                    record[field] = value
                    rc, result = self.intake(json.dumps(record))
                    self.assertEqual(1, rc)
                    self.assertTrue(any(v.get("field") == field for v in result["violations"]))

    def test_intake_enum_and_placeholder_evidence(self):
        for field, value in (("verdict", "banana"), ("quote", "N/A"), ("counter", "无")):
            record = self.valid_record()
            record[field] = value
            rc, result = self.intake(json.dumps(record))
            self.assertEqual((1, "FIND"), (rc, result["status"]))

    def test_intake_missing_input_is_execution_error(self):
        rc, result = self.invoke("source_intake.py", "--ledger", self.root / "missing", "--json")
        self.assertEqual((2, "ERROR"), (rc, result["status"]))

    def test_pipeline_valid_clean_and_successful_stamp(self):
        self.write("clean.py", 'print("measured: 0 defects")\n')
        stamp = self.root / "stamp.json"
        rc, result = self.pipeline([{"script": "clean.py"}], ["--stamp", str(stamp)])
        self.assertEqual((0, "CLEAN", 1), (rc, result["status"], result["clean"]))
        self.assertEqual(result, json.loads(stamp.read_text(encoding="utf-8")))

    def test_pipeline_true_findings_json_and_text_protocol(self):
        for flags in ([], ["--json"]):
            with self.subTest(flags=flags):
                self.write("empty.jsonl", "")
                rc, result = self.pipeline([{"script": str(SCRIPTS / "source_intake.py"), "args": ["--ledger", str(self.root / "empty.jsonl"), *flags]}])
                self.assertEqual((0, "FIND", 1, 0), (rc, result["status"], result["findings"], result["errors"]))

    def test_pipeline_crash_is_error_not_finding(self):
        self.write("crash.py", 'raise RuntimeError("detector crashed")\n')
        rc, result = self.pipeline([{"script": "crash.py"}])
        self.assertEqual((1, "ERROR", 0), (rc, result["status"], result["findings"]))
        self.assertIn("RuntimeError", result["rows"][0]["stderr"])

    def test_pipeline_marker_before_crash_is_still_error(self):
        self.write("crash.py", 'print("ARTIFACT_SELFCHECK_FIND")\nraise RuntimeError("crash after marker")\n')
        rc, result = self.pipeline([{"script": "crash.py"}])
        self.assertEqual((1, "ERROR"), (rc, result["status"]))

    def test_pipeline_exit_one_without_protocol_is_error(self):
        self.write("error.py", 'import sys\nprint("input missing")\nsys.exit(1)\n')
        rc, result = self.pipeline([{"script": "error.py"}])
        self.assertEqual((1, "ERROR"), (rc, result["status"]))

    def test_pipeline_legacy_protocol_requires_explicit_marker(self):
        self.write("legacy.py", 'import sys\nprint("KNOWN_RULE_FAIL")\nsys.exit(7)\n')
        rc, result = self.pipeline([{"script": "legacy.py", "finding_codes": [7], "finding_marker": "KNOWN_RULE_FAIL"}])
        self.assertEqual((0, "FIND"), (rc, result["status"]))

    def test_pipeline_explicit_protocol_error_cannot_be_green(self):
        for exit_code in (0, 1, 2):
            with self.subTest(exit_code=exit_code):
                payload = {"selfcheck_protocol": 1, "status": "ERROR", "error": "invalid input"}
                self.write("protocol.py", "import sys\nprint(%r)\nsys.exit(%d)\n" % (json.dumps(payload), exit_code))
                rc, result = self.pipeline([{"script": "protocol.py"}])
                self.assertEqual((1, "ERROR", 0), (rc, result["status"], result["clean"]))
                self.assertEqual("ERROR", result["rows"][0]["verdict"])

    def test_pipeline_protocol_status_must_match_exit_code(self):
        for status, exit_code in (("FIND", 0), ("CLEAN", 1), ("CLEAN", 7)):
            with self.subTest(status=status, exit_code=exit_code):
                text = json.dumps({"selfcheck_protocol": 1, "status": status})
                self.write("protocol.py", "import sys\nprint(%r)\nsys.exit(%d)\n" % (text, exit_code))
                # A configured marker cannot override contradictory JSON.
                rc, result = self.pipeline([{"script": "protocol.py", "finding_codes": [1, 7], "finding_marker": text}])
                self.assertEqual((1, "ERROR"), (rc, result["status"]))

    def test_pipeline_valid_protocol_clean(self):
        text = json.dumps({"selfcheck_protocol": 1, "status": "CLEAN"})
        self.write("protocol.py", "print(%r)\n" % text)
        rc, result = self.pipeline([{"script": "protocol.py"}])
        self.assertEqual((0, "CLEAN"), (rc, result["status"]))

    def test_pipeline_nonprotocol_json_remains_legacy_output(self):
        for payload in ({"status": "ERROR", "error": "domain data"}, {"status": "FIND"}, ["ERROR"], None):
            with self.subTest(payload=payload):
                self.write("ordinary.py", "print(%r)\n" % json.dumps(payload))
                rc, result = self.pipeline([{"script": "ordinary.py"}])
                self.assertEqual((0, "CLEAN"), (rc, result["status"]))

    def test_pipeline_invalid_protocol_envelope_is_error(self):
        for payload in ({"selfcheck_protocol": 1}, {"selfcheck_protocol": 1, "status": "UNKNOWN"},
                        {"selfcheck_protocol": True, "status": "CLEAN"}, {"selfcheck_protocol": 2, "status": "CLEAN"}):
            with self.subTest(payload=payload):
                self.write("protocol.py", "print(%r)\n" % json.dumps(payload))
                rc, result = self.pipeline([{"script": "protocol.py"}])
                self.assertEqual((1, "ERROR"), (rc, result["status"]))

    def test_pipeline_child_missing_input_is_error(self):
        rc, result = self.pipeline([{"script": str(SCRIPTS / "source_intake.py"), "args": ["--ledger", str(self.root / "missing"), "--json"]}])
        self.assertEqual((1, "ERROR", 2), (rc, result["status"], result["rows"][0]["rc"]))

    def test_pipeline_bad_config_is_structured_error(self):
        cases = ([], {}, {"checks": []}, {"checks": "bad"}, {"checks": [None]},
                 {"checks": [{"script": ""}]}, {"checks": [{"script": "x", "args": "bad"}]},
                 {"checks": [{"script": "x", "finding_codes": [True]}]},
                 {"checks": [{"script": "x", "finding_marker": ""}]})
        for cfg in cases:
            with self.subTest(cfg=cfg):
                path = self.write("config.json", json.dumps(cfg))
                rc, result = self.invoke("pipeline.py", "--config", path, "--json")
                self.assertEqual((1, "ERROR", 0), (rc, result["status"], result["checks"]))
                self.assertIn("config_error", result)

    def test_pipeline_missing_and_malformed_config(self):
        for path in (self.root / "missing.json", self.write("bad.json", "{")):
            rc, result = self.invoke("pipeline.py", "--config", path, "--json")
            self.assertEqual((1, "ERROR"), (rc, result["status"]))

    def test_pipeline_never_substitutes_same_basename(self):
        # The bundle contains source_intake.py; the explicitly selected path does not.
        rc, result = self.pipeline([{"script": "missing/source_intake.py"}])
        self.assertEqual((1, "ERROR", None), (rc, result["status"], result["rows"][0]["rc"]))
        self.assertIn("missing", result["rows"][0]["script"])

    def test_pipeline_stamp_write_failure_is_error_with_valid_json(self):
        self.write("clean.py", "pass\n")
        rc, result = self.pipeline([{"script": "clean.py"}], ["--stamp", str(self.root)])
        self.assertEqual((1, "ERROR", 1), (rc, result["status"], result["errors"]))
        self.assertIn("stamp_error", result)


if __name__ == "__main__":
    unittest.main()
