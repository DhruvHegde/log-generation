"""parser/parser_v2_tests.py

Comprehensive test suite for Parser V2.
Validates:
1. Generalized failure detection across F1, F2, F3, F4
2. Category-specific evidence extraction (syntax, dependency, pytest, timeout)
3. Step sequence and failed step extraction
4. Traceback block extraction (F1, F3) vs no traceback (F2, F4)
5. Ensuring ##[error] alone never determines failure category
6. Ensuring Python exceptions in pytest remain failure_class='test_failure'
7. Confidence scoring and unknown/fallback handling
8. Batch parsing APIs
"""

import unittest
from pathlib import Path
from parser.log_parser import (
    LogRecord,
    parse_log_text,
    parse_log_file,
    parse_batch,
    parse_all_categories,
)

BASE_DIR = Path(__file__).resolve().parent.parent / "logs"


class TestParserV2F1Syntax(unittest.TestCase):
    """F1: Python Syntax/Indentation/Tab errors."""

    def test_f1_real_log(self):
        f1_path = BASE_DIR / "F1" / "run_0001.log"
        if not f1_path.exists():
            self.skipTest("F1/run_0001.log not found")

        rec = parse_log_file(f1_path)
        self.assertEqual(rec.failure_class, "syntax_error")
        self.assertIn(rec.failure_subcategory, ("SyntaxError", "IndentationError", "TabError"))
        self.assertEqual(rec.failed_step, "Check App Syntax")
        self.assertEqual(rec.status, "failure")
        self.assertGreaterEqual(rec.parser_confidence, 0.8)
        self.assertTrue(len(rec.traceback_lines) > 0)
        self.assertTrue(len(rec.evidence_lines) > 0)
        self.assertIsNotNone(rec.file_path)
        self.assertIsNotNone(rec.line_number)
        self.assertIn("Check App Syntax", rec.step_sequence)
        self.assertEqual(rec.execution_path[-1], "Check App Syntax")


class TestParserV2F2Dependency(unittest.TestCase):
    """F2: Pip dependency installation errors."""

    def test_f2_real_log(self):
        f2_path = BASE_DIR / "F2" / "run_0005.log"
        if not f2_path.exists():
            self.skipTest("F2/run_0005.log not found")

        rec = parse_log_file(f2_path)
        self.assertEqual(rec.failure_class, "dependency_error")
        self.assertEqual(rec.failed_step, "Install Dependencies")
        self.assertEqual(rec.status, "failure")
        self.assertGreaterEqual(rec.parser_confidence, 0.8)
        self.assertEqual(rec.failing_package, "abcxyzpackage")
        self.assertTrue(len(rec.pip_commands) > 0)
        self.assertTrue(len(rec.evidence_lines) > 0)
        # Traceback should NOT be present for pip errors
        self.assertEqual(len(rec.traceback_lines), 0)
        self.assertEqual(rec.execution_path[-1], "Install Dependencies")

    def test_f2_invalid_requirement_variation(self):
        f2_path = BASE_DIR / "F2" / "run_0011.log"
        if not f2_path.exists():
            self.skipTest("F2/run_0011.log not found")

        rec = parse_log_file(f2_path)
        self.assertEqual(rec.failure_class, "dependency_error")
        self.assertEqual(rec.failure_subcategory, "pip_invalid_requirement")
        self.assertEqual(rec.failing_package, "requests=>=abc")


class TestParserV2F3Pytest(unittest.TestCase):
    """F3: Pytest test failures in GitHub Actions runner format."""

    def test_f3_real_log(self):
        # Pick first available F3 log
        f3_files = list((BASE_DIR / "F3").glob("*.log"))
        if not f3_files:
            self.skipTest("No F3 logs found")

        rec = parse_log_file(f3_files[0])
        self.assertEqual(rec.failure_class, "test_failure")
        self.assertEqual(rec.status, "failure")
        # Python exception in pytest failure MUST be captured as test_error_type
        self.assertIsNotNone(rec.test_error_type)
        self.assertEqual(rec.failure_subcategory, rec.test_error_type)
        self.assertNotEqual(rec.failure_class, "runtime_error")
        self.assertEqual(rec.tests_failed, 1)
        self.assertEqual(rec.tests_passed, 5)
        self.assertEqual(rec.tests_collected, 6)
        self.assertTrue(len(rec.failed_test_ids) > 0)
        self.assertTrue(rec.failed_test_ids[0].startswith("tests/test_app.py::"))
        self.assertIn("pytest tests/test_app.py -v", rec.failed_step)
        self.assertTrue(len(rec.traceback_lines) > 0)
        self.assertGreaterEqual(rec.parser_confidence, 0.8)


