"""rca/analyzers/timeout.py

Analyzer for workflow step timeouts (Category F4).
"""

from __future__ import annotations

from typing import Any

from rca.base import BaseCategoryAnalyzer, get_field, clean_line
from rca.schema import (
    RCAReport,
    CAUSAL_TIMEOUT,
)


class TimeoutAnalyzer(BaseCategoryAnalyzer):
    """Diagnoses step timeouts while strictly separating the observed timeout from unverified root causes."""

    @property
    def category_name(self) -> str:
        return "timeout"

    def can_analyze(self, record: Any) -> bool:
        return get_field(record, "failure_class") == "timeout"

    def analyze(self, record: Any) -> RCAReport:
        failed_step = get_field(record, "failed_step") or get_field(record, "step_name") or "Run Tests"
        dur_min = get_field(record, "timeout_duration_min")
        elapsed_s = get_field(record, "elapsed_step_seconds") or get_field(record, "duration")
        orphan_proc = get_field(record, "orphan_process")
        ev_lines = get_field(record, "evidence_lines") or []

        observed_evidence: dict[str, Any] = {
            "timeout_duration_min": dur_min,
            "elapsed_step_seconds": elapsed_s,
            "orphan_process": orphan_proc,
        }

        evidence_sources: dict[str, str] = {
            "timeout_duration_min": "parser.timeout_duration_min",
            "elapsed_step_seconds": "parser.elapsed_step_seconds",
            "orphan_process": "parser.orphan_process",
        }

        primary_lines = [clean_line(l) for l in ev_lines]

        dur_disp = f"{dur_min} minute(s)" if dur_min is not None else "the configured limit"
        elapsed_disp = f"{elapsed_s}s" if elapsed_s is not None else "unknown elapsed time"
        proc_disp = f"'{orphan_proc}'" if orphan_proc else "an active process"

        summary = f"Workflow step timed out: '{failed_step}' exceeded {dur_disp} (elapsed: {elapsed_disp})"

        likely_cause = (
            f"The step '{failed_step}' exceeded its configured timeout threshold of {dur_disp} "
            f"(elapsed execution: {elapsed_disp}) and was terminated by the CI runner. "
            f"Process {proc_disp} remained active at timeout expiration and was terminated during job cleanup. "
            f"The log establishes that execution exceeded the time limit, but does not provide thread stack traces "
            f"to identify the exact blocking operation."
        )

        investigation: list[str] = [
            f"Run the operations in '{failed_step}' locally with verbose per-test duration tracking (e.g. 'pytest --durations=10').",
            f"Investigate whether operations in '{failed_step}' perform blocking calls (such as un-mocked network requests, deadlocks, file locks, or unbounded loops).",
            "Check runner resource constraints (CPU/memory throttling) or external service latency during this run.",
            f"If the workload legitimately requires more execution time, increase 'timeout-minutes' in the workflow configuration for step '{failed_step}'.",
        ]

        # Reproduction command only if verified from step context
        local_cmd = "pytest --durations=10" if "test" in failed_step.lower() else None

        has_complete = bool(dur_min is not None and orphan_proc)
        confidence = 1.0 if has_complete else 0.8
        rationale = (
            "High evidence strength: direct GitHub Actions runner timeout annotation with timeout threshold and orphan process termination."
            if has_complete else
            "Medium evidence strength: timeout indicated but timeout threshold or orphan process was not parsed."
        )

        limitations = [
            "GitHub Actions timeout mechanisms terminate the runner step without capturing process thread dumps. The specific blocking function or statement cannot be determined from runner logs alone.",
            "Underlying causes such as infinite loops, deadlocks, or network delays remain hypotheses until verified locally.",
        ]

        return RCAReport(
            run_id=get_field(record, "run_id"),
            timestamp=get_field(record, "timestamp"),
            failure_class="timeout",
            failure_subcategory="gha_timeout",
            failed_stage=get_field(record, "stage") or "test",
            failed_step=failed_step,
            execution_path=get_field(record, "execution_path") or [],
            summary=summary,
            likely_cause=likely_cause,
            causal_category=CAUSAL_TIMEOUT,
            observed_evidence=observed_evidence,
            primary_evidence_lines=primary_lines,
            evidence_sources=evidence_sources,
            suggested_investigation=investigation,
            local_reproduction_command=local_cmd,
            rca_confidence=confidence,
            confidence_rationale=rationale,
            limitations=limitations,
        )
