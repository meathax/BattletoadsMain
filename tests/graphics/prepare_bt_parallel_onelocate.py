"""Prepare a reversible, CPU-local parallel OneLocate replacement.

The package, ALU result mux, operand registers and every CPU state edge remain
byte identical.  This helper is restricted to the frozen v13 CPU parent.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE_ROOT = ROOT / 'build/timing_closure_20261011/fg_controls_v13_private'
CPU_PATH = 'rtl/TMS34020/TMS34020.sv'
PACKAGE_PATH = 'rtl/TMS34020/TMS34020_pkg.sv'
CPU_SHA = '41aa8a3284515162c605048ae5b479e07eed11efb58a2fdf4e9e19f89e4f2183'
PACKAGE_SHA = '699ca3d9131296edf0116f051e7271f5be54ea500d06b69966155b18711e2c65'
ANCHOR = '\tfunction bit [32:0] BtCarryShifter(input bit [31:0] val, input bit [4:0] sa, input bit [3:0] code);'
OLD_CALL = '\t\tLOC_RES = OneLocate(ALU_B, DECI.ALU.CD[0]);'
NEW_CALL = '\t\tLOC_RES = BtOneLocate(ALU_B, DECI.ALU.CD[0]);'
sha = lambda value: hashlib.sha256(value).hexdigest()


def parallel_function():
    lines = [
        '\t// Resolve nibble priorities in parallel, before selecting direction.',
        '\t// Keep the package locator\'s zero cases: dir=0 -> 31, dir=1 -> 0.',
        '\tfunction bit [4:0] BtOneLocate(input bit [31:0] val, input bit dir);',
        '\t\tbit [7:0] present, high_group, low_group;',
        '\t\tbit [4:0] high_index, low_index, index;',
    ]
    for i in range(8):
        lines.append(f'\t\tpresent[{i}] = |val[{4*i+3}:{4*i}];')
    for i in range(8):
        suffix = f' & ~|present[7:{i+1}]' if i != 7 else ''
        lines.append(f'\t\thigh_group[{i}] = present[{i}]{suffix};')
    for i in range(8):
        suffix = f' & ~|present[{i-1}:0]' if i != 0 else ''
        lines.append(f'\t\tlow_group[{i}] = present[{i}]{suffix};')
    for name, group in [('high_index', 'high_group'), ('low_index', 'low_group')]:
        lines.extend([
            f'\t\t{name}[4] = |({group} & 8\'b11110000);',
            f'\t\t{name}[3] = |({group} & 8\'b11001100);',
            f'\t\t{name}[2] = |({group} & 8\'b10101010);',
        ])
    high1, high0, low1, low0 = [], [], [], []
    for i in range(8):
        lo, hi = 4*i, 4*i+3
        high1.append(f'(high_group[{i}] & |val[{hi}:{lo+2}])')
        high0.append(f'(high_group[{i}] & (val[{hi}] | (~val[{lo+2}] & val[{lo+1}])))')
        low1.append(f'(low_group[{i}] & ~|val[{lo+1}:{lo}] & |val[{hi}:{lo+2}])')
        low0.append(f'(low_group[{i}] & ((val[{lo+1}] & ~val[{lo}]) | (val[{hi}] & ~|val[{lo+2}:{lo}])))')
    for target, terms in [('high_index[1]', high1), ('high_index[0]', high0),
                          ('low_index[1]', low1), ('low_index[0]', low0)]:
        lines.append(f'\t\t{target} = ' + '\n\t\t\t| '.join(terms) + ';')
    lines.extend([
        '\t\tindex = dir ? low_index : high_index;',
        '\t\treturn ~index & {5{~dir | (|val)}};',
        '\tendfunction',
        '',
    ])
    return '\n'.join(lines) + '\n'


FUNCTION = parallel_function()


def extract_function(text, name):
    pattern = re.compile(r'(?m)^\s*function\b[^;]*\b' + re.escape(name)
                         + r'\s*\([^;]*;.*?\bendfunction\b', re.S)
    matches = list(pattern.finditer(text))
    assert len(matches) == 1, ('Expected exactly one function', name, len(matches))
    return matches[0][0].lstrip('\n')


def transform(data):
    assert sha(data) == CPU_SHA, 'Unqualified full CPU parent'
    text = data.decode('utf-8')
    assert '\r' not in text, 'This frozen raw parent uses LF'
    assert text.count(ANCHOR) == 1 and text.count(OLD_CALL) == 1
    assert 'BtOneLocate' not in text
    return text.replace(ANCHOR, FUNCTION + ANCHOR).replace(OLD_CALL, NEW_CALL).encode()


def reverse(data):
    text = data.decode('utf-8')
    assert text.count(FUNCTION) == 1 and text.count(NEW_CALL) == 1
    restored = text.replace(FUNCTION, '').replace(NEW_CALL, OLD_CALL).encode()
    assert sha(restored) == CPU_SHA, 'Change outside the exact locator edge'
    return restored


def prepare(output):
    output = output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite a frozen private edge'
    old_cpu = (BASE_ROOT / CPU_PATH).read_bytes()
    package = (BASE_ROOT / PACKAGE_PATH).read_bytes()
    assert sha(package) == PACKAGE_SHA
    candidate = transform(old_cpu)
    assert reverse(candidate) == old_cpu
    for relative, data in [(f'oracle/{CPU_PATH}', old_cpu),
                           (f'oracle/{PACKAGE_PATH}', package),
                           (f'candidate/{CPU_PATH}', candidate)]:
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        'schema': 'bt-cpu-parallel-onelocate-edge-v1',
        'parent_root': str(BASE_ROOT),
        'source_sha256': {CPU_PATH: CPU_SHA, PACKAGE_PATH: PACKAGE_SHA},
        'candidate_sha256': {CPU_PATH: sha(candidate)},
        'helper_sha256': sha(Path(__file__).read_bytes()),
        'old_function_sha256': sha(extract_function(package.decode(), 'OneLocate').encode()),
        'new_function_sha256': sha(extract_function(candidate.decode(), 'BtOneLocate').encode()),
        'raw_full_cpu_inverse_identical': True,
        'scope': 'One pure 2-state local function and one combinational call; all other CPU bytes unchanged',
        'registers_added': 0,
        'latency_cycles_added': 0,
        'timing_accepted': False,
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    manifest = prepare(args.output)
    print(json.dumps({'output': str(args.output.resolve()), **manifest}, indent=2))


if __name__ == '__main__':
    main()
