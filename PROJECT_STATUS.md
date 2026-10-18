# Project Status

## Project objective

This repository is intended to generate a dataset of dependency-install and dependency-resolution failures by repeatedly modifying the dependency list, pushing commits, and capturing the resulting GitHub Actions failure behavior. The design is to cycle through a list of intentionally broken dependency entries, let CI fail for each one, and collect the resulting logs and metadata as labeled examples.

Based on the current repository contents, the project is only partially implemented. The codebase contains the core sequencing logic and helper utilities for generating failing dependency commits, but it does not yet complete the full dataset-collection pipeline.

## Repository structure

- .github/workflows/ci.yml
  - GitHub Actions workflow that installs dependencies and runs pytest.

- automation/
  - Collection of helper modules for git, state, workflow polling, validation, and metadata handling.

- logs/
  - Intended location for generated workflow logs.

- metadata/
  - Intended location for saved metadata files.

- app.py
  - Minimal arithmetic helper.

- config.py
  - Repository and workflow configuration.

- dependency_errors.txt
  - List of dependency strings that are expected to fail in installation.

- generate_failures.py
  - Main generator script for creating failing dependency runs.

- labels.csv
  - Placeholder CSV schema for dataset labeling.

- requirements.txt
  - Current dependency input used by CI.

- state.json
  - Tracks current progress for the run loop.

- test_app.py
  - Unit test for the arithmetic helper.

- test_workflow.py
  - Script to exercise workflow polling and git commit/push behavior.

## Current execution flow

The repository’s current execution flow is as follows:

1. The script [generate_failures.py](generate_failures.py) loads the dependency list from [dependency_errors.txt](dependency_errors.txt).
2. It reads the current progress from [state.json](state.json).
3. It checks whether the run counter has reached the configured TOTAL_RUNS limit in [config.py](config.py).
4. If the limit has not been reached, it selects the next dependency item from the list.
5. It overwrites [requirements.txt](requirements.txt) with the selected dependency string.
6. It calls the git helper to stage files, commit, and push to the origin main branch.
7. The GitHub Actions workflow in [.github/workflows/ci.yml](.github/workflows/ci.yml) runs on push and attempts to install the dependency set and run pytest.
8. The workflow helper in [automation/workflow_utils.py](automation/workflow_utils.py) can query workflow runs and wait for a matching commit SHA.
9. The state file is updated to advance the run index.
10. The script exits.

The key gap is that there is no implemented code that follows the workflow run completion with log extraction, validation, metadata writeout, or final label generation. The script advances state, but does not complete the rest of the dataset collection process.

## Completed modules

The following modules are implemented and appear functional in the current repository:

- [config.py](config.py)
  - Project constants and runtime settings.

- [automation/state_utils.py](automation/state_utils.py)
  - Loads and saves JSON state.

- [automation/git_utils.py](automation/git_utils.py)
  - Stages, commits, pushes, and returns the HEAD SHA.

- [automation/workflow_utils.py](automation/workflow_utils.py)
  - Queries GitHub Actions runs and waits for completion by commit SHA.

- [automation/validator.py](automation/validator.py)
  - Detects common dependency error patterns in log text.

- [dependency_errors.txt](dependency_errors.txt)
  - Provides a list of dependency failures to try.

- [generate_failures.py](generate_failures.py)
  - Runs the dataset-generation loop at a basic level.

- [app.py](app.py)
  - Minimal arithmetic helper used by the basic app test.

- [test_app.py](test_app.py)
  - Basic unit test for the arithmetic helper.

- [.github/workflows/ci.yml](.github/workflows/ci.yml)
  - GitHub Actions workflow that installs requirements and runs pytest.

## Partially completed modules

The following modules exist but are not yet wired into an end-to-end dataset pipeline:

- [generate_failures.py](generate_failures.py)
  - Generates failed dependency runs but does not collect or validate the run results.

- [automation/workflow_utils.py](automation/workflow_utils.py)
  - Can monitor workflow runs, but is not connected to a full completion pipeline.

- [automation/metadata_utils.py](automation/metadata_utils.py)
  - Saves JSON metadata, but there are no actual run-processing calls using it.

- [test_workflow.py](test_workflow.py)
  - Useful as a manual script, but it is not a proper automated test and is not integrated into the main workflow.

## Missing modules

The repository currently does not contain implementations for:

- Workflow log download or retrieval
- Error-log interpretation after CI completion
- Metadata capture for each run
- Label generation for each run
- CSV or dataset construction
- Aggregation of collected failure examples into a final dataset
- End-to-end orchestration that starts after workflow completion and ends after dataset creation
- Real per-run artifact storage in the logs and metadata directories

## Current completion percentage

Based strictly on the repository’s current state, the project is approximately 35% complete.

Reasoning:
- Core configuration, git commit/push flow, and workflow polling are present.
- The dataset-generation loop is present at a basic level.
- The end-to-end processing of workflow results into logs, metadata, labels, and a dataset is missing.
- Several modules are placeholders or empty files.

## Known issues

- [automation/dataset_utils.py](automation/dataset_utils.py) is empty.
- [automation/log_utils.py](automation/log_utils.py) is empty.
- [automation/label_utils.py](automation/label_utils.py) is empty.
- [logs/F2/test](logs/F2/test) is just a placeholder with no real content.
- [metadata/F2](metadata/F2) exists but is empty.
- [labels.csv](labels.csv) contains only a header row, not actual dataset rows.
- [README.md](README.md) is effectively a placeholder and does not describe the project.
- [state.json](state.json) indicates progress has advanced, but there is no downstream processing for corresponding workflow results.
- The repository contains duplicated subprocess helper logic in [automation/git_utils.py](automation/git_utils.py) and [automation/workflow_utils.py](automation/workflow_utils.py).
- The project is not yet a complete autonomous dataset generator; it ends after commit/push and state update.

## Immediate next objective

The next objective should be to implement the missing post-workflow processing stage:

- Wait for the GitHub Actions run to complete for the current commit
- Retrieve or inspect the relevant workflow log
- Validate whether the failure matches a dependency error pattern
- Save the result to the log and metadata outputs
- Add the labeled record to a dataset or CSV
- Only then proceed to the next dependency item

This is the most important missing piece because without it the repository cannot convert dependency failures into an actual dataset.
