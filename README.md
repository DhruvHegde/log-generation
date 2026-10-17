# Category F7 — Network & External-Service Failure Generator (`feature/f7-network-errors`)

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
| **F7** | **Network & External-Service Failures** *(This Branch)* | `test` | DNS resolution failures, connection refusals/timeouts/resets, TLS handshake failures, remote 5xx errors, rate limiting, package repo unreachable, external service outages. | `feature/f7-network-errors` |

---

## 🎯 2. Category F7 Role: Network & External-Service Failures (`feature/f7-network-errors`)

This branch is specifically dedicated to **Category F7 (Network & External-Service Failures)** — simulating real-world CI/CD failures caused by network unreliability and external dependency outages.

### Mission & Core Workflow

1. **Baseline Scaffolding:** Maintain a testable baseline application (`src/app.py`) and test suite (`tests/test_app.py`) that passes cleanly under normal conditions.
2. **Synthetic Network Failure Injection Engine:** Dynamically inject 9 specific network and external-service failure types into `tests/test_app.py` using `automation/inject_network_failure.py`.
3. **Dynamic Parallel CI Matrix:** Generate `.f7_batch.json` and trigger high-speed parallel matrix execution on GitHub Actions (`.github/workflows/f7_test.yml`) with **up to 20 concurrent jobs per batch** (`fail-fast: false`, `max-parallel: 20`). The concurrency cap of 20 prevents GitHub Actions runner queuing and workflow timeouts that occur when too many jobs request runners simultaneously.
4. **Concurrent Log & Metadata Harvesting:** Automatically poll GitHub Actions for job completions and download raw console logs (`logs/F7/<job_id>.log`) and job JSON metadata (`metadata/F7/<job_id>.json`) concurrently via `ThreadPoolExecutor`.
5. **Unified Dataset Registry (`labels.csv`):** Record normalized matrix job metadata, execution conclusions, error types, timestamps, and artifact paths while strictly protecting non-F7 teammate records (`F0`, `F1`, `F2`, `F3`, `F4`, `F5`, `F6`).

---

## 🌐 3. The 9 Target Network Failure Types

Category F7 simulates realistic CI/CD network and external-service failures across 9 distinct categories:

| Error Type | Error Signature | Real-World CI Context |
| :--- | :--- | :--- |
| **`dns_resolution_failure`** | `socket.gaierror [Errno -3]`, `Could not resolve host`, `EAI_AGAIN` | CI job cannot resolve a dependency host or API domain; DNS server unreachable or misconfigured. |
| **`connection_refused`** | `ConnectionRefusedError [Errno 111]`, `curl: (7) Failed to connect` | Target service port is closed or the host actively refuses connections (no listener). |
| **`connection_timeout`** | `requests.exceptions.ConnectTimeout`, `ETIMEDOUT`, `Operation timed out` | TCP handshake never completes; network partition or firewall drops packets silently. |
| **`connection_reset`** | `ConnectionResetError [Errno 104] Connection reset by peer`, `ECONNRESET` | Peer abruptly closes the TCP connection mid-request; load balancer or proxy kills idle connections. |
| **`tls_handshake_failure`** | `net/http: TLS handshake timeout`, `SSL: CERTIFICATE_VERIFY_FAILED` | Certificate expiry, CA trust chain broken, or cipher suite mismatch prevents secure connection establishment. |
| **`remote_server_5xx`** | HTTP `502 Bad Gateway`, `503 Service Unavailable`, `504 Gateway Timeout` | Upstream service is overloaded, under maintenance, or experiencing partial outage; retries may help. |
| **`rate_limit_exceeded`** | HTTP `429 Too Many Requests`, registry API rate limiting | CI job hits GitHub API, PyPI, npm, or Docker Hub rate limits; requires backoff and retry logic. |
| **`package_repo_unreachable`** | PyPI CDN / package registry connection timeouts or TLS drops | Package index (PyPI, npm, Maven Central) is unreachable or returns malformed responses during `pip install`. |
| **`external_service_outage`** | Staging API / webhook / third-party test dependency service outages | Third-party dependencies (payment gateways, identity providers, webhook endpoints) are down or degraded. |

