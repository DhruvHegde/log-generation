import sys, csv, json
from collections import Counter
from pathlib import Path

sys.path.insert(0, '.')
from parser.log_parser import parse_log_file
from rca.engine import analyze_record

ext_data = Path('parser_rca_validation_bundle/parser_rca_validation_bundle/external_data')
raw_dir = ext_data / 'raw_logs'
gt_path = ext_data / 'ground_truth.csv'

with open(gt_path, encoding='utf-8') as f:
    gt = {r['log_filename']: r['true_category'] for r in csv.DictReader(f)}

CLASS_TO_F = {
    'syntax_error': 'F1',
    'dependency_error': 'F2',
    'test_failure': 'F3',
    'timeout': 'F4',
    'runtime_error': 'OOS',
    'unknown': 'OOS',
    None: 'OOS',
}

f4_fps = []
print("Auditing logs...")
for fn, truth in gt.items():
    if truth == 'F4':
        continue
    log_file = raw_dir / fn
    rec = parse_log_file(log_file)
    if rec.failure_class == 'timeout':
        f4_fps.append((fn, truth, rec))

print(f"Total False F4 Predictions: {len(f4_fps)}")
print(f"Breakdown: {Counter(item[1] for item in f4_fps)}")

for fn, truth, rec in f4_fps:
    has_explicit_timeout = "has timed out" in rec.log_text.lower() or "timeout-minutes" in rec.log_text.lower()
    has_cancel_msg = "operation was canceled" in rec.log_text.lower() or "job cancelled" in rec.log_text.lower()
    has_pytest_summary = len(rec.failed_test_ids) > 0 or rec.tests_failed is not None or "FAILED " in rec.log_text
    
    print(f"\n[FP] {fn} | GT: {truth} | Subcat: {rec.failure_subcategory}")
    print(f"     Failed Test IDs: {rec.failed_test_ids}")
    print(f"     Evidence lines: {rec.evidence_lines}")
    print(f"     Explicit timeout text? {has_explicit_timeout} | Cancel msg? {has_cancel_msg} | Pytest failure evidence? {has_pytest_summary}")
