"""rca/validate_rca.py

Dataset-wide RCA V1 validation script.

Parses all 1,992 logs (F1/F2/F3/F4) using Parser V2, runs RCA V1 on each
record, and reports engineering metrics per category:
  - Total records analyzed
  - Causal category distribution
  - rca_confidence statistics (mean, median, % high/medium/low)
  - Likely-cause coverage (non-empty string)
  - Investigation coverage (>=1 step)
  - Primary-evidence coverage (>=1 line)
  - Limitation coverage (>=1 entry)
  - Category-specific evidence field coverage

Usage:
    python rca/validate_rca.py
    python rca/validate_rca.py --base-dir logs
    python rca/validate_rca.py --json rca_validation_report.json
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

# Ensure repo root is on sys.path so `parser` and `rca` are importable.
_REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO_ROOT))

from parser.log_parser import parse_batch, LogRecord
from rca.engine import get_default_engine
from rca.schema import RCAReport

_CATEGORY_DIRS = {
    "F1": "F1",
    "F2": "F2",
    "F3": "F3",
    "F4": "F4",
}

_CATEGORY_FAILURE_CLASS = {
    "F1": "syntax_error",
    "F2": "dependency_error",
    "F3": "test_failure",
    "F4": "timeout",
}

# Per-category evidence fields to check for coverage
_CATEGORY_EVIDENCE_FIELDS: dict[str, list[str]] = {
    "F1": ["source_file", "error_type", "error_message"],
    "F2": ["failing_package", "pip_failure_subtype"],
    "F3": ["failed_test_ids", "test_error_type", "tests_failed"],
    "F4": ["timeout_duration_min", "orphan_process"],
}


def _collect_log_files(base_dir: Path, subdir: str) -> list[Path]:
    cat_dir = base_dir / subdir
    if not cat_dir.is_dir():
        return []
    files = sorted(
        f for f in cat_dir.iterdir()
        if f.is_file() and f.suffix.lower() == ".log" and not f.name.startswith(".")
    )
    return files


def _analyze_category(
    category: str,
    log_files: list[Path],
    engine,
) -> dict:
    """Parse + analyze one category's log files; return per-category metrics."""
    if not log_files:
        return {"category": category, "total": 0, "skipped": True}

    records: list[LogRecord] = []
    parse_errors = 0
    from parser.log_parser import parse_log_file
    for lf in log_files:
        try:
            r = parse_log_file(lf)
            records.append(r)
        except Exception:
            parse_errors += 1

    reports: list[RCAReport] = []
    rca_errors = 0
    for rec in records:
        try:
            report = engine.analyze_record(rec.to_dict())
            reports.append(report)
        except Exception:
            rca_errors += 1

    total = len(records)
    analyzed = len(reports)

    # Confidence stats
    confidences = [r.rca_confidence for r in reports]
    conf_mean = statistics.mean(confidences) if confidences else 0.0
    conf_median = statistics.median(confidences) if confidences else 0.0
    conf_high = sum(1 for c in confidences if c >= 0.9) / analyzed if analyzed else 0.0
    conf_medium = sum(1 for c in confidences if 0.5 <= c < 0.9) / analyzed if analyzed else 0.0
    conf_low = sum(1 for c in confidences if c < 0.5) / analyzed if analyzed else 0.0

    # Field coverage
    likely_cause_cov = sum(1 for r in reports if r.likely_cause) / analyzed if analyzed else 0.0
    investigation_cov = sum(1 for r in reports if r.suggested_investigation) / analyzed if analyzed else 0.0
    evidence_lines_cov = sum(1 for r in reports if r.primary_evidence_lines) / analyzed if analyzed else 0.0
    limitations_cov = sum(1 for r in reports if r.limitations) / analyzed if analyzed else 0.0

    # Per-category evidence field coverage
    ev_field_coverage: dict[str, float] = {}
    for field in _CATEGORY_EVIDENCE_FIELDS.get(category, []):
        present = sum(
            1 for r in reports
            if r.observed_evidence.get(field) not in (None, [], "")
        )
        ev_field_coverage[field] = present / analyzed if analyzed else 0.0

    # Causal category distribution
    causal_dist: dict[str, int] = {}
    for r in reports:
        causal_dist[r.causal_category] = causal_dist.get(r.causal_category, 0) + 1

    # Failure class agreement (does RCA output match the expected class?)
    expected_class = _CATEGORY_FAILURE_CLASS.get(category, "")
    class_match = sum(1 for r in reports if r.failure_class == expected_class)
    class_match_rate = class_match / analyzed if analyzed else 0.0

    return {
        "category": category,
        "total_logs": total,
        "analyzed": analyzed,
        "parse_errors": parse_errors,
        "rca_errors": rca_errors,
        "confidence": {
            "mean": round(conf_mean, 4),
            "median": round(conf_median, 4),
            "pct_high_ge_0.9": round(conf_high * 100, 1),
            "pct_medium_0.5_0.9": round(conf_medium * 100, 1),
            "pct_low_lt_0.5": round(conf_low * 100, 1),
        },
        "coverage": {
            "likely_cause_nonempty": round(likely_cause_cov * 100, 1),
            "investigation_nonempty": round(investigation_cov * 100, 1),
            "primary_evidence_lines_nonempty": round(evidence_lines_cov * 100, 1),
            "limitations_nonempty": round(limitations_cov * 100, 1),
        },
        "category_evidence_coverage_pct": {
            k: round(v * 100, 1) for k, v in ev_field_coverage.items()
        },
        "causal_distribution": causal_dist,
        "failure_class_match_rate_pct": round(class_match_rate * 100, 1),
    }