---

## 🎲 4. Inverse Historical Frequency Weighting

To ensure realistic, non-deterministic dataset distribution while preventing error starvation across large runs, error selection is stochastically randomized using **inverse historical frequency weighting**:

$$\text{Weight} = \frac{1.0}{1.0 + \text{historical\_count}}$$

where `historical_count` is the number of times an error type has already appeared in `labels.csv` for failure type `F7`.

* **Dynamic Weighting:** Error types with fewer completed runs in `labels.csv` receive higher sampling probability, gently balancing distribution across all 9 subcategories.
* **Non-Deterministic Sampling:** Uses `random.Random(seed).choices()` to allow realistic duplicates and varying batch distributions — selection does not guarantee equal distribution or one instance of every error type.
* **Deterministic Seeding:** Supports `--seed <int>` for reproducible dataset generation across serialized batches. Each batch uses a deterministic seed derived from the supplied seed and batch number.

---

## 🚀 5. Execution Commands (Identical to F3)

### Prerequisites

1. Copy `.env.example` to `.env` and configure your GitHub personal access token:
   ```env
   GITHUB_TOKEN=ghp_your_personal_access_token
   REPO_OWNER=DhruvHegde
   REPO_NAME=dependency-error-repo
   GIT_BRANCH=feature/f7-network-errors
   WORKFLOW_FILE=f7_test.yml
   ```

2. Install local Python dependencies:
   ```bash
   pip install pytest requests python-dotenv
   ```

### Execution Modes

**Append Mode (Default):** Verifies existing logs and generates only the delta needed to reach `--runs`. Exits cleanly if the target is already reached.

```bash
python generate_f7_runs.py --runs 250
```

**Clean Mode:** Purges `logs/F7/`, `metadata/F7/`, and all F7 records in `labels.csv`, then generates fresh from zero.

```bash
python generate_f7_runs.py --runs 250 --clean
```

**Deterministic Seeded Generation:** Reproducible runs with a fixed seed.

```bash
python generate_f7_runs.py --runs 250 --seed 42
```

### Unified CLI Invocation

If `dataset_pipeline.py` exists in the repo:

```bash
python dataset_pipeline.py --category F7 --runs 250
```

### Local Validation

Before remote execution, run local validation checks:
```bash
python -m py_compile generate_f7_runs.py
pytest tests/test_app.py -q
```

---

## ⚙️ 6. Execution Modes & Safety Rules

1. **Clean / Fresh Generation Mode (`--clean` passed):**
   * Purges previous F7 logs in `logs/F7/`, metadata in `metadata/F7/`, and prior F7 label entries in `labels.csv`.
   * **Teammate Safety Guarantee:** Strictly preserves all non-F7 records (`F0`, `F1`, `F2`, `F3`, `F4`, `F5`, `F6`) and non-F7 artifact directories.
   * Generates new batches until the target `--runs` count is reached.

2. **Resumption / Append Mode (Default, without `--clean`):**
   * Inspects existing F7 runs in `labels.csv` (using `failure_type == 'F7'`).
   * If the target `--runs` is already reached, exits cleanly without making remote calls.
   * Resumes in-flight matrix batches if a matching batch commit exists, avoiding duplicate runs.
   * Dynamically generates remaining batches of up to 20 jobs until `--runs` is satisfied.
   * Never overwrites or duplicates existing IDs in `labels.csv`.

---

## 📊 7. Dataset Schema (`labels.csv`)

The canonical `labels.csv` uses a **13-column schema** that records individual matrix job executions:

```csv
run_number,dependency,repository,commit_sha,workflow_id,workflow_conclusion,failure_type,stage,validation_status,matched_pattern,log_file,metadata_file,timestamp
```

### Field Definitions

