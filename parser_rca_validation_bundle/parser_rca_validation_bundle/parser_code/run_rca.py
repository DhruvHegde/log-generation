"""run_rca.py — RCA V1 command-line interface.

Parses one or more CI/CD log files with Parser V2, then runs
RCA V1 analysis on each record and outputs structured RCA reports.

Usage examples
--------------
# Analyze a single log file (dry-run, print to stdout):
    python run_rca.py --input logs/F1/run_0001.log

# Analyze a single log file, write JSON report:
    python run_rca.py --input logs/F1/run_0001.log --output report.json

# Analyze an entire F1 directory, write NDJSON:
    python run_rca.py --input logs/F1 --output rca_f1.ndjson

# Analyze all four categories:
    python run_rca.py --input logs/F1 --output rca_f1.ndjson
    python run_rca.py --input logs/F2 --output rca_f2.ndjson
    python run_rca.py --input logs/F3 --output rca_f3.ndjson
    python run_rca.py --input logs/F4 --output rca_f4.ndjson

Output formats
--------------
  json   — JSON array of RCA report dicts (default for single file)
  ndjson — newline-delimited JSON, one report per line (default for batch)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure repo root is importable
sys.path.insert(0, str(Path(__file__).parent))

from parser.log_parser import parse_log_file
from rca.engine import get_default_engine
from rca.schema import RCAReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _collect_log_files(input_path: Path) -> list[Path]:
    """Return sorted list of .log files from a file or directory."""
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        files = sorted(
            f for f in input_path.iterdir()
            if f.is_file() and f.suffix.lower() == ".log" and not f.name.startswith(".")
        )
        return files
    raise FileNotFoundError(f"Input path not found: {input_path}")


def _format_report_human(report: RCAReport, log_file: Path) -> str:
    """Format one RCAReport for human-readable console output."""
    lines = [
        f"\n{'='*60}",
        f"  Log file   : {log_file.name}",
        f"  Run ID     : {report.run_id or '—'}",
        f"  Category   : {report.failure_class}  /  {report.failure_subcategory or '—'}",
        f"  Stage      : {report.failed_stage}",
        f"  Step       : {report.failed_step}",
        f"{'='*60}",
        f"  Summary    : {report.summary}",
        f"",
        f"  Causal Category  : {report.causal_category}",
        f"  RCA Confidence   : {report.rca_confidence:.2f}  ({report.confidence_rationale})",
        f"",
        f"  Likely Cause:",
        f"    {report.likely_cause}",
        f"",
    ]

    if report.observed_evidence:
        lines.append("  Observed Evidence:")
        for k, v in report.observed_evidence.items():
            if v not in (None, [], ""):
                lines.append(f"    {k}: {v}")
        lines.append("")

    if report.primary_evidence_lines:
        lines.append("  Primary Evidence Lines:")
        for ln in report.primary_evidence_lines[:5]:
            lines.append(f"    | {ln}")
        if len(report.primary_evidence_lines) > 5:
            lines.append(f"    ... ({len(report.primary_evidence_lines) - 5} more)")
        lines.append("")

    if report.suggested_investigation:
        lines.append("  Suggested Investigation:")
        for i, step in enumerate(report.suggested_investigation, 1):
            lines.append(f"    {i}. {step}")
        lines.append("")

    if report.local_reproduction_command:
        lines.append(f"  Local Reproduction:")
        lines.append(f"    $ {report.local_reproduction_command}")
        lines.append("")

    if report.limitations:
        lines.append("  Limitations:")
        for lim in report.limitations:
            lines.append(f"    - {lim}")

    lines.append(f"{'='*60}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description="RCA V1: Parse CI/CD logs with Parser V2 and run Root Cause Analysis.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--input", "-i", required=True,
        help="Path to a single .log file or a directory of .log files.",
    )
    ap.add_argument(
        "--output", "-o", default=None,
        help="Output file path (.json or .ndjson). If omitted, prints to stdout.",
    )
    ap.add_argument(
        "--format", "-f", choices=["json", "ndjson", "human"], default=None,
        help=(
            "Output format. 'json' = JSON array, 'ndjson' = one JSON object per line, "
            "'human' = readable text. Auto-detected from output file extension if omitted."
        ),
    )
    ap.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print per-file progress to stderr.",
    )
    ap.add_argument(
        "--summary", action="store_true", default=True,
        help="Print a summary table after all files are analyzed (default: on).",
    )
    ap.add_argument(
        "--no-summary", dest="summary", action="store_false",
        help="Suppress summary table.",
    )

    args = ap.parse_args()

    input_path = Path(args.input)
    try:
        log_files = _collect_log_files(input_path)
    except FileNotFoundError as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        sys.exit(1)

    if not log_files:
        print(f"[ERROR] No .log files found at: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Determine output format
    fmt = args.format
    if fmt is None and args.output:
        ext = Path(args.output).suffix.lower()
        if ext == ".ndjson":
            fmt = "ndjson"
        elif ext == ".json":
            fmt = "json"
        else:
            fmt = "ndjson" if len(log_files) > 1 else "json"
    elif fmt is None:
        fmt = "human"

    print(
        f"[run_rca.py] {len(log_files)} log file(s) | format={fmt} | "
        f"output={'stdout' if not args.output else args.output}",
        file=sys.stderr,
    )

    engine = get_default_engine()
    reports: list[tuple[Path, RCAReport]] = []

    for lf in log_files:
        if args.verbose:
            print(f"  Parsing {lf.name} ...", end="", flush=True, file=sys.stderr)
        try:
            record = parse_log_file(lf)
            report = engine.analyze_record(record.to_dict())
            reports.append((lf, report))
            if args.verbose:
                print(
                    f" {report.failure_class} | conf={report.rca_confidence:.2f}",
                    file=sys.stderr,
                )
        except Exception as exc:
            print(f"\n  [WARN] Failed on {lf.name}: {exc}", file=sys.stderr)

    # Build output
    if fmt == "human":
        output_lines = [_format_report_human(rpt, lf) for lf, rpt in reports]
        output_text = "\n".join(output_lines)
    elif fmt == "ndjson":
        output_text = "\n".join(
            json.dumps({"log_file": lf.name, **rpt.to_dict()}, default=str)
            for lf, rpt in reports
        )
    else:  # json
        output_text = json.dumps(
            [{"log_file": lf.name, **rpt.to_dict()} for lf, rpt in reports],
            indent=2,
            default=str,
        )

    if args.output:
        Path(args.output).write_text(output_text, encoding="utf-8")
        print(f"[run_rca.py] Wrote {len(reports)} reports → {args.output}", file=sys.stderr)
    else:
        print(output_text)

    # Summary table
    if args.summary and len(reports) > 1:
        from collections import Counter
        class_counts = Counter(rpt.failure_class for _, rpt in reports)
        causal_counts = Counter(rpt.causal_category for _, rpt in reports)
        confs = [rpt.rca_confidence for _, rpt in reports]
        import statistics as stats

        print(f"\n{'─'*55}", file=sys.stderr)
        print(f"  RCA Summary  ({len(reports)} records)", file=sys.stderr)
        print(f"{'─'*55}", file=sys.stderr)
        print("  Failure class distribution:", file=sys.stderr)
        for fc, cnt in class_counts.most_common():
            print(f"    {fc:<25}: {cnt:>5}", file=sys.stderr)
        print("  Causal category distribution:", file=sys.stderr)
        for cc, cnt in causal_counts.most_common():
            print(f"    {cc:<25}: {cnt:>5}", file=sys.stderr)
        print(
            f"  Confidence  mean={stats.mean(confs):.3f}  "
            f"median={stats.median(confs):.3f}  "
            f"min={min(confs):.2f}  max={max(confs):.2f}",
            file=sys.stderr,
        )
        print(f"{'─'*55}", file=sys.stderr)


if __name__ == "__main__":
    main()
