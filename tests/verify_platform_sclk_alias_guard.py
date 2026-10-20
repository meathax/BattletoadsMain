"""Execute the exact alias-validation Tcl with positive/negative collections."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from prepare_platform_io_sclk_alias import ALIAS_PROC, transform

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--candidate', type=Path, required=True)
args = parser.parse_args()
directory = args.candidate.resolve()
manifest_path = directory / 'manifest.json'
manifest = json.loads(manifest_path.read_text())
raw = (ROOT / 'rtl/bt_platform_io.sdc').read_bytes()
candidate = directory / 'rtl/bt_platform_io.sdc'
assert transform(raw) == candidate.read_bytes()
sha = lambda data: hashlib.sha256(data).hexdigest()
assert manifest['old_sha256'] == sha(raw) and manifest['new_sha256'] == sha(candidate.read_bytes())
base = ['mcp23009|i2c|I2C_CLOCK', 'mcp23009|i2c|SCLK']
clone = 'mcp23009|i2c|SCLK~DUPLICATE'
positives = [base, base + [clone], base[::-1], [n.replace('mcp23009|i2c|', 'mcp23009:mcp23009|i2c:i2c|') for n in base + [clone]]]
negatives = [[], [base[0]], [base[1]], [base[0], clone], base + [base[0]], base + [clone, clone],
             base + ['mcp23009|i2c|I2C_CLOCK~DUPLICATE'], base + [clone + '1'],
             base + ['mcp23009|i2c|ACK'], base + ['other|i2c|SCLK'], base + ['SCLK']]
lines = [ALIAS_PROC]
for collection in positives:
    expression = '[list ' + ' '.join('{' + n + '}' for n in collection) + ']'
    lines += [f'if {{[catch {{bt_platform_validate_scl_names {expression}}} reason]}} {{error "positive failed: $reason"}}']
for collection in negatives:
    expression = '[list ' + ' '.join('{' + n + '}' for n in collection) + ']'
    lines += [f'if {{![catch {{bt_platform_validate_scl_names {expression}}}]}} {{error {{negative accepted}}}}']
lines += [f'puts {{ALIAS_GUARD_PASS positives={len(positives)} negatives={len(negatives)}}}']
script = directory / 'alias_guard_test.tcl'
script.write_text('\n'.join(lines) + '\n')
command = ['D:/q17/quartus/bin64/tclsh86.exe', str(script)]
result = subprocess.run(command, capture_output=True, text=True)
(directory / 'alias_guard.log').write_text(result.stdout + result.stderr)
assert result.returncode == 0 and result.stdout.strip() == f'ALIAS_GUARD_PASS positives={len(positives)} negatives={len(negatives)}', result.stdout + result.stderr
manifest.update(status='GUARD_PASS', guard_positive_cases=len(positives), guard_negative_cases=len(negatives),
                guard_command=command, guard_log_sha256=sha((directory / 'alias_guard.log').read_bytes()),
                guard_script_sha256=sha(script.read_bytes()), guard_runner_sha256=sha(Path(__file__).read_bytes()))
manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'status': 'GUARD_PASS', 'manifest': str(manifest_path), 'positives': len(positives), 'negatives': len(negatives), 'sdc_sha256': manifest['new_sha256']}))
