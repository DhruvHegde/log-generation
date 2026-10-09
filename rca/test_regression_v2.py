"""rca/test_regression_v2.py

Comprehensive regression test suite for Parser V2 and RCA V1 enhancements.
Covers ANSI code preprocessing, wrapped pytest (tox/uv), Docker dependency extraction,
timeout & cancellation distinction, and syntax error routing.
"""

from __future__ import annotations

import pytest

from parser.log_parser import parse_log_text
from rca.engine import analyze_record
from rca.schema import (
    CAUSAL_CODE_DEFECT,
    CAUSAL_DEPENDENCY,
    CAUSAL_TEST,
    CAUSAL_TEST_EXECUTION,
    CAUSAL_TIMEOUT,
    CAUSAL_UNKNOWN,
)


# =============================================================================
# 1. ANSI Escape-Code Handling Tests (Section 2)
# =============================================================================

def test_ansi_coloured_pytest_failure():
    log_text = (
        "ci-job\tRun Tests\t2026-10-09T10:00:00Z \x1b[31mFAILED tests/test_app.py::test_calc - AssertionError: assert 1 == 2\x1b[0m\n"
        "ci-job\tRun Tests\t2026-10-09T10:00:01Z \x1b[1m= \x1b[31m1 failed\x1b[0m, \x1b[32m5 passed\x1b[0m in 0.05s =\x1b[0m\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "test_failure"
    assert rec.test_error_type == "AssertionError"
    assert "tests/test_app.py::test_calc" in rec.failed_test_ids

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_TEST
    assert "tests/test_app.py::test_calc" in report.summary


def test_ansi_coloured_syntax_traceback():
    log_text = (
        "job1\tCheck App Syntax\t2026-10-09T10:00:00Z Traceback (most recent call last):\n"
        "job1\tCheck App Syntax\t2026-10-09T10:00:01Z \x1b[36m  File \"src/main.py\", line 15\x1b[0m\n"
        "job1\tCheck App Syntax\t2026-10-09T10:00:02Z     def foo()\n"
        "job1\tCheck App Syntax\t2026-10-09T10:00:03Z              ^\n"
        "job1\tCheck App Syntax\t2026-10-09T10:00:04Z \x1b[31;1mSyntaxError: invalid syntax\x1b[0m\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "syntax_error"
    assert rec.file_path == "src/main.py"
    assert rec.line_number == 15

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_CODE_DEFECT
    assert report.local_reproduction_command == "python -m py_compile src/main.py"


def test_ansi_caret_notation_and_normal_logs():
    log_text = (
        "job1\tInstall Dependencies\t2026-10-09T10:00:00Z ^[[36;1mpython -m pip install scipy==999.0.0^[[0m\n"
        "job1\tInstall Dependencies\t2026-10-09T10:00:01Z ^[[31mERROR: Could not find a version that satisfies the requirement scipy==999.0.0^[[0m\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "dependency_error"
    assert rec.failing_package == "scipy==999.0.0"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_DEPENDENCY


# =============================================================================
# 2. Nested Pytest, Tox, and UV Output Tests (Section 3)
# =============================================================================

def test_pytest_wrapped_in_tox():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run tox -e py310\n"
        "2026-10-09T10:00:01Z py310: commands[0]> pytest\n"
        "2026-10-09T10:00:02Z py310: FAILED tests/unit/test_auth.py::TestLogin::test_failure - ValueError: Invalid credentials\n"
        "2026-10-09T10:00:03Z py310: === 1 failed, 12 passed in 1.25s ===\n"
        "2026-10-09T10:00:04Z ##[error]Process completed with exit code 1\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "test_failure"
    assert rec.test_error_type == "ValueError"
    assert "tests/unit/test_auth.py::TestLogin::test_failure" in rec.failed_test_ids
    assert "tox" in rec.tools_detected

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_TEST_EXECUTION


def test_pytest_wrapped_in_uv():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run uv run pytest\n"
        "2026-10-09T10:00:01Z [uv] FAILED src/tests/test_api.py::test_endpoint - KeyError: 'access_token'\n"
        "2026-10-09T10:00:02Z [uv] = 1 failed, 8 passed in 0.45s =\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "test_failure"
    assert rec.test_error_type == "KeyError"
    assert "uv" in rec.tools_detected

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_TEST_EXECUTION


# =============================================================================
# 3. Docker Build Dependency Detection Tests (Section 4)
# =============================================================================

def test_docker_build_with_pip_dependency_error():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run docker build -t myapp .\n"
        "2026-10-09T10:00:01Z #5 [2/4] RUN pip install non_existent_pkg_12345==1.0\n"
        "2026-10-09T10:00:02Z #5 1.543 ERROR: Could not find a version that satisfies the requirement non_existent_pkg_12345==1.0\n"
        "2026-10-09T10:00:03Z #5 1.544 ERROR: No matching distribution found for non_existent_pkg_12345==1.0\n"
        "2026-10-09T10:00:04Z #5 ERROR: process \"/bin/sh -c pip install non_existent_pkg_12345==1.0\" did not complete successfully: exit code: 1\n"
        "2026-10-09T10:00:05Z ERROR: failed to solve: process \"/bin/sh -c pip install non_existent_pkg_12345==1.0\" did not complete successfully: exit code: 1\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "dependency_error"
    assert rec.failing_package == "non_existent_pkg_12345==1.0"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_DEPENDENCY
    assert "non_existent_pkg_12345==1.0" in report.summary


def test_docker_build_failure_without_dependency_error():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run docker build -t myapp .\n"
        "2026-10-09T10:00:01Z #5 [3/4] RUN gcc -o main main.c\n"
        "2026-10-09T10:00:02Z #5 2.100 main.c: fatal error: missing_header.h: No such file or directory\n"
        "2026-10-09T10:00:03Z #5 ERROR: process \"/bin/sh -c gcc -o main main.c\" did not complete successfully: exit code: 1\n"
        "2026-10-09T10:00:04Z ##[error]Process completed with exit code 1\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class != "dependency_error"

    report = analyze_record(rec)
    assert report.causal_category != CAUSAL_DEPENDENCY


def test_package_resolution_conflict():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run pip install -r requirements.txt\n"
        "2026-10-09T10:00:01Z ERROR: Cannot install packageA and packageB because these package versions have conflicting dependencies.\n"
        "2026-10-09T10:00:02Z ResolutionImpossible: The conflict is caused by packageA==1.0 and packageB==2.0\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "dependency_error"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_DEPENDENCY


def test_ordinary_docker_build_error():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run docker build .\n"
        "2026-10-09T10:00:01Z #4 [1/2] COPY invalid_file.txt /app/\n"
        "2026-10-09T10:00:02Z #4 ERROR: \"invalid_file.txt\" not found: failed to calculate checksum\n"
        "2026-10-09T10:00:03Z ##[error]Process completed with exit code 1\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class != "dependency_error"


# =============================================================================
# 4. Timeout and Cancellation Tests (Section 5)
# =============================================================================

def test_explicit_timeout():
    log_text = (
        "job\tRun Tests\t2026-10-09T10:00:00Z ##[error]The action 'Run Tests' has timed out after 15 minutes\n"
        "job\tRun Tests\t2026-10-09T10:15:00Z Terminate orphan process: pid (1234) (pytest)\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "timeout"
    assert rec.timeout_duration_min == 15.0
    assert rec.orphan_process == "pytest"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_TIMEOUT
    assert report.rca_confidence == 1.0


def test_cancellation_without_timeout_text():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run pytest\n"
        "2026-10-09T10:02:00Z ##[error]The operation was canceled.\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "timeout"
    assert rec.failure_subcategory == "gha_cancellation"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_TIMEOUT
    assert report.rca_confidence < 1.0
    assert any("Cancellation signals do not distinguish" in lim for lim in report.limitations)


def test_exit_code_137():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run test suite\n"
        "2026-10-09T10:01:00Z ##[error]Process completed with exit code 137\n"
    )
    rec = parse_log_text(log_text)
    assert rec.exit_code == 137
    assert rec.failure_class == "unknown"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_UNKNOWN
    assert report.rca_confidence <= 0.4
    assert any("SIGKILL" in lim or "137" in lim for lim in report.limitations)


def test_exit_code_143():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run long task\n"
        "2026-10-09T10:01:00Z ##[error]Process completed with exit code 143\n"
    )
    rec = parse_log_text(log_text)
    assert rec.exit_code == 143

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_UNKNOWN
    assert any("SIGTERM" in lim or "143" in lim for lim in report.limitations)


def test_unrelated_text_with_timeout_word():
    log_text = (
        "job\tRun Tests\t2026-10-09T10:00:00Z Setting DEFAULT_TIMEOUT = 30 seconds in config.py\n"
        "job\tRun Tests\t2026-10-09T10:00:01Z FAILED tests/test_net.py::test_connect - AssertionError: assert False\n"
        "job\tRun Tests\t2026-10-09T10:00:02Z = 1 failed in 0.10s =\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "test_failure"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_TEST


# =============================================================================
# 5. Syntax-Error Routing Tests (Section 6)
# =============================================================================

def test_syntax_error_inside_pytest_collection():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run pytest\n"
        "2026-10-09T10:00:01Z ============================= ERRORS =============================\n"
        "2026-10-09T10:00:02Z ________________ ERROR collecting tests/test_bad_syntax.py ________________\n"
        "2026-10-09T10:00:03Z Traceback (most recent call last):\n"
        "2026-10-09T10:00:04Z   File \"tests/test_bad_syntax.py\", line 12\n"
        "2026-10-09T10:00:05Z     def test_foo()\n"
        "2026-10-09T10:00:06Z                  ^\n"
        "2026-10-09T10:00:07Z SyntaxError: expected ':'\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "syntax_error"
    assert rec.file_path == "tests/test_bad_syntax.py"
    assert rec.line_number == 12

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_CODE_DEFECT
    assert report.local_reproduction_command == "python -m py_compile tests/test_bad_syntax.py"


def test_syntax_string_path_resolution():
    log_text = (
        "job\tCheck Syntax\t2026-10-09T10:00:00Z Traceback (most recent call last):\n"
        "job\tCheck Syntax\t2026-10-09T10:00:01Z   File \"<string>\", line 1, in <module>\n"
        "job\tCheck Syntax\t2026-10-09T10:00:02Z   File \"src/app/core.py\", line 42\n"
        "job\tCheck Syntax\t2026-10-09T10:00:03Z SyntaxError: invalid syntax\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class == "syntax_error"

    report = analyze_record(rec)
    assert report.causal_category == CAUSAL_CODE_DEFECT
    assert report.observed_evidence["source_file"] == "src/app/core.py"
    assert report.local_reproduction_command == "python -m py_compile src/app/core.py"


def test_genuine_assertion_vs_execution_exception():
    # Assertion failure
    log_assert = (
        "ci\tRun Tests\t2026-10-09T10:00:00Z FAILED tests/test_a.py::test_val - AssertionError: assert 10 == 20\n"
        "ci\tRun Tests\t2026-10-09T10:00:01Z = 1 failed in 0.01s =\n"
    )
    rec_a = parse_log_text(log_assert)
    rep_a = analyze_record(rec_a)
    assert rep_a.causal_category == CAUSAL_TEST

    # Execution exception (ZeroDivisionError)
    log_exec = (
        "ci\tRun Tests\t2026-10-09T10:00:00Z FAILED tests/test_b.py::test_div - ZeroDivisionError: division by zero\n"
        "ci\tRun Tests\t2026-10-09T10:00:01Z = 1 failed in 0.01s =\n"
    )
    rec_e = parse_log_text(log_exec)
    rep_e = analyze_record(rec_e)
    assert rep_e.causal_category == CAUSAL_TEST_EXECUTION


def test_syntax_related_words_without_syntax_exception():
    log_text = (
        "2026-10-09T10:00:00Z ##[group]Run check syntax guidelines\n"
        "2026-10-09T10:00:01Z Checking file syntax formatting...\n"
        "2026-10-09T10:00:02Z Process completed with exit code 0\n"
    )
    rec = parse_log_text(log_text)
    assert rec.failure_class != "syntax_error"
