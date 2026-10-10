# External Public-Log Validation Worksheet — Module II (70% Milestone, Section D)

Independent validation of Aditya's Parser V2 + RCA V1 against **real-world** GitHub Actions failure logs collected from public repositories, kept strictly separate from the synthetic F1–F4 dataset.

## Section D — External Dataset Worksheet

| Field | Value |
| --- | --- |
| Source/dataset | GitHub Actions failed workflow-run logs from 10 public repositories: encode/httpx, encode/starlette, pallets/click, pallets/flask, pallets/jinja, pallets/werkzeug, psf/black, psf/requests, pytest-dev/pytest, tiangolo/fastapi (fetched live via the GitHub REST API `GET /repos/{owner}/{repo}/actions/runs/{run_id}/logs`) |
| URL/citation | https://github.com/encode/httpx, https://github.com/encode/starlette, https://github.com/pallets/click, https://github.com/pallets/flask, https://github.com/pallets/jinja, https://github.com/pallets/werkzeug, https://github.com/psf/black, https://github.com/psf/requests, https://github.com/pytest-dev/pytest, https://github.com/tiangolo/fastapi — GitHub REST API v3 (https://docs.github.com/en/rest/actions/workflow-runs) |
| License checked? | Yes — Apache-2.0, BSD-3-Clause, MIT (all permissive OSI licenses) |
| Candidate logs | 586 failed-run logs fetched (roughly 3x that many failed runs were scanned; older runs skipped because GitHub retains Actions logs for ~90 days) |
| Selected logs | 586 (all 586 logs were successfully read and produced a structured RCA report) |
| Labels available? | Partial (Auto-extracted via regex) |
| Label verification | 25-log manual audit completed (see `manual_audit_sample.md`) |
| Categories represented | F1 (Syntax errors), F2 (Dependency errors), F3 (Test failures), F4 (Timeouts) |
| Categories missing | none of F1–F4; additionally 355/586 logs are Out-of-Scope (workflow-config, lint/pre-commit, infra/toolchain) failures that lie outside the F1–F4 scope and broke straight through the parser as 'unknown' |
| Separate from synthetic data? | Yes — stored under `external_data/`, disjoint from the synthetic `logs/` tree |

## Aditya Parser V2 Performance

How Aditya's rule-based Parser V2 + RCA V1 coped with real-world CI noise, graded against the independently regex-labeled `ground_truth.csv`.

### Headline numbers

- **Overall category accuracy:** 493/586 = **84.1%**
- **In-scope accuracy (ground truth ∈ F1–F4):** 141/231 = **61.0%** — the number that actually matters, and far below the headline figure
- **OOS abstention:** 352/355 out-of-scope logs were labeled 'unknown' (mapped to OOS) — the parser safely declines rather than misclassifies, which inflates the headline accuracy because the real corpus is 61% OOS
- **Mean RCA confidence:** 0.408 (parser's own self-reported confidence, low because most logs fell through to the fallback analyzer)

### Predicted `failure_class` distribution (raw parser output)

| failure_class | count |
| --- | --- |
| unknown | 421 |
| test_failure | 142 |
| runtime_error | 19 |
| syntax_error | 4 |

### Confusion matrix (rows = ground truth, cols = parser prediction)

| truth ↓ / pred → | F1 | F2 | F3 | F4 | OOS | total |
|  --- | --- | --- | --- | --- | --- | --- |
| **F1** | 4 | 0 | 2 | 0 | 0 | 6 |
| **F2** | 0 | 0 | 0 | 0 | 1 | 1 |
| **F3** | 0 | 0 | 137 | 0 | 72 | 209 |
| **F4** | 0 | 0 | 0 | 0 | 15 | 15 |
| **OOS** | 0 | 0 | 3 | 0 | 352 | 355 |
| **total** | 4 | 0 | 142 | 0 | 440 | 586 |

### Per-category precision / recall

| Category | Support | Predicted | Recall | Precision |
| --- | --- | --- | --- | --- |
| F1 (Syntax errors) | 6 | 4 | 66.7% | 100.0% |
| F2 (Dependency errors) | 1 | 0 | 0.0% | — |
| F3 (Test failures) | 209 | 142 | 65.6% | 96.5% |
| F4 (Timeouts) | 15 | 0 | 0.0% | — |
| OOS (Out of Scope) | 355 | 440 | 99.2% | 80.0% |

### Interpretation

- **Precision is high, recall is not.** When the parser commits to an in-scope class it is essentially always right (F1 and F3 precision = 100%), but it commits far too rarely — it recognised only 137/209 real test failures (F3 recall 65.6%). The synthetic-tuned regexes (`FAILED tests/...::name`, the 3-column job/step/timestamp layout) do not generalise to real multi-job logs, different test-path layouts, or lint/pre-commit output.
- **Timeouts/cancellations are missed (F4 recall 0%).** The parser only detects the literal GHA string `has timed out after`; real runner cancellations (`The operation was canceled`, exit 137/143) are not matched and fall through to 'unknown'.
- **No dependency-resolution failures occurred** in this organically-collected sample (F2 support = 0), so F2 could not be exercised against real data here.
- **The real-world failure distribution is dominated by Out-of-Scope causes** (355/586): workflow-config errors (an over-length `github-token` input), lint/formatting hooks (ruff, pre-commit), and infra/toolchain faults (artifact download, Dependabot, unavailable Python versions). Aditya's parser correctly refuses to guess on these (labels them 'unknown'), which is the safe behaviour but means it delivers **no actionable RCA for ~61% of real failures**.
- **Bottom line:** the rule-based approach is safe (high precision, honest abstention) but brittle on real noise (low recall, 61% in-scope accuracy). The headline 84% overall accuracy is an artifact of the corpus being mostly OOS — it should not be read as production readiness. Closing the gap needs broader test-failure/timeout patterns and an explicit OOS/environment category rather than a catch-all 'unknown'.
