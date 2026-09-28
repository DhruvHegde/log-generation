"""rca/analyzers/fallback.py

Fallback analyzer for unknown, unclassified, and runtime errors outside F1-F4.
"""

from __future__ import annotations

from typing import Any

from rca.base import BaseCategoryAnalyzer, get_field, clean_line
from rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
    CAUSAL_ENVIRONMENT,
    CAUSAL_UNKNOWN,
)


class FallbackAnalyzer(BaseCategoryAnalyzer):
    """Handles runtime exceptions outside pytest and unclassified/unknown failures."""

    @property
    def category_name(self) -> str:
        return "fallback"

    def can_analyze(self, record: Any) -> bool:
        # Acts as catch-all at the end of the analyzer chain
        return True

    def analyze(self, record: Any) -> RCAReport:
        failure_class = get_field(record, "failure_class") or "unknown"
        failure_subcat = get_field(record, "failure_subcategory")
        failed_step = get_field(record, "failed_step") or get_field(record, "step_name")
        exit_code = get_field(record, "exit_code")
        error_type = get_field(record, "error_type")
        error_msg = get_field(record, "error_message") or ""
        tb_lines = get_field(record, "traceback_lines") or []
        ev_lines = get_field(record, "evidence_lines") or []
        log_line_count = get_field(record, "log_line_count") or 0

        observed_evidence: dict[str, Any] = {
            "failure_class": failure_class,
            "failure_subcategory": failure_subcat,
            "exit_code": exit_code,
            "error_type": error_type,
            "error_message": error_msg,
        }

        evidence_sources: dict[str, str] = {
            "failure_class": "parser.failure_class",
            "exit_code": "parser.exit_code",
        }
        if error_type:
            evidence_sources["error_type"] = "parser.error_type"
        if error_msg:
            evidence_sources["error_message"] = "parser.error_message"

        primary_lines = [clean_line(l) for l in (tb_lines or ev_lines)]

        investigation: list[str] = []
        limitations: list[str] = []

        if failure_class == "runtime_error":
            causal_category = CAUSAL_CODE_DEFECT
            summary = f"Runtime exception: {error_type or 'Unhandled error'}"
            likely_cause = (
                f"An unhandled {error_type or 'exception'}{(': ' + error_msg) if error_msg else ''} occurred "
                f"during step '{failed_step or 'unknown'}' outside of pytest test execution."
            )
            investigation.append(f"Inspect step '{failed_step or 'unknown'}' and trace where {error_type or 'the exception'} was raised.")
            investigation.append("Check application logs and environment variables required for this script.")
            confidence = 0.7 if error_type and tb_lines else 0.5
            rationale = "Medium evidence strength: general Python exception and traceback observed outside standard test runners."
            limitations.append("The failure occurred in a standalone script or non-test step; full test report context is unavailable.")

        elif log_line_count == 0 or not get_field(record, "log_text", "").strip():
            causal_category = CAUSAL_UNKNOWN
            summary = "Empty log: no execution data recorded"
            likely_cause = "The log content is empty or unrecorded. No pipeline execution data is available for diagnosis."
            investigation.append("Verify pipeline job triggers and runner connectivity to ensure logs are uploaded properly.")
            confidence = 0.0
            rationale = "Insufficient evidence: empty log content."
            limitations.append("No log records or timestamps were found.")

        else:
            causal_category = CAUSAL_UNKNOWN
            step_disp = f"step '{failed_step}'" if failed_step else "an unidentified pipeline step"
            code_disp = f" (exit code {exit_code})" if exit_code is not None else ""
            summary = f"Unknown pipeline failure in {step_disp}{code_disp}"
            likely_cause = (
                f"Unable to determine root cause. The pipeline failed in {step_disp}{code_disp}, "
                f"but log content did not match recognized syntax, dependency, test, or timeout diagnostic patterns."
            )
            investigation.append(f"Inspect raw console output for {step_disp} to locate unparsed error messages.")
            investigation.append("Re-run the pipeline with runner debug logging enabled (ACTIONS_RUNNER_DEBUG=true).")
            if exit_code is not None:
                investigation.append(f"Check documentation or exit code reference for exit code {exit_code} on commands run in {step_disp}.")

            if exit_code is not None:
                confidence = 0.4 if failed_step else 0.3
                rationale = f"Low evidence strength: exit code {exit_code} observed without category-specific diagnostic signatures."
                limitations.append(
                    f"Exit code {exit_code} was observed, but runner logs do not include compiler, package manager, or test runner error messages to identify the underlying trigger."
                )
            elif failed_step:
                confidence = 0.3
                rationale = "Low evidence strength: failure step identified, but no recognized error signatures found."
                limitations.append(
                    "Insufficient log evidence. Generic failure step observed without accompanying compiler, package manager, or test framework diagnostic records."
                )
            else:
                confidence = 0.2
                rationale = "Insufficient evidence: no recognizable error signatures or failure exit codes."
                limitations.append(
                    "Insufficient log evidence. Generic failure annotations were observed without accompanying compiler, package manager, or test framework diagnostic records."
                )

        return RCAReport(
            run_id=get_field(record, "run_id"),
            timestamp=get_field(record, "timestamp"),
            failure_class=failure_class,
            failure_subcategory=failure_subcat,
            failed_stage=get_field(record, "stage") or "unknown",
            failed_step=failed_step,
            execution_path=get_field(record, "execution_path") or [],
            summary=summary,
            likely_cause=likely_cause,
            causal_category=causal_category,
            observed_evidence=observed_evidence,
            primary_evidence_lines=primary_lines,
            evidence_sources=evidence_sources,
            suggested_investigation=investigation,
            local_reproduction_command=None,
            rca_confidence=confidence,
            confidence_rationale=rationale,
            limitations=limitations,
        )
