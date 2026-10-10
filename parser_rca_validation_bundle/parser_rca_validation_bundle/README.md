# Parser V2 + RCA V1 — External Validation Bundle

Generated: 2026-10-09 19:33

This bundle contains the complete real-world validation run of the CI/CD log
Parser V2 and RCA V1 engine, graded against independent ground-truth labels.

## What this experiment did

1. **Fetched real failed logs** — 586 genuine *failed* GitHub Actions
   workflow logs pulled from ~10 public Python repositories (flask, requests,
   fastapi, pytest, httpx, werkzeug, black, jinja, starlette, pytest) via the
   GitHub REST API. These are real-world CI failures, kept strictly separate
   from the synthetic F1-F4 training data.
2. **Independently labeled them** — a separate regex labeler assigned each log a
   ground-truth category (F1 Syntax, F2 Dependency, F3 Test, F4 Timeout,
   OOS Out-of-Scope). This is the reference, independent of the parser.
3. **Ran them through Parser V2 + RCA V1** — the same raw logs were fed to
   `parse_logs.py` and `run_rca.py`, producing structured output and
   root-cause reports.
4. **Compared prediction vs. ground truth** — producing the confusion matrix
   and accuracy metrics.

## Headline results (586 logs)

- Overall category accuracy: **84.1%** (493/586)
- High precision, low recall: when the parser commits to an in-scope class it
  is almost always right, but it misses many real failures (72 real test
  failures and all 15 timeouts fell through to OOS/"unknown").
- The real corpus is ~60% genuinely Out-of-Scope (infra, lint, auth, config);
  the parser safely abstains on those rather than hallucinating.

## Contents

```
parser_rca_validation_bundle/
├── README.md                         <- this file
├── confusion_matrix.png              <- 300 DPI heatmap (truth vs prediction)
├── external_data/
│   ├── raw_logs/                     <- 586 raw GitHub Actions .log files
│   ├── ground_truth.csv              <- independent labels [log, category, snippet] (586 rows)
│   ├── public_logs_catalog.csv       <- MANIFEST: log -> repository, run_id, license
│   ├── fetch_metadata.json           <- richer manifest: workflow name, event, html_url, created_at
│   ├── manual_audit_sample.md        <- 25-log stratified manual audit
│   ├── external_data_worksheet.md    <- Section-D worksheet + performance writeup
│   ├── parser_parsed.csv             <- Parser V2 structured output
│   ├── parser_rca_output.ndjson      <- RCA V1 predictions (one JSON report per line)
│   └── Module_II_External_Log_Validation_Report.docx
├── scripts/
│   ├── 01_fetch_public_logs.py       <- fetcher (GitHub API -> raw_logs/)
│   ├── 02_ground_truth_labeler.py    <- independent regex labeler
│   ├── 03_evaluate_parser.py         <- METRICS: runs pipeline + grades vs ground truth
│   ├── plot_confusion_matrix.py      <- METRICS: builds confusion matrix + accuracy
│   └── inspect_rca_samples.py
└── parser_code/                      <- Parser V2 + RCA V1 source (self-contained)
    ├── parse_logs.py
    ├── run_rca.py
    ├── parser/                       <- log_parser.py (Parser V2)
    └── rca/                          <- engine, schema, analyzers (RCA V1)
```

## How the metrics were calculated

- `scripts/plot_confusion_matrix.py` reads `external_data/ground_truth.csv`
  (truth) and `external_data/parser_rca_output.ndjson` (predictions), maps the
  parser's `failure_class` onto the 5-category F-scheme
  (syntax_error->F1, dependency_error->F2, test_failure->F3, timeout->F4,
  runtime_error/unknown->OOS), builds the confusion matrix and overall accuracy,
  and renders `confusion_matrix.png`.
- `scripts/03_evaluate_parser.py` does the full grading (per-category
  precision/recall, in-scope vs overall accuracy, mean RCA confidence) and
  writes the worksheet.

## How to reproduce the numbers

```bash
pip install matplotlib seaborn pandas python-docx
# from a dir containing parser_code/ on the path (or copy the scripts next to parse_logs.py):
python scripts/plot_confusion_matrix.py      # -> confusion_matrix.png + accuracy
python scripts/03_evaluate_parser.py         # -> full worksheet + per-category metrics
```

Note: the raw logs are already included, so you do NOT need the GitHub API or
`gh` auth to reproduce the grading — only `01_fetch_public_logs.py` needs it.
