"""Validation helpers for identifying genuine Docker/container build failures (F5).

This module is designed for the combined 7-class CI/CD failure dataset:
- F1: Syntax errors (SyntaxError, IndentationError, TabError)
- F2: Dependency errors (pip, apt, npm package resolution failures)
- F3: Test failures (pytest, unittest assertions)
- F4: Timeouts (runner and step timeouts)
- F5: Docker build failures (Dockerfile parsing, build context, stage refs, BuildKit configs)
- F6: CI/CD configuration & permissions (runner setup, daemon unavailable, docker.sock perm)
- F7: Network / remote service failures (registry down, rate limits, TLS/DNS drop)

Canonical label: docker_build_failure
Category ID: F5
"""

import re
from pathlib import Path

# Explicit rejection signatures that belong to the other 6 categories
EXCLUSION_PATTERNS = {
    "F1_syntax": [
        re.compile(r"SyntaxError:\s*.+", re.IGNORECASE),
        re.compile(r"IndentationError:\s*.+", re.IGNORECASE),
        re.compile(r"TabError:\s*.+", re.IGNORECASE),
    ],
    "F2_dependency": [
        re.compile(r"Could not find a version that satisfies the requirement", re.IGNORECASE),
        re.compile(r"No matching distribution found", re.IGNORECASE),
        re.compile(r"ResolutionImpossible", re.IGNORECASE),
        re.compile(r"Invalid requirement:\s*", re.IGNORECASE),
        re.compile(r"E: Unable to locate package\s+", re.IGNORECASE),
        re.compile(r"npm ERR!\s*404\s*Not Found", re.IGNORECASE),
        re.compile(r"apk add.*ERROR: unable to select packages", re.IGNORECASE),
        re.compile(r"cargo.*failed to select a version", re.IGNORECASE),
    ],
    "F3_test": [
        re.compile(r"===+ FAILURES ===+", re.IGNORECASE),
        re.compile(r"FAILED\s+\(failures=\d+\)", re.IGNORECASE),
        re.compile(r"^E\s+assert\s+.+", re.MULTILINE),
        re.compile(r"FAILED\s+[^\s:]+::[^\s:]+", re.IGNORECASE),
    ],
    "F4_timeout": [
        re.compile(r"has exceeded the maximum execution time", re.IGNORECASE),
        re.compile(r"The operation was canceled because it has timed out", re.IGNORECASE),
        re.compile(r"timed out after \d+ (minutes|seconds)", re.IGNORECASE),
        re.compile(r"The action '.*' has timed out", re.IGNORECASE),
    ],
    "F6_daemon_workflow": [
        re.compile(r"Cannot connect to the Docker daemon at unix:///var/run/docker\.sock", re.IGNORECASE),
        re.compile(r"Is the docker daemon running\?", re.IGNORECASE),
        re.compile(r"permission denied while trying to connect to the Docker daemon socket", re.IGNORECASE),
        re.compile(r"docker: command not found", re.IGNORECASE),
        re.compile(r"/var/run/docker\.sock: connect: permission denied", re.IGNORECASE),
    ],
    "F7_network": [
        re.compile(r"toomanyrequests:\s*You have reached your pull rate limit", re.IGNORECASE),
        re.compile(r"dial tcp: lookup registry-1\.docker\.io: no such host", re.IGNORECASE),
        re.compile(r"net/http:\s*TLS handshake timeout", re.IGNORECASE),
        re.compile(r"Connection reset by peer", re.IGNORECASE),
        re.compile(r"Client\.Timeout exceeded while awaiting headers", re.IGNORECASE),
    ],
}

