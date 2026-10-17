# CI/CD Failure Predictor & Dataset Generator (`log-generation`)

An automated synthetic failure generation and dataset collection framework designed to generate, execute, collect, and label real-world GitHub Actions CI/CD failure logs for training machine learning models in failure prediction, classification, and automated root-cause analysis.

---

## 🌐 1. Project-Wide Overview & Failure Taxonomy

In modern software engineering, CI/CD pipeline failures occur across different lifecycle stages. This Capstone project models and collects failure datasets across **8 standardized failure categories**:

| Category | Failure Domain | Stage | Description | Branch Name |
| :--- | :--- | :--- | :--- | :--- |
| **F0** | **Healthy Pass Baseline** | `test` | Clean, passing CI runs with no injected failures — baseline control group. | `feature/f3-test-failures` |
| **F1** | **Syntax / Compilation & Linting Errors** | `build` | Broken Python syntax, invalid indentation, unparseable code, lint violations. | `feature/syntax-errors` |
| **F2** | **Dependency & Environment Conflicts** | `build` | Invalid `requirements.txt`, impossible package versions, missing packages. | `main` |
| **F3** | **Test Assertion Regressions** | `test` | Controlled runtime exceptions, assertion errors, and Pytest test failures. | `feature/f3-test-failures` |
| **F4** | **Build Timeouts & Hanging Processes** | `runtime` | Long-running jobs, hanging processes, infinite loops, workflow timeouts. | `feature/timeout-errors` |
| **F5** | **Docker & Container Build Failures** | `deploy` | Dockerfile errors, image build failures, container startup failures. | `feature/f4-deployment-errors` |
| **F6** | **CI/CD Configuration & Permission Failures** | `deploy` | Workflow YAML errors, permission issues, secret/config misconfiguration. | `feature/dataset-collector` |
| **F7** | **Network & External-Service Failures** | `test` | DNS resolution failures, connection refusals/timeouts/resets, TLS handshake failures, remote 5xx errors, rate limiting, package repo unreachable, external service outages. | `feature/f7-network-errors` |

---

## 🎯 2. Category F3 Role: Controlled Test Failures (`feature/f3-test-failures`)

This branch is specifically dedicated to **Category F3 (Controlled Test Failures)**.

### Mission & Core Workflow

1. **Baseline Scaffolding:** Maintain a testable baseline application (`src/app.py`) and test suite (`tests/test_app.py`) that passes cleanly under normal conditions.
2. **Synthetic Mutation Engine:** Dynamically inject 8 specific Python runtime exception and assertion error types into `tests/test_app.py`.
3. **Dynamic Parallel CI Matrix:** Generate `.f3_batch.json` and trigger high-speed parallel matrix execution on GitHub Actions (`.github/workflows/f3_test.yml`) with **up to 250 concurrent jobs per batch** (`fail-fast: false`, `max-parallel: 250`).
4. **Concurrent Log & Metadata Harvesting:** Automatically poll GitHub Actions for job completions and download raw console logs (`logs/F3/<job_id>.log`) and job JSON metadata (`metadata/F3/<job_id>.json`) concurrently via `ThreadPoolExecutor`.
5. **Unified Dataset Registry (`labels.csv`):** Record normalized matrix job metadata, execution conclusions, error types, timestamps, and artifact paths while strictly protecting non-F3 teammate records (`F0`, `F1`, `F2`, `F4`, `F5`, `F6`, `F7`).

---

## 🧪 3. The 8 Target Pytest Failure Mutations

Category F3 simulates realistic test failures mapping to 8 standard Python runtime exceptions and assertions:

| Error Type | Function Target | Mutation / Failure Trigger |
| :--- | :--- | :--- |
| **`AssertionError`** | `assert_positive(n)` | Passes negative number (`-5`), failing the assertion check. |
| **`IndexError`** | `get_list_item(lst, index)` | Accesses out-of-bounds list index (`999`). |
| **`KeyError`** | `get_dict_value(d, key)` | Accesses non-existent dictionary key (`"missing_key"`). |
| **`TypeError`** | `calculate_division(a, b)` | Passes non-numeric string type (`"invalid_string"`) to division. |
| **`ValueError`** | `convert_to_int(val)` | Passes non-numeric string (`"unparseable_alphanumeric_0x99"`) to integer conversion. |
| **`AttributeError`** | `get_object_attribute(obj)` | Accesses non-existent attribute on a dummy object. |
| **`ZeroDivisionError`** | `calculate_division(a, b)` | Passes denominator `b = 0`. |
| **`FileNotFoundError`** | `read_config_file(path)` | Attempts to open a non-existent configuration file path. |

### 🎲 Weighted Random Selection Engine

To ensure realistic, non-deterministic dataset distribution while preventing error starvation across large runs, error selection is stochastically randomized using **inverse historical frequency weighting**:

$$\text{Weight} = \frac{1.0}{1.0 + \text{historical\_count}}$$

* **Dynamic Weighting:** Error types with fewer completed runs in `labels.csv` receive higher sampling probability.
* **Non-Deterministic Sampling:** Uses `random.choices()` to allow realistic duplicates and varying batch distributions.
* **Deterministic Seeding:** Supports `--seed <int>` for reproducible dataset generation runs across serialized batches.

---

## 📂 4. Repository Directory Structure

