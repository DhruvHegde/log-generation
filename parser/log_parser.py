"""parser/log_parser.py

Reusable Parser V2 for raw GitHub Actions CI/CD log files.

Supports both:
  1. Structured 3-column format:
     <job-name>\\t<step-name>\\t<ISO-timestamp>Z <message>
     (used in F1 syntax, F2 dependency, and F4 timeout logs)

  2. GitHub Actions group runner format:
     <ISO-timestamp>Z <message>
     (used in F3 pytest runner logs with ##[group]Run <command> boundaries)

Public API
----------
LogRecord                                                    (dataclass schema)
parse_log_text(text: str, *, run_id=None, failure_type=None) -> LogRecord
parse_log_file(path, *, run_id=None, failure_type=None)     -> LogRecord
parse_batch(directory, *, category=None)                     -> list[LogRecord]
parse_all_categories(base_dir)                               -> dict[str, list[LogRecord]]
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Union


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# 3-column structured format
_LINE_RE = re.compile(
    r"^(?P<job>[^\t]+)\t"
    r"(?P<step>[^\t]+)\t"
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"(?:\s(?P<msg>.*))?$"
)

# Single-timestamp format (GHA runner lines)
_BARE_LINE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)"
    r"(?:\s(?P<msg>.*))?$"
)

# Strip ANSI control sequences and BOM
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\ufeff")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# Exit code annotation / process exit pattern
_EXIT_CODE_RE = re.compile(
    r"(?:##\[error\]Process completed with exit code|Process exited unexpectedly with code|exited with code|exit code)\s+(\d+)",
    re.IGNORECASE
)

# GitHub Actions timeout annotation
_TIMEOUT_RE = re.compile(
    r"##\[error\]The action '(?P<step>[^']+)' has timed out after (?P<dur>\d+(?:\.\d+)?) minutes"
)

# Orphan process termination in GHA cleanup
_ORPHAN_PROC_RE = re.compile(r"Terminate orphan process:\s+pid\s+\(\d+\)\s+\((?P<proc>[^)]+)\)")

# Syntax/Indentation error patterns
_SYNTAX_ERROR_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("TabError",         re.compile(r"\bTabError\s*:\s*(.+)")),
    ("IndentationError", re.compile(r"\bIndentationError\s*:\s*(.+)")),
    ("SyntaxError",      re.compile(r"\bSyntaxError\s*:\s*(.+)")),
]

# Standard Python traceback file pointer
_TRACEBACK_FILE_RE = re.compile(r'File\s+"([^"]+)",\s+line\s+(\d+)')

# General Python exceptions
_GENERIC_EXCEPTION_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("ModuleNotFoundError", re.compile(r"\bModuleNotFoundError\s*:\s*(.+)")),
    ("ImportError",         re.compile(r"\bImportError\s*:\s*(.+)")),
    ("NameError",           re.compile(r"\bNameError\s*:\s*(.+)")),
    ("TypeError",           re.compile(r"\bTypeError\s*:\s*(.+)")),
    ("ValueError",          re.compile(r"\bValueError\s*:\s*(.+)")),
    ("AttributeError",      re.compile(r"\bAttributeError\s*:\s*(.+)")),
    ("KeyError",            re.compile(r"\bKeyError\s*:\s*(.+)")),
    ("IndexError",          re.compile(r"\bIndexError\s*:\s*(.+)")),
    ("ZeroDivisionError",   re.compile(r"\bZeroDivisionError\s*:\s*(.+)")),
    ("FileNotFoundError",   re.compile(r"\bFileNotFoundError\s*:\s*(.+)")),
    ("AssertionError",      re.compile(r"\bAssertionError(?:\s*:\s*(.*))?")),
    ("RuntimeError",        re.compile(r"\bRuntimeError\s*:\s*(.+)")),
]

# Pip failure patterns
_PIP_NO_MATCH_RE = re.compile(
    r"ERROR:\s+(?:No matching distribution found for|Could not find a version that satisfies the requirement)\s+([^\s\r\n]+)"
)
_PIP_INVALID_REQ_RE = re.compile(r"ERROR:\s+Invalid requirement:\s+'([^']+)'")
_PIP_BUILD_FAIL_RE = re.compile(r"ERROR:\s+Failed to build\s+'([^']+)'")

# Pytest failure patterns
_PYTEST_SUMMARY_FAIL_RE = re.compile(r"^FAILED\s+(tests/[^\s:]+::\w+)\s+-\s+([A-Za-z0-9_]+)(?::\s*(.*))?$")
_PYTEST_COUNTS_RE = re.compile(r"=\s*(?:(?P<failed>\d+)\s+failed)?(?:,\s*)?(?:(?P<passed>\d+)\s+passed)?(?:\s+in\s+[\d\.]+s)?\s*=")
_PYTEST_SESSION_RE = re.compile(r"platform\s+\w+\s+--\s+Python\s+[\d\.]+,?\s+(pytest-[\d\.]+)")

# Tool detection keywords
_TOOL_KEYWORDS = ["pytest", "pip", "python", "git", "flake8", "black", "mypy", "bash"]


def _clean(text: str) -> str:
    """Remove ANSI escapes, BOM, and non-printable control chars."""
    text = text.replace("\ufeff", "")
    text = _ANSI_RE.sub("", text)
    text = _CTRL_RE.sub("", text)
    return text


def _parse_ts(ts_str: str) -> Optional[datetime]:
    """Parse an ISO 8601 timestamp string into a timezone-aware datetime."""
    try:
        dt = datetime.fromisoformat(ts_str.rstrip("Z"))
        return dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _infer_stage(step_name: Optional[str]) -> str:
    """Map a step name to a pipeline stage label."""
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


# ---------------------------------------------------------------------------
# Data class schema for LogRecord (V1 preserved + V2 enriched)
# ---------------------------------------------------------------------------

@dataclass
class LogRecord:
    """Structured representation of a parsed CI/CD log."""

    # --- required V1 schema columns (preserved) ---
    run_id:        Optional[str]   = None
    timestamp:     Optional[str]   = None   # ISO-8601 UTC string
    step_name:     Optional[str]   = None
    stage:         Optional[str]   = None
    duration:      Optional[float] = None   # seconds
    status:        Optional[str]   = None   # "success" | "failure" | "unknown"
    error_type:    Optional[str]   = None
    error_message: Optional[str]   = None
    log_text:      str             = ""     # full raw log
    failure_type:  Optional[str]   = None

    # --- optional V1 enrichment columns (preserved) ---
    line_number:   Optional[int]   = None
    file_path:     Optional[str]   = None
    matched_line:  Optional[str]   = None
    exit_code:     Optional[int]   = None
    python_version: Optional[str]  = None

    # --- Parser V2: generalized failure fields ---
    failure_class:        Optional[str]   = None  # "syntax_error" | "dependency_error" | "test_failure" | "timeout" | "runtime_error" | "unknown"
    failure_subcategory:  Optional[str]   = None  # e.g. "SyntaxError", "pip_missing_dependency", "ZeroDivisionError", "gha_timeout"

    # --- step sequence ---
    step_sequence:        list[str]       = field(default_factory=list)
    failed_step:          Optional[str]   = None
    execution_path:       list[str]       = field(default_factory=list)

    # --- evidence ---
    evidence_lines:       list[str]       = field(default_factory=list)
    traceback_lines:      list[str]       = field(default_factory=list)

    # --- command/tool/framework ---
    commands_run:         list[str]       = field(default_factory=list)
    tools_detected:       list[str]       = field(default_factory=list)
    frameworks_detected:  list[str]       = field(default_factory=list)

    # --- dependency evidence (F2) ---
    failing_package:      Optional[str]   = None
    packages_attempted:   list[str]       = field(default_factory=list)
    pip_commands:         list[str]       = field(default_factory=list)

    # --- test evidence (F3) ---
    pytest_session:       Optional[str]   = None
    tests_collected:      Optional[int]   = None
    tests_passed:         Optional[int]   = None
    tests_failed:         Optional[int]   = None
    failed_test_ids:      list[str]       = field(default_factory=list)
    test_error_type:      Optional[str]   = None

    # --- timeout evidence (F4) ---
    timeout_duration_min: Optional[float] = None
    elapsed_step_seconds: Optional[float] = None
    orphan_process:       Optional[str]   = None

    # --- meta ---
    log_format:           Optional[str]   = None  # "structured" | "bare"
    log_line_count:       Optional[int]   = None
    parser_confidence:    float           = 0.0
    parse_errors:         list[str]       = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Core parsing logic
# ---------------------------------------------------------------------------

_BOILERPLATE_STEPS = {
    "set up job", "complete job", "post checkout repository",
    "runner image provisioner", "operating system", "runner image",
    "github_token permissions"
}

def _is_boilerplate(step: str) -> bool:
    s = step.strip().lower()
    if s in _BOILERPLATE_STEPS or s.startswith("post "):
        return True
    return False


def parse_log_text(
    text: str,
    *,
    run_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> LogRecord:
    """
    Parse raw CI/CD log text and return a fully structured LogRecord.
    """
    record = LogRecord(run_id=run_id, log_text=text, failure_type=failure_type)

    raw_lines = text.splitlines()
    record.log_line_count = len(raw_lines)
    if not text.strip() or not raw_lines:
        record.status = "unknown"
        record.failure_class = "unknown"
        record.parser_confidence = 0.0
        return record

    # 1. Parse lines and auto-detect format
    structured_entries: list[dict] = []
    bare_entries: list[dict] = []
    for raw in raw_lines:
        cleaned = _clean(raw)
        m_struct = _LINE_RE.match(cleaned)
        if m_struct:
            structured_entries.append({
                "job": m_struct.group("job"),
                "step": m_struct.group("step"),
                "ts": m_struct.group("ts"),
                "msg": (m_struct.group("msg") or "").strip(),
                "raw": cleaned,
            })
            continue
        m_bare = _BARE_LINE_RE.match(cleaned)
        if m_bare:
            bare_entries.append({
                "ts": m_bare.group("ts"),
                "msg": (m_bare.group("msg") or "").strip(),
                "raw": cleaned,
            })

    if structured_entries and len(structured_entries) >= len(bare_entries):
        record.log_format = "structured"
        parsed_stream = structured_entries
    elif bare_entries:
        record.log_format = "bare"
        parsed_stream = bare_entries
    else:
        record.log_format = "bare"
        parsed_stream = [{"ts": None, "msg": _clean(r).strip(), "raw": _clean(r)} for r in raw_lines]

    # Timestamp: first timestamp observed
    for item in parsed_stream:
        if item.get("ts"):
            record.timestamp = item["ts"]
            break

    # 2. Extract step sequence, commands, tools, frameworks
    step_sequence: list[str] = []
    seen_steps: set[str] = set()
    current_step: Optional[str] = None
    step_entry_map: dict[str, list[dict]] = {}

    commands_run: list[str] = []
    tools_detected: set[str] = set()
    frameworks_detected: set[str] = set()
    packages_attempted: list[str] = []
    pip_commands: list[str] = []

    if record.log_format == "structured":
        for entry in parsed_stream:
            step = entry.get("step")
            msg = entry.get("msg", "")

            if step:
                if step not in step_entry_map:
                    step_entry_map[step] = []
                step_entry_map[step].append(entry)

                if not _is_boilerplate(step) and step not in seen_steps:
                    seen_steps.add(step)
                    step_sequence.append(step)

            # Commands detection
            if msg.startswith("[command]"):
                cmd = msg[len("[command]"):].strip()
                if cmd not in commands_run:
                    commands_run.append(cmd)
            elif step == "Check App Syntax" and "python -c" in msg:
                if msg not in commands_run:
                    commands_run.append(msg)
            elif "pip install" in msg:
                if msg not in pip_commands:
                    pip_commands.append(msg)
                if msg not in commands_run:
                    commands_run.append(msg)

            # Attempted packages
            if msg.startswith("Collecting "):
                pkg = msg.split()[1]
                if pkg not in packages_attempted:
                    packages_attempted.append(pkg)

    else:
        # Bare / runner group format
        for entry in parsed_stream:
            msg = entry.get("msg", "")
            if "##[group]Run " in msg:
                step_cmd = msg.split("##[group]Run ", 1)[1].strip()
                current_step = step_cmd
                if current_step not in seen_steps:
                    seen_steps.add(current_step)
                    step_sequence.append(current_step)

            if current_step:
                if current_step not in step_entry_map:
                    step_entry_map[current_step] = []
                step_entry_map[current_step].append(entry)

            # Commands
            if "##[group]Run " in msg:
                cmd = msg.split("##[group]Run ", 1)[1].strip()
                if cmd not in commands_run:
                    commands_run.append(cmd)
            elif msg.startswith("[command]"):
                cmd = msg[len("[command]"):].strip()
                if cmd not in commands_run:
                    commands_run.append(cmd)
            elif "pip install" in msg:
                if msg not in pip_commands:
                    pip_commands.append(msg)
                if msg not in commands_run:
                    commands_run.append(msg)

            if msg.startswith("Collecting "):
                pkg = msg.split()[1]
                if pkg not in packages_attempted:
                    packages_attempted.append(pkg)

    record.step_sequence = step_sequence
    record.packages_attempted = packages_attempted
    record.pip_commands = pip_commands

    # Detect tools & frameworks from log messages
    full_text_lower = text.lower()
    for tool in _TOOL_KEYWORDS:
        if tool in full_text_lower or any(tool in cmd.lower() for cmd in commands_run):
            tools_detected.add(tool)

    for entry in parsed_stream:
        msg = entry.get("msg", "")
        # Python version
        if not record.python_version:
            m_pv = re.search(r"(?:CPython|Python)\s+\(?(\d+\.\d+\.\d+)\)?", msg)
            if m_pv:
                record.python_version = m_pv.group(1)
        # Pytest session & framework
        m_pytest = _PYTEST_SESSION_RE.search(msg)
        if m_pytest:
            record.pytest_session = msg
            frameworks_detected.add(m_pytest.group(1))
        # Exit code
        m_ec = _EXIT_CODE_RE.search(msg)
        if m_ec:
            record.exit_code = int(m_ec.group(1))

    record.tools_detected = sorted(tools_detected)
    record.frameworks_detected = sorted(frameworks_detected)
    record.commands_run = commands_run

    # 3. Category-specific failure detectors (in strict priority order)
    # Rule 1: ##[error] alone must NOT determine category.
    # Rule 2: Exception in pytest must be failure_class = "test_failure".
    detected_class: Optional[str] = None
    detected_subcat: Optional[str] = None
    failed_step: Optional[str] = None
    evidence_lines: list[str] = []
    traceback_lines: list[str] = []
    confidence: float = 0.0

    # -------------------------------------------------------------
    # (A) Check for Timeout (F4)
    # -------------------------------------------------------------
    m_timeout = _TIMEOUT_RE.search(text)
    if m_timeout:
        detected_class = "timeout"
        detected_subcat = "gha_timeout"
        failed_step = m_timeout.group("step")
        dur_min = float(m_timeout.group("dur"))
        record.timeout_duration_min = dur_min

        # Orphan process detection
        m_orphan = _ORPHAN_PROC_RE.search(text)
        if m_orphan:
            record.orphan_process = m_orphan.group("proc")

        # Locate evidence lines
        for entry in parsed_stream:
            msg = entry.get("msg", "")
            if "has timed out after" in msg or "Terminate orphan process" in msg:
                evidence_lines.append(entry.get("raw", msg))

        confidence = 1.0 if (dur_min and record.orphan_process) else 0.85

    # -------------------------------------------------------------
    # (B) Check for Pytest test failure (F3)
    # -------------------------------------------------------------
    if not detected_class:
        is_test_failure = False
        pytest_failed_tests: list[str] = []
        pytest_error_type: Optional[str] = None
        pytest_err_msg: Optional[str] = None

        # Look for short test summary lines
        for entry in parsed_stream:
            msg = entry.get("msg", "")
            m_fail = _PYTEST_SUMMARY_FAIL_RE.match(msg)
            if m_fail:
                is_test_failure = True
                test_id = m_fail.group(1)
                etype = m_fail.group(2)
                emsg = (m_fail.group(3) or "").strip()
                if test_id not in pytest_failed_tests:
                    pytest_failed_tests.append(test_id)
                if not pytest_error_type:
                    pytest_error_type = etype
                    pytest_err_msg = emsg

        # Check for counts line (e.g. "= 1 failed, 5 passed in 0.03s =")
        m_failed_cnt = re.search(r"\b(\d+)\s+failed\b", text)
        if m_failed_cnt:
            record.tests_failed = int(m_failed_cnt.group(1))
            if record.tests_failed > 0:
                is_test_failure = True

        m_passed_cnt = re.search(r"\b(\d+)\s+passed\b", text)
        if m_passed_cnt:
            record.tests_passed = int(m_passed_cnt.group(1))

        if is_test_failure or "= FAILURES =" in text:
            detected_class = "test_failure"
            detected_subcat = pytest_error_type or "pytest_failure"
            record.test_error_type = pytest_error_type
            record.failed_test_ids = pytest_failed_tests
            record.error_type = pytest_error_type
            record.error_message = pytest_err_msg

            # In bare runner format or structured format, identify the failed step
            for step in reversed(step_sequence):
                if "test" in step.lower() or "pytest" in step.lower():
                    failed_step = step
                    break
            if not failed_step and step_sequence:
                failed_step = step_sequence[-1]

            # Extract pytest traceback block
            tb_collecting = False
            for entry in parsed_stream:
                raw_l = entry.get("raw", "")
                msg_l = entry.get("msg", "")
                if "=== FAILURES ===" in raw_l:
                    tb_collecting = True
                if tb_collecting:
                    traceback_lines.append(raw_l)
                    if "=== short test summary info ===" in raw_l and len(traceback_lines) > 2:
                        tb_collecting = False

            # Evidence lines: short summary lines + counts line
            for entry in parsed_stream:
                msg = entry.get("msg", "")
                if msg.startswith("FAILED tests/") or _PYTEST_COUNTS_RE.search(msg):
                    evidence_lines.append(entry.get("raw", msg))

            # Pytest items collected count
            m_coll = re.search(r"collected\s+(\d+)\s+items?", text)
            if m_coll:
                record.tests_collected = int(m_coll.group(1))

            confidence = 1.0 if (pytest_failed_tests and pytest_error_type) else 0.85

    # -------------------------------------------------------------
    # (C) Check for Dependency / Pip failure (F2)
    # -------------------------------------------------------------
    if not detected_class:
        m_pip_no_match = _PIP_NO_MATCH_RE.search(text)
        m_pip_invalid = _PIP_INVALID_REQ_RE.search(text)
        m_pip_build = _PIP_BUILD_FAIL_RE.search(text)

        if m_pip_no_match or m_pip_invalid or m_pip_build:
            detected_class = "dependency_error"
            if m_pip_no_match:
                record.failing_package = m_pip_no_match.group(1)
                detected_subcat = "pip_missing_dependency"
                record.error_message = f"No matching distribution or requirement for {record.failing_package}"
            elif m_pip_invalid:
                record.failing_package = m_pip_invalid.group(1)
                detected_subcat = "pip_invalid_requirement"
                record.error_message = f"Invalid requirement: {record.failing_package}"
            elif m_pip_build:
                record.failing_package = m_pip_build.group(1)
                detected_subcat = "pip_build_failure"
                record.error_message = f"Failed to build {record.failing_package}"

            record.error_type = detected_subcat
            for step in step_sequence:
                if any(kw in step.lower() for kw in ("install", "dep", "pip")):
                    failed_step = step
                    break
            if not failed_step:
                failed_step = "Install Dependencies"

            for entry in parsed_stream:
                msg = entry.get("msg", "")
                if "ERROR:" in msg:
                    evidence_lines.append(entry.get("raw", msg))

            confidence = 1.0 if record.failing_package else 0.85

    # -------------------------------------------------------------
    # (D) Check for Syntax errors (F1)
    # -------------------------------------------------------------
    if not detected_class:
        for etype, pattern in _SYNTAX_ERROR_PATTERNS:
            m_syntax = pattern.search(text)
            if m_syntax:
                detected_class = "syntax_error"
                detected_subcat = etype
                record.error_type = etype
                record.error_message = m_syntax.group(1).strip()
                record.matched_line = m_syntax.group(0).strip()
                break

        if detected_class == "syntax_error":
            # Find file and line number
            m_tb_file = _TRACEBACK_FILE_RE.search(text)
            if m_tb_file:
                record.file_path = m_tb_file.group(1)
                record.line_number = int(m_tb_file.group(2))

            # Extract python traceback block
            tb_block: list[str] = []
            capturing = False
            for entry in parsed_stream:
                raw_l = entry.get("raw", "")
                msg = entry.get("msg", "")
                if "Traceback (most recent call last):" in msg or "File " in msg and not capturing:
                    capturing = True
                if capturing:
                    tb_block.append(raw_l)
                    if any(etype in msg for etype in ("SyntaxError:", "IndentationError:", "TabError:")):
                        capturing = False
            traceback_lines = tb_block
            evidence_lines = list(tb_block) if tb_block else [record.matched_line or ""]

            for step in step_sequence:
                if any(kw in step.lower() for kw in ("syntax", "check app syntax")):
                    failed_step = step
                    break
            if not failed_step:
                failed_step = "Check App Syntax"

            confidence = 1.0 if (traceback_lines and record.file_path) else 0.85

    # -------------------------------------------------------------
    # (E) Check for Generic Runtime Python Exception (outside pytest/syntax)
    # -------------------------------------------------------------
    if not detected_class:
        for etype, pattern in _GENERIC_EXCEPTION_PATTERNS:
            m_exc = pattern.search(text)
            if m_exc:
                detected_class = "runtime_error"
                detected_subcat = etype
                record.error_type = etype
                record.error_message = (m_exc.group(1) or "").strip()
                record.matched_line = m_exc.group(0).strip()
                break

        if detected_class == "runtime_error":
            m_tb_file = _TRACEBACK_FILE_RE.search(text)
            if m_tb_file:
                record.file_path = m_tb_file.group(1)
                record.line_number = int(m_tb_file.group(2))

            for step in reversed(step_sequence):
                if not _is_boilerplate(step):
                    failed_step = step
                    break

            confidence = 0.8

    # -------------------------------------------------------------
    # (F) Fallback / Unknown
    # -------------------------------------------------------------
    if not detected_class:
        # Check if generic exit code or ##[error] exists
        if record.exit_code is not None or "##[error]" in text:
            detected_class = "unknown"
            detected_subcat = "unknown_failure"
            confidence = 0.5
            for entry in parsed_stream:
                msg = entry.get("msg", "")
                if "##[error]" in msg:
                    evidence_lines.append(entry.get("raw", msg))
        else:
            detected_class = "unknown"
            detected_subcat = None
            confidence = 0.0

    record.failure_class = detected_class
    record.failure_subcategory = detected_subcat
    record.failed_step = failed_step
    record.step_name = failed_step
    record.evidence_lines = evidence_lines
    record.traceback_lines = traceback_lines
    record.parser_confidence = confidence

    # Status
    if record.failure_class in ("syntax_error", "dependency_error", "test_failure", "timeout", "runtime_error"):
        record.status = "failure"
    elif record.exit_code is not None:
        record.status = "failure" if record.exit_code != 0 else "success"
    elif "##[error]" in text:
        record.status = "failure"
    else:
        record.status = "unknown"

    # Execution path: substantive steps up to and including the failed step
    execution_path: list[str] = []
    for step in step_sequence:
        execution_path.append(step)
        if step == failed_step:
            break
    record.execution_path = execution_path

    # Stage inference
    record.stage = _infer_stage(record.failed_step or record.step_name)

    # Calculate duration of the failed step
    target_step = record.failed_step or record.step_name
    if target_step and target_step in step_entry_map:
        step_lines = step_entry_map[target_step]
        if len(step_lines) >= 2 and step_lines[0].get("ts") and step_lines[-1].get("ts"):
            t0 = _parse_ts(step_lines[0]["ts"])
            t1 = _parse_ts(step_lines[-1]["ts"])
            if t0 and t1:
                delta = round((t1 - t0).total_seconds(), 3)
                record.duration = delta
                record.elapsed_step_seconds = delta

    # Map failure_type for V1 backward compatibility if not provided
    if record.failure_type is None:
        record.failure_type = record.failure_class

    return record


def parse_log_file(
    path: Union[str, Path],
    *,
    run_id: Optional[str] = None,
    failure_type: Optional[str] = None,
) -> LogRecord:
    """
    Parse a single CI/CD log file and return a LogRecord.
    """
    path = Path(path)
    if run_id is None:
        run_id = path.stem

    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_log_text(text, run_id=run_id, failure_type=failure_type)


def parse_batch(
    directory: Union[str, Path],
    *,
    category: Optional[str] = None,
) -> list[LogRecord]:
    """
    Scan a directory for files, parse each as a LogRecord, and return the list.
    """
    dir_path = Path(directory)
    if not dir_path.exists() or not dir_path.is_dir():
        return []

    files = sorted(
        f for f in dir_path.iterdir()
        if f.is_file()
        and f.suffix.lower() == ".log"
        and not f.name.startswith(".")
    )
    records: list[LogRecord] = []
    for f in files:
        rec = parse_log_file(f, failure_type=category)
        records.append(rec)
    return records


def parse_all_categories(base_dir: Union[str, Path] = "logs") -> dict[str, list[LogRecord]]:
    """
    Scan standard subdirectories (F1, F2, F3, F4) under base_dir and parse all logs.
    """
    base = Path(base_dir)
    results: dict[str, list[LogRecord]] = {}
    for cat in ["F1", "F2", "F3", "F4"]:
        cat_dir = base / cat
        if cat_dir.exists() and cat_dir.is_dir():
            results[cat] = parse_batch(cat_dir)
        else:
            results[cat] = []
    return results