# Positive signatures for the 10 scenario families (D1 - D10)
SCENARIO_PATTERNS = {
    "D1": [
        re.compile(r"failed to calculate checksum of ref.*not found", re.IGNORECASE),
        re.compile(r'failed to calculate checksum of ref .*: ".*": not found', re.IGNORECASE),
        re.compile(r"failed to walk .*: lstat .*: no such file or directory", re.IGNORECASE),
        re.compile(r'COPY failed: file not found in build context or excluded by \.dockerignore: stat .*: file does not exist', re.IGNORECASE),
        re.compile(r'stat .*: no such file or directory', re.IGNORECASE),
    ],
    "D2": [
        re.compile(r"dockerfile parse error.*:\s*unknown instruction:\s*", re.IGNORECASE),
        re.compile(r"unknown instruction:\s*[A-Z_]+", re.IGNORECASE),
        re.compile(r"instruction '[A-Z_]+' is not supported", re.IGNORECASE),
    ],
    "D3": [
        re.compile(r"stage --from index out of range:\s*\d+", re.IGNORECASE),
        re.compile(r"flag needs an argument:\s*--from", re.IGNORECASE),
        re.compile(r"invalid from flag value.*:\s*invalid reference format", re.IGNORECASE),
        re.compile(r"invalid from flag value", re.IGNORECASE),
        re.compile(r"base name \([a-zA-Z0-9_-]+\) should not be blank", re.IGNORECASE),
    ],
    "D4": [
        re.compile(r"invalid reference format:\s*repository name must be lowercase", re.IGNORECASE),
        re.compile(r"invalid reference format", re.IGNORECASE),
        re.compile(r"could not parse reference:\s*", re.IGNORECASE),
        re.compile(r"failed to solve: ([a-zA-Z0-9_]+): invalid reference format", re.IGNORECASE),
    ],
    "D5": [
        re.compile(r"unable to prepare context:\s*path .* not found", re.IGNORECASE),
        re.compile(r"unable to prepare context:\s*path .*: no such file or directory", re.IGNORECASE),
        re.compile(r"error checking context:\s*'can't stat .*'", re.IGNORECASE),
        re.compile(r"context directory .* does not exist", re.IGNORECASE),
        re.compile(r"failed to solve: failed to read context: open .*: no such file or directory", re.IGNORECASE),
    ],
    "D6": [
        re.compile(r"failed to solve: secret .* not found", re.IGNORECASE),
        re.compile(r"failed to solve: target stage \".*\" could not be found", re.IGNORECASE),
        re.compile(r"failed to solve: target stage .* could not be found", re.IGNORECASE),
        re.compile(r"secret .* not found: secret not found", re.IGNORECASE),
    ],
    "D7": [
        re.compile(r"failed to solve.*circular dependency between stages", re.IGNORECASE),
        re.compile(r"circular dependency between stages:\s*", re.IGNORECASE),
        re.compile(r"failed to solve:\s*circular dependency", re.IGNORECASE),
    ],
    "D8": [
        re.compile(r"/bin/sh:\s*.*:\s*not found", re.IGNORECASE),
        re.compile(r"ERROR: failed to solve: process \"/bin/sh -c .*\" did not complete successfully: exit code: 127", re.IGNORECASE),
        re.compile(r"process \"/bin/sh -c .*\" did not complete successfully: exit code: 127", re.IGNORECASE),
    ],
    "D9": [
        re.compile(r"failed to read dockerfile:\s*open .*: no such file or directory", re.IGNORECASE),
        re.compile(r"cannot find Dockerfile:\s*", re.IGNORECASE),
        re.compile(r"unknown flag:\s*--[a-zA-Z0-9_-]+", re.IGNORECASE),
        re.compile(r"unknown shorthand flag:\s*'-[a-zA-Z0-9]'", re.IGNORECASE),
    ],
    "D10": [
        re.compile(r"/bin/sh:\s*.*:\s*Permission denied", re.IGNORECASE),
        re.compile(r"process \"/bin/sh -c .*\" did not complete successfully: exit code: 126", re.IGNORECASE),
        re.compile(r"ERROR: failed to solve: process \"/bin/sh -c .*\".*exit code: 126", re.IGNORECASE),
    ],
}


