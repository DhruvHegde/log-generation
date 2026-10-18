"""Validation helpers for identifying genuine Python syntax failures.

This module is the F1 counterpart to automation/validator.py (which handles
F2 dependency-resolution errors).  It searches a workflow log for real Python
interpreter output — SyntaxError, IndentationError, or TabError — and
explicitly rejects logs that merely failed for unrelated reasons.
"""

from pathlib import Path


# Patterns that indicate a genuine Python syntax-level failure.
# These strings are emitted by the CPython interpreter itself and will appear
# verbatim in a GitHub Actions log when `python -c "import app"` or
# `pytest` encounters a broken source file.
SYNTAX_PATTERNS = [
    "SyntaxError",
    "IndentationError",
    "TabError",
]


def validate_syntax_log(log_text):
    """Check whether log text contains a genuine Python syntax failure.

    The function scans every line of the log.  It is intentionally strict:
    the pattern must appear in the CPython error output, not just anywhere in
    the log.  A workflow that failed for an unrelated reason (e.g. network
    timeout, missing file) will not contain these strings and will be
    correctly classified as invalid.

    Args:
        log_text (str): The raw workflow log content to inspect.

    Returns:
        tuple: (is_syntax_error, matched_pattern, matched_line)
            is_syntax_error  – True only when a known syntax pattern is found.
            matched_pattern  – The pattern string that matched, or None.
            matched_line     – The exact log line that contained the match, or None.
    """
    if log_text is None:
        return False, None, None

    for line in log_text.splitlines():
        for pattern in SYNTAX_PATTERNS:
            if pattern in line:
                return True, pattern, line.strip()

    return False, None, None


def validate_syntax_log_file(log_file_path):
    """Read a workflow log file and determine whether it contains a syntax error.

    This mirrors the interface of automation/validator.validate_workflow_log_file()
    so the calling code in generate_syntax_failures.py is symmetric with the
    existing F2 generator.

    Args:
        log_file_path (str or Path): Path to the log file to inspect.

    Returns:
        dict: Structured validation result with keys:
            - is_syntax_error (bool)
            - matched_pattern (str | None)
            - matched_line    (str | None)
            - status          ("valid" | "invalid" | "error")
    """
    file_path = Path(log_file_path)

    if not file_path.exists():
        return {
            "is_syntax_error": False,
            "matched_pattern": None,
            "matched_line": None,
            "status": "error",
        }

    try:
        with file_path.open("r", encoding="utf-8", errors="replace") as log_file:
            log_text = log_file.read()
    except OSError:
        return {
            "is_syntax_error": False,
            "matched_pattern": None,
            "matched_line": None,
            "status": "error",
        }

    is_syntax_error, matched_pattern, matched_line = validate_syntax_log(log_text)

    if is_syntax_error:
        return {
            "is_syntax_error": True,
            "matched_pattern": matched_pattern,
            "matched_line": matched_line,
            "status": "valid",
        }

    return {
        "is_syntax_error": False,
        "matched_pattern": None,
        "matched_line": None,
        "status": "invalid",
    }