| Column | Type | Description | F7 Example |
| :--- | :--- | :--- | :--- |
| **`run_number`** | string | Unique GitHub Actions matrix job database ID. | `100991130618` |
| **`dependency`** | string | Injected network failure type (one of the 9 error types). | `dns_resolution_failure` |
| **`repository`** | string | Target GitHub repository (`owner/repo`). | `DhruvHegde/dependency-error-repo` |
| **`commit_sha`** | string | 40-character Git commit hash that triggered the CI batch. | `662918f99782429600c2c3d5153248f654497263` |
| **`workflow_id`** | string | Workflow file name responsible for the run. | `f7_test.yml` |
| **`workflow_conclusion`** | string | GitHub Actions job conclusion status (`failure` or `success`). | `failure` |
| **`failure_type`** | string | Dataset failure taxonomy code. | `F7` |
| **`stage`** | string | Pipeline lifecycle stage (`test` for F7). | `test` |
| **`validation_status`** | string | Validation result recorded for the collected job. | `failure` |
| **`matched_pattern`** | string | Injected error type matched in the matrix job title. | `dns_resolution_failure` |
| **`log_file`** | string | Relative path to the raw console log. | `logs/F7/100991130618.log` |
| **`metadata_file`** | string | Relative path to the GitHub Actions job JSON metadata. | `metadata/F7/100991130618.json` |
| **`timestamp`** | string | Job completion ISO-8601 timestamp (`completed_at`). | `2026-09-04T10:22:44Z` |

---

## 🏗️ 8. F7 Core Architecture

```
generate_f7_runs.py
├── select_error_types()        # Weighted random selection with inverse frequency
├── write_batch_spec()          # Writes .f7_batch.json for GitHub Actions matrix
├── sync_and_prepare_labels()   # Canonical schema enforcement; append vs clean
├── git_commit_and_push()       # Triggers workflow via git push to feature/f7-network-errors
├── poll_workflow_run()         # GitHub Actions REST polling for workflow completion
├── get_matrix_jobs()           # Fetches matrix jobs, filters test-f7 jobs
├── wait_for_matrix_jobs()      # Reports progress while waiting for batch completion
└── fetch_and_save_matrix_artifacts()
    ├── Downloads console logs  → logs/F7/<job_id>.log
    ├── Downloads job metadata  → metadata/F7/<job_id>.json
    └── Appends labels.csv records with 13-column schema
```

**Concurrency:** `max-parallel: 20` in `.github/workflows/f7_test.yml` and `BATCH_SIZE = 20` in `generate_f7_runs.py`. The batch size matches the workflow concurrency cap to prevent GitHub Actions runner queuing and workflow timeouts.

---

## 📂 9. Repository Directory Structure

```text
log-generation/
├── .github/
│   └── workflows/
│       └── f7_test.yml           # Dynamic parallel matrix CI workflow (F7)
├── automation/
│   └── inject_network_failure.py # Synthetic network failure mutation engine
├── logs/
│   └── F7/                       # Harvested raw job logs (<job_id>.log)
├── metadata/
│   └── F7/                       # Harvested GitHub job JSON metadata (<job_id>.json)
├── src/
│   └── app.py                    # Baseline application functions
├── tests/
│   └── test_app.py               # Baseline Pytest test suite (mutated per batch)
├── .env.example                  # Environment configuration template
├── .f7_batch.json                # Dynamic matrix batch specification (1-20 entries)
├── .gitignore                    # Git ignore rules (excludes .env, logs/, metadata/, labels.csv)
├── F7_SETUP_SUMMARY.md           # Phase-by-phase setup and execution summary
├── generate_f7_runs.py           # Core F7 failure generation, REST polling, and harvester
├── labels.csv                    # Master dataset run registry & labels
└── README.md                     # Complete project & branch documentation (this file)
```

---

## 🔒 10. Security Notes

* **Never commit `.env`** — it contains `GITHUB_TOKEN` and other sensitive credentials.
* `.env` is listed in `.gitignore` and must remain local only.
* Do not expose `GITHUB_TOKEN` in logs, commits, or issue descriptions.
