import re
from typing import Any

from rca.base import BaseCategoryAnalyzer, get_field, clean_line
from rca.schema import (
    RCAReport,
    CAUSAL_DEPENDENCY,
)


def _extract_package_name(pkg_spec: str) -> str:
    if not pkg_spec:
        return ""
    base = re.split(r"[=<>!~@;\s]", pkg_spec)[0].strip()
    return base


class DependencyAnalyzer(BaseCategoryAnalyzer):
    """Diagnoses pip dependency installation and resolution errors."""

    @property
    def category_name(self) -> str:
        return "dependency_error"

    def can_analyze(self, record: Any) -> bool:
        return get_field(record, "failure_class") == "dependency_error"

    def analyze(self, record: Any) -> RCAReport:
        failed_step = get_field(record, "failed_step") or get_field(record, "step_name") or "Install Dependencies"
        subcat = get_field(record, "failure_subcategory") or "pip_missing_dependency"
        failing_pkg = get_field(record, "failing_package")
        py_ver = get_field(record, "python_version")
        ev_lines = get_field(record, "evidence_lines") or []
        pip_cmds = get_field(record, "pip_commands") or []

        pkg_name = _extract_package_name(failing_pkg) if failing_pkg else ""

        observed_evidence: dict[str, Any] = {
            "failing_package": failing_pkg,
            "pip_failure_subtype": subcat,
            "python_version": py_ver,
            "pip_commands": pip_cmds,
        }

        evidence_sources: dict[str, str] = {
            "failing_package": "parser.failing_package",
            "pip_failure_subtype": "parser.failure_subcategory",
            "python_version": "parser.python_version",
            "pip_commands": "parser.pip_commands",
        }

        primary_lines = [clean_line(l) for l in ev_lines]

        investigation: list[str] = []
        py_disp = f" on Python {py_ver}" if py_ver else ""

        # Check if any pip command references a requirements file
        req_file = None
        for cmd in pip_cmds:
            if "-r " in cmd:
                parts = cmd.split("-r ", 1)[1].strip().split()
                if parts:
                    req_file = parts[0]
                    break

        if subcat == "pip_invalid_requirement":
            summary = f"Pip requirement syntax invalid: '{failing_pkg or 'unknown requirement'}'"
            likely_cause = (
                f"pip failed during step '{failed_step}' because the requirement specification "
                f"'{failing_pkg or 'unknown'}' was reported as invalid requirement syntax (PEP 508)."
            )
            if failing_pkg:
                target = f"in {req_file} around '{failing_pkg}'" if req_file else f"around '{failing_pkg}'"
                investigation.append(
                    f"Inspect dependency specifications {target} and correct invalid comparison operators."
                )
            else:
                investigation.append("Inspect dependency specifications and correct invalid package specifier syntax.")

            if req_file:
                investigation.append(f"Validate requirements file locally: pip install --dry-run -r {req_file}")
            else:
                investigation.append(f"Validate package specifier locally: pip install --dry-run '{failing_pkg or 'package'}'")
            local_cmd = f"pip install '{failing_pkg}'" if failing_pkg else None

        elif subcat == "pip_build_failure":
            summary = f"Pip wheel build failed: '{pkg_name or failing_pkg or 'unknown package'}'"
            likely_cause = (
                f"pip encountered an error while building the wheel for package '{pkg_name or failing_pkg or 'unknown'}' "
                f"in step '{failed_step}'{py_disp}. The package build may require compiler toolchains, header files, or system libraries."
            )
            investigation.append(
                f"Check compiler build error output in step '{failed_step}' to identify missing header files or system libraries."
            )
            if pkg_name:
                investigation.append(
                    f"Ensure OS build prerequisites (e.g. gcc, python-dev) are installed prior to building '{pkg_name}'."
                )
                investigation.append(
                    f"Check if pre-compiled binary wheels exist for '{pkg_name}' on Python {py_ver or 'target version'}."
                )
            else:
                investigation.append("Ensure OS build prerequisites are installed prior to building source wheels.")
            local_cmd = f"pip install --no-binary :all: {failing_pkg}" if failing_pkg else None

        else:  # pip_missing_dependency / default
            summary = f"Pip dependency resolution failed: '{failing_pkg or 'unknown package'}'"
            likely_cause = (
                f"pip was unable to find a release for package '{failing_pkg or 'unknown'}' matching requirements "
                f"in step '{failed_step}'{py_disp}. Potential causes to investigate include package name spelling, "
                f"requested version availability on PyPI or configured indexes, and Python version compatibility."
            )
            if pkg_name:
                investigation.append(
                    f"Confirm package name spelling and check available releases on PyPI: pip index versions {pkg_name}"
                )
            else:
                investigation.append("Confirm package name spelling and available releases on PyPI.")

            target_file_disp = f"in {req_file}" if req_file else "in project dependency specifications"
            investigation.append(f"Check dependency pins {target_file_disp} for typos or conflicting version constraints.")

            if pkg_name:
                investigation.append(
                    f"If '{pkg_name}' is a private or internal package, verify repository credentials and index URLs (e.g. --extra-index-url) in the workflow."
                )
            else:
                investigation.append("If installing private or internal packages, verify repository credentials and index URLs in the workflow.")
            local_cmd = f"pip install {failing_pkg}" if failing_pkg else None

        confidence = 1.0 if failing_pkg else 0.7
        rationale = (
            "High evidence strength: direct pip ERROR output with explicit package identifier."
            if failing_pkg else
            "Medium evidence strength: pip failure detected but failing package name was unparsed."
        )

        limitations = [
            "RCA cannot determine whether missing packages exist in unconfigured private registries or were removed from PyPI.",
            "System library prerequisites for build failures cannot be verified without package build documentation.",
        ]

        return RCAReport(
            run_id=get_field(record, "run_id"),
            timestamp=get_field(record, "timestamp"),
            failure_class="dependency_error",
            failure_subcategory=subcat,
            failed_stage=get_field(record, "stage") or "build",
            failed_step=failed_step,
            execution_path=get_field(record, "execution_path") or [],
            summary=summary,
            likely_cause=likely_cause,
            causal_category=CAUSAL_DEPENDENCY,
            observed_evidence=observed_evidence,
            primary_evidence_lines=primary_lines,
            evidence_sources=evidence_sources,
            suggested_investigation=investigation,
            local_reproduction_command=local_cmd,
            rca_confidence=confidence,
            confidence_rationale=rationale,
            limitations=limitations,
        )
