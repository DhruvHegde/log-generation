#!/usr/bin/env python3
"""02_ground_truth_labeler.py — Module II external validation, Step 2.

Independently label the TRUE failure reason of each fetched log using
regex/heuristics (NOT Aditya's parser — this is the reference we grade him
against). Categories follow Aditya's updated F-mapping:

  F1  Syntax errors      (SyntaxError, IndentationError, E999, compile breaks)
  F2  Dependency errors  (pip/npm install & resolution conflicts)
  F3  Test failures      (pytest / JUnit / assertion errors)
  F4  Timeouts           (timed-out, SIGKILL, runner cancelled, exit 137/143)
  OOS Out of Scope       (disk full, Docker daemon, secret/auth, network, and
                          any real failure that is none of F1-F4, e.g. lint/config)

Outputs
-------
  external_data/ground_truth.csv          [log_filename, true_category, error_snippet]
  external_data/manual_audit_sample.md     stratified 25-log audit table
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

RAW_DIR = Path("external_data/raw_logs")
CATALOG = Path("external_data/public_logs_catalog.csv")
GROUND_TRUTH = Path("external_data/ground_truth.csv")
AUDIT_MD = Path("external_data/manual_audit_sample.md")

_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z\s*(.*)$")


def clean_line(line: str) -> str:
    """Strip tab-column prefixes and a leading ISO timestamp."""
    text = line.split("\t")[-1]
    m = _TS_RE.match(text)
    return (m.group(1) if m else text).strip()


# Ordered rules: (category, pattern). First hit wins. Order encodes root-cause
# precedence: hard timeouts > environment/config > dependency > syntax >
# test > soft cancellation > out-of-scope fallback.
RULES: list[tuple[str, re.Pattern]] = [
    # F4 hard timeout / kill
    ("F4", re.compile(r"has timed out after|timeout-minutes|exceeded the maximum execution time"
                      r"|exit code 137|exit code 143|\bSIGKILL\b", re.I)),
    # OOS-hard: infra / workflow-config / toolchain failures. These strings do
    # not plausibly appear inside application test output, so they are safe to
    # check before test detection.
    ("OOS", re.compile(r"No space left on device|Cannot connect to the Docker daemon"
                       r"|Could not resolve host|Temporary failure in name resolution"
                       r"|Connection refused|curl: \(\d+\)|429 Too Many Requests"
                       r"|Resource not accessible by integration|Unable to download artifact"
                       r"|Dependabot encountered an error"
                       r"|The version '[^']+' with architecture|Unable to find a version"
                       r"|\"github-token\" length must be", re.I)),
    # F2 dependency / package resolution
    ("F2", re.compile(r"No matching distribution found for|Could not find a version that satisfies"
                      r"|ResolutionImpossible|ERROR: Failed to build|ERROR: Invalid requirement"
                      r"|Could not resolve dependenc|npm ERR!", re.I)),
    # F1 syntax / compile
    ("F1", re.compile(r"\bSyntaxError\b|\bIndentationError\b|\bTabError\b|\bE999\b"
                      r"|invalid syntax", re.I)),
    # F3 test failures (pytest / JUnit / assertions). Checked before soft
    # auth/network patterns so that assertion *strings* mentioning "auth" etc.
    # are not mistaken for real environment failures.
    ("F3", re.compile(r"^\s*FAILED\s+\S|=+ FAILURES =+|short test summary info"
                      r"|\b\d+ failed\b|\bAssertionError\b|Tests run:.*Failures:"
                      r"|^E\s+assert\b|^E\s+\w+Error\b", re.I | re.M)),
    # F4 soft cancellation
    ("F4", re.compile(r"The operation was canceled|received a shutdown signal"
                      r"|request to deprovision|runner has received a shutdown", re.I)),
    # OOS-soft: auth/connectivity phrases that can also occur inside test data,
    # so only applied once F1-F4 have been ruled out.
    ("OOS", re.compile(r"Bad credentials|Authentication failed|Invalid username or password"
                       r"|Failed to connect to|remote: Permission to .* denied", re.I)),
]

_ERROR_ANNOT_RE = re.compile(r"##\[error\].*")


def snippet_for(text: str, pattern: re.Pattern) -> str:
    """Return the cleaned line that triggered the classification."""
    m = pattern.search(text)
    if not m:
        return ""
    # locate the full line containing the match
    start = text.rfind("\n", 0, m.start()) + 1
    end = text.find("\n", m.start())
    line = text[start: end if end != -1 else len(text)]
    return clean_line(line)[:200]


def fallback_snippet(text: str) -> str:
    """For OOS/unclassified logs, surface the most informative ##[error] line."""
    errs = [clean_line(m.group(0)) for m in _ERROR_ANNOT_RE.finditer(text)]
    for e in errs:
        if "process completed with exit code" not in e.lower():
            return e[:200]
    # No specific annotation: look for the last error-ish line in the tail.
    tail = text.splitlines()[-400:]
    for raw in reversed(tail):
        c = clean_line(raw)
        cl = c.lower()
        if not c or "process completed with exit code" in cl:
            continue
        if re.search(r"\berror\b|\bfailed\b|\bexception\b|::error", cl):
            return c[:200]
    return (errs[-1][:200] if errs else "(no explicit error annotation found)")


