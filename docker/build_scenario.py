"""Execution and catalog definition for F5 Successful Docker Build Scenarios.

Used both by GitHub Actions workflow and local test suites to ensure 100%
synchronization between workflow execution and dataset validation.
"""

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

SCENARIO_CATALOG: Dict[str, Dict[str, Any]] = {
    "DS01_python_app": {
        "scenario_id": "DS01_python_app",
        "name": "Python Application Container",
        "description": "Standard Python 3.11 container build with requirements and non-root user.",
        "dockerfile": "docker/success_scenarios/DS01_python_app/Dockerfile",
        "context": "docker/success_scenarios/DS01_python_app",
        "tag": "f5-success-ds01:latest",
        "cli_args": [],
        "feature_evidence": ["pip install", "COPY app.py"],
    },
    "DS02_alpine_multi_stage": {
        "scenario_id": "DS02_alpine_multi_stage",
        "name": "Alpine Multi-Stage Build",
        "description": "Multi-stage artifact compilation in builder stage and copy to runtime.",
        "dockerfile": "docker/success_scenarios/DS02_alpine_multi_stage/Dockerfile",
        "context": "docker/success_scenarios/DS02_alpine_multi_stage",
        "tag": "f5-success-ds02:latest",
        "cli_args": [],
        "feature_evidence": ["AS builder", "COPY --from=builder"],
    },
    "DS03_node_static_site": {
        "scenario_id": "DS03_node_static_site",
        "name": "Node.js to Nginx Multi-Stage Site",
        "description": "Static HTML asset processing in Node bundler stage and deployment to Nginx.",
        "dockerfile": "docker/success_scenarios/DS03_node_static_site/Dockerfile",
        "context": "docker/success_scenarios/DS03_node_static_site",
        "tag": "f5-success-ds03:latest",
        "cli_args": [],
        "feature_evidence": ["AS bundler", "COPY --from=bundler"],
    },
    "DS04_debian_env_config": {
        "scenario_id": "DS04_debian_env_config",
        "name": "Debian Environment & Label Layout",
        "description": "Debian Bookworm with multiple ENV declarations, labels, and config copy.",
        "dockerfile": "docker/success_scenarios/DS04_debian_env_config/Dockerfile",
        "context": "docker/success_scenarios/DS04_debian_env_config",
        "tag": "f5-success-ds04:latest",
        "cli_args": [],
        "feature_evidence": ["maintainer=\"capstone-team\"", "APP_MODE=production"],
    },
    "DS05_build_arguments": {
        "scenario_id": "DS05_build_arguments",
        "name": "Parameterized Build Arguments",
        "description": "Docker build parameterization using explicit --build-arg values.",
        "dockerfile": "docker/success_scenarios/DS05_build_arguments/Dockerfile",
        "context": "docker/success_scenarios/DS05_build_arguments",
        "tag": "f5-success-ds05:latest",
        "cli_args": ["--build-arg", "APP_VERSION=2.4.0", "--build-arg", "BUILD_ENV=production"],
        "feature_evidence": ["APP_VERSION=2.4.0", "BUILD_ENV=production"],
    },
    "DS06_target_stages": {
        "scenario_id": "DS06_target_stages",
        "name": "Targeted Stage Multi-Stage Build",
        "description": "Explicit target selection building release_stage while bypassing dev/test stages.",
        "dockerfile": "docker/success_scenarios/DS06_target_stages/Dockerfile",
        "context": "docker/success_scenarios/DS06_target_stages",
        "tag": "f5-success-ds06:latest",
        "cli_args": ["--target", "release_stage"],
        "feature_evidence": ["release_stage", "release_marker.txt"],
        "negative_evidence": ["dev_marker.txt", "test_marker.txt"],
    },
    "DS07_cache_mounts": {
        "scenario_id": "DS07_cache_mounts",
        "name": "BuildKit Cache Mount Execution",
        "description": "BuildKit cache mount instruction execution via --mount=type=cache.",
        "dockerfile": "docker/success_scenarios/DS07_cache_mounts/Dockerfile",
        "context": "docker/success_scenarios/DS07_cache_mounts",
        "tag": "f5-success-ds07:latest",
        "cli_args": [],
        "feature_evidence": ["--mount=type=cache", "Cache mount exercised successfully"],
    },
    "DS08_custom_dockerfile": {
        "scenario_id": "DS08_custom_dockerfile",
        "name": "Non-Standard Dockerfile Path",
        "description": "Build executing deliberate non-standard Containerfile.custom path.",
        "dockerfile": "docker/success_scenarios/DS08_custom_dockerfile/Containerfile.custom",
        "context": "docker/success_scenarios/DS08_custom_dockerfile",
        "tag": "f5-success-ds08:latest",
        "cli_args": ["-f", "docker/success_scenarios/DS08_custom_dockerfile/Containerfile.custom"],
        "feature_evidence": ["Containerfile.custom", "Built using non-standard Containerfile.custom path"],
    },
    "DS09_entrypoint_exec": {
        "scenario_id": "DS09_entrypoint_exec",
        "name": "Entrypoint Script & Permission Setup",
        "description": "Custom executable entrypoint script with proper POSIX execution permissions.",
        "dockerfile": "docker/success_scenarios/DS09_entrypoint_exec/Dockerfile",
        "context": "docker/success_scenarios/DS09_entrypoint_exec",
        "tag": "f5-success-ds09:latest",
        "cli_args": [],
        "feature_evidence": ["chmod 755 /app/entrypoint.sh", "ENTRYPOINT"],
    },
    "DS10_distroless_minimal": {
        "scenario_id": "DS10_distroless_minimal",
        "name": "Distroless Minimal Packaging",
        "description": "Multi-stage packaging using public Google Distroless static image.",
        "dockerfile": "docker/success_scenarios/DS10_distroless_minimal/Dockerfile",
        "context": "docker/success_scenarios/DS10_distroless_minimal",
        "tag": "f5-success-ds10:latest",
        "cli_args": [],
        "feature_evidence": ["gcr.io/distroless/static-debian12", "USER nonroot:nonroot"],
    },
}

