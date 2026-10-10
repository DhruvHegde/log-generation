"""inspect_rca_samples.py

Read-only inspection script to manually review representative RCA V1 reports.

Selects 2-3 sample .log files from each available category (F1, F2, F3, F4)
and runs them through Parser V2 and the RCA V1 Engine. Handles fallback/unknown
log payload demonstration gracefully if no raw unknown log file exists.

Usage:
    python inspect_rca_samples.py
    python inspect_rca_samples.py --samples-per-cat 2
    python inspect_rca_samples.py --base-dir logs
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Ensure workspace root is in sys.path
_REPO_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(_REPO_ROOT))

from parser.log_parser import parse_log_file, parse_log_text, LogRecord
from rca.engine import get_default_engine
from rca.schema import RCAReport
from run_rca import _format_report_human

_CATEGORIES = ["F1", "F2", "F3", "F4"]


def _collect_samples(base_dir: Path, count_per_cat: int) -> list[tuple[str, Path]]:
    """
    Collect 2-3 sample log files per category directory.
    Returns list of (category_label, file_path) tuples.
    """
    samples: list[tuple[str, Path]] = []
    for cat in _CATEGORIES:
        cat_dir = base_dir / cat
        if not cat_dir.is_dir():
            print(f"[INFO] Category directory missing: {cat_dir}", file=sys.stderr)
            continue
        
        log_files = sorted(
            f for f in cat_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".log" and not f.name.startswith(".")
        )
        selected = log_files[:count_per_cat]
        for lf in selected:
            samples.append((cat, lf))
            
    return samples


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Read-only manual inspection tool for RCA V1 reports."
    )
    parser.add_argument(
        "--base-dir", "-b", default="logs",
        help="Base directory containing category subdirectories (F1, F2, F3, F4). Default: logs",
    )
    parser.add_argument(
        "--samples-per-cat", "-n", type=int, default=2,
        help="Number of log samples to select per category (default: 2, recommended: 2-3).",
    )
    args = parser.parse_args()

    base_dir = Path(args.base_dir)
    if not base_dir.is_dir():
        print(f"[ERROR] Base directory does not exist: {base_dir}", file=sys.stderr)
        sys.exit(1)

    engine = get_default_engine()
    samples = _collect_samples(base_dir, args.samples_per_cat)

    if not samples:
        print(f"[WARN] No .log sample files found under: {base_dir}", file=sys.stderr)

    inspected_records: list[dict[str, str]] = []

    print("============================================================")
    print("      RCA V1 MANUAL REPORT INSPECTION SAMPLES")
    print("============================================================")

    # 1. Process category log file samples
    for idx, (cat_label, file_path) in enumerate(samples, 1):
        try:
            record: LogRecord = parse_log_file(file_path)
            report: RCAReport = engine.analyze_record(record)
            
            print(f"\n--- [SAMPLE #{idx}] Category Directory: {cat_label} ---")
            print(_format_report_human(report, file_path))

            inspected_records.append({
                "sample_id": f"Sample #{idx}",
                "source": file_path.name,
                "category_dir": cat_label,
                "failure_class": report.failure_class,
                "failure_subcategory": report.failure_subcategory or "unknown",
                "causal_category": report.causal_category,
                "confidence": f"{report.rca_confidence:.2f}",
            })
        except Exception as err:
            print(f"[ERROR] Failed to parse/analyze {file_path}: {err}", file=sys.stderr)

    # 2. Check for or demonstrate unknown/fallback example
    unknown_dir = base_dir / "unknown"
    unknown_file: Path | None = None
    if unknown_dir.is_dir():
        unknown_logs = sorted(
            f for f in unknown_dir.iterdir()
            if f.is_file() and f.suffix.lower() == ".log"
        )
        if unknown_logs:
            unknown_file = unknown_logs[0]

    if unknown_file:
        print(f"\n--- [FALLBACK/UNKNOWN SAMPLE] Raw File: {unknown_file.name} ---")
        try:
            record = parse_log_file(unknown_file)
            report = engine.analyze_record(record)
            print(_format_report_human(report, unknown_file))
            inspected_records.append({
                "sample_id": "Fallback Sample",
                "source": unknown_file.name,
                "category_dir": "unknown",
                "failure_class": report.failure_class,
                "failure_subcategory": report.failure_subcategory or "unknown",
                "causal_category": report.causal_category,
                "confidence": f"{report.rca_confidence:.2f}",
            })
        except Exception as err:
            print(f"[ERROR] Failed analyzing unknown file {unknown_file}: {err}", file=sys.stderr)
    else:
        # Demonstrate FallbackAnalyzer on an unrecognized/generic log payload
        print("\n--- [FALLBACK/UNKNOWN DEMONSTRATION] ---")
        print("[INFO] No raw unknown/fallback log file found in dataset; demonstrating FallbackAnalyzer on generic error payload.")
        demo_log_text = "2026-09-28T12:00:00Z ##[error]Process exited unexpectedly with code 137\n2026-09-28T12:00:01Z Out of memory signal received"
        record = parse_log_text(demo_log_text, run_id="demo_unknown")
        report = engine.analyze_record(record)
        print(_format_report_human(report, Path("demo_unknown_fallback.log")))
        inspected_records.append({
            "sample_id": "Fallback Demo",
            "source": "demo_unknown_fallback.log",
            "category_dir": "N/A (synthetic)",
            "failure_class": report.failure_class,
            "failure_subcategory": report.failure_subcategory or "unknown",
            "causal_category": report.causal_category,
            "confidence": f"{report.rca_confidence:.2f}",
        })

    # 3. Compact Summary Table
    print("\n============================================================")
    print("             SUMMARY OF INSPECTED RCA SAMPLES")
    print("============================================================")
    print(f"{'#':<4} {'Source File':<22} {'Folder':<14} {'Failure Class':<18} {'Causal Cat':<22} {'Conf':<6}")
    print("-" * 88)
    for rec in inspected_records:
        print(
            f"{rec['sample_id']:<4} {rec['source']:<22} {rec['category_dir']:<14} "
            f"{rec['failure_class']:<18} {rec['causal_category']:<22} {rec['confidence']:<6}"
        )
    print("============================================================")


if __name__ == "__main__":
    main()