```text
log-generation/
├── .github/
│   └── workflows/
│       ├── ci.yml                 # Baseline CI workflow (F2)
│       └── f3_test.yml            # Dynamic parallel matrix CI workflow (F3)
├── automation/
│   ├── git_utils.py               # Git operations helper
│   ├── inject_mutation.py         # Synthetic failure mutation engine
│   ├── metadata_utils.py          # Metadata helper
│   ├── state_utils.py             # State persistence helper
│   ├── validator.py               # Pattern validator
│   └── workflow_utils.py          # Workflow helper
├── logs/
│   └── F3/                        # Harvested raw job logs (<job_id>.log)
├── metadata/
│   └── F3/                        # Harvested GitHub job JSON metadata (<job_id>.json)
├── src/
│   └── app.py                     # Baseline application functions
├── tests/
│   └── test_app.py                # Baseline Pytest test suite
├── .env.example                   # Environment configuration template
├── .f3_batch.json                 # Dynamic matrix batch specification (1-250 entries)
├── AGENTS.md                      # Repository rules & architecture guide
├── dataset_pipeline.py            # Unified pipeline runner CLI
├── generate_f3_runs.py            # Core F3 failure generation, REST polling, and harvester
├── labels.csv                     # Master dataset run registry & labels
├── pytest.ini                     # Local pytest configuration
└── README.md                      # Complete project & branch documentation
```

---

## 🚀 5. How to Run the Pipeline

### Prerequisites

1. Copy `.env.example` to `.env` and configure your GitHub personal access token:
   ```env
   GITHUB_TOKEN=ghp_your_personal_access_token
   REPO_OWNER=DhruvHegde
   REPO_NAME=log-generation
   GIT_BRANCH=feature/f3-test-failures
   WORKFLOW_FILE=f3_test.yml
   ```

2. Install local Python dependencies:
   ```bash
   pip install pytest requests python-dotenv
   ```

### Execution Commands

Run the F3 generator directly:
```bash
# Generate target runs (e.g. 250 runs across batches of 250)
python generate_f3_runs.py --runs 250

# Fresh run: purge prior F3 data and start from scratch
python generate_f3_runs.py --runs 250 --clean

# Reproducible run with a fixed seed
python generate_f3_runs.py --runs 250 --seed 42
```

Or run via the unified dataset pipeline CLI:
```bash
python dataset_pipeline.py --category F3 --runs 250
```

### Local Validation

Before remote execution, run local validation checks:
```bash
python -m py_compile generate_f3_runs.py
pytest tests/test_app.py -q
```

---

## ⚙️ 6. Execution Modes & Safety Rules

1. **Clean / Fresh Generation Mode (`--clean` passed):**
   * Purges previous F3 logs in `logs/F3/`, metadata in `metadata/F3/`, and prior F3 label entries in `labels.csv`.
   * **Teammate Safety Guarantee:** Strictly preserves all non-F3 records (`F0`, `F1`, `F2`, `F4`, `F5`, `F6`, `F7`) and non-F3 artifact directories.
   * Generates new batches until the target `--runs` count is reached.

2. **Resumption / Append Mode (Default, without `--clean`):**
   * Inspects existing F3 runs in `labels.csv`.
   * If the target `--runs` is already reached, exits cleanly without making remote calls.
   * Resumes in-flight matrix batches if a matching batch commit exists, avoiding duplicate runs.
   * Dynamically generates remaining batches of up to 250 jobs until `--runs` is satisfied.

---

## 📊 7. Dataset Schema (`labels.csv`)

The canonical `labels.csv` uses a 13-column schema that records individual matrix job executions:

```csv
run_number,dependency,repository,commit_sha,workflow_id,workflow_conclusion,failure_type,stage,validation_status,matched_pattern,log_file,metadata_file,timestamp
```

### Field Definitions

| Column | Description | Example |
| :--- | :--- | :--- |
| **`run_number`** | Unique GitHub Actions matrix job database ID. | `100991130618` |
| **`dependency`** | Injected error type (e.g., `AssertionError`, `KeyError`). | `ZeroDivisionError` |
| **`repository`** | Target GitHub repository (`owner/repo`). | `DhruvHegde/log-generation` |
| **`commit_sha`** | 40-character Git commit hash that triggered the CI batch. | `662918f99782429600c2c3d5153248f654497263` |
| **`workflow_id`** | Workflow file name responsible for the run. | `f3_test.yml` |
| **`workflow_conclusion`** | GitHub Actions job conclusion status (`failure` or `success`). | `failure` |
| **`failure_type`** | Dataset failure taxonomy code (`F0`, `F1`, `F2`, `F3`, `F4`, `F5`, `F6`, `F7`). | `F3` |
| **`stage`** | Pipeline lifecycle stage (`test` for F3). | `test` |
| **`validation_status`** | Validation result recorded for the collected job. | `failure` |
| **`matched_pattern`** | Injected error type matched in the matrix job title. | `ZeroDivisionError` |
| **`log_file`** | Relative path to the raw console log. | `logs/F3/100991130618.log` |
| **`metadata_file`** | Relative path to the GitHub Actions job JSON metadata. | `metadata/F3/100991130618.json` |
| **`timestamp`** | Job completion ISO-8601 timestamp (`completed_at`). | `2026-09-04T10:22:44Z` |