SCENARIOS_LIST = list(SCENARIO_CATALOG.values())


def build_command_for_scenario(scenario_id: str) -> List[str]:
    """Construct the exact docker build command for a scenario."""
    if scenario_id not in SCENARIO_CATALOG:
        raise KeyError(f"Unknown scenario ID: {scenario_id}")

    meta = SCENARIO_CATALOG[scenario_id]
    cmd = ["docker", "build"]

    # Append custom cli args (e.g. --target, --build-arg, -f)
    if meta.get("cli_args"):
        cmd.extend(meta["cli_args"])

    # If -f wasn't explicitly supplied in cli_args, add it
    if "-f" not in cmd and "--file" not in cmd:
        cmd.extend(["-f", meta["dockerfile"]])

    cmd.extend(["-t", meta["tag"]])
    cmd.append(meta["context"])
    return cmd


def execute_scenario_build(scenario_id: str, run_id: str = "S_F5_run_0001") -> int:
    """Execute docker build command and stream output."""
    if scenario_id not in SCENARIO_CATALOG:
        print(f"Error: Unknown scenario '{scenario_id}'.")
        print(f"Available scenarios: {list(SCENARIO_CATALOG.keys())}")
        return 1

    cmd = build_command_for_scenario(scenario_id)
    cmd_str = " ".join(cmd)

    print("=" * 70)
    print(f"Executing F5 Docker Success Scenario: {scenario_id} (Run: {run_id})")
    print(f"Build Command: {cmd_str}")
    print("=" * 70)

    # Use standard subprocess to inherit stdout/stderr
    res = subprocess.run(cmd, text=True)
    if res.returncode != 0:
        print(f"\n[ERROR] Docker build command exited with non-zero exit code: {res.returncode}")
        return res.returncode

    print(f"\n[SUCCESS] Docker build completed successfully for {scenario_id}.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Build Runner for F5 Docker Success Scenarios")
    parser.add_argument("--scenario", required=True, choices=list(SCENARIO_CATALOG.keys()), help="Scenario ID")
    parser.add_argument("--run-id", default="S_F5_run_0001", help="Dataset run identifier")
    args = parser.parse_args()

    exit_code = execute_scenario_build(args.scenario, args.run_id)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
