"""rca/analyzers/test_failure.py

Analyzer for Pytest test execution failures (Category F3).
"""

from __future__ import annotations

from typing import Any

from rca.base import BaseCategoryAnalyzer, get_field, clean_line
from rca.schema import (
    RCAReport,
    CAUSAL_TEST,
    CAUSAL_TEST_EXECUTION,
)


class TestFailureAnalyzer(BaseCategoryAnalyzer):
    """Diagnoses pytest failures while strictly describing only what the test output establishes."""

    @property
    def category_name(self) -> str:
        return "test_failure"

    def can_analyze(self, record: Any) -> bool:
        return get_field(record, "failure_class") == "test_failure"

    def analyze(self, record: Any) -> RCAReport:
        failed_step = get_field(record, "failed_step") or get_field(record, "step_name") or "Run Tests"
        subcat = get_field(record, "test_error_type") or get_field(record, "failure_subcategory") or "TestFailure"
        failed_test_ids = get_field(record, "failed_test_ids") or []
        err_msg = get_field(record, "error_message") or ""
        tests_failed = get_field(record, "tests_failed")
        tests_passed = get_field(record, "tests_passed")
        tests_coll = get_field(record, "tests_collected")
        tb_lines = get_field(record, "traceback_lines") or []
        ev_lines = get_field(record, "evidence_lines") or []

        observed_evidence: dict[str, Any] = {
            "failed_test_ids": failed_test_ids,
            "test_error_type": subcat,
            "error_message": err_msg,
            "tests_failed": tests_failed,
            "tests_passed": tests_passed,
            "tests_collected": tests_coll,
        }

        evidence_sources: dict[str, str] = {
            "failed_test_ids": "parser.failed_test_ids",
            "test_error_type": "parser.test_error_type",
            "error_message": "parser.error_message",
            "tests_failed": "parser.tests_failed",
            "tests_passed": "parser.tests_passed",
            "tests_collected": "parser.tests_collected",
        }

        # Filter clean evidence lines
        primary_lines = [clean_line(l) for l in (ev_lines or tb_lines)]
        primary_lines = [l for l in primary_lines if l and not l.startswith("=====")]

        failing_id_str = failed_test_ids[0] if failed_test_ids else "a test"
        err_msg_str = f": {err_msg}" if err_msg else ""
        passed_str = f"{tests_passed} passed, " if tests_passed is not None else ""
        failed_str = f"{tests_failed} failed" if tests_failed is not None else "failed"

        is_assertion = (subcat == "AssertionError" or "AssertionError" in subcat or subcat == "TestFailure")
        if is_assertion:
            causal_cat = CAUSAL_TEST
            summary = f"Pytest test assertion failure: {failing_id_str} failed assertion ({subcat})"
            cause_detail = f"failed a test assertion ({subcat}{err_msg_str})"
        else:
            causal_cat = CAUSAL_TEST_EXECUTION
            summary = f"Pytest test execution failure: {failing_id_str} raised unhandled {subcat}"
            cause_detail = f"raised an unhandled {subcat} exception{err_msg_str} during test execution"

        likely_cause = (
            f"Pytest execution terminated with failures in step '{failed_step}'. Specifically, {failing_id_str} "
            f"{cause_detail} (summary: {passed_str}{failed_str}). "
            f"While {passed_str}tests passed, this indicates the failure occurred within the scope of the failing test execution; "
            f"alternative causes such as shared state, test ordering, or environment-dependent edge cases cannot be excluded from log data alone."
        )

        investigation: list[str] = []
        if failed_test_ids:
            primary_test = failed_test_ids[0]
            investigation.append(f"Reproduce the failing test locally with verbose output: pytest {primary_test} -vv")
            test_file = primary_test.split("::")[0]
            if is_assertion:
                investigation.append(
                    f"Inspect the test assertion in '{test_file}' and underlying logic for unexpected return values."
                )
            else:
                investigation.append(
                    f"Inspect test implementation in '{test_file}' and underlying application functions for unhandled {subcat} exceptions."
                )
            local_cmd = f"pytest {primary_test} -vv"
        else:
            investigation.append("Run pytest locally with verbose output: pytest -vv")
            investigation.append("Inspect the test files reported in pytest output.")
            local_cmd = "pytest -vv"

        investigation.append("Review recent commit diffs for logic or interface changes affecting the failing test.")
        investigation.append("Check whether tests run prior to the failure could have modified shared global state or temporary fixtures.")

        has_complete = bool(failed_test_ids and subcat)
        confidence = 1.0 if has_complete else 0.8
        rationale = (
            "High evidence strength: explicit pytest short summary info and unhandled exception details."
            if has_complete else
            "Medium evidence strength: pytest failure detected but test node IDs were partial."
        )

        limitations = [
            "Runner logs report test outcome only; they do not establish whether the failure stems from application code defect, test assertion error, or test environment state.",
            "Runner logs do not prove whether preceding passed tests left side effects that contributed to this failure.",
        ]

        return RCAReport(
            run_id=get_field(record, "run_id"),
            timestamp=get_field(record, "timestamp"),
            failure_class="test_failure",
            failure_subcategory=subcat,
            failed_stage=get_field(record, "stage") or "test",
            failed_step=failed_step,
            execution_path=get_field(record, "execution_path") or [],
            summary=summary,
            likely_cause=likely_cause,
            causal_category=causal_cat,
            observed_evidence=observed_evidence,
            primary_evidence_lines=primary_lines,
            evidence_sources=evidence_sources,
            suggested_investigation=investigation,
            local_reproduction_command=local_cmd,
            rca_confidence=confidence,
            confidence_rationale=rationale,
            limitations=limitations,
        )
