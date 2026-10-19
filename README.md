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
# Generate target runs (500 failures + 300 successes)
python generate_f3_runs.py --runs 500 --success-runs 300

# Fresh run: purge prior F3 data and start from scratch
python generate_f3_runs.py --runs 500 --success-runs 300 --clean

# Reproducible run with a fixed seed
python generate_f3_runs.py --runs 500 --success-runs 300 --seed 42
```

Or run via the unified dataset pipeline CLI:
```bash
python dataset_pipeline.py --category F3 --runs 500 --success-runs 300
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

The canonical `labels.csv` uses a **23-column unified schema** that records individual matrix job executions for both failure runs (F3) and success baselines (S_F3):

```csv
run_id,outcome,category_id,failure_type,scenario_id,success_family,stage,workflow_id,job_id,repository,commit_sha,workflow_conclusion,generation_method,actual_execution_validated,validation_status,error_signature,log_file,metadata_file,timestamp,github_run_id,workflow_file,is_synthetic,failure_origin
```

### Field Definitions

| Column | Type | Description | F3 Failure Example | F3 Success Example |
| :--- | :--- | :--- | :--- | :--- |
| **`run_id`** | string | Unique sequential run identifier. | `F3_run_123456789` | `S_F3_run_123456789` |
| **`outcome`** | string | Run outcome (`failure` or `success`). | `failure` | `success` |
| **`category_id`** | string | Dataset failure taxonomy code. | `F3` | (empty) |
| **`failure_type`** | string | Injected test failure type (one of 8 error types). | `KeyError` | (empty) |
| **`scenario_id`** | string | Specific error scenario identifier. | `KeyError` | `valid_python_project` |
| **`success_family`** | string | Success family identifier (only for success runs). | (empty) | `F3` |
| **`stage`** | string | Pipeline lifecycle stage (`test` for F3). | `test` | `test` |
| **`workflow_id`** | string | GitHub Actions workflow run ID. | `17255341234` | `17255541234` |
| **`job_id`** | string | GitHub Actions job ID. | `117672415778` | `117759331399` |
| **`repository`** | string | Target GitHub repository (`owner/repo`). | `DhruvHegde/log-generation` | `DhruvHegde/log-generation` |
| **`commit_sha`** | string | 40-character Git commit hash that triggered the CI batch. | `d9735b735e340a3f8265f12c5986ee675302cca5` | `2ace4b8b605cab1fdd2e3281341f2cda194e8a29` |
| **`workflow_conclusion`** | string | GitHub Actions job conclusion status. | `failure` | `success` |
| **`generation_method`** | string | Generation method (`live_workflow_controlled_failure` or `live_workflow`). | `live_workflow_controlled_failure` | `live_workflow` |
| **`actual_execution_validated`** | boolean | Whether actual execution was validated (`true`/`false`). | `true` | `true` |
| **`validation_status`** | string | Validation result (`valid` or `failed_validation`). | `valid` | `valid` |
| **`error_signature`** | string | Matched error signature in log. | `TEST ERROR: KeyError` | `all_tests_passed` |
| **`log_file`** | string | Relative path to the raw console log. | `logs/F3/123456789.log` | `logs/success/F3/123456789.log` |
| **`metadata_file`** | string | Relative path to the structured metadata JSON. | `metadata/F3/123456789.json` | `metadata/success/F3/123456789.json` |
| **`timestamp`** | string | Job completion ISO-8601 timestamp. | `2026-10-18T12:14:05Z` | `2026-10-18T18:50:59Z` |
| **`github_run_id`** | string | GitHub Actions workflow run database ID. | `17255341234` | `17255541234` |
| **`workflow_file`** | string | Workflow filename that executed the job. | `f3_test.yml` | `f3_test.yml` |
| **`is_synthetic`** | boolean | Whether the run was synthetically generated. | `true` | `false` |
| **`failure_origin`** | string | Origin of failure for synthetic runs. | `test_mutation` | (empty) |

---

### Final Dataset Counts

| Run Type | Count | Run ID Range |
| :--- | :--- | :--- |
| **F3 Test Failures** | 500 | `F3_run_<job_id>` (500 unique job IDs) |
| **S_F3 Success Baselines** | 300 | `S_F3_run_<job_id>` (300 unique job IDs) |
| **Total** | **800** | |

---

## 🏗️ 8. F3 Core Architecture

```
generate_f3_runs.py
├── select_error_types()        # Weighted random selection with inverse frequency
├── write_batch_spec()          # Writes .f3_batch.json for GitHub Actions matrix
├── sync_and_prepare_labels()   # Canonical schema enforcement; append vs clean
├── git_commit_and_push()       # Triggers workflow via git push to feature/f3-test-failures
├── poll_workflow_run()         # GitHub Actions REST polling for workflow completion
├── get_matrix_jobs()           # Fetches matrix jobs, filters test-f3 jobs
├── wait_for_matrix_jobs()      # Reports progress while waiting for batch completion
└── fetch_and_save_matrix_artifacts()
    ├── Downloads console logs  → logs/F3/<job_id>.log
    ├── Downloads job metadata  → metadata/F3/<job_id>.json
    └── Appends labels.csv records with 23-column unified schema
```

**Concurrency:** `max-parallel: 250` in `.github/workflows/f3_test.yml` and `BATCH_SIZE = 250` in `generate_f3_runs.py`. The batch size matches the workflow concurrency cap to enable full parallel execution of up to 250 jobs simultaneously.

---

## 📂 9. Repository Directory Structure

```text
log-generation/
├── .github/
│   └── workflows/
│       └── f3_test.yml            # Dynamic parallel matrix CI workflow (F3)
├── automation/
│   ├── git_utils.py               # Git operations helper
│   ├── inject_mutation.py         # Synthetic failure mutation engine
│   ├── metadata_utils.py          # Metadata helper
│   ├── state_utils.py             # State persistence helper
│   ├── validator.py               # Pattern validator
│   └── workflow_utils.py          # Workflow helper
├── logs/
│   ├── F3/                        # Harvested raw job logs (<job_id>.log)
│   └── success/
│       └── F3/                    # Harvested success job logs (<job_id>.log)
├── metadata/
│   ├── F3/                        # Harvested GitHub job JSON metadata (<job_id>.json)
│   └── success/
│       └── F3/                    # Harvested success job JSON metadata (<job_id>.json)
├── src/
│   └── app.py                     # Baseline application functions
├── tests/
│   └── test_app.py                # Baseline Pytest test suite (mutated per batch)
├── .env.example                   # Environment configuration template
├── .f3_batch.json                 # Dynamic matrix batch specification (1-250 entries)
├── AGENTS.md                      # Repository rules & architecture guide
├── dataset_pipeline.py            # Unified pipeline runner CLI
├── generate_f3_runs.py            # Core F3 failure/success generation, REST polling, and harvester
├── labels.csv                     # Master dataset run registry & labels (23 columns)
├── F3_VALIDATION_REPORT.md        # Dataset validation report
├── pytest.ini                     # Local pytest configuration
└── README.md                      # Complete project & branch documentation (this file)
```

---

## 🔒 10. Security Notes

* **Never commit `.env`** — it contains `GITHUB_TOKEN` and other sensitive credentials.
* `.env` is listed in `.gitignore` and must remain local only.
* Do not expose `GITHUB_TOKEN` in logs, commits, or issue descriptions.
