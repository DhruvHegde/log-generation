"""parser/log_parser.py

Reusable parser for raw GitHub Actions CI/CD log files.

Log format (each line):
    <job-name>\\t<step-name>\\t<ISO-timestamp>Z <message>

Example:
    dependency-test\\tCheck App Syntax\\t2026-08-19T14:06:54.5495401Z SyntaxError: expected ':'

Public API
----------
parse_log_text(text: str, *, run_id=None, failure_type=None) -> LogRecord
parse_log_file(path, *, run_id=None, failure_type=None)     -> LogRecord
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Log-line structure
# ---------------------------------------------------------------------------

# Each raw log line is:
#   <job>\t<step>\t<ISO-timestamp>Z <message>
_LINE_RE = re.compile(
    r"^(?P<job>[^\t]+)\t"
    r"(?P<step>[^\t]+)\t"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z)"
    r"(?:\s(?P<msg>.*))?$"
)

# Strip ANSI control sequences and BOM that GitHub adds to step header lines
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\ufeff")

_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _clean(text: str) -> str:
    """Remove ANSI escapes, BOM, and non-printable control chars."""
    text = text.replace("\ufeff", "")
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


# ---------------------------------------------------------------------------
# Error-type detection
# ---------------------------------------------------------------------------

# Ordered so more-specific types are checked before generic ones.
# Each entry: (canonical_name, regex_pattern)
_ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("TabError",            re.compile(r"\bTabError\s*:")),
    ("IndentationError",    re.compile(r"\bIndentationError\s*:")),
    ("ModuleNotFoundError", re.compile(r"\bModuleNotFoundError\s*:")),
    ("ImportError",         re.compile(r"\bImportError\s*:")),
    ("NameError",           re.compile(r"\bNameError\s*:")),
    ("TypeError",           re.compile(r"\bTypeError\s*:")),
    ("ValueError",          re.compile(r"\bValueError\s*:")),
    ("AttributeError",      re.compile(r"\bAttributeError\s*:")),
    ("SyntaxError",         re.compile(r"\bSyntaxError\s*:")),
]

# Message after the colon: "SyntaxError: expected ':'" → "expected ':'"
_ERR_MSG_RE = re.compile(
    r"\b(?:TabError|IndentationError|ModuleNotFoundError|ImportError|"
    r"NameError|TypeError|ValueError|AttributeError|SyntaxError)\s*:\s*(.+)"
)

# File path and line number from Python traceback:
#   File "/home/runner/.../app.py", line 4
_TRACEBACK_FILE_RE = re.compile(
    r'File\s+"([^"]+)",\s+line\s+(\d+)'
)

# GitHub Actions failure annotation (NOT a Python exception):
#   ##[error]Process completed with exit code 1.
_EXIT_CODE_RE = re.compile(r"##\[error\]Process completed with exit code (\d+)")

# Step-level timestamps for duration calculation
_TS_RE = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+)Z")


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    try:
        # Python 3.11+ fromisoformat handles the fractional seconds
        dt = datetime.fromisoformat(ts_str.rstrip("Z"))
        return dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Data class for a parsed record
# ---------------------------------------------------------------------------

@dataclass
class LogRecord:
    """Structured representation of a single parsed CI/CD log."""

    # --- required schema columns (in presentation order) ---
    run_id:        Optional[str]   = None
    timestamp:     Optional[str]   = None   # ISO-8601 UTC string
    step_name:     Optional[str]   = None
    stage:         Optional[str]   = None
    duration:      Optional[float] = None   # seconds, or None
    status:        Optional[str]   = None   # "success" | "failure" | "unknown"
    error_type:    Optional[str]   = None
    error_message: Optional[str]   = None
    log_text:      str             = ""     # full raw log
    failure_type:  Optional[str]   = None

    # --- optional enrichment columns ---
    line_number:   Optional[int]   = None
    file_path:     Optional[str]   = None
    matched_line:  Optional[str]   = None
    exit_code:     Optional[int]   = None
    python_version: Optional[str]  = None

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core parsing logic
# ---------------------------------------------------------------------------

def _infer_stage(step_name: Optional[str]) -> str:
    """
    Map a step name to a pipeline stage label.

    This is intentionally heuristic — the parser never hard-codes 'build'
    unconditionally.  If the step name doesn't match a known pattern the
    function returns 'unknown'.
    """
    if not step_name:
        return "unknown"
    lower = step_name.lower()
    if any(kw in lower for kw in ("syntax", "install", "build", "compile", "lint")):
        return "build"
    if any(kw in lower for kw in ("test", "pytest", "unittest", "spec")):
        return "test"
    if any(kw in lower for kw in ("deploy", "publish", "release", "push")):
        return "deploy"
    if any(kw in lower for kw in ("checkout", "setup", "set up")):
        return "setup"
    return "unknown"


def parse_log_text(
    text: str,
    *,
    run_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> LogRecord:
    """
    Parse raw GitHub Actions log text and return a LogRecord.

    Parameters
    ----------
    text:
        Full raw content of a .log file (as a string).
    run_id:
        Optional identifier for this run (e.g. "run_0001").
    failure_type:
        Optional label for the failure category (e.g. "syntax_error").
        If None, the parser will attempt to infer it from the detected error.

    Returns
    -------
    LogRecord
        Populated with all fields extractable from the log.
        Fields that cannot be reliably extracted are left as None.
    """
    record = LogRecord(run_id=run_id, log_text=text, failure_type=failure_type)

    # Collect all parsed lines for structured analysis
    lines = text.splitlines()
    parsed_lines: list[dict] = []
    for raw in lines:
        cleaned = _clean(raw)
        m = _LINE_RE.match(cleaned)
        if m:
            parsed_lines.append({
                "job":  m.group("job"),
                "step": m.group("step"),
                "ts":   m.group("ts"),
                "msg":  (m.group("msg") or "").strip(),
            })

    if not parsed_lines:
        record.status = "unknown"
        return record

    # --- timestamp: first timestamp seen in the log ---
    first_ts_str = parsed_lines[0]["ts"]
    record.timestamp = first_ts_str

    # --- python version ---
    for pl in parsed_lines:
        pv = re.search(r"CPython\s+\((\d+\.\d+\.\d+)\)", pl["msg"])
        if pv:
            record.python_version = pv.group(1)
            break

    # --- identify the failing step ---
    # Look for the step that contains a known Python exception.
    # We search every line's message for the error patterns.
    failing_step: Optional[str] = None
    error_type:   Optional[str] = None
    error_message: Optional[str] = None
    matched_line:  Optional[str] = None
    line_number:   Optional[int] = None
    file_path:     Optional[str] = None

    for pl in parsed_lines:
        msg = pl["msg"]

        # Skip GitHub Actions annotations — they contain "[error]" or "[warning]"
        # but are NOT Python exceptions.
        if msg.startswith("##["):
            # Still check for exit code
            ec = _EXIT_CODE_RE.search(msg)
            if ec:
                record.exit_code = int(ec.group(1))
            continue

        # Check for Python error types
        for etype, pattern in _ERROR_PATTERNS:
            if pattern.search(msg):
                # Only take the FIRST match (the primary error)
                if error_type is None:
                    error_type = etype
                    failing_step = pl["step"]
                    matched_line = msg

                    # Extract message text after the colon
                    em = _ERR_MSG_RE.search(msg)
                    if em:
                        error_message = em.group(1).strip()
                break

        # File path and line number from Python traceback lines
        if file_path is None:
            tf = _TRACEBACK_FILE_RE.search(msg)
            if tf:
                file_path = tf.group(1)
                line_number = int(tf.group(2))

    record.error_type    = error_type
    record.error_message = error_message
    record.matched_line  = matched_line
    record.line_number   = line_number
    record.file_path     = file_path

    # --- failing step name ---
    # Use the step containing the error; fall back to the last non-cleanup step.
    if failing_step:
        record.step_name = failing_step
    else:
        # Last step that is not a post-cleanup step
        for pl in reversed(parsed_lines):
            step = pl["step"]
            if not step.lower().startswith("post ") and step not in ("Complete job", "Set up job"):
                record.step_name = step
                break

    # --- stage inference ---
    record.stage = _infer_stage(record.step_name)

    # --- status ---
    if record.exit_code is not None:
        record.status = "failure" if record.exit_code != 0 else "success"
    elif record.error_type is not None:
        record.status = "failure"
    else:
        # Check for explicit success/failure signals in messages
        for pl in reversed(parsed_lines):
            msg = pl["msg"]
            if "##[error]" in msg:
                record.status = "failure"
                break
            if "passed" in msg.lower() or "succeeded" in msg.lower():
                record.status = "success"
                break
        else:
            record.status = "unknown"

    # --- duration (step-level, not whole workflow) ---
    # Find the first and last timestamp for the failing step.
    if record.step_name:
        step_lines = [pl for pl in parsed_lines if pl["step"] == record.step_name]
        if len(step_lines) >= 2:
            t0 = _parse_ts(step_lines[0]["ts"])
            t1 = _parse_ts(step_lines[-1]["ts"])
            if t0 and t1:
                delta = (t1 - t0).total_seconds()
                record.duration = round(delta, 3)

    # --- failure_type inference (when not supplied by caller) ---
    if record.failure_type is None and record.error_type:
        if record.error_type in ("SyntaxError", "IndentationError", "TabError"):
            record.failure_type = "syntax_error"
        elif record.error_type in ("ImportError", "ModuleNotFoundError"):
            record.failure_type = "dependency_error"
        else:
            record.failure_type = "runtime_error"

    return record


def parse_log_file(
    path,
    *,
    run_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> LogRecord:
    """
    Parse a single log file and return a LogRecord.

    Parameters
    ----------
    path:
        Path to the .log file (str or Path).
    run_id:
        Optional run identifier.  If None, inferred from the filename stem
        (e.g. 'run_0001' from 'run_0001.log').
    failure_type:
        Optional failure category label passed through to parse_log_text.
    """
    path = Path(path)
    if run_id is None:
        run_id = path.stem  # e.g. "run_0001"

    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_log_text(text, run_id=run_id, failure_type=failure_type)