class TestParserV2F4Timeout(unittest.TestCase):
    """F4: GitHub Actions workflow step timeout."""

    def test_f4_real_log(self):
        f4_path = BASE_DIR / "F4" / "run_0001.log"
        if not f4_path.exists():
            self.skipTest("F4/run_0001.log not found")

        rec = parse_log_file(f4_path)
        self.assertEqual(rec.failure_class, "timeout")
        self.assertEqual(rec.failure_subcategory, "gha_timeout")
        self.assertEqual(rec.failed_step, "Run Tests")
        self.assertEqual(rec.status, "failure")
        self.assertEqual(rec.timeout_duration_min, 1.0)
        self.assertEqual(rec.orphan_process, "pytest")
        self.assertGreaterEqual(rec.parser_confidence, 0.8)
        self.assertTrue(len(rec.evidence_lines) > 0)
        # Traceback should NOT be present for GHA timeout
        self.assertEqual(len(rec.traceback_lines), 0)


class TestParserV2F4Cancellation(unittest.TestCase):
    """F4: GHA platform-level cancellation (##[error]The operation was canceled.)."""

    def test_gha_cancellation_maps_to_timeout_class(self):
        """The definitive GHA cancellation annotation must classify as timeout/gha_cancellation."""
        log_text = (
            "2026-08-06T03:11:00.000Z ##[group]Run pytest\n"
            "2026-08-06T03:11:10.000Z tests/test_app.py::test_one PASSED [ 50%]\n"
            "2026-08-06T03:11:20.000Z ##[error]The operation was canceled.\n"
            "2026-08-06T03:11:20.100Z ##[endgroup]\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "timeout",
                         "GHA cancellation annotation must map to failure_class='timeout'")
        self.assertEqual(rec.failure_subcategory, "gha_cancellation")
        self.assertEqual(rec.status, "failure")
        self.assertGreaterEqual(rec.parser_confidence, 0.6)
        self.assertTrue(len(rec.evidence_lines) > 0,
                        "Evidence lines must contain the cancellation annotation")

    def test_exit_code_137_alone_stays_unknown(self):
        """Exit code 137 without a GHA cancellation annotation must remain unknown (ambiguous)."""
        log_text = (
            "job1\tstep1\t2026-08-19T14:00:00.000Z Starting step\n"
            "job1\tstep1\t2026-08-19T14:00:10.000Z ##[error]Process completed with exit code 137.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "unknown",
                         "Exit code 137 alone is ambiguous and must remain 'unknown'")
        self.assertNotEqual(rec.failure_class, "timeout")


class TestParserV2ClassificationRules(unittest.TestCase):
    """Classification rules & edge cases."""

    def test_error_annotation_alone_never_determines_category(self):
        # A log with only generic ##[error] must NOT classify as syntax, dependency, test, or timeout
        log_text = (
            "job1\tstep1\t2026-08-19T14:00:00.000Z Starting step\n"
            "job1\tstep1\t2026-08-19T14:00:01.000Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "unknown")
        self.assertNotEqual(rec.failure_class, "syntax_error")
        self.assertNotEqual(rec.failure_class, "dependency_error")
        self.assertNotEqual(rec.failure_class, "test_failure")
        self.assertNotEqual(rec.failure_class, "timeout")
        self.assertEqual(rec.parser_confidence, 0.5)

    def test_empty_log_fallback(self):
        rec = parse_log_text("")
        self.assertEqual(rec.failure_class, "unknown")
        self.assertEqual(rec.parser_confidence, 0.0)
        self.assertEqual(rec.status, "unknown")

    def test_runtime_error_outside_pytest(self):
        # Unhandled Python error outside pytest test run
        log_text = (
            "job1\tRun Script\t2026-08-19T14:00:00.000Z python script.py\n"
            "job1\tRun Script\t2026-08-19T14:00:01.000Z Traceback (most recent call last):\n"
            "job1\tRun Script\t2026-08-19T14:00:01.100Z   File \"script.py\", line 10, in <module>\n"
            "job1\tRun Script\t2026-08-19T14:00:01.200Z RuntimeError: Database connection lost\n"
            "job1\tRun Script\t2026-08-19T14:00:02.000Z ##[error]Process completed with exit code 1.\n"
        )
        rec = parse_log_text(log_text)
        self.assertEqual(rec.failure_class, "runtime_error")
        self.assertEqual(rec.failure_subcategory, "RuntimeError")


class TestParserV2BatchAPIs(unittest.TestCase):
    """Batch parsing APIs."""

    def test_parse_batch(self):
        f1_dir = BASE_DIR / "F1"
        if not f1_dir.exists():
            self.skipTest("logs/F1 not found")
        records = parse_batch(f1_dir)
        self.assertEqual(len(records), 500)
        self.assertTrue(all(r.failure_class == "syntax_error" for r in records))


if __name__ == "__main__":
    unittest.main()