def check_exclusions(log_text):
    """Check if the log contains error patterns that belong to other categories (F1-F4, F6-F7).

    Returns:
        tuple[bool, str | None, str | None]: (is_excluded, category, matched_line)
    """
    for category, patterns in EXCLUSION_PATTERNS.items():
        for pattern in patterns:
            for line in log_text.splitlines():
                if pattern.search(line):
                    return True, category, line.strip()
    return False, None, None


def validate_docker_log(log_text, expected_scenario=None):
    """Validate that log text represents a genuine F5 docker build failure.

    Args:
        log_text (str): Raw log output.
        expected_scenario (str | None): Optional scenario ID (D1..D10) to match specifically.

    Returns:
        dict: Standardized validation dictionary.
    """
    if not log_text or not log_text.strip():
        return {
            "is_docker_error": False,
            "scenario_id": None,
            "matched_pattern": None,
            "matched_line": None,
            "status": "invalid",
            "rejection_reason": "Log is empty",
        }

    # Step 1: Reject successful builds
    if "naming to docker.io" in log_text and "ERROR:" not in log_text and "##[error]" not in log_text:
        return {
            "is_docker_error": False,
            "scenario_id": None,
            "matched_pattern": None,
            "matched_line": None,
            "status": "invalid",
            "rejection_reason": "Docker build succeeded without errors",
        }

    # Step 2: Strict cross-category rejection (F1, F2, F3, F4, F6, F7)
    is_excluded, excluded_cat, excluded_line = check_exclusions(log_text)
    if is_excluded:
        return {
            "is_docker_error": False,
            "scenario_id": None,
            "matched_pattern": excluded_cat,
            "matched_line": excluded_line,
            "status": "rejected",
            "rejection_reason": f"Excluded by boundary rule: primary cause is {excluded_cat}",
        }

    # Step 3: Match against F5 scenario families
    candidate_scenarios = [expected_scenario] if expected_scenario and expected_scenario in SCENARIO_PATTERNS else SCENARIO_PATTERNS.keys()

    for sc_id in candidate_scenarios:
        patterns = SCENARIO_PATTERNS[sc_id]
        for pattern in patterns:
            for line in log_text.splitlines():
                if pattern.search(line):
                    return {
                        "is_docker_error": True,
                        "scenario_id": sc_id,
                        "matched_pattern": pattern.pattern,
                        "matched_line": line.strip(),
                        "status": "valid",
                        "rejection_reason": None,
                    }

    # Step 4: General BuildKit failure fallback (if not excluded)
    general_error_patterns = [
        re.compile(r"ERROR:\s*failed to solve:\s*(.+)", re.IGNORECASE),
        re.compile(r"##\[error\]buildx failed with:\s*(.+)", re.IGNORECASE),
    ]
    for pattern in general_error_patterns:
        for line in log_text.splitlines():
            m = pattern.search(line)
            if m:
                return {
                    "is_docker_error": True,
                    "scenario_id": "D_UNKNOWN",
                    "matched_pattern": pattern.pattern,
                    "matched_line": line.strip(),
                    "status": "valid",
                    "rejection_reason": None,
                }

    return {
        "is_docker_error": False,
        "scenario_id": None,
        "matched_pattern": None,
        "matched_line": None,
        "status": "invalid",
        "rejection_reason": "No recognized Docker build failure signature found in log",
    }


def validate_docker_log_file(log_file_path, expected_scenario=None):
    """Read a log file and validate it for genuine F5 Docker build failure."""
    path = Path(log_file_path)
    if not path.exists():
        return {
            "is_docker_error": False,
            "scenario_id": None,
            "matched_pattern": None,
            "matched_line": None,
            "status": "error",
            "rejection_reason": f"File does not exist: {path}",
        }

    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            log_text = f.read()
    except OSError as e:
        return {
            "is_docker_error": False,
            "scenario_id": None,
            "matched_pattern": None,
            "matched_line": None,
            "status": "error",
            "rejection_reason": f"OS error reading file: {e}",
        }

    return validate_docker_log(log_text, expected_scenario=expected_scenario)