def _print_report(results: list[dict], grand_total: int) -> None:
    sep = "=" * 65
    print(f"\n{sep}")
    print("  RCA V1 DATASET-WIDE VALIDATION REPORT")
    print(sep)
    print(f"  Total logs analyzed: {grand_total}")
    print(sep)

    for res in results:
        cat = res["category"]
        if res.get("skipped"):
            print(f"\n[{cat}] — directory not found, skipped.")
            continue

        total = res["total_logs"]
        analyzed = res["analyzed"]
        print(f"\n{'-'*55}")
        print(f"  Category: {cat}  |  Logs: {total}  |  Analyzed: {analyzed}")
        print(f"{'-'*55}")
        if res["parse_errors"]:
            print(f"  [WARN] parse_errors : {res['parse_errors']}")
        if res["rca_errors"]:
            print(f"  [WARN] rca_errors   : {res['rca_errors']}")

        c = res["confidence"]
        print(f"  RCA Confidence  : mean={c['mean']:.3f}  median={c['median']:.3f}")
        print(f"                    high(>=0.9)={c['pct_high_ge_0.9']}%  "
              f"medium(0.5-0.9)={c['pct_medium_0.5_0.9']}%  "
              f"low(<0.5)={c['pct_low_lt_0.5']}%")

        print(f"\n  Field Coverage (% records with non-empty field):")
        cov = res["coverage"]
        print(f"    likely_cause             : {cov['likely_cause_nonempty']}%")
        print(f"    suggested_investigation  : {cov['investigation_nonempty']}%")
        print(f"    primary_evidence_lines   : {cov['primary_evidence_lines_nonempty']}%")
        print(f"    limitations              : {cov['limitations_nonempty']}%")

        ev_cov = res["category_evidence_coverage_pct"]
        if ev_cov:
            print(f"\n  Category-Specific Evidence Coverage:")
            for field, pct in ev_cov.items():
                print(f"    {field:<30}: {pct}%")

        print(f"\n  Causal Category Distribution:")
        for ccat, cnt in sorted(res["causal_distribution"].items(), key=lambda x: -x[1]):
            print(f"    {ccat:<28}: {cnt:>5}  ({100*cnt/analyzed:.1f}%)")

        print(f"\n  Failure Class Match Rate (vs expected): {res['failure_class_match_rate_pct']}%")

    print(f"\n{sep}")
    print("  NOTE: rca_confidence is an evidence-strength indicator, not a")
    print("  probability that the diagnosis is correct. These results measure")
    print("  structural completeness of RCA output, not diagnostic accuracy.")
    print(sep)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="RCA V1 dataset-wide validation against all F1-F4 log categories.",
    )
    ap.add_argument(
        "--base-dir", "-b", default="logs",
        help="Base directory containing F1/, F2/, F3/, F4/ subdirectories. Default: logs",
    )
    ap.add_argument(
        "--json", "-j", default=None,
        help="Optional output path for machine-readable JSON validation report.",
    )
    args = ap.parse_args()

    base_dir = Path(args.base_dir)
    if not base_dir.is_dir():
        print(f"[ERROR] Base directory not found: {base_dir}", file=sys.stderr)
        sys.exit(1)

    engine = get_default_engine()
    results = []
    grand_total = 0

    for category, subdir in _CATEGORY_DIRS.items():
        log_files = _collect_log_files(base_dir, subdir)
        print(f"[{category}] Found {len(log_files)} .log files in {base_dir / subdir}")
        res = _analyze_category(category, log_files, engine)
        results.append(res)
        grand_total += res.get("analyzed", 0)

    _print_report(results, grand_total)

    if args.json:
        report_data = {
            "grand_total_analyzed": grand_total,
            "categories": results,
        }
        out_path = Path(args.json)
        out_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")
        print(f"\nJSON report written to: {out_path}")


if __name__ == "__main__":
    main()
