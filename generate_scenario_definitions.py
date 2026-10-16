"""Script to generate the authoritative docker_errors.json scenario catalog.

Revised with strict failure semantics for the combined seven-class dataset (F1 - F7):
- D1: Missing COPY source (context missing file)
- D2: Invalid Dockerfile instruction keyword
- D3: Invalid build-stage reference (stage index out of range / invalid from flag syntax)
- D4: Invalid image reference syntax (uppercase / illegal chars)
- D5: Invalid build context path (missing directory)
- D6: Invalid Docker build configuration / secret mount (missing BuildKit secret / invalid target)
- D7: Circular multi-stage dependency (DAG cycle)
- D8: Container OS environment / tool mismatch (/bin/bash in alpine, systemctl in container)
- D9: Invalid Dockerfile path (-f) or unknown CLI build option
- D10: Container build-time file permission failure (0644 non-executable script executed in RUN)
"""

import json
from pathlib import Path

FAMILIES = {
    "D1": {
        "family_name": "Missing COPY source",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Docker build context does not contain a file or directory referenced by a COPY instruction",
        "failure_mechanism": "BuildKit evaluates COPY instruction and fails to find source file in staged build context",
        "expected_log_evidence": "ERROR: failed to calculate checksum of ref ...: \"<filename>\": not found",
        "exclusion_conditions": ["Missing package manager dependencies (F2)", "Network error (F7)"],
        "validation_method": "Regex match on BuildKit ref checksum error or missing file stat",
        "reproduction_prerequisites": "Docker build context prepared without the requested copy source",
        "expected_exit_code": 1,
    },
    "D2": {
        "family_name": "Invalid Dockerfile instruction",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Malformed, misspelled, or unsupported Dockerfile instruction keyword",
        "failure_mechanism": "Docker build parser encounters unrecognized instruction keyword during AST generation",
        "expected_log_evidence": "dockerfile parse error on line <N>: unknown instruction: <INSTRUCTION>",
        "exclusion_conditions": ["Valid instruction with failed runtime execution (D8/F2)", "CI workflow YAML syntax error (F6)"],
        "validation_method": "Regex match on dockerfile parse error / unknown instruction",
        "reproduction_prerequisites": "Dockerfile containing malformed instruction token",
        "expected_exit_code": 1,
    },
    "D3": {
        "family_name": "Invalid build-stage reference",
        "canonical_label": "docker_build_failure",
        "primary_cause": "A multi-stage build instruction (COPY --from) references an invalid or out-of-range stage identifier",
        "failure_mechanism": "BuildKit stage index resolver rejects numerical stage out of range, missing from argument, or illegal stage identifier",
        "expected_log_evidence": "dockerfile parse error on line <N>: stage --from index out of range: <N> OR invalid from flag value",
        "exclusion_conditions": ["Valid stage reference failing at build time", "Remote registry pull failure (F7)"],
        "validation_method": "Regex match on invalid from flag value or stage index out of range",
        "reproduction_prerequisites": "Multi-stage Dockerfile referencing out-of-range stage index or invalid stage reference",
        "expected_exit_code": 1,
    },
    "D4": {
        "family_name": "Invalid image reference",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Syntactically invalid image repository name, tag, or digest format in FROM instruction",
        "failure_mechanism": "Docker image reference parser rejects reference before attempting registry connection",
        "expected_log_evidence": "invalid reference format: repository name must be lowercase OR invalid reference format",
        "exclusion_conditions": ["Valid image format failing authentication (F6) or network lookup (F7)"],
        "validation_method": "Regex match on 'invalid reference format'",
        "reproduction_prerequisites": "Dockerfile with uppercase characters, invalid separators, or malformed tag",
        "expected_exit_code": 1,
    },
    "D5": {
        "family_name": "Invalid build context",
        "canonical_label": "docker_build_failure",
        "primary_cause": "The directory specified as build context does not exist or cannot be accessed",
        "failure_mechanism": "Docker CLI or BuildKit client fails to open or stat the context path argument",
        "expected_log_evidence": "unable to prepare context: path \"<path>\" not found OR can't stat '<path>'",
        "exclusion_conditions": ["Valid context with missing internal file (D1)", "Filesystem permission error on runner (F6)"],
        "validation_method": "Regex match on unable to prepare context or missing context directory",
        "reproduction_prerequisites": "Docker build command executed against non-existent context directory",
        "expected_exit_code": 1,
    },
    "D6": {
        "family_name": "Invalid build argument/configuration",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Native Docker/BuildKit configuration failure such as missing BuildKit secret mount or nonexistent target stage",
        "failure_mechanism": "BuildKit fails LLB generation because required secret was not provided via --secret, or target stage (--target) does not exist",
        "expected_log_evidence": "failed to solve: secret <SECRET_ID> not found OR failed to solve: target stage \"<STAGE>\" could not be found",
        "exclusion_conditions": ["Shell-level assertion inside container (application error)", "Missing CI environment variable (F6)"],
        "validation_method": "Regex match on native BuildKit secret mount or target stage error",
        "reproduction_prerequisites": "Dockerfile with RUN --mount=type=secret or docker build --target with nonexistent target",
        "expected_exit_code": 1,
    },
    "D7": {
        "family_name": "Invalid multi-stage build configuration",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Circular dependency between stages in a multi-stage Dockerfile",
        "failure_mechanism": "BuildKit DAG cycle detector identifies circular dependency graph between stages",
        "expected_log_evidence": "failed to solve: circular dependency between stages: <stage_a> -> <stage_b> -> <stage_a>",
        "exclusion_conditions": ["Stage reference typo (D3)", "Runtime command error inside stage (D8)"],
        "validation_method": "Regex match on circular dependency between stages",
        "reproduction_prerequisites": "Dockerfile where stage A depends on stage B and stage B depends on stage A",
        "expected_exit_code": 1,
    },
    "D8": {
        "family_name": "Container OS environment/tool mismatch",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Dockerfile RUN instruction invokes a shell or OS-level utility not present in the chosen base container OS",
        "failure_mechanism": "Container shell fails to locate expected OS binary (/bin/bash on Alpine, systemctl in container), returning exit code 127",
        "expected_log_evidence": "/bin/sh: <binary>: not found AND exit code: 127",
        "exclusion_conditions": ["pip, apt, npm, or dependency resolution failure (F2)", "Python syntax error (F1)", "Test assertion failure (F3)"],
        "validation_method": "Regex match on exit code 127 and shell binary missing, with strict exclusion of package managers",
        "reproduction_prerequisites": "Dockerfile invoking missing shell or system binary on minimal base image",
        "expected_exit_code": 127,
    },
    "D9": {
        "family_name": "Invalid Dockerfile path/build option",
        "canonical_label": "docker_build_failure",
        "primary_cause": "Docker CLI cannot locate the specified Dockerfile path (-f) or rejects an unknown build option",
        "failure_mechanism": "Docker build client checks file existence for -f path before sending build request",
        "expected_log_evidence": "failed to read dockerfile: open <path>: no such file or directory OR unknown flag: --<flag>",
        "exclusion_conditions": ["Dockerfile exists but syntax is invalid (D2)", "Missing context path (D5)"],
        "validation_method": "Regex match on failed to read dockerfile or unknown build flag",
        "reproduction_prerequisites": "Docker build command targeting missing Dockerfile name via -f or invalid build flag",
        "expected_exit_code": 1,
    },
    "D10": {
        "family_name": "Container build-time file/permission failure",
        "canonical_label": "docker_build_failure",
        "primary_cause": "A required build-time script or file copied into container lacks execute permissions (mode 0644)",
        "failure_mechanism": "Container shell attempts to execute non-executable file copied without --chmod=755, returning exit code 126 (Permission denied)",
        "expected_log_evidence": "/bin/sh: <script>: Permission denied AND exit code: 126",
        "exclusion_conditions": ["Runner file permission error outside container on /var/run/docker.sock (F6)", "File missing error (D1)"],
        "validation_method": "Regex match on Permission denied and exit code 126",
        "reproduction_prerequisites": "Dockerfile copying script without executable bit and attempting RUN ./script",
        "expected_exit_code": 126,
    },
}

