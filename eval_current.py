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

confusion = Counter()
correct = 0
preds = {}
f4_false_positives = []

for fn, truth in gt.items():
    log_file = raw_dir / fn
    rec = parse_log_file(log_file)
    rep = analyze_record(rec)
    pred = CLASS_TO_F.get(rep.failure_class, 'OOS')
    preds[fn] = (pred, rep.failure_class, rep.failure_subcategory)
    confusion[(truth, pred)] += 1
    if truth == pred:
        correct += 1
    if pred == 'F4' and truth != 'F4':
        f4_false_positives.append((fn, truth, rep.failure_class, rep.failure_subcategory))

total = len(gt)
inscope = [(truth, preds[fn][0]) for fn, truth in gt.items() if truth in ('F1', 'F2', 'F3', 'F4')]
inscope_correct = sum(1 for t, p in inscope if t == p)

print(f'Overall accuracy: {correct}/{total} = {correct/total*100:.1f}%')
print(f'In-scope accuracy: {inscope_correct}/{len(inscope)} = {inscope_correct/len(inscope)*100:.1f}%')
print(f'F4 predicted total: {sum(confusion.get((t, "F4"), 0) for t in ["F1", "F2", "F3", "F4", "OOS"])}')
print(f'F4 correct (true F4): {confusion.get(("F4", "F4"), 0)}')
print(f'F4 false positives: {len(f4_false_positives)}')

cats = ['F1', 'F2', 'F3', 'F4', 'OOS']
print('\nConfusion matrix (truth -> pred):')
header = 'Truth \\ Pred\t' + '\t'.join(cats) + '\tTotal'
print(header)
for t in cats:
    row = [str(confusion.get((t, p), 0)) for p in cats]
    print(f'{t}\t\t' + '\t'.join(row) + f'\t{sum(confusion.get((t, p), 0) for p in cats)}')

print('\nF4 false positives breakdown by truth:')
fp_by_truth = Counter(item[1] for item in f4_false_positives)
for k, v in sorted(fp_by_truth.items()):
    print(f'  {k}: {v}')