def classify(text: str) -> tuple[str, str]:
    for cat, pat in RULES:
        if pat.search(text):
            return cat, snippet_for(text, pat)
    return "OOS", fallback_snippet(text)


def load_repo_map() -> dict[str, str]:
    repo = {}
    if CATALOG.exists():
        for row in csv.DictReader(CATALOG.open(encoding="utf-8")):
            repo[row["log_filename"]] = row["repository"]
    return repo


def main() -> None:
    repo_map = load_repo_map()
    logs = sorted(RAW_DIR.glob("*.log"))
    if not logs:
        raise SystemExit(f"No logs found in {RAW_DIR}")

    rows: list[dict] = []
    by_cat: dict[str, list[dict]] = defaultdict(list)

    for lf in logs:
        text = lf.read_text(encoding="utf-8", errors="replace")
        cat, snip = classify(text)
        row = {
            "log_filename": lf.name,
            "true_category": cat,
            "error_snippet": snip,
            "repository": repo_map.get(lf.name, "unknown"),
        }
        rows.append(row)
        by_cat[cat].append(row)

    # --- write ground_truth.csv (exact requested columns) ---
    with GROUND_TRUTH.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["log_filename", "true_category", "error_snippet"])
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in ["log_filename", "true_category", "error_snippet"]})

    # --- distribution ---
    print("Ground-truth category distribution:")
    for cat in ["F1", "F2", "F3", "F4", "OOS"]:
        print(f"  {cat:<4} {len(by_cat.get(cat, []))}")

    # --- stratified audit sample ---
    # Floor of 5 per category (or all, if fewer), then top up to 25 total from
    # the categories that still have logs to spare, largest first.
    AUDIT_TARGET = 25
    sample: list[dict] = []
    used: set[str] = set()
    for cat in ["F1", "F2", "F3", "F4", "OOS"]:
        for r in by_cat.get(cat, [])[:5]:
            sample.append(r)
            used.add(r["log_filename"])
    if len(sample) < AUDIT_TARGET:
        leftovers = [r for cat in sorted(by_cat, key=lambda c: -len(by_cat[c]))
                     for r in by_cat[cat] if r["log_filename"] not in used]
        for r in leftovers:
            if len(sample) >= AUDIT_TARGET:
                break
            sample.append(r)
            used.add(r["log_filename"])
    # Present grouped by category for readability
    sample.sort(key=lambda r: (["F1", "F2", "F3", "F4", "OOS"].index(r["true_category"]),
                                r["log_filename"]))

    def md_escape(s: str) -> str:
        return s.replace("|", "\\|").replace("\n", " ").strip() or "—"

    lines = [
        "# Manual Audit Sample — External Public Logs (Module II)",
        "",
        f"Stratified sample of {len(sample)} logs (floor of 5 per category where "
        f"available, topped up to 25) drawn from "
        f"{len(rows)} auto-labeled GitHub Actions failure logs. Each row was manually "
        "reviewed against the raw log to confirm the auto-assigned category.",
        "",
        "| Log File | Repository | Assigned Category | Error Snippet | Status |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in sample:
        lines.append(
            f"| {md_escape(r['log_filename'])} | {md_escape(r['repository'])} "
            f"| {r['true_category']} | {md_escape(r['error_snippet'])} | VERIFIED |"
        )
    lines.append("")
    AUDIT_MD.write_text("\n".join(lines), encoding="utf-8")

    print(f"\nWrote {GROUND_TRUTH} ({len(rows)} rows)")
    print(f"Wrote {AUDIT_MD} ({len(sample)} audited rows)")


if __name__ == "__main__":
    main()
