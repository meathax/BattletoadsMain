"""Strict source applicability of the accepted platform simulation to v12.

No simulation is retagged or rerun: unchanged compiled inputs retain their
original receipt; the original static assertions execute on the current top.
"""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import re
import runpy
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PARENT = 'build/platform_features/platform-f2b6102a8b924732bc010cc6f7264cf1/receipt.json'
PARENT_SHA = '780975de25e4f795c229a78058113c68a196a7e77a917c2608a53db42dd35740'
BRIDGE_SHA = '397beb18a2b4decc3683a962b43fbbf5691148a8c65bd83dbc32f4a833c5b572'
MANIFEST = 'build/ddr_parallel_sources_v9_v2/manifest.json'
MANIFEST_SHA = 'e4327fe756a1a6537eb1ac0bac8946bf9fc440ec2fae477d4b6364eb00718b2d'
TRANSFORM = 'tests/graphics/prepare_bt_parallel_ddr_write.py'
TRANSFORM_SHA = 'cb61d4ce35648066f6c31a463f64420ed4f08bae0ecbdf0e7810a8b1cdaf1f57'
TOP = 'Arcade-Battletoads.sv'
TOP_OLD = 'b1a1b77918f8c9a883f349a221db7830c0a3126dcc144d0bcd80c7a0359580da'
CONTEXT = {
    TOP: 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf',
    'rtl/BT.sv': 'd4d78ae052a7510003990f56377537c790428f418bb6e56d3db42a5d21566aa0',
    'rtl/TMS34020/TMS34020.sv': '691e53a54c1796dc391e90afdc74679b9b10e285baafee6fec5151c5623efff3',
    'rtl/TMS34020/TMS34020_MC.sv': '026ffd76251e84a532fd749076f8fbc11d0792941df67140c69f9f8fd05adce0',
    'rtl/ddram.sv': 'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'rtl/bt_platform_io.sdc': '18aaeadc8ddf1006c4915818ab501084ab4af6d3f4d8621df643ea279bdd8ce8',
}
PLATFORM_SOURCES = ['tests/platform_features_tb.sv', 'rtl/bt_clock_enables.sv',
                    'rtl/bt_pause_bridge.sv', 'rtl/bt_nvram.sv']
BRIDGE_SOURCES = ['rtl/bt_video_ddr.sv', 'tests/fixtures/bt_video_ddr_rotation_oracle.sv',
                  'tests/bt_video_ddr_memory_equiv_tb.sv']


def check(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def target_name(node):
    return node.targets[0].id if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name) else None


def static_blocks(root, retained):
    """Execute the original AST nodes, including every original static check."""
    path = root / 'tests/verify_platform_features.py'
    text = path.read_text()
    function = next(n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef) and n.name == 'main')
    body = function.body
    boundary = next(i for i, n in enumerate(body) if target_name(n) == 'retained')
    report = next(i for i, n in enumerate(body) if target_name(n) == 'report')
    bridge = next(i for i, n in enumerate(body) if target_name(n) == 'bridge')
    asm = next(i for i, n in enumerate(body) if target_name(n) == 'asm')
    consistency = next(i for i, n in enumerate(body) if isinstance(n, ast.Assert) and 'original_hashes' in ast.get_source_segment(text, n.test))
    selected = {'source_contract': body[:boundary], 'original_phase_report': body[report:bridge],
                'source_raster': body[asm:consistency]}
    environment = runpy.run_path(str(path))
    check(environment['ROOT'].resolve() == root, 'Original runner root changed')
    environment['retained'] = retained
    records = {}
    messages = io.StringIO()
    with contextlib.redirect_stdout(messages):
        for name, nodes in selected.items():
            code = compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec')
            exec(code, environment)
            source = '\n'.join(text.splitlines()[nodes[0].lineno-1:nodes[-1].end_lineno]) + '\n'
            records[name] = {'first_line': nodes[0].lineno, 'last_line': nodes[-1].end_lineno,
                             'source_lf_sha256': sha(source.encode()),
                             'assertions': sum(isinstance(n, ast.Assert) for n in ast.walk(ast.Module(body=nodes, type_ignores=[])))}
    receipt = next(n for n in body if target_name(n) == 'receipt')
    phase_expression = next(value for key, value in zip(receipt.value.keys, receipt.value.values)
                            if isinstance(key, ast.Constant) and key.value == 'phase_coverage')
    environment['phase_coverage'] = eval(compile(ast.Expression(body=phase_expression), str(path), 'eval'), environment)
    records['original_coverage_expression'] = {'first_line': phase_expression.lineno,
        'last_line': phase_expression.end_lineno,
        'source_lf_sha256': sha(ast.get_source_segment(text, phase_expression).encode()), 'assertions': 0}
    return environment, records, messages.getvalue()


