"""rca/schema.py

Data structures and schemas for RCA V1.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Causal categories taxonomy
# ---------------------------------------------------------------------------
CAUSAL_CODE_DEFECT = "code_defect"
CAUSAL_DEPENDENCY = "dependency_resolution"
CAUSAL_TEST = "test_assertion"
CAUSAL_TEST_EXECUTION = "test_execution_failure"
CAUSAL_TIMEOUT = "execution_timeout"
CAUSAL_ENVIRONMENT = "environment_failure"
CAUSAL_UNKNOWN = "unknown"

VALID_CAUSAL_CATEGORIES = {
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
    CAUSAL_TEST,
    CAUSAL_TEST_EXECUTION,
    CAUSAL_TIMEOUT,
    CAUSAL_ENVIRONMENT,
    CAUSAL_UNKNOWN,
}


# ---------------------------------------------------------------------------
# RCAReport Data Structure
# ---------------------------------------------------------------------------
@dataclass
class RCAReport:
    """Structured, evidence-grounded Root Cause Analysis report."""

    # Run metadata
    run_id: Optional[str] = None
    timestamp: Optional[str] = None

    # Category classification (preserved from parser)
    failure_class: str = "unknown"
    failure_subcategory: Optional[str] = None

    # Pipeline context
    failed_stage: Optional[str] = None
    failed_step: Optional[str] = None
    execution_path: list[str] = field(default_factory=list)

    # RCA Diagnosis
    summary: str = ""
    likely_cause: str = ""
    causal_category: str = CAUSAL_UNKNOWN

    # Verifiable Evidence & Traceability
    observed_evidence: dict[str, Any] = field(default_factory=dict)
    primary_evidence_lines: list[str] = field(default_factory=list)
    evidence_sources: dict[str, str] = field(default_factory=dict)

    # Actionable Guidance
    suggested_investigation: list[str] = field(default_factory=list)
    local_reproduction_command: Optional[str] = None

    # Quality, Confidence & Limitations
    rca_confidence: float = 0.0
    confidence_rationale: str = ""
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Convert report to dictionary representation."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize report to formatted JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)
