"""Independent, temporary fixtures for sampling and coverage contracts.

No historical report or other test's diagnostic output is used as an oracle.
Run: python -m unittest discover -s tests -p test_sampling.py -v
"""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("sampling_audit_under_test", SCRIPTS / "sampling_audit.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class FixtureCase(unittest.TestCase):
    def setUp(self):
        # The managed Windows runtime's default TEMP may not be writable.
        self.temp = tempfile.TemporaryDirectory(prefix="sampling_contract_", dir=SCRIPTS.parent)
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "project"
        self.root.mkdir()

    def write(self, relative, content, root=None):
        target = (root or self.root) / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target

    def cli(self, script, *args, as_json=True):
        command = [sys.executable, str(SCRIPTS / script), *map(str, args)]
        if as_json:
            command.append("--json")
        completed = subprocess.run(command, encoding="utf-8", capture_output=True)
        if as_json:
            data = json.loads(completed.stdout)
            self.assertEqual(data["selfcheck_protocol"], 1)
            self.assertEqual(data["status"], {0: "CLEAN", 1: "FIND", 2: "ERROR"}[completed.returncode])
            return completed.returncode, data
        return completed


class SampleTraceTests(FixtureCase):
    def test_dangling_ids_are_detected_instead_of_zero_references(self):
        for identifier in ("CARD-PRINT-999", "WORLD-RULE-A-12345", "ACT-1", "Card-Mixed-42"):
            with self.subTest(identifier=identifier):
                self.write("sample.md", "见 " + identifier)
                code, result = self.cli("sample_trace.py", self.root)
                self.assertEqual(code, 1)
                self.assertEqual(result["samples"][0]["refs"], 1)
                self.assertEqual(result["samples"][0]["dangling"][0]["ref"], identifier)

    def test_plain_mentions_do_not_define_each_other(self):
        self.write("a.md", "见 CARD-PRINT-999")
        self.write("b.md", "再次引用 CARD-PRINT-999")
        code, result = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 1)
        self.assertEqual(result["dangling_total"], 2)

    def test_structured_id_and_alias_definitions(self):
        self.write("sample.md", "见 CARD-PRINT-999、WORLD-RULE-A-12345、ACT-42")
        self.write("_definitions.yaml", "id: CARD-PRINT-999\naliases:\n  - WORLD-RULE-A-12345\n  - ACT-42\n")
        code, result = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 0)
        self.assertEqual(result["pool"], 1)

    def test_heading_and_filename_definitions(self):
        self.write("sample.md", "见 CARD-PRINT-999、WORLD-RULE-A-12345")
        self.write("_definitions.md", "# CARD-PRINT-999 印刷规则")
        self.write("_WORLD-RULE-A-12345.md", "规则正文")
        code, _ = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 0)

    def test_compact_nested_json_definitions(self):
        self.write("sample.md", "见 CARD-PRINT-999、WORLD-RULE-A-12345")
        self.write("_defs.json", json.dumps({"cards": [{"id": "CARD-PRINT-999", "aliases": ["WORLD-RULE-A-12345"]}]}))
        code, _ = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 0)

    def test_external_alias_requires_explicit_search_root(self):
        external = self.base / "external"
        self.write("sample.md", "见 CARD-PRINT-999")
        self.write("definitions.yaml", "id: CARD-PRINT-1\naliases: [CARD-PRINT-999]", root=external)
        code, _ = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 1)
        code, result = self.cli("sample_trace.py", self.root, "--also", external)
        self.assertEqual(code, 0)
        self.assertEqual(result["pool"], 1, "external files are not added to the sample pool")
        self.assertEqual(set(result["roots_searched"]), {str(self.root), str(external)})

    def test_project_auto_is_opt_in_and_does_not_expand_pool(self):
        self.write("sample.md", "见 CARD-PRINT-999")
        self.write("defs.yaml", "id: CARD-PRINT-999", root=self.base / "sibling")
        code, result = self.cli("sample_trace.py", self.root, "--project-auto")
        self.assertEqual(code, 0)
        self.assertEqual(result["pool"], 1)

    def test_missing_root_empty_pool_and_invalid_n_are_errors(self):
        for args in ((self.root / "missing",), (self.root,), (self.root, "--n", 0), (self.root, "--n", -1)):
            with self.subTest(args=args):
                code, _ = self.cli("sample_trace.py", *args)
                self.assertEqual(code, 2)

    def test_missing_extra_root_is_error_not_silently_ignored(self):
        self.write("sample.md", "无引用的有效文本")
        code, _ = self.cli("sample_trace.py", self.root, "--also", self.base / "missing")
        self.assertEqual(code, 2)

    def test_seed_reproduces_selection_after_directory_order_changes(self):
        for index in range(12):
            self.write("d%d/item.md" % index, "有效正文")
        code, first = self.cli("sample_trace.py", self.root, "--n", 4, "--seed", 17)
        self.assertEqual(code, 0)
        # Recreate in reverse insertion order; filesystem order must not affect it.
        for index in reversed(range(12)):
            path = self.root / ("d%d/item.md" % index)
            content = path.read_text(encoding="utf-8")
            path.unlink()
            path.write_text(content, encoding="utf-8")
        _, second = self.cli("sample_trace.py", self.root, "--n", 4, "--seed", 17)
        self.assertEqual(first["samples"], second["samples"])
        self.assertEqual(first["sampled"], 4)
        self.assertEqual(first["pool"], 12)

    def test_path_and_number_references_resolve_without_double_counting(self):
        self.write("sample.md", "见 docs/12_rules.md 和 docs/12")
        self.write("docs/12_rules.md", "正文")
        code, result = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 0)
        sample = next(row for row in result["samples"] if row["file"] == "sample.md")
        self.assertEqual(sample["refs"], 2)

    def test_number_reference_cannot_match_unrelated_same_number(self):
        self.write("sample.md", "见 docs/12")
        self.write("other/12_wrong.md", "不应匹配")
        code, _ = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 1)

    def test_url_id_and_number_are_unverified_not_dangling(self):
        self.write("sample.md", "https://example.invalid/docs/12/CARD-PRINT-999")
        code, result = self.cli("sample_trace.py", self.root)
        self.assertEqual(code, 0)
        self.assertEqual(result["samples"][0]["unverified_refs"], 1)
        self.assertEqual(result["samples"][0]["refs"], 1)

    def test_text_find_marker_is_a_standalone_line(self):
        self.write("sample.md", "见 CARD-PRINT-999")
        result = self.cli("sample_trace.py", self.root, as_json=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ARTIFACT_SELFCHECK_FIND", result.stdout.splitlines())


class SamplingAuditTests(FixtureCase):
    def check_report(self, body, count=5, pool=10, coverage="其余 5 个文件未查", ratio=1.0):
        path = self.write("report.md", "抽 %d / 池 %d\n%s\n%s" % (count, pool, coverage, body))
        return audit.audit_report(path, ratio)

    def test_bare_ids_are_not_readings(self):
        result = self.check_report("\n".join("CARD-PRINT-%d" % n for n in range(5)))
        self.assertEqual(result["item_lines"], 0)
        self.assertTrue(result["issues"])

    def test_duplicates_do_not_satisfy_threshold(self):
        result = self.check_report("\n".join(["CARD-PRINT-999 bytes=123"] * 4))
        self.assertEqual(result["item_lines"], 1)
        self.assertTrue(result["issues"])

    def test_equivalent_path_spellings_are_deduplicated(self):
        result = self.check_report("`docs/a.md` bytes=123\n`./docs/a.md` bytes=123\n`docs/../docs/a.md` bytes=123")
        self.assertEqual(result["item_lines"], 1)
        self.assertTrue(result["issues"])

    def test_distinct_historical_id_readings_are_accepted(self):
        # Controlled representation of old reports: IDs plus checkmarks/ratios.
        rows = ["CARD-PRINT-101 ✅", "CARD-PRINT-102 2/2", "CARD-PRINT-103 引用 3 条", "CARD-PRINT-104 读数：0", "CARD-PRINT-105 bytes=16"]
        result = self.check_report("\n".join(rows))
        self.assertEqual(result["item_lines"], 5)
        self.assertFalse(result["issues"])
        self.assertTrue(result["evidence_complete"])

    def test_historical_backticked_paths_units_and_table_cells(self):
        result = self.check_report("\n".join(["`cards/a.yaml` 126 B", "`docs/b.md` 行数: 42",
                                                "| `cards/c.json` | 0 |", "`scripts/d.py` PASS", "`docs/e.md` refs=2"]))
        self.assertEqual(result["item_lines"], 5)
        self.assertFalse(result["issues"])

    def test_filename_digits_and_list_ordinals_are_not_readings(self):
        result = self.check_report("1. `docs/2026.md`\n2. CARD-PRINT-123\n| CARD-PRINT-123 |\n| 3 | CARD-PRINT-124 |")
        self.assertEqual(result["item_lines"], 0)
        self.assertTrue(result["issues"])

    def test_multiple_ids_with_shared_reading_are_not_independent_rows(self):
        result = self.check_report("CARD-PRINT-1、CARD-PRINT-2、CARD-PRINT-3、CARD-PRINT-4 共 4 条")
        self.assertEqual(result["item_lines"], 0)
        self.assertTrue(result["issues"])

    def test_ratio_uses_ceiling_not_floor(self):
        result = self.check_report("CARD-PRINT-1 ✅", count=2, pool=10, ratio=0.8)
        self.assertTrue(result["issues"])

    def test_default_requires_five_unique_readings_for_claim_of_five(self):
        # Contract correction: the old default ratio 0.8 admitted four/five.
        # L6's N-readings requirement makes that FIND by default, regardless
        # of any current report's score; only explicit tolerance can admit it.
        rows = ["CARD-PRINT-%d bytes=10" % n for n in range(5)]
        for observed, expected_code in ((4, 1), (5, 0)):
            with self.subTest(observed=observed):
                self.check_report("\n".join(rows[:observed]))
                code, payload = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md")
                self.assertEqual(code, expected_code)
                self.assertEqual(payload["min_item_ratio"], 1.0)
                self.assertEqual(payload["evidence_mode"], "full_evidence")
                self.assertEqual(payload["evidence_complete"], observed == 5)
                self.assertEqual(payload["rows"][0]["evidence_complete"], observed == 5)

    def test_explicit_tolerance_is_not_complete_evidence(self):
        rows = "\n".join("CARD-PRINT-%d bytes=10" % n for n in range(4))
        self.check_report(rows)
        code, payload = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md", "--min-item-ratio", 0.8)
        self.assertEqual(code, 0)
        self.assertEqual(payload["evidence_mode"], "heuristic_tolerance")
        self.assertFalse(payload["evidence_complete"])
        self.assertFalse(payload["rows"][0]["evidence_complete"])
        self.assertEqual(payload["rows"][0]["evidence_required"], 5)
        result = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md", "--min-item-ratio", 0.8, as_json=False)
        self.assertEqual(result.returncode, 0)
        self.assertIn("heuristic/tolerance", result.stdout)
        self.assertIn("evidence_complete=false", result.stdout)
        # Opting into tolerance never removes the scope declaration rule.
        self.check_report(rows, coverage="")
        code, _ = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md", "--min-item-ratio", 0.8)
        self.assertEqual(code, 1)

    def test_partial_sample_cannot_hide_simultaneous_exhaustive_claim(self):
        path = self.write("report.md", "抽 1 / 池 10\n其余 9 未查\n全量读数，共 10 条\nCARD-PRINT-1 bytes=10")
        result = audit.audit_report(path)
        self.assertTrue(result["issues"])
        self.assertFalse(result["coverage_claims_consistent"])
        self.assertFalse(result["evidence_complete"])
        self.assertEqual(result["evidence_required"], 10)
        code, _ = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md")
        self.assertEqual(code, 1)

    def test_equal_full_sample_and_exhaustive_claim_can_pass(self):
        path = self.write("report.md", "抽 2 / 池 2\n全量读数，共 2 条\nCARD-PRINT-1 bytes=10\nCARD-PRINT-2 bytes=12")
        result = audit.audit_report(path)
        self.assertFalse(result["issues"])
        self.assertTrue(result["coverage_claims_consistent"])
        self.assertTrue(result["evidence_complete"])

    def test_exhaustive_total_must_match_equal_sample_and_pool(self):
        path = self.write("report.md", "抽 2 / 池 2\n全量读数，共 3 条\nCARD-PRINT-1 bytes=10\nCARD-PRINT-2 bytes=12")
        result = audit.audit_report(path)
        self.assertTrue(result["issues"])
        self.assertFalse(result["coverage_claims_consistent"])

    def test_negated_exhaustive_phrases_do_not_invent_full_coverage(self):
        for statement in ("本轮不做全量", "本轮不做全量读数", "尚未穷尽", "不是全量推进"):
            with self.subTest(statement=statement):
                path = self.write("report.md", "抽 1 / 池 10\n其余 9 未查\n%s\nCARD-PRINT-1 bytes=10" % statement)
                result = audit.audit_report(path)
                self.assertFalse(result["issues"])
                self.assertFalse(result["exhaustive"])

    def test_zero_count_zero_pool_and_oversized_sample_fail(self):
        for count, pool in ((0, 10), (0, 0), (1, 0), (2, 1)):
            with self.subTest(count=count, pool=pool):
                result = self.check_report("CARD-PRINT-1 ✅\nCARD-PRINT-2 ✅", count=count, pool=pool)
                self.assertTrue(result["issues"])

    def test_missing_pool_fails(self):
        path = self.write("report.md", "抽样数：1\nCARD-PRINT-1 ✅\n只对抽样框负责")
        self.assertTrue(audit.audit_report(path, 0.8)["issues"])

    def test_exhaustive_empty_and_unread_sets_fail(self):
        for text in ("穷尽，池大小：0", "全量读数，共 0 条", "穷尽，共 10 条"):
            with self.subTest(text=text):
                path = self.write("report.md", text)
                self.assertTrue(audit.audit_report(path, 0.8)["issues"])

    def test_positive_exhaustive_with_evidence(self):
        path = self.write("report.md", "穷尽，共 2 条\nCARD-PRINT-1 ✅\nCARD-PRINT-2 ✅")
        self.assertFalse(audit.audit_report(path, 0.8)["issues"])

    def test_missing_coverage_declaration_fails(self):
        result = self.check_report("\n".join("CARD-PRINT-%d ✅" % n for n in range(5)), coverage="")
        self.assertTrue(result["issues"])

    def test_glob_empty_missing_directory_and_invalid_options_error(self):
        for args in (("--reports", self.base / "missing"), ("--reports", self.root),
                     ("--reports", self.root, "--last", 0),
                     ("--reports", self.root, "--min-item-ratio", 0),
                     ("--reports", self.root, "--min-item-ratio", "nan")):
            with self.subTest(args=args):
                code, _ = self.cli("sampling_audit.py", *args)
                self.assertEqual(code, 2)

    def test_cli_clean_and_find_protocol(self):
        self.write("report.md", "抽 1 / 池 1\nCARD-PRINT-1 bytes=2")
        code, _ = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md")
        self.assertEqual(code, 0)
        self.write("report.md", "抽 1 / 池 1\nCARD-PRINT-1")
        code, result = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md")
        self.assertEqual(code, 1)
        self.assertEqual(result["rows"][0]["item_lines"], 0)
        result = self.cli("sampling_audit.py", "--reports", self.root, "--glob", "*.md", as_json=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("ARTIFACT_SELFCHECK_FIND", result.stdout.splitlines())


if __name__ == "__main__":
    unittest.main()
