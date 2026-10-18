"""Validation helpers for identifying dependency-installation failures."""

from pathlib import Path
import re


DEPENDENCY_PATTERNS = [
    "Could not find a version that satisfies the requirement",
    "No matching distribution found",
    "ResolutionImpossible",
    "Invalid requirement",
    "ERROR: Could not find",
    "Ignored the following versions",
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


def _normalize_package_name(name):
    """Apply PEP 503 normalisation: fold [-_.] runs to a single hyphen, lowercase.

    pip always emits package names in normalised form in its output lines.
    Applying the same transformation to a user-supplied specifier lets the
    two sides be compared directly.

    Args:
        name: A raw package name or requirement specifier prefix.

    Returns:
        str: Normalised, lower-cased name.
    """
    return re.sub(r"[-_.]+", "-", name).lower()


def validate_success_workflow_log(log_text, dependency=None):
    """Confirm dependency installation, compilation, and test evidence in a log.

    The function looks for three independent signals:

    1. The "Install Selected Dependency" step ran and pip reported
       ``Successfully installed`` a line that includes the bare package name
       (case-insensitive). This confirms the selected dependency was installed
       rather than inferring success from the overall workflow conclusion.
    2. The "Compile Python Sources" step produced the compilation-pass message.
    3. The "Run Test Suite" step produced a non-zero passing-test count.

    If *dependency* is provided, installation evidence is checked against that
    specifier; if it is None, the install-step check is skipped and the notes
    will omit the installation claim.

    Args:
        log_text (str): Full text of the GitHub Actions log.
        dependency (str | None): The pip requirement specifier that was
            installed, e.g. ``"requests==2.31.0"``. Pass None to skip the
            dependency-installation check.

    Returns:
        dict with keys:
            status (str): ``"valid"`` or ``"invalid"``.
            validation_notes (str | None): Human-readable summary, or None.
    """
    if not log_text or not log_text.strip():
        return {"status": "invalid", "validation_notes": None, "matched_line": None}

    lowered_log = log_text.lower()

    # --- 1. Dependency installation check ------------------------------------
    install_note = None
    matched_install_line = None
    if dependency is not None:
        # Apply PEP 503 normalisation to the specifier's bare name so that
        # underscores, hyphens, and dots are treated as equivalent.
        # pip always emits "name-VERSION" in "Successfully installed" lines,
        # so we require the normalised name to be followed immediately by
        # "-<digit>" — this prevents 'six' matching 'six-another-1.0'.
        bare_norm = _normalize_package_name(
            re.split(r"[=<>!\[]", dependency)[0].strip()
        )
        install_pattern = re.compile(
            re.escape(bare_norm) + r"-\d",
            re.IGNORECASE,
        )

        install_found = False
        in_install_step = False
        for line in log_text.splitlines():
            lowered_line = line.lower()
            if "install selected dependency" in lowered_line:
                in_install_step = True
            # Step boundaries in gh-actions logs are tab-separated fields;
            # a new step name resets context.
            elif in_install_step and "\t" in line:
                parts = line.split("\t")
                # parts[1] is the step name
                if len(parts) >= 2 and "install selected dependency" not in parts[1].lower():
                    in_install_step = False

            if in_install_step:
                normalised_line = _normalize_package_name(line)

                # Primary evidence: pip "Successfully installed name-VERSION ..."
                if "successfully installed" in lowered_line:
                    if install_pattern.search(normalised_line):
                        # Strip the GitHub Actions log prefix
                        # (format: "step\tStep Name\tTIMESTAMP text" or plain text)
                        raw_text = line.split("\t")[-1].strip()
                        matched_install_line = raw_text
                        install_found = True
                        break

                # Secondary evidence: "Requirement already satisfied: name==ver ..."
                # Accept only when the specifier's normalised name and the
                # version from the spec appear explicitly in the line.
                if "requirement already satisfied" in lowered_line:
                    if install_pattern.search(normalised_line):
                        # Additionally verify the version from the spec is present.
                        # Extract version part after the first == / >= / etc.
                        version_match = re.search(r"[=<>!]+([\d][^\s,;\]]*)", dependency)
                        version_str = version_match.group(1) if version_match else None
                        if version_str and version_str in line:
                            raw_text = line.split("\t")[-1].strip()
                            matched_install_line = raw_text
                            install_found = True
                            break

        if not install_found:
            return {"status": "invalid", "validation_notes": None, "matched_line": None}
        install_note = f"Dependency installation succeeded for {dependency}"

    # --- 2. Compilation check ------------------------------------------------
    required_steps = ("compile python sources", "run test suite")
    if any(step not in lowered_log for step in required_steps):
        return {"status": "invalid", "validation_notes": None, "matched_line": None}

    if "python syntax/compilation checks passed" not in lowered_log:
        return {"status": "invalid", "validation_notes": None, "matched_line": None}

    # --- 3. Test-count check -------------------------------------------------
    test_summary = re.search(r"\b([1-9]\d*) passed\b", lowered_log)
    if test_summary is None:
        return {"status": "invalid", "validation_notes": None, "matched_line": None}

    # --- Assemble notes ------------------------------------------------------
    compile_note = "Python syntax/compilation checks passed"
    test_note = f"pytest reported {test_summary.group(1)} passed"

    parts = [p for p in [install_note, compile_note, test_note] if p]
    notes = "; ".join(parts)

    return {"status": "valid", "validation_notes": notes, "matched_line": matched_install_line}