def qualify(root):
    parent_path = root / PARENT
    check(sha(parent_path.read_bytes()) == PARENT_SHA, 'Accepted platform receipt changed')
    parent = json.loads(parent_path.read_text())
    check(parent['status'] == 'PASS', 'Platform simulation did not pass')
    check(all(type(c['exit_code']) is int and c['exit_code'] == 0 for c in parent['commands']), 'Platform command failed')
    inputs = parent['inputs']
    check(set(PLATFORM_SOURCES).issubset(inputs), 'Missing compiled platform sources')
    current = {name: sha((root / name).read_bytes()) for name in inputs}
    changed = {name for name in inputs if current[name] != inputs[name]}
    check(changed == {TOP}, 'A platform simulator/static input changed beyond the reviewed top')
    check(inputs[TOP] == TOP_OLD, 'Wrong prior top')
    check({name: sha((root / name).read_bytes()) for name in CONTEXT} == CONTEXT, 'Wrong integrated v12 sources')

    check(sha((root / MANIFEST).read_bytes()) == MANIFEST_SHA, 'Top transform receipt changed')
    check(sha((root / TRANSFORM).read_bytes()) == TRANSFORM_SHA, 'Top transform helper changed')
    transform = json.loads((root / MANIFEST).read_text())
    check(transform['status'] == 'PASS' and transform['transform_source'] == TRANSFORM_SHA, 'Top transform incomplete')
    check(transform['base_sources'][TOP] == TOP_OLD and transform['candidate_sources'][TOP] == CONTEXT[TOP], 'Wrong top transform endpoints')
    edits = transform['edits'][TOP]
    check(len(edits) == 4, 'Unexpected top transform scope')
    top_raw = (root / TOP).read_bytes()
    top = top_raw.decode().replace('\r\n', '\n')
    check(top_raw == top.replace('\n', '\r\n').encode(), 'Current top is not the declared uniform CRLF stage')
    restored = top
    for edit in reversed(edits):
        check(restored.count(edit['after']) == 1, 'Top reversal anchor changed')
        restored = restored.replace(edit['after'], edit['before'], 1)
    check(sha(restored.encode()) == TOP_OLD, 'Exact original LF top bytes not recovered')
    forward = restored
    for edit in edits:
        check(forward.count(edit['before']) == 1, 'Top forward anchor changed')
        forward = forward.replace(edit['before'], edit['after'], 1)
    check(forward == top, 'Top transform not reversible')

    retained = parent_path.parent
    environment, blocks, messages = static_blocks(root, retained)
    relative = retained.relative_to(root).as_posix()
    expected = [environment['simulation_command'](['verilator', '--binary', '--assert', '--timing',
        '--top-module', 'platform_features_tb', '-Wno-fatal', '-j', '2', '--Mdir', relative+'/obj', *PLATFORM_SOURCES]),
        environment['simulation_command'](['./'+relative+'/obj/Vplatform_features_tb'])]
    check([c['command'] for c in parent['commands']] == expected, 'Actual platform commands/source list changed')
    check(environment['phase_coverage'] == parent['phase_coverage'], 'Prior coverage differs from retained PASS log')
    check(parent['phase_coverage'] == {'halt_acks': 4, 'resumed_F': 4, 'resumed_R': 4, 'closing_R_writes': 1, 'save_pulses': 1}, 'Missing actual pause/NVRAM coverage')

    bridge_path = Path(parent['bridge_receipt']).resolve()
    check(bridge_path.is_relative_to(retained), 'Bridge receipt escaped platform evidence')
    check(sha(bridge_path.read_bytes()) == parent['bridge_receipt_sha256'] == BRIDGE_SHA, 'Accepted bridge receipt changed')
    bridge = json.loads(bridge_path.read_text())
    check(bridge['status'] == 'PASS' and bridge['simulator'] == 'verilator', 'Memory bridge did not pass')
    check(len(bridge['commands']) == 2 and all(type(c['exit_code']) is int and c['exit_code'] == 0 for c in bridge['commands']), 'Bridge command failed')
    bridge_inputs = {}
    for item in bridge['inputs']:
        prefix = '/mnt/d/Arcade/AI/aCORES/BT/'
        check(item['path'].startswith(prefix), 'Unknown bridge input path')
        name = item['path'][len(prefix):]
        check(name not in bridge_inputs and sha((root / name).read_bytes()) == item['sha256'], 'Bridge compiled input changed')
        bridge_inputs[name] = item['sha256']
    check(set(bridge_inputs) == set(BRIDGE_SOURCES), 'Bridge source list changed')
    # Exact expression in the unchanged original qualifier, line 55.
    check(bridge['coverage'] == bridge['commands'][1]['stdout'].strip(), 'Bridge coverage detached from original stdout expression')
    pattern = r'PASS memory-only cycle equivalence: (\d+) cycles, (\d+) exhaustive sequences; (\d+) ordered commands \((\d+) reads/(\d+) writes\), (\d+) full-rate commands, (\d+) held/(\d+) full-skid cycles, all (\d+) masks and bursts'
    match = re.search(pattern, bridge['coverage'])
    check(match is not None, 'Missing actual bridge coverage')
    counts = list(map(int, match.groups()))
    check(counts == [565530, 65536, 22078, 11048, 11030, 4096, 19140, 18236, 256], 'Wrong bridge coverage')

    snapshots = current | bridge_inputs | CONTEXT
    snapshots.update({PARENT: PARENT_SHA, MANIFEST: MANIFEST_SHA, TRANSFORM: TRANSFORM_SHA,
                      bridge_path.relative_to(root).as_posix(): BRIDGE_SHA})
    for name in ['phase_0.log', 'phase_1.log']:
        path = retained / name
        snapshots[path.relative_to(root).as_posix()] = sha(path.read_bytes())
    helper = Path(__file__).resolve()
    snapshots[helper.relative_to(root).as_posix()] = sha(helper.read_bytes())
    check(all(sha((root / name).read_bytes()) == digest for name, digest in snapshots.items()), 'Input changed during qualification')
    return {'schema': 'bt-platform-current-source-edge-v1', 'status': 'PASS',
        'scope': 'Fresh v12 static source checks and exact top reversal; prior platform/bridge simulation applies through byte-identical compiled inputs. No new simulation, CPU/DDR-controller execution, SDC validation, physical timing, hardware or RBF claim.',
        'prior_simulation_receipt': PARENT, 'prior_simulation_sha256': PARENT_SHA,
        'prior_bridge_receipt': bridge_path.relative_to(root).as_posix(), 'prior_bridge_sha256': BRIDGE_SHA,
        'current_inputs': snapshots, 'compiled_input_identity': {name: snapshots[name] for name in PLATFORM_SOURCES + BRIDGE_SOURCES},
        'context_only_not_compiled': CONTEXT, 'top_edge': {'manifest': MANIFEST, 'manifest_sha256': MANIFEST_SHA,
            'old_raw_sha256': TOP_OLD, 'current_raw_sha256': CONTEXT[TOP], 'exact_full_top_reversal': True,
            'serialization_stage': {'original': 'uniform LF', 'current': 'uniform CRLF',
                'candidate_lf_sha256': sha(top.encode()), 'restored_original_lf_raw_sha256': sha(restored.encode())}, 'edits': edits},
        'static_assertion_blocks': blocks, 'static_output': messages, 'phase_coverage': parent['phase_coverage'],
        'bridge_coverage_expression': "commands[-1]['stdout'].strip() (original qualifier line 55)",
        'nvram_image_bytes': 8192, 'memory_bridge_coverage': dict(zip(['cycles', 'exhaustive_sequences', 'commands', 'reads', 'writes', 'full_rate_commands', 'held_cycles', 'full_skid_cycles', 'masks'], counts)),
        'new_simulations': 0, 'prior_receipts_unchanged': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    output = args.out.resolve() if args.out else root/'build/platform_features'/('platform-current-v12-'+uuid.uuid4().hex)/'receipt.json'
    check(output.is_relative_to(root/'build') and not output.exists(), 'Fresh isolated evidence path required')
    result = qualify(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({'status': result['status'], 'receipt': str(output), 'receipt_sha256': sha(output.read_bytes()),
                      'static_assertions': sum(b['assertions'] for b in result['static_assertion_blocks'].values()),
                      'phase_coverage': result['phase_coverage'], 'memory_bridge_coverage': result['memory_bridge_coverage'],
                      'new_simulations': 0}, sort_keys=True))


if __name__ == '__main__':
    main()
