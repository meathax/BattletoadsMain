"""Prove the private v12 declaration repair with compiler preprocessing only."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
VERILATOR = Path('D:/vibes/fpga/bin/verilator.exe')
VERILATOR_SHA = '003d1fa18138344fe6157e1a5194a9989eb440265da6151fbcb734feeb575d81'
ORIGINAL = ROOT / 'build/timing_closure_20261011/integrated_v9_private'
ORIGINAL_SHA = {
    'rtl/TMS34020/TMS34020.sv': 'b559dd361d02705cc19088d9b09389b1f978645b7c7f3cb8cb761877226de1a9',
    'rtl/TMS34020/TMS34020_MC.sv': '01bc6d0da7355616fa615b3c75132e85ab30810f68c5474620fb045b8be25531',
}
EXPECTED = {
    'rtl/TMS34020/TMS34020.sv': '41aa8a3284515162c605048ae5b479e07eed11efb58a2fdf4e9e19f89e4f2183',
    'rtl/TMS34020/TMS34020_MC.sv': '57253587cec0d804ce875fbbe0da930c4442c378c2ba1348ce81cc0bc02b77f6',
}
MACROS = ['SOUND_EN=1', 'MISTER_FB=1', 'MISTER_SMALL_VBUF=1',
          'MISTER_DISABLE_ALSA=1', 'MISTER_DISABLE_YC=1']
CONDITIONALS = {'DEBUG', 'MISTER_CPU_PHASE_CHECK', 'MISTER_ALU_PIPE_CHECK', 'SYNTHESIS', 'VERILATOR'}
sha = lambda data: hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def tokens(text):
    # Retain literals and escaped identifiers exactly; discard only comments,
    # whitespace and compiler-generated source-line directives.
    text = re.sub(r'(?m)^\s*`line[^\n]*\n?', '', text)
    lexer = re.compile(
        r'(?P<space>\s+)|(?P<comment>//[^\n]*|/\*.*?\*/)|'
        r'(?P<string>"(?:\\.|[^"\\])*")|(?P<escaped>\\[^\s]+)|'
        r"(?P<number>(?:[0-9][0-9_]*)?'[sS]?[bBoOdDhH][0-9a-fA-F_xXzZ?]+|'[01xXzZ]|[0-9][0-9_]*(?:\.[0-9_]+)?(?:[eE][+-]?[0-9_]+)?)|"
        r'(?P<identifier>[a-zA-Z_$][a-zA-Z0-9_$]*)|'
        r'(?P<operator>>>>=|<<<=|===|!==|>>>|<<<|>>=|<<=|::|==|!=|<=|>=|&&|\|\||\+\+|--|\*\*|<<|>>|\+=|-=|\*=|/=|%=|&=|\|=|\^=|~\^|\^~|->|=>|\*>|##)|'
        r'(?P<punctuation>[^\w\s])', re.S)
    result, position = [], 0
    for match in lexer.finditer(text):
        assert match.start() == position, ('Unrecognized compiler token', text[position:match.start()])
        position = match.end()
        if match.lastgroup not in {'space', 'comment'}:
            result.append(match[0])
    assert position == len(text)
    assert '`' not in result, 'All remaining preprocessor directives must be resolved'
    return result


def signature(text):
    header = text[:text.index(');') + 2]
    values = tokens(header)
    first, last = values.index('('), len(values) - 2
    assert values[last:] == [')', ';']
    ports, part = [], []
    for token in values[first + 1:last] + [',']:
        if token == ',':
            assert part, 'Empty ANSI port'
            ports.append(part)
            part = []
        else:
            part.append(token)
    return ports


def names(signature_array):
    return [part[-1] for part in signature_array]


def reject(label, operation, controls):
    try:
        operation()
    except (AssertionError, ValueError):
        controls.append({'name': label, 'rejected': True})
        return
    raise AssertionError('Negative control accepted: ' + label)


def equal(a, b):
    assert a == b


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    edge, output = args.edge.resolve(), args.output.resolve()
    edge.relative_to(ROOT / 'build')
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never rewrite accepted proof receipts'
    output.mkdir(parents=True)
    preparer = load(ROOT / 'tests/graphics/prepare_bt_append_debug_ports.py', 'append_port_preparer')
    manifest_path = edge / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['helper_sha256'] == sha(Path(preparer.__file__).read_bytes())
    assert sha(VERILATOR.read_bytes()) == VERILATOR_SHA
    version = subprocess.run([str(VERILATOR), '--version'], capture_output=True, text=True, check=True)
    snapshot_path = ROOT / 'build/timing_closure_20261011/vram_request_v12_private-snapshot.json'
    snapshot = json.loads(snapshot_path.read_text())
    qsf_path = preparer.BASE_ROOT / 'Arcade-Battletoads.qsf'
    assert sha(qsf_path.read_bytes()) == snapshot['sources']['Arcade-Battletoads.qsf']
    qsf = qsf_path.read_text()
    assigned = re.findall(r'(?m)^\s*set_global_assignment -name VERILOG_MACRO "([^"]+)"\s*$', qsf)
    assert assigned == MACROS and not re.search(r'(?m)^\s*source\s+sys/sys_dual_sdram.tcl', qsf)
    macro_sources = {}
    for name, expected_hash in snapshot['sources'].items():
        if Path(name).suffix.lower() not in {'.qsf', '.qip', '.tcl'}:
            continue
        data = (preparer.BASE_ROOT / name).read_bytes()
        assert sha(data) == expected_hash
        lines = [line for line in data.decode().splitlines()
                 if 'VERILOG_MACRO' in line and not line.lstrip().startswith('#')]
        if lines:
            macro_sources[name] = {'sha256': expected_hash, 'assignments': lines}
    assert set(macro_sources) == {'Arcade-Battletoads.qsf', 'sys/sys_dual_sdram.tcl'}
    assert 'MISTER_DUAL_SDRAM' not in CONDITIONALS
    workspace = Path('R:/Verilator/BT') / ('declaration-preprocess-' + uuid.uuid4().hex)
    workspace.mkdir(parents=True)
    env = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
               VERILATOR_WORKSPACE=str(workspace), VERILATOR_RAM_WORKSPACE=str(workspace))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    compiler_runs, source_records, controls = [], {}, []
    for name, expected_before in preparer.BASE.items():
        before, candidate = (edge / 'oracle' / name).read_bytes(), (edge / 'candidate' / name).read_bytes()
        original = (ORIGINAL / name).read_bytes()
        assert sha(before) == expected_before and sha(original) == ORIGINAL_SHA[name]
        expected, edits = preparer.transform(name, before)
        assert candidate == expected and sha(candidate) == EXPECTED[name]
        assert manifest['sources'][name]['sha256'] == EXPECTED[name] and manifest['changes'][name] == edits
        assert before.split(b');', 1)[1] == candidate.split(b');', 1)[1]
        directives = re.findall(r'(?m)^\s*`(\w+)(?:\s+(\w+))?', preparer.lf(before))
        assert all(op in {'ifdef', 'ifndef', 'else', 'endif'} for op, _ in directives)
        used = {symbol for op, symbol in directives if op in {'ifdef', 'ifndef'}}
        assert used <= CONDITIONALS
        profiles = {}
        for debug in (False, True):
            label = 'debug' if debug else 'release'
            outputs = {}
            for stage, path in [('original', ORIGINAL / name), ('v12', edge / 'oracle' / name),
                                ('fixed', edge / 'candidate' / name)]:
                invocation = [str(VERILATOR), '-E', '--Mdir', str(workspace / (Path(name).stem + '-' + label + '-' + stage)),
                              '--language', '1800-2005', '-DSYNTHESIS=1', '-UVERILATOR',
                              '-UMISTER_CPU_PHASE_CHECK', '-UMISTER_ALU_PIPE_CHECK',
                              '-DDEBUG=1' if debug else '-UDEBUG'] + ['-D' + macro for macro in MACROS] + [str(path)]
                result = subprocess.run(invocation, cwd=workspace, env=env, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, creationflags=flags)
                stem = Path(name).stem + '-' + label + '-' + stage
                (output / (stem + '.pp.sv')).write_bytes(result.stdout)
                (output / (stem + '.stderr.log')).write_bytes(result.stderr)
                assert result.returncode == 0 and not result.stderr, (stem, result.returncode, result.stderr.decode(errors='replace'))
                decoded = result.stdout.decode()
                parsed = tokens(decoded)
                compiler_runs.append({'name': name, 'profile': label, 'stage': stage, 'command': invocation,
                                      'exit_code': result.returncode, 'stdout_path': str(output / (stem + '.pp.sv')),
                                      'stdout_sha256': sha(result.stdout), 'stderr_sha256': sha(result.stderr),
                                      'tokens_sha256': sha(json.dumps(parsed, separators=(',', ':')).encode()),
                                      'token_count': len(parsed)})
                outputs[stage] = (decoded, parsed, signature(decoded))
            old_sig, fixed_sig = outputs['original'][2], outputs['fixed'][2]
            appended = ['DBUS_ADDR_CLASS', 'VRAM_REQUEST'] if name.endswith('_MC.sv') else ['ADDR_CLASS', 'VRAM_REQUEST']
            assert fixed_sig[:-2] == old_sig and names(fixed_sig[-2:]) == appended
            assert outputs['v12'][2][-1] == fixed_sig[-1]
            if not debug:
                assert outputs['v12'][1] == outputs['fixed'][1], 'Actual complete release compiler tokens changed'
            profiles[label] = {'original_signature': old_sig, 'v12_signature': outputs['v12'][2],
                               'fixed_signature': fixed_sig, 'original_names': names(old_sig),
                               'fixed_names': names(fixed_sig), 'original_indices_preserved': True,
                               'release_full_tokens_identical': not debug}
            reject(name + ':' + label + ':changed_original_port', lambda: equal(fixed_sig[:-2], old_sig[:-1]), controls)
            reject(name + ':' + label + ':changed_request_width',
                   lambda: equal(fixed_sig[-1], ['output', '[', '2', ':', '0', ']', 'VRAM_REQUEST']), controls)
            reject(name + ':' + label + ':lost_original_port', lambda: equal(names(fixed_sig[:-2]), names(old_sig)[1:]), controls)
            if not debug:
                reject(name + ':changed_release_body_token', lambda: equal(outputs['v12'][1], outputs['fixed'][1] + ['logic']), controls)
        reject(name + ':changed_functional_body', lambda: equal(before.split(b');', 1)[1], candidate.split(b');', 1)[1] + b'\nlogic altered;'), controls)
        source_records[name] = {**manifest['sources'][name], 'original_sha256': ORIGINAL_SHA[name],
                                'functional_body_sha256': sha(candidate.split(b');', 1)[1]),
                                'referenced_conditionals': sorted(used), 'profiles': profiles,
                                'reversible_declaration_edits': edits}
    receipt = {'schema': 'bt-v12-debug-port-compiler-preservation-v1', 'status': 'PASS',
               'preparer_sha256': sha(Path(preparer.__file__).read_bytes()), 'helper_sha256': sha(Path(__file__).read_bytes()),
               'manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path.read_bytes()),
               'snapshot': str(snapshot_path), 'snapshot_sha256': sha(snapshot_path.read_bytes()),
               'compiler': {'path': str(VERILATOR), 'sha256': VERILATOR_SHA, 'version': version.stdout.strip(),
                            'mode': 'preprocessing only (-E)', 'language': '1800-2005',
                            'explicit_release_macros': MACROS + ['SYNTHESIS=1'],
                            'explicit_release_undefined': ['DEBUG', 'VERILATOR', 'MISTER_CPU_PHASE_CHECK', 'MISTER_ALU_PIPE_CHECK'],
                            'macro_assignment_source_inventory': macro_sources,
                            'unused_dual_sdram_assignment': 'Not sourced by QSF; not referenced by either input file'},
               'sources': source_records, 'compiler_runs': compiler_runs, 'negative_controls': controls,
               'release_full_tokens_identical': True, 'functional_bodies_raw_byte_identical': True,
               'original_debug_and_release_port_indices_preserved': True,
               'root_modified': False, 'simulated': False, 'quartus_rerun': False,
               'scope': 'Strict declaration-only edge and actual Verilator release preprocessing identity; '
                        'composes existing release functional evidence, not a fresh Quartus, timing, native or hardware run.'}
    receipt_path = output / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'status': receipt['status'], 'receipt': str(receipt_path),
                      'sha256': sha(receipt_path.read_bytes()), 'compiler_preprocessing_runs': len(compiler_runs),
                      'negative_controls_rejected': len(controls)}))


if __name__ == '__main__':
    main()
