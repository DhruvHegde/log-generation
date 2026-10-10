"""parse_logs.py — CLI for the CI/CD log parser.

Usage examples
--------------
# Parse a single log file:
    python parse_logs.py --input logs/F1/run_0001.log --output parsed_single.csv

# Parse an entire directory:
    python parse_logs.py --input logs/F1 --output parsed_f1.csv

# Provide a known failure_type for all logs in the batch:
    python parse_logs.py --input logs/F1 --output parsed_f1.csv --failure-type syntax_error

# Dry-run: print the parsed record for a single file without writing:
    python parse_logs.py --input logs/F1/run_0001.log --dry-run
"""

import argparse
import csv
import json
import sys
from pathlib import Path

# Add repo root to path so `parser` package is importable from anywhere.
sys.path.insert(0, str(Path(__file__).parent))

from parser.log_parser import parse_log_file, LogRecord


# ---------------------------------------------------------------------------
# Column order for the CSV output
# ---------------------------------------------------------------------------

COLUMNS = [
    "run_id",
    "timestamp",
    "step_name",
    "stage",
    "duration",
    "status",
    "error_type",
    "error_message",
    "log_text",
    "failure_type",
    # enrichment columns
    "line_number",
    "file_path",
    "matched_line",
    "exit_code",
    "python_version",
]


def _record_to_row(record: LogRecord) -> dict:
    """Convert a LogRecord to a CSV-ready dict with columns in the right order."""
    d = record.to_dict()
    # Ensure every column is present even if the dataclass gains new fields
    return {col: d.get(col, None) for col in COLUMNS}


def _collect_log_files(input_path: Path) -> list[Path]:
    """Return a sorted list of .log files from a file or directory."""
    if input_path.is_file():
        return [input_path]
    if input_path.is_dir():
        files = sorted(input_path.glob("run_*.log"))
        if not files:
            # Fall back to any .log file in the directory
            files = sorted(input_path.glob("*.log"))
        return files
    raise FileNotFoundError(f"Input path not found: {input_path}")


def parse_batch(
    log_files: list[Path],
    *,
    failure_type: str | None = None,
    verbose: bool = False,
) -> list[LogRecord]:
    """Parse a list of log files and return a list of LogRecord objects."""
    records: list[LogRecord] = []
    for log_file in log_files:
        if verbose:
            print(f"  Parsing {log_file.name} ...", end="", flush=True)
        record = parse_log_file(log_file, failure_type=failure_type)
        records.append(record)
        if verbose:
            print(f" {record.status} / {record.error_type or '—'}")
    return records


def write_csv(records: list[LogRecord], output_path: Path) -> None:
    """Write a list of LogRecord objects to a CSV file."""
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            writer.writerow(_record_to_row(record))


def print_stats(records: list[LogRecord]) -> None:
    """Print a summary statistics block to stdout."""
    total = len(records)
    if total == 0:
        print("No records parsed.")
        return

    statuses       = {}
    error_types    = {}
    failure_types  = {}
    no_error       = 0
    no_step        = 0

    for r in records:
        statuses[r.status or "None"]          = statuses.get(r.status or "None", 0) + 1
        failure_types[r.failure_type or "None"] = failure_types.get(r.failure_type or "None", 0) + 1
        if r.error_type:
            error_types[r.error_type] = error_types.get(r.error_type, 0) + 1
        else:
            no_error += 1
        if not r.step_name:
            no_step += 1

    print(f"\n{'='*50}")
    print(f"  PARSER STATISTICS  ({total} logs)")
    print(f"{'='*50}")
    print(f"\nStatus distribution:")
    for k, v in sorted(statuses.items(), key=lambda x: -x[1]):
        print(f"  {k:<12}: {v:>5}  ({100*v/total:.1f}%)")

    print(f"\nError type distribution:")
    for k, v in sorted(error_types.items(), key=lambda x: -x[1]):
        print(f"  {k:<25}: {v:>5}  ({100*v/total:.1f}%)")
    if no_error:
        print(f"  {'(no error detected)':<25}: {no_error:>5}  ({100*no_error/total:.1f}%)")

    print(f"\nFailure type distribution:")
    for k, v in sorted(failure_types.items(), key=lambda x: -x[1]):
        print(f"  {k:<20}: {v:>5}  ({100*v/total:.1f}%)")

    has_line = sum(1 for r in records if r.line_number is not None)
    has_file = sum(1 for r in records if r.file_path is not None)
    has_dur  = sum(1 for r in records if r.duration  is not None)
    print(f"\nOptional field coverage:")
    print(f"  line_number  : {has_line}/{total} ({100*has_line/total:.1f}%)")
    print(f"  file_path    : {has_file}/{total} ({100*has_file/total:.1f}%)")
    print(f"  duration     : {has_dur}/{total}  ({100*has_dur/total:.1f}%)")
    print(f"  step (none)  : {no_step}/{total}")
    print(f"{'='*50}\n")


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Parse GitHub Actions CI/CD log files into structured CSV.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument(
        "--input", "-i", required=True,
        help="Path to a single .log file or a directory containing run_*.log files.",
    )
    ap.add_argument(
        "--output", "-o", default=None,
        help="Output CSV file path.  Required unless --dry-run is set.",
    )
    ap.add_argument(
        "--failure-type", default=None,
        help=(
            "Override failure_type for all logs in this batch "
            "(e.g. 'syntax_error', 'dependency_error').  "
            "If omitted, the parser infers it from the detected error."
        ),
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="Parse the first log file found and print the result; do not write CSV.",
    )
    ap.add_argument(
        "--verbose", "-v", action="store_true",
        help="Print per-file progress.",
    )
    ap.add_argument(
        "--stats", action="store_true", default=True,
        help="Print summary statistics after parsing (default: on).",
    )
    ap.add_argument(
        "--no-stats", dest="stats", action="store_false",
        help="Suppress summary statistics.",
    )

    args = ap.parse_args()

    input_path = Path(args.input)
    log_files  = _collect_log_files(input_path)

    if not log_files:
        print(f"No log files found at: {input_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(log_files)} log file(s) under: {input_path}")

    # --- dry-run: parse the first file and dump the result ---
    if args.dry_run:
        record = parse_log_file(log_files[0], failure_type=args.failure_type)
        d = record.to_dict()
        # Print without the full log_text (too long)
        d_display = {k: v for k, v in d.items() if k != "log_text"}
        d_display["log_text"] = f"<{len(record.log_text)} chars>"
        print("\nParsed record:")
        for k, v in d_display.items():
            print(f"  {k:<16}: {v!r}")
        return

    # --- full batch parse ---
    records = parse_batch(
        log_files,
        failure_type=args.failure_type,
        verbose=args.verbose,
    )

    if args.stats:
        print_stats(records)

    if args.output:
        output_path = Path(args.output)
        write_csv(records, output_path)
        print(f"Wrote {len(records)} records -> {output_path}")
    else:
        print("No --output specified; CSV not written.", file=sys.stderr)


if __name__ == "__main__":
    main()
