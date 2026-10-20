"""Bind retained v12 execution evidence through the declaration-only DEBUG ABI repair.

This validates saved compiler outputs and execution artifacts; it runs no compiler,
simulator or timing tool. FG hardware changes are recorded as a separate obligation.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/timing_closure_20261011/vram_request_v12_private'
EDGE = ROOT / 'build/v12_debug_ports_v1'
CPU = 'rtl/TMS34020/TMS34020.sv'
MC = 'rtl/TMS34020/TMS34020_MC.sv'
FG = 'rtl/fg_vram.sv'
BT = 'rtl/BT.sv'
PINS = {
    'tests/graphics/prepare_bt_append_debug_ports.py': 'e3024de4ce955ea7a820ceb7347c6b7aa7e1c73b7115bfabc758e7ee46e15d11',
    'tests/graphics/qualify_bt_append_debug_ports.py': '314a4bf983feefe7bc9012a2682cf3ba64b9084dbc51f6344efbe14cf8958d07',
    'tests/graphics/verify_bt_current_qualification.py': '6eb3bfd1a05546607bd781c7e520f56cf07f2694eb2c645d7d253bb24eb3d9cc',
    'tests/graphics/bt_native_mc_scope.py': '7f23835da455da242662c99783134446240c8099c8c74d962769e0cfdac67e2c',
    'tests/graphics/native_run.py': '3a81f2d5e5b37733bb3e7220bf81b301bc655c3dccb33c3ed795c0cab3f8f4e4',
    'build/v12_debug_ports_v1/compiler-proof/receipt.json': '91e7e2487f4433b0a7923ebb0d0719324f97455b54371574244a538bbba92f7f',
    'build/v12_debug_ports_v1/manifest.json': 'ce34233eb09dcd4eb7a83d47c9580d1a9917d0d44c43f8a8f32ca4a7a3e96716',
    'build/timing_closure_20261011/vram_request_v12_private-snapshot.json': '1f35793c94c6d71ee24bde284f1409ecab139431c3dfb3acfff13d95a759f896',
    'build/timing_closure_20261011/v12-current-stage-validation-r1.json': '4433af9b7b81178d62394e460d5b32e8293627a10660447759391f9c03917281',
}
STAGES = {
    'production': ('616b9707c5d34bf28314687ab3a720fb', 'b3666d07f4b016a0c9976451494f5d212b23258197cb0a4b47050d2394a0a28e'),
    'alternating': ('579b3ec9d47f435bac9aebfbcebcb5a7', '62f0f72e28e6752261a16c1b0f806ef93db495ae73daa9ca1996e1235471fc43'),
}
NATIVE = 'native-f9d79850638040a484dc327ddd0da0c1'
REFERENCE = 'native-420798b04be444c29f867aea732b88d1'
NATIVE_SHA = 'da2577491b0024815a64cbc0c2d0d796a7b2eda6baa984195f2e6d07a1a2f2f6'
RASTER_SHA = '1ea1b4b38ddd861808f1d19c8d104419b249988f421767a02ba2cdee505ee485'
FG_BEFORE = '233061bcfdcb986e250a204ce488f2171372250baac073a28086065529d64fec'
FG_AFTER = 'f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b'
FG_PROOF = 'build/fg_serial_controls_v12_v2/receipt.json'
FG_PROOF_SHA = 'ab3e638d6d180d2b27f707deecde06cd0197db43a11cf52b4847662e32d16aee'
FG_SUPPLEMENTAL = {
    'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2.json': 'b69b35a83a218444197b7ac7a7629d9e3a71d82c3ffa0d53309b0ffd4fa8d91a',
    'build/fg_serial_controls_v12_v2/vendor-applicability-v13.json': '84976ae407f2b9e216df012363b7ce0625269982bd4caf66709d71b1c2f3592d',
}
SDC_BEFORE = 'ed10269eaa854edbe9a8b43b46067053c6583633737444d15e8f1e4eab2701fd'
SDC_AFTER = '18aaeadc8ddf1006c4915818ab501084ab4af6d3f4d8621df643ea279bdd8ce8'
sha = lambda data: hashlib.sha256(data).hexdigest()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def read_json(path, expected=None):
    data = path.read_bytes()
    check(expected is None or sha(data) == expected, 'Changed proof artifact: ' + str(path))
    return json.loads(data)


def ref(path):
    return {'path': str(path), 'sha256': sha(path.read_bytes())}


def canonical(data):
    check(b'\r' not in data.replace(b'\r\n', b''), 'Lone CR is not a supported normalization')
    return data.replace(b'\r\n', b'\n').decode('utf-8')


def verify_source_edge(name, before, after, manifest, preparer, compiler):
    expected, edits = preparer.transform(name, before)
    check(after == expected and sha(after) == compiler.EXPECTED[name], 'Foreign header/body change: ' + name)
    check(manifest['changes'][name] == edits, 'Declaration edit order changed')
    item = manifest['sources'][name]
    check(item['before_sha256'] == sha(before) and item['sha256'] == sha(after), 'Source edge hash changed')
    check(before.split(b');', 1)[1] == after.split(b');', 1)[1], 'Functional body changed')
    # The actual header edit depends only on DEBUG. It therefore applies to the
    # native/stage assertion profiles as well as the saved SYNTHESIS preprocesses.
    for source in (before, after):
        directives = re.findall(r'(?m)^\s*`(\w+)(?:\s+(\w+))?', canonical(source).split(');', 1)[0])
        check(all(op in {'ifdef', 'endif'} and (op != 'ifdef' or symbol == 'DEBUG')
                  for op, symbol in directives), 'New header profile dependence')
    return {'edge_type': 'bt-v12-debug-append-only-declaration-v1',
            'before_sha256': sha(before), 'after_sha256': sha(after),
            'functional_body_raw_sha256': sha(after.split(b');', 1)[1]),
            'exact_reversible_edits': edits, 'header_conditional': 'DEBUG only'}


def verify_preprocess_runs(proof, compiler, preparer):
    check(proof['schema'] == 'bt-v12-debug-port-compiler-preservation-v1' and proof['status'] == 'PASS', 'Compiler proof failed')
    check(proof['helper_sha256'] == PINS['tests/graphics/qualify_bt_append_debug_ports.py'], 'Compiler helper changed')
    check(proof['preparer_sha256'] == PINS['tests/graphics/prepare_bt_append_debug_ports.py'], 'Preparer changed')
    check(proof['manifest_sha256'] == PINS['build/v12_debug_ports_v1/manifest.json'], 'Compiler manifest changed')
    check(proof['snapshot_sha256'] == PINS['build/timing_closure_20261011/vram_request_v12_private-snapshot.json'], 'Compiler input snapshot changed')
    check(sha(compiler.VERILATOR.read_bytes()) == compiler.VERILATOR_SHA == proof['compiler']['sha256'], 'Compiler binary changed')
    expected_keys = {(name, profile, stage) for name in (CPU, MC)
                     for profile in ('release', 'debug') for stage in ('original', 'v12', 'fixed')}
    check(len(proof['compiler_runs']) == 12, 'Missing actual preprocessing run')
    parsed, artifacts = {}, []
    for run in proof['compiler_runs']:
        key = run['name'], run['profile'], run['stage']
        check(key in expected_keys and key not in parsed, 'Duplicate/foreign compiler profile')
        name, profile, stage = key
        source = {'original': compiler.ORIGINAL / name, 'v12': EDGE / 'oracle' / name,
                  'fixed': EDGE / 'candidate' / name}[stage]
        source_sha = compiler.ORIGINAL_SHA[name] if stage == 'original' else preparer.BASE[name] if stage == 'v12' else compiler.EXPECTED[name]
        check(sha(source.read_bytes()) == source_sha, 'Compiler input changed')
        command = run['command']
        stem = Path(name).stem + '-' + profile + '-' + stage
        check(len(command) == 17 and command[:3] == [str(compiler.VERILATOR), '-E', '--Mdir'], 'Unexpected compiler command')
        check(Path(command[3]).name == stem, 'Compiler profile workspace changed')
        check(command[4:] == ['--language', '1800-2005', '-DSYNTHESIS=1', '-UVERILATOR',
                             '-UMISTER_CPU_PHASE_CHECK', '-UMISTER_ALU_PIPE_CHECK',
                             '-DDEBUG=1' if profile == 'debug' else '-UDEBUG'] +
              ['-D' + macro for macro in compiler.MACROS] + [str(source)], 'Compiler profile/source flags changed')
        stdout = EDGE / 'compiler-proof' / (stem + '.pp.sv')
        stderr = EDGE / 'compiler-proof' / (stem + '.stderr.log')
        check(Path(run['stdout_path']) == stdout and run['exit_code'] == 0, 'Compiler output lineage changed')
        check(sha(stdout.read_bytes()) == run['stdout_sha256'] and stderr.read_bytes() == b'' and
              sha(stderr.read_bytes()) == run['stderr_sha256'], 'Saved compiler output changed')
        values = compiler.tokens(stdout.read_text())
        check(len(values) == run['token_count'] and sha(json.dumps(values, separators=(',', ':')).encode()) == run['tokens_sha256'], 'Compiler token evidence changed')
        parsed[key] = values, compiler.signature(stdout.read_text())
        artifacts.extend([ref(source), ref(stdout), ref(stderr)])
    check(set(parsed) == expected_keys, 'Preprocessing profile coverage incomplete')
    profiles = {}
    for name in (CPU, MC):
        profiles[name] = {}
        for profile in ('release', 'debug'):
            original = parsed[name, profile, 'original'][1]
            prior = parsed[name, profile, 'v12'][1]
            fixed = parsed[name, profile, 'fixed'][1]
            ports = ['DBUS_ADDR_CLASS', 'VRAM_REQUEST'] if name == MC else ['ADDR_CLASS', 'VRAM_REQUEST']
            check(fixed[:-2] == original and compiler.names(fixed[-2:]) == ports, 'Original ABI port order/signature changed')
            prior_appended = {part[-1]: part for part in prior if part[-1] in ports}
            check(len(prior_appended) == 2 and fixed[-2:] == [prior_appended[port] for port in ports] and
                  all(part[0] == 'output' and part[-6:-1] == ['[', '3', ':', '0', ']'] for part in fixed[-2:]), 'Appended output signature/width changed')
            record = proof['sources'][name]['profiles'][profile]
            check(record['original_signature'] == original and record['fixed_signature'] == fixed and
                  record['v12_signature'] == prior, 'Stored ABI signature differs from actual compiler output')
            if profile == 'release':
                check(parsed[name, profile, 'v12'][0] == parsed[name, profile, 'fixed'][0], 'Complete release tokens changed')
            profiles[name][profile] = {'original_ports': len(original), 'fixed_ports': len(fixed),
                                      'original_signature_sha256': sha(json.dumps(original).encode()),
                                      'fixed_signature_sha256': sha(json.dumps(fixed).encode()),
                                      'original_indices_preserved': True, 'appended_ports': ports,
                                      'complete_release_tokens_identical': profile == 'release'}
    return parsed, profiles, artifacts


def named_bindings(text, module, signature, compiler, unconnected_outputs=None):
    # Mask comments and strings for the instance inventory; parse connection
    # expressions with the same literal-preserving lexer as the compiler proof.
    masked = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
                    lambda m: ' ' * len(m[0]), text, flags=re.S)
    found = []
    for mention in re.finditer(r'\b' + re.escape(module) + r'\b', masked):
        prefix = masked[:mention.start()]
        if re.search(r'\bmodule\s*$', prefix):
            continue
        match = re.match(r'\s+([A-Za-z_$][\w$]*)\s*\(', masked[mention.end():])
        check(match is not None, 'Unsupported/positional module consumption')
        begin = mention.end() + match.end() - 1
        depth, end = 1, begin + 1
        while depth and end < len(masked):
            depth += (masked[end] == '(') - (masked[end] == ')')
            end += 1
        check(depth == 0 and masked[end:].lstrip().startswith(';'), 'Incomplete consuming instance')
        values = compiler.tokens(text[begin + 1:end - 1])
        parts, part, level = [], [], 0
        for token in values + [',']:
            if token == ',' and level == 0:
                check(part, 'Empty/positional connection')
                parts.append(part)
                part = []
            else:
                part.append(token)
                level += (token == '(') - (token == ')')
                check(level >= 0, 'Unbalanced named connection')
        connections = {}
        for part in parts:
            check(len(part) >= 4 and part[0] == '.' and part[2] == '(' and part[-1] == ')' and
                  re.fullmatch(r'[A-Za-z_$][\w$]*', part[1]), 'Positional/wildcard binding is not applicable')
            check(part[1] not in connections, 'Duplicate consuming port')
            connections[part[1]] = part[3:-1]
        missing = set(compiler.names(signature)) - set(connections)
        allowed = (unconnected_outputs or {}).get(match[1], set())
        check(missing == allowed and not (set(connections) - set(compiler.names(signature))),
              'Missing/foreign release consuming port in ' + match[1] + ': missing=' + str(sorted(missing)) +
              ' foreign=' + str(sorted(set(connections) - set(compiler.names(signature)))))
        check(all(part[0] == 'output' for part in signature if part[-1] in missing), 'Unconnected input is not an applicable ABI')
        for declaration in signature:
            if declaration[0] == 'input':
                check(connections[declaration[-1]], 'Unbound production input')
        enclosing = re.findall(r'\bmodule\s+([A-Za-z_$][\w$]*)', prefix)
        check(enclosing, 'Instance has no enclosing source module')
        found.append({'module': module, 'enclosing_module': enclosing[-1], 'instance': match[1], 'line': text.count('\n', 0, mention.start()) + 1,
                      'named_connections': connections, 'unconnected_outputs': sorted(missing),
                      'connection_sha256': sha(json.dumps(connections, sort_keys=True).encode())})
    return found


def snapshot_inputs(path):
    snapshot = read_json(path)
    check(snapshot['schema'] == 'bt-isolated-source-v1' and len(snapshot['sources']) == 144 and
          snapshot['assembled'] is False, 'Not the complete check-only input snapshot')
    root = Path(snapshot['project']).parent.resolve()
    check(root.is_relative_to(ROOT / 'build'), 'Snapshot outside private workspace')
    for name, expected in snapshot['sources'].items():
        check(not Path(name).is_absolute() and '..' not in Path(name).parts, 'Unsafe source inventory name')
        check(sha((root / name).read_bytes()) == expected, 'Frozen snapshot input changed: ' + name)
    return snapshot, root


def verify_native_counts(text):
    def counters(prefix):
        records = re.findall(r'(?m)^' + re.escape(prefix) + r'([^\n]*)$', text)
        check(len(records) == 1, 'Missing/duplicate native completion counters: ' + prefix)
        return {key: int(value) for key, value in re.findall(r'(\w+)=(\d+)', records[0])}
    complete = counters('NATIVE_COMPLETE ')
    check(complete == {'frames': 128, 'cycles': 172308065, 'DDR_commands': 2878478}, 'Native run incomplete/changed')
    parallel = counters('DDR_PARALLEL_PHASE frame=128 ')
    check(parallel['captures'] == parallel['launch_age_checks'] == 2573046 and
          parallel['cpu'] == 279286 and parallel['fg0'] == parallel['fg1'] == 1146880 and parallel['sprite'] == 0 and
          sum(parallel[key] for key in ('cpu', 'fg0', 'fg1', 'sprite')) == parallel['captures'], 'Raw owner coverage changed')
    check(parallel['probe_checks'] == 171038303 and all(parallel[key] >= 5 for key in ('min_ext', 'min_fs', 'min_ba')) and parallel['min_buf'] >= 3, 'Actual reload-age coverage missing')
    phase = counters('DDR_PHASE frame=128 ')
    check(phase['return_captures'] == 8408774 and phase['physical_return_captures'] == 5167437 and
          phase['accepted_writes'] == phase['write_edges'] == parallel['captures'], 'Physical return/write coverage changed')
    check(not re.search(r'(?im)assertion failed|%error|\bfatal\b|aborting|NATIVE_FAILED', text), 'Native assertions failed')
    return {'complete': complete, 'parallel': parallel, 'phase': phase}


def verify_native(proof, path, compiler, preparer, signatures, native_scope):
    check(proof['exit_code'] == 0 and proof['requested_frames'] == 128 and len(proof['commands']) == 4, 'Native run failed')
    snapshot = Path(proof['snapshot'])
    check(snapshot.name == NATIVE, 'Wrong native compiled image')
    source_map = {name.replace('\\', '/'): value for name, value in proof['sources'].items()}
    check(len(source_map) == len(proof['sources']), 'Duplicate native source alias')
    base_snapshot = read_json(ROOT / 'build/timing_closure_20261011/vram_request_v12_private-snapshot.json')
    unused = []
    for name, expected in source_map.items():
        if name == 'rtl/bt_platform_io.sdc':
            check(expected == SDC_BEFORE and base_snapshot['sources'][name] == SDC_AFTER, 'Undeclared native SDC edge')
            unused.append({'path': name, 'native_directory_sha256': expected, 'fit_source_sha256': SDC_AFTER,
                           'compiled_by_native': False, 'scope': 'Guard-only SCLK alias edge belongs to the fit manifest.'})
            continue
        origin = BASE / name if (BASE / name).is_file() else ROOT / name
        check(sha(origin.read_bytes()) == expected, 'Native source input mismatch: ' + name)
    command = proof['commands'][2]
    check(command[0].replace('\\', '/') == 'D:/vibes/fpga/bin/verilator.exe' and '--assert' in command and
          '-DMISTER_CPU_PHASE_CHECK=1' in command and '-DMISTER_ALU_PIPE_CHECK=1' in command and
          not any(item.startswith('-DDEBUG') or item.startswith('-DSYNTHESIS') for item in command), 'Native assertion/profile flags changed')
    check(proof['commands'][3][5] == '128' and proof['commands'][3][-1] == str(snapshot / 'inputs.txt'), 'Native replay command changed')
    check(sha((path.parent / 'inputs.txt').read_bytes()) == proof['input_journal']['sha256'] ==
          sha(Path(proof['input_journal']['path']).read_bytes()), 'Input journal changed')
    compiled, bindings = [], []
    for item in command:
        file = Path(item)
        if file.suffix.lower() != '.sv':
            continue
        check(file.is_relative_to(snapshot), 'Unbound native compiler input')
        name = file.relative_to(snapshot).as_posix()
        origin = BASE / name if name.startswith('rtl/') else ROOT / 'tests/graphics' / name
        before = origin.read_bytes()
        expected = canonical(before)
        if name == MC:
            local, anchor = '\t\tbit         READ_LATCH;', '\tbit          FETCH_LATCH;'
            check(expected.count(local) == expected.count(anchor) == 1, 'READ_LATCH visibility edge changed')
            expected = expected.replace(local, '').replace(anchor, anchor + '\n\tbit          READ_LATCH;')
            expected, scope = native_scope.expose_launch_scope(expected)
            check(read_json(path.parent / 'mc_launch_scope.json') == scope, 'Native actual-load probe source binding changed')
        elif name == BT:
            check(expected.count('rtl/bsmt2000.mif') == 1, 'DSP memory adaptation changed')
            expected = expected.replace('rtl/bsmt2000.mif', 'rtl/bsmt2000.hex')
        check(canonical(file.read_bytes()) == expected, 'Native compiled source differs from the exact adapter: ' + name)
        compiled.append({**ref(file), 'source_parent': str(origin), 'source_parent_sha256': sha(before),
                         'compiled_lf_sha256': sha(expected.encode())})
        if name == BT:
            bindings += named_bindings(expected, 'TMS34020', signatures[CPU], compiler)
        elif name == CPU:
            bindings += named_bindings(expected, 'TMS34020_MC', signatures[MC], compiler)
    check({entry['module'] for entry in bindings} == {'TMS34020', 'TMS34020_MC'} and len(bindings) == 2, 'Native consuming ABI coverage incomplete')
    for name in ('build.log', 'run.log', 'ghdl-analyze.log', 'ghdl-synth.log', 'inputs.txt'):
        check((path.parent / name).read_bytes() == (snapshot / name).read_bytes(), 'Retained native log differs from executed snapshot')
    counts = verify_native_counts((path.parent / 'run.log').read_text())
    return {'receipt': ref(path), 'run_log': ref(path.parent / 'run.log'),
            'build_log': ref(path.parent / 'build.log'), 'commands': proof['commands'],
            'compiled_inputs': compiled, 'named_consumers': bindings, 'coverage': counts,
            'uncompiled_constraint_boundary': unused,
            'scope': proof['scope'], 'new_simulation': False}


def verify_rasters(path):
    proof = read_json(path, RASTER_SHA)
    check(proof['reference'] == REFERENCE and proof['candidate'] == NATIVE and proof['exit_code'] == 0 and
          proof['failures'] == [] and len(proof['comparisons']) == 24, 'Raster comparison failed/incomplete')
    directory = path.parent.parent
    for receipt in proof['run_receipts']:
        check(Path(receipt['path']).parent.name in {NATIVE, REFERENCE}, 'Foreign raster image')
        data = read_json(Path(receipt['path']), receipt['sha256'])
        check(data['exit_code'] == 0 and data['requested_frames'] == 128, 'Compared native image failed')
    check(len(proof['run_receipts']) == 2, 'Missing raster image receipt')
    seen = set()
    for item in proof['comparisons']:
        pair = item['kind'], item['name']
        check(pair not in seen and item['kind'] in {'frames', 'frames-pre'} and Path(item['name']).name == item['name'], 'Foreign/duplicate raster capture')
        seen.add(pair)
        before, after = directory / REFERENCE / item['kind'] / item['name'], directory / NATIVE / item['kind'] / item['name']
        check(item['equal'] is True and sha(before.read_bytes()) == item['reference_sha256'] ==
              sha(after.read_bytes()) == item['candidate_sha256'], 'Raster bytes changed')
    return {'receipt': ref(path), 'raw_comparisons': 24, 'reference': REFERENCE, 'candidate': NATIVE,
            'new_replay': False, 'new_raster_comparison': False, 'scope': proof['scope']}


def rejected(label, operation, records):
    try:
        operation()
    except (AssertionError, ValueError, KeyError):
        records.append({'name': label, 'rejected': True})
        return
    raise AssertionError('Negative control accepted: ' + label)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target-snapshot', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output, target_path = args.output.resolve(), args.target_snapshot.resolve()
    check(output.is_relative_to(ROOT / 'build') and not output.exists(), 'Use a new private receipt path')
    # Preserve and check the exact evidence/helper inputs before and after this binding.
    retained = {name: ref(ROOT / name) for name in PINS}
    for name, expected in PINS.items():
        check(retained[name]['sha256'] == expected, 'Pinned evidence/helper changed: ' + name)
    preparer = load(ROOT / 'tests/graphics/prepare_bt_append_debug_ports.py', 'abi_edge_preparer')
    compiler = load(ROOT / 'tests/graphics/qualify_bt_append_debug_ports.py', 'abi_compiler_proof')
    validator = load(ROOT / 'tests/graphics/verify_bt_current_qualification.py', 'abi_stage_validator')
    native_scope = load(ROOT / 'tests/graphics/bt_native_mc_scope.py', 'abi_native_scope')
    manifest = read_json(EDGE / 'manifest.json', PINS['build/v12_debug_ports_v1/manifest.json'])
    compiler_proof = read_json(EDGE / 'compiler-proof/receipt.json', PINS['build/v12_debug_ports_v1/compiler-proof/receipt.json'])
    base_manifest, base_root = snapshot_inputs(ROOT / 'build/timing_closure_20261011/vram_request_v12_private-snapshot.json')
    check(base_root == BASE, 'Wrong v12 execution source root')
    target, target_root = snapshot_inputs(target_path)
    check(set(target['sources']) == set(base_manifest['sources']), 'Full144 source inventory changed')
    deltas = {name for name in target['sources'] if target['sources'][name] != base_manifest['sources'][name]}
    check(deltas in ({CPU, MC}, {CPU, MC, FG}), 'Undeclared hardware/source change')
    edge_records, controls = {}, []
    for name in (CPU, MC):
        before, after = (BASE / name).read_bytes(), (target_root / name).read_bytes()
        check(before == (EDGE / 'oracle' / name).read_bytes() and after == (EDGE / 'candidate' / name).read_bytes(), 'ABI candidate/oracle identity changed')
        edge_records[name] = verify_source_edge(name, before, after, manifest, preparer, compiler)
        rejected(name + ':body_change', lambda n=name, b=before, a=after: verify_source_edge(n, b, a + b'\nlogic changed;', manifest, preparer, compiler), controls)
        rejected(name + ':foreign_parent', lambda n=name, b=before, a=after: verify_source_edge(n, b + b'\n', a, manifest, preparer, compiler), controls)
        wrong = copy.deepcopy(manifest)
        wrong['changes'][name].reverse()
        rejected(name + ':edit_order', lambda n=name, b=before, a=after, m=wrong: verify_source_edge(n, b, a, m, preparer, compiler), controls)
    parsed, profiles, compiler_artifacts = verify_preprocess_runs(compiler_proof, compiler, preparer)
    signatures = {name: parsed[name, 'release', 'fixed'][1] for name in (CPU, MC)}
    production_consumers = []
    for name in target['sources']:
        if Path(name).suffix.lower() not in {'.sv', '.v'}:
            continue
        text = canonical((target_root / name).read_bytes())
        for module, declaration in [('TMS34020', CPU), ('TMS34020_MC', MC)]:
            for consumer in named_bindings(text, module, signatures[declaration], compiler):
                production_consumers.append({'source': name, 'source_sha256': target['sources'][name], **consumer})
    check(len(production_consumers) == 2 and
          {(item['source'], item['module'], item['instance']) for item in production_consumers} ==
          {(BT, 'TMS34020', 'CPU'), (CPU, 'TMS34020_MC', 'MC')}, 'Actual production consumer inventory changed')
    for source, module, name in [(BT, 'TMS34020', CPU), (CPU, 'TMS34020_MC', MC)]:
        old = named_bindings(canonical((BASE / source).read_bytes()), module, signatures[name], compiler)
        new = named_bindings(canonical((target_root / source).read_bytes()), module, signatures[name], compiler)
        check(old[0]['named_connections'] == new[0]['named_connections'], 'Actual connection expression changed')
        text = canonical((target_root / source).read_bytes())
        start = re.search(r'(?m)^[ \t]*' + module + r'\s+\w+\s*\(', text).start()
        prefix, instance_tail = text[:start], text[start:]
        rejected(name + ':positional_connection', lambda p=prefix, t=instance_tail, m=module, s=signatures[name]: named_bindings(p + t.replace('.CLK(CLK)', 'CLK', 1), m, s, compiler), controls)
        rejected(name + ':missing_original_input', lambda p=prefix, t=instance_tail, m=module, s=signatures[name]: named_bindings(p + t.replace('.CLK(CLK),', '', 1), m, s, compiler), controls)
        rejected(name + ':duplicate_binding', lambda p=prefix, t=instance_tail, m=module, s=signatures[name]: named_bindings(p + t.replace('.CLK(CLK),', '.CLK(CLK),.CLK(CLK),', 1), m, s, compiler), controls)
    stages, saved = {}, read_json(ROOT / 'build/timing_closure_20261011/v12-current-stage-validation-r1.json')
    for phase, (identifier, expected) in STAGES.items():
        path = ROOT / 'tests/graphics/evidence/ddr-be-bridge' / ('ddr-be-bridge-' + identifier) / 'receipt.json'
        proof = read_json(path, expected)
        outcome = validator.validate_current_stage(proof, path, ROOT, BASE)
        check(outcome == saved['coverage']['stage_' + phase] and len(saved['negative_controls'][phase]) == 47, 'Retained strict stage gate differs')
        fixture = ROOT / proof['current_stage_adapter']['fixture']
        compiled_fixture = path.parent / 'compiled_inputs' / fixture.relative_to(ROOT)
        check(sha(compiled_fixture.read_bytes()) == proof['sources'][compiled_fixture.relative_to(ROOT).as_posix()], 'Stage consuming fixture changed')
        ref_outputs = {
            'REF': {'DBUS_ANY_BE', 'DBUS_ANY_BE_FG', 'DBUS_ADDR_CLASS', 'VRAM_REQUEST'},
            'CLASS_PROBE': {'CACHE_WR', 'DBUS_ANY_BE', 'DBUS_ANY_BE_FG', 'DBUS_BE', 'DBUS_CODE',
                            'DBUS_DO', 'DBUS_RD_EXT', 'DIN', 'DIN_F', 'VRAM_REQUEST', 'WAIT'},
        }
        consumers = named_bindings(canonical(compiled_fixture.read_bytes()), 'TMS34020_MC', signatures[MC], compiler, ref_outputs)
        # The pinned complete fixture also contains full-width directed subfixtures.
        # Its exact compiled hash and retained strict gate fix their inventory;
        # every instance independently requires named ports and all inputs above.
        check({'MC', 'REF', 'CLASS_PROBE'} <= {item['instance'] for item in consumers}, 'Stage actual MC/raw reference/class probe consuming ABI missing')
        check(len({(item['enclosing_module'], item['instance']) for item in consumers}) == len(consumers), 'Duplicate consuming instance within a module')
        text = canonical(compiled_fixture.read_bytes())
        rejected(phase + ':missing_stage_input', lambda t=text, u=ref_outputs: named_bindings(t.replace('.CE_F(CE_F),', '', 1), 'TMS34020_MC', signatures[MC], compiler, u), controls)
        rejected(phase + ':unconnected_output_scope_change', lambda t=text, u=ref_outputs: named_bindings(t.replace('.DBUS_A(ba),', '', 1), 'TMS34020_MC', signatures[MC], compiler, u), controls)
        stages[phase] = {'receipt': ref(path), 'run_log': ref(path.parent / 'run.log'), 'strict_gate': ref(ROOT / 'build/timing_closure_20261011/v12-current-stage-validation-r1.json'),
                         'retained_rejection_controls': 47, 'outcome': outcome, 'compiled_consuming_fixture': ref(compiled_fixture),
                         'named_consumers': consumers, 'new_simulation': False,
                         'scope': 'CPU/MC declaration and unchanged functional-body applicability; FG hardware edge remains separate.'}
    native_path = ROOT / 'tests/graphics/evidence/native' / NATIVE / 'receipt.json'
    native_proof = read_json(native_path, NATIVE_SHA)
    native = verify_native(native_proof, native_path, compiler, preparer, signatures, native_scope)
    raster = verify_rasters(native_path.parent / 'raster_comparison.json')
    rejected('native_incomplete', lambda: verify_native_counts((native_path.parent / 'run.log').read_text().replace('frames=128 cycles=', 'frames=127 cycles=')), controls)
    rejected('native_reload_age', lambda: verify_native_counts((native_path.parent / 'run.log').read_text().replace('min_buf=3 ', 'min_buf=1 ')), controls)
    rejected('native_owner_count', lambda: verify_native_counts((native_path.parent / 'run.log').read_text().replace('cpu=279286 ', 'cpu=279285 ')), controls)
    for label, change in [('missing_preprocess', lambda p: p['compiler_runs'].pop()),
                          ('compiler_output_hash', lambda p: p['compiler_runs'][0].update(stdout_sha256='0' * 64)),
                          ('foreign_debug_profile', lambda p: p['compiler_runs'][0]['command'].__setitem__(10, '-DDEBUG=1'))]:
        changed = copy.deepcopy(compiler_proof)
        change(changed)
        rejected(label, lambda p=changed: verify_preprocess_runs(p, compiler, preparer), controls)
    hardware = {'status': 'UNCHANGED', 'new_simulation': False}
    if FG in deltas:
        fg = read_json(ROOT / FG_PROOF, FG_PROOF_SHA)
        edge = target['control_and_header_edges'][FG]
        check(target['sources'][FG] == edge['sha256'] == fg['sha256'] == FG_AFTER and
              base_manifest['sources'][FG] == edge['before_sha256'] == fg['before_sha256'] == FG_BEFORE and
              edge['induction_proof_sha256'] == FG_PROOF_SHA and fg['status'] == 'PASS', 'FG hardware edge is foreign')
        supplemental = []
        for name, expected in FG_SUPPLEMENTAL.items():
            read_json(ROOT / name, expected)
            supplemental.append(ref(ROOT / name))
        hardware = {'status': 'SEPARATE_PIN_VENDOR_EVIDENCE_REQUIRES_FINAL_COMPOSITION', 'source': FG,
                    'before_sha256': FG_BEFORE, 'after_sha256': FG_AFTER,
                    'induction_proof': ref(ROOT / FG_PROOF), 'new_simulation': False,
                    'separate_pin_vendor_evidence': supplemental,
                    'scope': 'Recorded full-source FG edge; not accepted as declaration/token identity.',
                    'remaining': ['Explicit reviewed pin/vendor FG edge into stage/native scope',
                                  'Accepted exact all-corner fit and physical I/O']}
    for name, item in retained.items():
        check(sha((ROOT / name).read_bytes()) == item['sha256'], 'Binding mutated retained proof/helper')
    receipt = {'schema': 'bt-v12-debug-abi-execution-applicability-v1', 'status': 'PASS_HEADER_APPLICABILITY',
               'helper': ref(Path(__file__)), 'command': [sys.executable] + sys.argv,
               'target_snapshot': ref(target_path), 'target_source_root': str(target_root),
               'full_source_count': 144, 'changed_sources': sorted(deltas), 'unchanged_sources': 144 - len(deltas),
               'base_snapshot': ref(ROOT / 'build/timing_closure_20261011/vram_request_v12_private-snapshot.json'),
               'retained_inputs': retained, 'typed_header_edges': edge_records,
               'compiler_profiles': profiles, 'actual_preprocessing_runs': 12, 'compiler_artifacts': compiler_artifacts,
               'production_named_consumers': production_consumers, 'stage_applicability': stages,
               'native_component_applicability': native, 'retained_raster_preservation': raster,
               'fg_hardware_applicability': hardware, 'negative_controls': controls,
               'original_receipts_unchanged': True, 'functional_bodies_raw_byte_identical': True,
               'release_compiler_tokens_identical': True, 'original_debug_and_release_signatures_preserved': True,
               'new_simulation': False, 'timing_accepted': False, 'physical_io_accepted': False, 'rbf_built': False,
               'scope': 'Only the exact CPU/MC header edge composes retained execution evidence. DEBUG behavior, changed FG hardware, fitted timing and platform hardware qualification remain separate.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': receipt['status'], 'receipt': str(output), 'sha256': sha(output.read_bytes()),
                      'negative_controls': len(controls), 'actual_preprocessing_runs': 12,
                      'actual_release_consumers': len(production_consumers), 'source_count': 144,
                      'fg_status': hardware['status']}))


if __name__ == '__main__':
    main()
