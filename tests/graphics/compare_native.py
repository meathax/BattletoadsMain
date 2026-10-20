"""Save exact before/after raster preservation evidence for two native runs.

This proves equivalence between the named runs, not accuracy against MAME.
Both complete run receipts must succeed and use the same input journal.
"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


parser = argparse.ArgumentParser()
parser.add_argument('reference', type=Path)
parser.add_argument('candidate', type=Path)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
receipts = []
retained_folders = []
inputs = []
for folder in (args.reference, args.candidate):
    receipt_path = root/'tests/graphics/evidence/native'/folder.name/'receipt.json'
    receipt = json.loads(receipt_path.read_text())
    if receipt['exit_code'] or receipt.get('requested_frames', 0) < 128:
        raise SystemExit('A successful 128-frame receipt is required: ' + str(receipt_path))
    receipts.append({'path': str(receipt_path), 'sha256': sha(receipt_path)})
    retained_folders.append(receipt_path.parent)
    inputs.append(receipt['input_journal']['sha256'])
    if sha(receipt_path.parent/'inputs.txt') != inputs[-1]:
        raise SystemExit('Retained journal differs from its receipt')
if inputs[0] != inputs[1]:
    raise SystemExit('Input journals differ')
comparisons = []
failures = []
for kind in ('frames', 'frames-pre'):
    left = {f.name: f for f in (retained_folders[0]/kind).glob('*.ppm')}
    right = {f.name: f for f in (retained_folders[1]/kind).glob('*.ppm')}
    if not left and not right:
        failures.append('Raster inventory empty: '+kind)
        continue
    if not left or left.keys() != right.keys():
        failures.append('Raster inventory differs: ' + kind)
    for name in sorted(left.keys() & right.keys()):
        before, after = sha(left[name]), sha(right[name])
        comparisons.append({'kind': kind, 'name': name, 'reference_sha256': before,
                            'candidate_sha256': after, 'equal': before == after})
        if before != after:
            failures.append(kind + '/' + name)
if len(comparisons)<24:
    failures.append('Expected at least 24 retained rasters from the 128-frame replay')
result = {'scope': 'Exact raster preservation between successful 128-frame native runs; not MAME equivalence',
          'reference': str(args.reference), 'candidate': str(args.candidate),
          'run_receipts': receipts, 'input_journal_sha256': inputs[1],
          'comparisons': comparisons, 'failures': failures, 'exit_code': int(bool(failures))}
out = root/'tests/graphics/evidence/native'/args.candidate.name/'raster_comparison.json'
out.write_text(json.dumps(result, indent=2))
print(json.dumps({'comparisons': len(comparisons), 'failures': failures,
                  'receipt': str(out)}, indent=2))
raise SystemExit(bool(failures))
