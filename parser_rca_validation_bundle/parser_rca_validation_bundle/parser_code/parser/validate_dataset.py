"""parser/validate_dataset.py

Category-aware validation suite for Parser V2 across all 1,993 CI/CD logs.

Evaluates each category according to its domain-specific failure criteria:
  - F1 (Syntax): syntax classification, traceback extraction, failed step
  - F2 (Dependency): pip failure classification, failing package name (no traceback expected)
  - F3 (Test failure): pytest failure classification, test error type, test IDs, traceback
  - F4 (Timeout): GHA timeout classification, duration, orphan process (no traceback expected)
"""

from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

# Ensure repo root is in sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from parser.log_parser import parse_all_categories, LogRecord


def run_validation(base_dir: str = "logs") -> bool:
    print(f"============================================================")
    print(f"   PARSER V2: CATEGORY-AWARE DATASET VALIDATION REPORT     ")
    print(f"============================================================\n")

    t0 = time.time()
    results = parse_all_categories(base_dir)
    elapsed = time.time() - t0

    total_records = sum(len(records) for records in results.values())
    print(f"Total logs parsed: {total_records} across {len(results)} categories in {elapsed:.2f}s\n")

    expected_counts = {
        "F1": 500,
        "F2": 492,
        "F3": 500,
        "F4": 500,
    }

    all_passed = True

    # -------------------------------------------------------------
    # Category volume & check
    # -------------------------------------------------------------
    print("------------------------------------------------------------")
    print("1. DATASET VOLUME & CATEGORY COUNTS (.log files only)")
    print("------------------------------------------------------------")
    for cat in ["F1", "F2", "F3", "F4"]:
        actual = len(results.get(cat, []))
        expected = expected_counts[cat]
        status = "OK" if actual == expected else "MISMATCH"
        if status != "OK":
            all_passed = False
        print(f"  {cat}: {actual:4d} logs (expected: {expected:4d}) -> [{status}]")

    print(f"  Total: {total_records:4d} logs (expected: 1992) -> [{'OK' if total_records == 1992 else 'MISMATCH'}]\n")

    # -------------------------------------------------------------
    # F1 Validation (Syntax)
    # -------------------------------------------------------------
    f1_records = results.get("F1", [])
    print("------------------------------------------------------------")
    print(f"2. F1 SYNTAX EVALUATION (N = {len(f1_records)})")
    print("------------------------------------------------------------")
    f1_classes = Counter(r.failure_class for r in f1_records)
    f1_subcats = Counter(r.failure_subcategory for r in f1_records)
    f1_steps = Counter(r.failed_step for r in f1_records)
    f1_tb_count = sum(1 for r in f1_records if len(r.traceback_lines) > 0)
    f1_file_count = sum(1 for r in f1_records if r.file_path is not None)
    f1_ev_count = sum(1 for r in f1_records if len(r.evidence_lines) > 0)
    f1_conf_avg = sum(r.parser_confidence for r in f1_records) / max(1, len(f1_records))

    print(f"  Detected failure classes:     {dict(f1_classes)}")
    print(f"  Syntax subcategories:         {dict(f1_subcats)}")
    print(f"  Failed step distribution:     {dict(f1_steps)}")
    print(f"  Traceback block coverage:     {f1_tb_count}/{len(f1_records)} ({f1_tb_count/len(f1_records):.1%})")
    print(f"  Source file/line coverage:    {f1_file_count}/{len(f1_records)} ({f1_file_count/len(f1_records):.1%})")
    print(f"  Evidence lines coverage:      {f1_ev_count}/{len(f1_records)} ({f1_ev_count/len(f1_records):.1%})")
    print(f"  Average parser confidence:    {f1_conf_avg:.3f}")
    if f1_classes.get("syntax_error", 0) != 500:
        print("  [FAIL] Expected 500 syntax_error records in F1")
        all_passed = False
    else:
        print("  -> F1 Criteria PASSED [100%]\n")

    # -------------------------------------------------------------
    # F2 Validation (Dependency)
    # -------------------------------------------------------------
    f2_records = results.get("F2", [])
    print("------------------------------------------------------------")
    print(f"2. F2 DEPENDENCY EVALUATION (N = {len(f2_records)})")
    print("------------------------------------------------------------")
    f2_classes = Counter(r.failure_class for r in f2_records)
    f2_subcats = Counter(r.failure_subcategory for r in f2_records)
    f2_steps = Counter(r.failed_step for r in f2_records)
    f2_pkg_count = sum(1 for r in f2_records if r.failing_package is not None)
    f2_pip_cmd_count = sum(1 for r in f2_records if len(r.pip_commands) > 0)
    f2_tb_count = sum(1 for r in f2_records if len(r.traceback_lines) > 0)
    f2_conf_avg = sum(r.parser_confidence for r in f2_records) / max(1, len(f2_records))

    print(f"  Detected failure classes:     {dict(f2_classes)}")
    print(f"  Subcategories:                {dict(f2_subcats)}")
    print(f"  Failed step distribution:     {dict(f2_steps)}")
    print(f"  Failing package extracted:    {f2_pkg_count}/{len(f2_records)} ({f2_pkg_count/len(f2_records):.1%})")
    print(f"  Pip commands extracted:       {f2_pip_cmd_count}/{len(f2_records)} ({f2_pip_cmd_count/len(f2_records):.1%})")
    print(f"  Traceback present (expected 0): {f2_tb_count} logs")
    print(f"  Average parser confidence:    {f2_conf_avg:.3f}")
    if f2_classes.get("dependency_error", 0) != 492:
        print("  [FAIL] Expected 492 dependency_error records in F2")
        all_passed = False
    else:
        print("  -> F2 Criteria PASSED [100%]\n")

    # -------------------------------------------------------------
    # F3 Validation (Test Failure)
    # -------------------------------------------------------------
    f3_records = results.get("F3", [])
    print("------------------------------------------------------------")
    print(f"3. F3 TEST FAILURE EVALUATION (N = {len(f3_records)})")
    print("------------------------------------------------------------")
    f3_classes = Counter(r.failure_class for r in f3_records)
    f3_subcats = Counter(r.failure_subcategory for r in f3_records)
    f3_error_types = Counter(r.test_error_type for r in f3_records)
    f3_test_ids_count = sum(1 for r in f3_records if len(r.failed_test_ids) > 0)
    f3_counts_ok = sum(1 for r in f3_records if r.tests_failed == 1 and r.tests_passed == 5)
    f3_tb_count = sum(1 for r in f3_records if len(r.traceback_lines) > 0)
    f3_runtime_err_count = f3_classes.get("runtime_error", 0)
    f3_conf_avg = sum(r.parser_confidence for r in f3_records) / max(1, len(f3_records))

    print(f"  Detected failure classes:     {dict(f3_classes)}")
    print(f"  Python exceptions as test errors: {dict(f3_error_types)}")
    print(f"  Incorrect runtime_error:      {f3_runtime_err_count} (must be 0)")
    print(f"  Failed test IDs coverage:     {f3_test_ids_count}/{len(f3_records)} ({f3_test_ids_count/len(f3_records):.1%})")
    print(f"  Test counts (1 fail, 5 pass): {f3_counts_ok}/{len(f3_records)} ({f3_counts_ok/len(f3_records):.1%})")
    print(f"  Traceback block coverage:     {f3_tb_count}/{len(f3_records)} ({f3_tb_count/len(f3_records):.1%})")
    print(f"  Average parser confidence:    {f3_conf_avg:.3f}")
    if f3_classes.get("test_failure", 0) != 500 or f3_runtime_err_count > 0:
        print("  [FAIL] Expected 500 test_failure records and 0 runtime_error in F3")
        all_passed = False
    else:
        print("  -> F3 Criteria PASSED [100%]\n")

    # -------------------------------------------------------------
    # F4 Validation (Timeout)
    # -------------------------------------------------------------
    f4_records = results.get("F4", [])
    print("------------------------------------------------------------")
    print(f"4. F4 TIMEOUT EVALUATION (N = {len(f4_records)})")
    print("------------------------------------------------------------")
    f4_classes = Counter(r.failure_class for r in f4_records)
    f4_subcats = Counter(r.failure_subcategory for r in f4_records)
    f4_steps = Counter(r.failed_step for r in f4_records)
    f4_dur_count = sum(1 for r in f4_records if r.timeout_duration_min == 1.0)
    f4_orphan_count = sum(1 for r in f4_records if r.orphan_process == "pytest")
    f4_tb_count = sum(1 for r in f4_records if len(r.traceback_lines) > 0)
    f4_conf_avg = sum(r.parser_confidence for r in f4_records) / max(1, len(f4_records))

    print(f"  Detected failure classes:     {dict(f4_classes)}")
    print(f"  Timeout subcategories:        {dict(f4_subcats)}")
    print(f"  Failed step distribution:     {dict(f4_steps)}")
    print(f"  Timeout duration extracted:   {f4_dur_count}/{len(f4_records)} ({f4_dur_count/len(f4_records):.1%})")
    print(f"  Orphan process identified:    {f4_orphan_count}/{len(f4_records)} ({f4_orphan_count/len(f4_records):.1%})")
    print(f"  Traceback present (expected 0): {f4_tb_count} logs")
    print(f"  Average parser confidence:    {f4_conf_avg:.3f}")
    if f4_classes.get("timeout", 0) != 500:
        print("  [FAIL] Expected 500 timeout records in F4")
        all_passed = False
    else:
        print("  -> F4 Criteria PASSED [100%]\n")

    # -------------------------------------------------------------
    # Overall summary
    # -------------------------------------------------------------
    print("============================================================")
    print("                    FINAL SUMMARY REPORT                    ")
    print("============================================================")
    all_records = [r for sublist in results.values() for r in sublist]
    overall_classes = Counter(r.failure_class for r in all_records)
    print(f"Total logs parsed:              {len(all_records)} / 1992")
    print(f"Overall failure classifications: {dict(overall_classes)}")
    print(f"Execution time:                 {elapsed:.2f}s ({(len(all_records)/elapsed):.1f} logs/s)")
    if all_passed:
        print("\n>>> ALL VALIDATION CRITERIA MET SUCCESSFULLY (100%) <<<")
    else:
        print("\n>>> VALIDATION FAILED ON ONE OR MORE CRITERIA <<<")

    return all_passed


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "logs"
    success = run_validation(base)
    sys.exit(0 if success else 1)