BASE_IMAGES = [
    "python:3.11-slim",
    "ubuntu:22.04",
    "alpine:3.19",
    "node:20-alpine",
    "golang:1.22-bookworm",
    "debian:bookworm-slim",
    "python:3.10-slim",
    "rust:1.76-slim",
    "openjdk:17-slim",
    "ruby:3.3-slim",
]

def generate_catalog():
    catalog = {"version": "2.0", "scenario_families": {}}

    for fam_id, meta in FAMILIES.items():
        family_entry = dict(meta)
        variants = []

        for i in range(1, 51):
            var_num = f"{i:02d}"
            var_id = f"{fam_id}_{var_num}"
            base_img = BASE_IMAGES[(i - 1) % len(BASE_IMAGES)]

            if fam_id == "D1":
                file_types = [
                    f"config/settings_{var_num}.yaml",
                    f"assets/data_bundle_{var_num}.json",
                    f"certs/client_cert_{var_num}.pem",
                    f"bin/embedded_tool_{var_num}",
                    f"schemas/v1_schema_{var_num}.proto",
                    f"static/styles/theme_{var_num}.css",
                    f"configs/database_{var_num}.toml",
                    f"resources/locales_{var_num}.bin",
                    f"data/training_seed_{var_num}.csv",
                    f"scripts/post_install_{var_num}.sh",
                ]
                missing_file = file_types[(i - 1) % len(file_types)]
                desc = f"Missing source file '{missing_file}' in COPY instruction ({base_img})"
                dockerfile = (
                    f"FROM {base_img}\n"
                    "WORKDIR /app\n"
                    f"COPY {missing_file} /app/data/\n"
                    "CMD [\"echo\", \"built\"]\n"
                )
                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "missing_source_file": missing_file,
                    "cli_options": ["-t", f"app-d1:{var_num}", "."],
                    "expected_pattern": f'failed to calculate checksum of ref.*"{missing_file}": not found',
                }

            elif fam_id == "D2":
                bad_instructions = [
                    "INCLUDELIB", "CONFIG_ENV", "PACK_DEPS", "FETCH_SRC", "EXPORT_VAR",
                    "IMPORT_MOD", "MOUNT_VOL", "SERVICE_START", "DEFINE_PROP", "EXEC_SHELL",
                ]
                bad_instr = bad_instructions[(i - 1) % len(bad_instructions)]
                desc = f"Invalid Dockerfile instruction '{bad_instr}' ({base_img})"
                dockerfile = (
                    f"FROM {base_img}\n"
                    "WORKDIR /app\n"
                    f"{bad_instr} option_param_{var_num}\n"
                    "CMD [\"echo\", \"built\"]\n"
                )
                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "invalid_instruction": bad_instr,
                    "cli_options": ["-t", f"app-d2:{var_num}", "."],
                    "expected_pattern": f"unknown instruction: {bad_instr}",
                }

            elif fam_id == "D3":
                # Strict Docker stage reference failures without registry pull ambiguity
                # Modes: (1) Numerical stage index out of range, (2) Empty from flag, (3) Illegal stage name format
                mode = i % 3
                if mode == 0:
                    stage_idx = 50 + i
                    desc = f"Stage index out of range '--from={stage_idx}' in COPY instruction"
                    dockerfile = (
                        f"FROM {base_img} AS builder\n"
                        "WORKDIR /src\n"
                        "RUN echo 'building' > out.txt\n\n"
                        f"FROM {base_img} AS runner\n"
                        "WORKDIR /app\n"
                        f"COPY --from={stage_idx} /src/out.txt /app/out.txt\n"
                    )
                    expected_pat = f"stage --from index out of range: {stage_idx}"
                elif mode == 1:
                    desc = f"Empty --from flag in COPY instruction (line 6)"
                    dockerfile = (
                        f"FROM {base_img} AS builder\n"
                        "WORKDIR /src\n"
                        "RUN echo 'building' > out.txt\n\n"
                        f"FROM {base_img} AS runner\n"
                        "WORKDIR /app\n"
                        "COPY --from= /src/out.txt /app/out.txt\n"
                    )
                    expected_pat = "flag needs an argument: --from"
                else:
                    illegal_stage = f"Stage_Uppercase_Illegal_{var_num}"
                    desc = f"Invalid stage reference identifier '{illegal_stage}' in COPY --from"
                    dockerfile = (
                        f"FROM {base_img} AS builder\n"
                        "WORKDIR /src\n"
                        "RUN echo 'building' > out.txt\n\n"
                        f"FROM {base_img} AS runner\n"
                        "WORKDIR /app\n"
                        f"COPY --from={illegal_stage} /src/out.txt /app/out.txt\n"
                    )
                    expected_pat = f"invalid from flag value {illegal_stage}: invalid reference format"

                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "cli_options": ["-t", f"app-d3:{var_num}", "."],
                    "expected_pattern": expected_pat,
                }

            elif fam_id == "D4":
                invalid_repos = [
                    f"MyOrg_AppService/Server_{var_num}:1.0",
                    f"PYTHON_RUNTIME:{var_num}.0-slim",
                    f"UBUNTU_BASE_IMAGE:v{var_num}",
                    f"App_Microservice_{var_num}::latest",
                    f"InternalRegistry.Local/DataApp_{var_num}:v1",
                    f"CORE_UTILITY_RUNNER:{var_num}",
                    f"Custom_Python_Base_{var_num}:3.11",
                    f"Prod_Backend_Service_{var_num}:stable",
                    f"Pipeline_Worker_Image_{var_num}:test",
                    f"Release_Container_{var_num}:latest",
                ]
                invalid_img = invalid_repos[(i - 1) % len(invalid_repos)]
                desc = f"Syntactically invalid image reference '{invalid_img}' with uppercase/illegal chars"
                dockerfile = (
                    f"FROM {invalid_img}\n"
                    "WORKDIR /app\n"
                    "CMD [\"echo\", \"done\"]\n"
                )
                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "dockerfile_content": dockerfile,
                    "invalid_image": invalid_img,
                    "cli_options": ["-t", f"app-d4:{var_num}", "."],
                    "expected_pattern": "invalid reference format",
                }

            elif fam_id == "D5":
                missing_ctx = f"nonexistent_context_dir_{var_num}"
                desc = f"Build context directory '{missing_ctx}' does not exist"
                dockerfile = (
                    f"FROM {base_img}\n"
                    "WORKDIR /app\n"
                    "COPY . .\n"
                )
                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "missing_context_dir": missing_ctx,
                    "cli_options": ["-t", f"app-d5:{var_num}", f"./{missing_ctx}"],
                    "expected_pattern": f"unable to prepare context: path.*{missing_ctx}.*not found",
                }

            elif fam_id == "D6":
                # Native Docker/BuildKit configuration failures (Secret mount missing OR Nonexistent build target)
                if i % 2 == 0:
                    secret_id = f"build_token_secret_{var_num}"
                    desc = f"BuildKit secret mount '{secret_id}' required but not provided via --secret"
                    dockerfile = (
                        f"FROM {base_img}\n"
                        f"RUN --mount=type=secret,id={secret_id} cat /run/secrets/{secret_id}\n"
                        "WORKDIR /app\n"
                    )
                    expected_pat = f"failed to solve: secret {secret_id} not found"
                    cli_opts = ["-t", f"app-d6:{var_num}", "."]
                else:
                    target_stage = f"missing_target_stage_{var_num}"
                    desc = f"Docker build target stage '{target_stage}' does not exist in Dockerfile"
                    dockerfile = (
                        f"FROM {base_img} AS base_runtime\n"
                        "WORKDIR /app\n"
                        "RUN echo 'base' > status.txt\n"
                    )
                    expected_pat = f'failed to solve: target stage "{target_stage}" could not be found'
                    cli_opts = ["--target", target_stage, "-t", f"app-d6:{var_num}", "."]

                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "cli_options": cli_opts,
                    "expected_pattern": expected_pat,
                }

            elif fam_id == "D7":
                s1 = f"stage_alpha_{var_num}"
                s2 = f"stage_beta_{var_num}"
                desc = f"Circular multi-stage dependency: {s1} -> {s2} -> {s1}"
                dockerfile = (
                    f"FROM {s2} AS {s1}\n"
                    "WORKDIR /app\n"
                    "RUN touch a.txt\n\n"
                    f"FROM {s1} AS {s2}\n"
                    "WORKDIR /app\n"
                    "RUN touch b.txt\n"
                )
                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "circular_stages": [s1, s2],
                    "cli_options": ["-t", f"app-d7:{var_num}", "."],
                    "expected_pattern": f"circular dependency between stages.*{s1}",
                }

            elif fam_id == "D8":
                # Container OS mismatch: Alpine calling bash, or systemctl in container without systemd
                if i % 2 == 0:
                    missing_tool = "/bin/bash"
                    desc = f"Container OS tool mismatch: invoking '{missing_tool}' in Alpine container (/bin/sh: not found)"
                    dockerfile = (
                        "FROM alpine:3.19\n"
                        "WORKDIR /app\n"
                        "RUN /bin/bash -c 'echo initializing container environment'\n"
                    )
                    expected_pat = "/bin/sh: /bin/bash: not found"
                else:
                    missing_tool = "/usr/bin/systemctl"
                    desc = f"Container OS tool mismatch: invoking '{missing_tool}' in non-init container (/bin/sh: not found)"
                    dockerfile = (
                        "FROM debian:bookworm-slim\n"
                        "WORKDIR /app\n"
                        "RUN /usr/bin/systemctl start daemon\n"
                    )
                    expected_pat = "/bin/sh: /usr/bin/systemctl: not found"

                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "dockerfile_content": dockerfile,
                    "missing_tool": missing_tool,
                    "cli_options": ["-t", f"app-d8:{var_num}", "."],
                    "expected_pattern": expected_pat,
                }

            elif fam_id == "D9":
                if i % 2 == 0:
                    missing_df = f"Dockerfile.custom_release_{var_num}.prod"
                    desc = f"Specified Dockerfile '{missing_df}' not found (-f flag)"
                    dockerfile = f"FROM {base_img}\nWORKDIR /app\n"
                    cli_opts = ["-f", missing_df, "-t", f"app-d9:{var_num}", "."]
                    expected_pat = f"failed to read dockerfile: open {missing_df}: no such file or directory"
                else:
                    invalid_flag = f"--invalid-buildkit-opt-{var_num}"
                    desc = f"Unknown Docker build CLI option '{invalid_flag}'"
                    dockerfile = f"FROM {base_img}\nWORKDIR /app\n"
                    cli_opts = [invalid_flag, "-t", f"app-d9:{var_num}", "."]
                    expected_pat = f"unknown flag: {invalid_flag}"

                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "cli_options": cli_opts,
                    "expected_pattern": expected_pat,
                }

            elif fam_id == "D10":
                script_name = f"setup_entrypoint_{var_num}.sh"
                desc = f"Container script '{script_name}' lacks execute permissions (mode 0644, exit code 126)"
                dockerfile = (
                    f"FROM {base_img}\n"
                    "WORKDIR /app\n"
                    f"COPY {script_name} /app/{script_name}\n"
                    f"RUN /app/{script_name}\n"
                )
                variant = {
                    "variant_id": var_id,
                    "description": desc,
                    "base_image": base_img,
                    "dockerfile_content": dockerfile,
                    "script_name": script_name,
                    "script_content": "#!/bin/sh\necho 'Running setup...'\n",
                    "file_mode": 0o644,
                    "cli_options": ["-t", f"app-d10:{var_num}", "."],
                    "expected_pattern": f"/bin/sh: /app/{script_name}: Permission denied",
                }

            variants.append(variant)

        family_entry["variants"] = variants
        catalog["scenario_families"][fam_id] = family_entry

    output_path = Path("docker_errors.json")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2)

    total_variants = sum(len(f["variants"]) for f in catalog["scenario_families"].values())
    print(f"Generated {output_path} (v2.0) with {len(catalog['scenario_families'])} families and {total_variants} total variants.")

if __name__ == "__main__":
    generate_catalog()
