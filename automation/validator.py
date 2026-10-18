"""Validation helpers for identifying dependency-installation failures."""

from pathlib import Path
import re


DEPENDENCY_PATTERNS = [
    "Could not find a version that satisfies the requirement",
    "No matching distribution found",
    "ResolutionImpossible",
    "Invalid requirement",
    "ERROR: Could not find",
    "Ignored the following versions"
    "Cannot install",
    "requires a different Python",
    "Failed building wheel",
    "Could not build wheels",
    "metadata-generation-failed",
    "subprocess-exited-with-error"
]


def validate_dependency_log(log_text):
    """Check whether log text contains a known dependency resolution failure.

    Args:
        log_text (str): The workflow log content to inspect.

    Returns:
        tuple: (is_dependency_error, matched_pattern, matched_line)
    """
    if log_text is None:
        return False, None, None

    for line in log_text.splitlines():
        lowered_line = line.lower()
        for pattern in DEPENDENCY_PATTERNS:
            if pattern.lower() in lowered_line:
                return True, pattern, line.strip()

    return False, None, None


def validate_workflow_log_file(log_file_path):
    """Read a workflow log file and determine whether it is a dependency error.

    Args:
        log_file_path (str or Path): Path to the log file to inspect.

    Returns:
        dict: Structured validation result with keys:
            - is_dependency_error: bool
            - matched_pattern: str or None
            - matched_line: str or None
            - status: "valid", "invalid", or "error"
    """
    file_path = Path(log_file_path)

    if not file_path.exists():
        return {
            "is_dependency_error": False,
            "matched_pattern": None,
            "matched_line": None,
            "status": "error"
        }

    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as log_file:
            log_text = log_file.read()
    except OSError:
        return {
            "is_dependency_error": False,
            "matched_pattern": None,
            "matched_line": None,
            "status": "error"
        }

    is_dependency_error, matched_pattern, matched_line = validate_dependency_log(log_text)

    if is_dependency_error:
        return {
            "is_dependency_error": True,
            "matched_pattern": matched_pattern,
            "matched_line": matched_line,
            "status": "valid"
        }

    return {
        "is_dependency_error": False,
        "matched_pattern": None,
        "matched_line": None,
        "status": "invalid"
    }


def validate_success_workflow_log(log_text):
    """Confirm the expected Python compilation and pytest results are in a log."""
    if not log_text or not log_text.strip():
        return {"status": "invalid", "validation_notes": None}

    lowered_log = log_text.lower()
    required_steps = ("compile python sources", "run test suite")
    if any(step not in lowered_log for step in required_steps):
        return {"status": "invalid", "validation_notes": None}

    if "python syntax/compilation checks passed" not in lowered_log:
        return {"status": "invalid", "validation_notes": None}

    test_summary = re.search(r"\b([1-9]\d*) passed\b", lowered_log)
    if test_summary is None:
        return {"status": "invalid", "validation_notes": None}

    return {
        "status": "valid",
        "validation_notes": (
            "Python syntax/compilation checks passed; "
            f"pytest reported {test_summary.group(1)} passed"
        ),
    }