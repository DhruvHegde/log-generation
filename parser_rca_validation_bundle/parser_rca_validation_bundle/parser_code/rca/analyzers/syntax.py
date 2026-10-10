"""rca/analyzers/syntax.py

Analyzer for Python syntax, indentation, and tab errors (Category F1).
"""

from __future__ import annotations

import re
from typing import Any, Optional

from rca.base import BaseCategoryAnalyzer, get_field, clean_line
from rca.schema import (
    RCAReport,
    CAUSAL_CODE_DEFECT,
)

_TB_FILE_RE = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+)')


class SyntaxAnalyzer(BaseCategoryAnalyzer):
    """Diagnoses Python compilation and syntax errors."""

    @property
    def category_name(self) -> str:
        return "syntax_error"

    def can_analyze(self, record: Any) -> bool:
        failure_class = get_field(record, "failure_class")
        error_type = get_field(record, "error_type")
        return failure_class == "syntax_error" or error_type in ("SyntaxError", "IndentationError", "TabError")

    def analyze(self, record: Any) -> RCAReport:
        failed_step = get_field(record, "failed_step") or get_field(record, "step_name") or "Check App Syntax"
        error_type = get_field(record, "error_type") or get_field(record, "failure_subcategory") or "SyntaxError"
        error_msg = get_field(record, "error_message") or ""
        tb_lines = get_field(record, "traceback_lines") or []
        ev_lines = get_field(record, "evidence_lines") or []
        exit_code = get_field(record, "exit_code")

        # Resolve actual source file and line from traceback lines if record.file_path is '<string>' or None
        file_path = get_field(record, "file_path")
        line_no = get_field(record, "line_number")
        resolved_from_tb = False

        if not file_path or file_path == "<string>":
            for line in tb_lines:
                m = _TB_FILE_RE.search(line)
                if m and m.group(1) != "<string>":
                    file_path = m.group(1)
                    line_no = int(m.group(2))
                    resolved_from_tb = True
                    break

        observed_evidence: dict[str, Any] = {
            "error_type": error_type,
            "error_message": error_msg,
            "source_file": file_path,
            "source_line": line_no,
            "exit_code": exit_code,
        }

        evidence_sources: dict[str, str] = {
            "error_type": "parser.error_type",
            "error_message": "parser.error_message",
            "source_file": "parser.traceback_lines" if resolved_from_tb else "parser.file_path",
            "source_line": "parser.traceback_lines" if resolved_from_tb else "parser.line_number",
        }

        primary_lines = [clean_line(l) for l in (tb_lines or ev_lines)]
        if not primary_lines and get_field(record, "matched_line"):
            primary_lines = [clean_line(get_field(record, "matched_line"))]

        file_disp = file_path if file_path and file_path != "<string>" else "the target Python file"
        line_disp = f" at line {line_no}" if line_no is not None else ""

        summary = f"Python syntax compilation failed: {error_type} in {file_disp}{line_disp}"
        likely_cause = (
            f"Python syntax compilation failed during step '{failed_step}'. A {error_type} was encountered in "
            f"{file_disp}{line_disp} ('{error_msg}'). The source file violates Python syntax and cannot be parsed or imported."
        )

        investigation = []
        if file_path and file_path != "<string>":
            investigation.append(
                f"Inspect '{file_path}' around line {line_no or '?'} for syntax errors (e.g. missing colons, "
                f"unmatched parentheses/brackets, or indentation discrepancies)."
            )
            investigation.append(f"Verify syntax locally without executing: python -m py_compile {file_path}")
            investigation.append(f"Inspect git diff for recent changes to '{file_path}': git diff HEAD~1 {file_path}")
            local_cmd = f"python -m py_compile {file_path}"
        else:
            investigation.append("Inspect the modified source files for syntax errors around the failing import.")
            investigation.append("Verify syntax locally: python -m py_compile <path-to-source-file>")
            investigation.append("Inspect git diff for recent changes: git diff HEAD~1")
            local_cmd = None

        has_complete_details = bool(file_path and file_path != "<string>" and line_no is not None and error_msg)
        confidence = 1.0 if has_complete_details else 0.8
        rationale = (
            "High evidence strength: direct CPython syntax error message, confirmed source file, line number, and traceback."
            if has_complete_details else
            "Medium evidence strength: syntax error signal detected but source file or line number was partially resolved."
        )

        limitations = [
            "RCA identifies the location where the Python parser failed, which may be one token or line after the actual omitted syntax element.",
            "RCA does not hypothesize developer intent or generate code modifications.",
        ]

        return RCAReport(
            run_id=get_field(record, "run_id"),
            timestamp=get_field(record, "timestamp"),
            failure_class="syntax_error",
            failure_subcategory=error_type,
            failed_stage=get_field(record, "stage") or "build",
            failed_step=failed_step,
            execution_path=get_field(record, "execution_path") or [],
            summary=summary,
            likely_cause=likely_cause,
            causal_category=CAUSAL_CODE_DEFECT,
            observed_evidence=observed_evidence,
            primary_evidence_lines=primary_lines,
            evidence_sources=evidence_sources,
            suggested_investigation=investigation,
            local_reproduction_command=local_cmd,
            rca_confidence=confidence,
            confidence_rationale=rationale,
            limitations=limitations,
        )
