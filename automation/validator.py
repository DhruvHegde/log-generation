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
    """Confirm dependency installation evidence in a log.

    A record is accepted when the "Install Selected Dependency" step contains
    pip output confirming the selected package was installed:

    - Primary: ``Successfully installed name-VERSION ...`` where *name* matches
      the specifier's bare name under PEP 503 normalisation and the token is
      followed by ``-<digit>`` to prevent substring false positives.
    - Secondary: ``Requirement already satisfied: name==ver ...`` when the
      normalised package name and the exact version from the specifier are
      both present in the line.

    ``Collecting`` alone is not accepted as proof of success.

    If *dependency* is None the install check is skipped (used in tests that
    only exercise the structural wrapper).

    Args:
        log_text (str): Full text of the GitHub Actions log.
        dependency (str | None): The pip requirement specifier that was
            installed, e.g. ``"requests==2.31.0"``.

    Returns:
        dict with keys:
            status (str): ``"valid"`` or ``"invalid"``.
            validation_notes (str | None): Human-readable summary, or None.
            matched_line (str | None): The stripped pip output line that
                confirmed installation, or None.
    """
    if not log_text or not log_text.strip():
        return {"status": "invalid", "validation_notes": None, "matched_line": None}

    # --- Dependency installation check --------------------------------------
    matched_install_line = None

    if dependency is not None:
        # PEP 503: fold [-_.] runs to a single hyphen, lowercase, so that
        # underscores, hyphens, and dots in specifiers match pip's output.
        bare_norm = _normalize_package_name(
            re.split(r"[=<>!\[]", dependency)[0].strip()
        )
        # pip emits "name-VERSION" — require a digit immediately after the
        # name-separator hyphen to prevent 'six' matching 'six-another-1.0'.
        install_pattern = re.compile(
            re.escape(bare_norm) + r"-\d",
            re.IGNORECASE,
        )

        install_found = False
        in_install_step = False
        for line in log_text.splitlines():
            lowered_line = line.lower()

            # Track which step we are in using the tab-delimited log format.
            if "install selected dependency" in lowered_line:
                in_install_step = True
            elif in_install_step and "\t" in line:
                parts = line.split("\t")
                if (
                    len(parts) >= 2
                    and "install selected dependency" not in parts[1].lower()
                ):
                    in_install_step = False

            if not in_install_step:
                continue

            normalised_line = _normalize_package_name(line)

            # Primary evidence: "Successfully installed name-VERSION ..."
            if "successfully installed" in lowered_line:
                if install_pattern.search(normalised_line):
                    # Strip the log prefix ("step\tStep Name\tTIMESTAMP text").
                    # The last tab-field may still carry a leading ISO timestamp;
                    # remove it before storing.
                    raw_text = line.split("\t")[-1].strip()
                    raw_text = re.sub(
                        r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*", "", raw_text
                    )
                    matched_install_line = raw_text
                    install_found = True
                    break

            # Secondary evidence: "Requirement already satisfied: name==ver ..."
            # The name appears as "name==ver" (not "name-ver"), so use an
            # operator-boundary pattern rather than the install_pattern to
            # avoid 'six' matching 'six-tools==1.16.0'.
            if "requirement already satisfied" in lowered_line:
                req_name_pattern = re.compile(
                    re.escape(bare_norm) + r"(?:==|>=|<=|!=|~=|\[|\s|\Z)",
                    re.IGNORECASE,
                )
                if req_name_pattern.search(lowered_line):
                    version_match = re.search(
                        r"[=<>!]+([\d][^\s,;\]]*)", dependency
                    )
                    version_str = version_match.group(1) if version_match else None
                    if version_str and version_str in line:
                        raw_text = line.split("\t")[-1].strip()
                        raw_text = re.sub(
                            r"^\d{4}-\d{2}-\d{2}T[\d:.]+Z\s*", "", raw_text
                        )
                        matched_install_line = raw_text
                        install_found = True
                        break

        if not install_found:
            return {
                "status": "invalid",
                "validation_notes": None,
                "matched_line": None,
            }

    notes = (
        f"Dependency installation succeeded for {dependency}"
        if dependency is not None
        else "Installation step completed"
    )
    return {
        "status": "valid",
        "validation_notes": notes,
        "matched_line": matched_install_line,
    }