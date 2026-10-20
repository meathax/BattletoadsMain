"""Compose the private v16 reset attribute with the immutable v15 proof graph.

Only retained sources, executed artifacts and Git blobs are read. No compiler,
simulator, Quartus job, board replay, Git write or hardware action is started.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TOP = 'Arcade-Battletoads.sv'
V15 = ROOT / 'build/timing_closure_20261011/cpu_locator_v15_private'
V15_SNAPSHOT = V15.parent / (V15.name + '-snapshot.json')
V15_SNAPSHOT_SHA = '40e06ad6b48607845413f1216e39bf180a8659fb8382fd4983cdc64b18f0858e'
V16_SNAPSHOT_SHA = '2db7810663dafc319f1463fd11576487b269542dc3346b8f625afaa6d1a9c50b'
PARENT = ROOT / 'build/final_v15_current_input_qualification/receipt.json'
PARENT_SHA = '31fcfe88957ee3cf4e584a15bb3c21968142a77e73e5e15c76d7b39a9aeb742f'
PARENT_HELPER = ROOT / 'tests/graphics/bind_bt_final_locator_inputs.py'
PARENT_HELPER_SHA = '09dc00082afe916287bd512879e4499253aedff4d454ef4172b0066fe1bb0051'
V13_RECEIPT = ROOT / 'build/final_v13_current_input_qualification/receipt.json'
V13_RECEIPT_SHA = 'd6e51a25915d92145fda9291b8523cf6cc506e31f403b2b46da501e84a42c5ea'
EDGE = ROOT / 'build/reset_maxfan_v15_v1'
MANIFEST_SHA = '59192152312db439fa507565a01a48c60abf99b94a8cd60affb5ee54239ff08f'
PROOF_SHA = '8e7affd6008dc90960d248598997808e9cb14e22fa37a64eecba80749ae017ab'
PREPARER = ROOT / 'tests/graphics/prepare_bt_reset_maxfan.py'
PREPARER_SHA = 'eb58299611b74c92adba2c1d6d6898c3ddca4b7d300e7bebf8c5beedfb0592de'
QUALIFIER = ROOT / 'tests/graphics/qualify_bt_reset_maxfan.py'
QUALIFIER_SHA = 'd67067826bc0d34ddaa31e9a7dfb090c0abd7ef5c5716f7cf2ffe06d9a0f0087'
OLD_TOP_SHA = 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf'
NEW_TOP_SHA = '618da541646cf5a902a3d8e8cc94ac7a047f8bd0636282293d970b90f83ca92c'
OLD = b"\treg reset = 1'b1;\r\n"
NEW = b"\t(* maxfan = 32 *) reg reset = 1'b1;\r\n"
ATTRIBUTE = b'(* maxfan = 32 *) '
GIT = 'D:/vibes/fpga/bin/git.EXE'
SCHEMA = 'bt-v16-current-input-reset-composition-v1'
STATUS = 'PASS_SCOPED_COMPOSITION'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Evidence:
    def __init__(self):
        self.files = {}
        self.oracles = {}

    def file(self, path, expected=None):
        path = Path(path).resolve()
        assert path.is_file() and not path.is_symlink(), ('Missing retained file', str(path))
        data = path.read_bytes()
        digest = sha(data)
        assert expected is None or digest == expected, ('Changed fingerprint', str(path))
        assert str(path) not in self.files or self.files[str(path)] == digest, 'Evidence changed during binding'
        self.files[str(path)] = digest
        return data

    def git(self, key, expected):
        commit, name = key.split(':', 1)
        assert re.fullmatch(r'[0-9a-f]{40}', commit)
        data = subprocess.check_output([GIT, 'show', commit + ':' + name], cwd=ROOT)
        assert sha(data) == expected, ('Immutable Git provenance changed', key)
        self.oracles[key] = expected

    def recheck(self):
        for name, expected in self.files.items():
            assert sha(Path(name).read_bytes()) == expected, ('Evidence changed during binding', name)


def validate_inventory(current, parent):
    assert len(current['sources']) == len(parent['sources']) == 144
    assert set(current['sources']) == set(parent['sources'])
    changed = {name for name in current['sources'] if current['sources'][name] != parent['sources'][name]}
    assert changed == {TOP}, 'Only the proved reset declaration attribute may change'
    assert parent['sources'][TOP] == OLD_TOP_SHA and current['sources'][TOP] == NEW_TOP_SHA
    assert current['original_qsf_sha256'] == parent['original_qsf_sha256']
    assert current['build_date'] == parent['build_date'] == '261011'
    assert current['constraints_changed'] is False and current['timing_budgets_changed'] is False
    return changed


def inverse(data):
    assert data.count(NEW) == data.count(ATTRIBUTE) == 1 and data.count(OLD) == 0
    restored = data.replace(NEW, OLD, 1)
    assert sha(restored) == OLD_TOP_SHA, 'Unreviewed change outside reset maxfan attribute'
    return restored


def same(data, expected):
    assert sha(data) == expected, 'Changed retained artifact/source'


def no_failure(data):
    assert not re.search(rb'%Error|Assertion failed|\b(?:FAIL|FATAL|Aborting)\b', data), 'Failure in retained compiler/execution log'


def reject(name, operation, controls):
    try:
        operation()
    except (AssertionError, ValueError):
        controls.append({'name': name, 'rejected': True})
        return
    raise AssertionError('Negative control accepted: ' + name)


def verify_composition_receipt(path):
    """Rehash this frozen graph without launching or relabeling its executions."""
    result = json.loads(Path(path).read_bytes())
    assert result['schema'] == SCHEMA and result['status'] == STATUS
    assert result['helper_sha256'] == sha(Path(__file__).read_bytes())
    assert result['snapshot_sha256'] == V16_SNAPSHOT_SHA
    assert result['parent_v15_receipt']['sha256'] == PARENT_SHA
    assert result['all144_source_inventory_entries_verified'] is True
    assert result['only_changed_sources'] == [TOP] and result['unchanged_sources'] == 143
    assert result['new_compiler_or_simulator_run'] is False and result['new_whole_board_native_run'] is False
    assert result['timing_accepted'] is False and result['eligible_for_RBF'] is False
    evidence = Evidence()
    for name, expected in result['bound_evidence_files'].items():
        evidence.file(name, expected)
    for key, expected in result['immutable_git_oracles'].items():
        evidence.git(key, expected)
    assert len(evidence.oracles) == 10
    assert all(item['rejected'] for item in result['new_negative_controls'])
    assert len(result['new_negative_controls']) == 14
    assert all(item['rejected'] for values in result['preserved_negative_controls'].values() for item in values)
    evidence.recheck()
    return {'status': STATUS, 'verified_evidence_files': len(evidence.files),
            'verified_immutable_git_oracles': len(evidence.oracles), 'receipt': str(Path(path).resolve())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    current, output = args.source_root.resolve(), args.output.resolve()
    current.relative_to(ROOT / 'build'); output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite an accepted or failed record'
    evidence = Evidence()
    evidence.file(Path(__file__))
    parent = json.loads(evidence.file(PARENT, PARENT_SHA))
    evidence.file(PARENT_HELPER, PARENT_HELPER_SHA)
    assert parent['schema'] == 'bt-v15-current-input-locator-composition-v1' and parent['status'] == STATUS
    assert parent['helper_sha256'] == PARENT_HELPER_SHA and parent['snapshot_sha256'] == V15_SNAPSHOT_SHA
    assert parent['all144_source_inventory_entries_verified'] is True and len(parent['bound_evidence_files']) == 670
    for name, expected in parent['bound_evidence_files'].items():
        evidence.file(name, expected)
    v13 = json.loads(evidence.file(V13_RECEIPT, V13_RECEIPT_SHA))
    assert v13['status'] == STATUS and len(v13['immutable_git_oracles']) == 10
    for key, expected in v13['immutable_git_oracles'].items():
        evidence.git(key, expected)
    old_inventory = json.loads(evidence.file(V15_SNAPSHOT, V15_SNAPSHOT_SHA))
    inventory_path = current.parent / (current.name + '-snapshot.json')
    inventory = json.loads(evidence.file(inventory_path, V16_SNAPSHOT_SHA))
    assert Path(inventory['project']).resolve().parent == current
    assert Path(inventory['parent_manifest']).resolve() == V15_SNAPSHOT
    assert inventory['parent_manifest_sha256'] == V15_SNAPSHOT_SHA
    changed = validate_inventory(inventory, old_inventory)
    for name, digest in inventory['sources'].items():
        (current / name).resolve().relative_to(current)
        evidence.file(current / name, digest)
        evidence.file(V15 / name, old_inventory['sources'][name])
    old = evidence.file(V15 / TOP, OLD_TOP_SHA)
    new = evidence.file(current / TOP, NEW_TOP_SHA)
    assert inverse(new) == old
    manifest = json.loads(evidence.file(EDGE / 'manifest.json', MANIFEST_SHA))
    proof = json.loads(evidence.file(EDGE / 'proof/receipt.json', PROOF_SHA))
    assert manifest['schema'] == 'bt-v15-reset-maxfan32-edge-v1'
    assert manifest['parent_sha256'] == proof['parent_sha256'] == OLD_TOP_SHA
    assert manifest['candidate_sha256'] == proof['candidate_sha256'] == NEW_TOP_SHA
    assert manifest['raw_full_top_inverse_identical'] and manifest['producer_behavior_without_attribute_byte_identical']
    assert manifest['registers_added'] == manifest['reset_latency_edges_added'] == 0
    assert proof['schema'] == 'bt-reset-maxfan32-qualification-v1' and proof['status'] == 'PASS'
    assert proof['raw_full_top_inverse_identical'] and proof['attribute_only_infinite_trace_identity']
    assert proof['compiled_actual_original_and_candidate_producer_scopes'] and proof['independent_nba_chronology_model']
    assert proof['producer_original_edges_initial_values_rhs_and_every_consumer_unchanged']
    assert proof['clock_periods_ps'] == {'clk_sys': 12500, 'clk_mem': 6250}
    assert proof['return_codes'] == {'version': 0, 'compile': 0, 'run': 0}
    assert manifest['timing_accepted'] is proof['timing_accepted'] is False
    artifacts = {}
    for item in proof['artifacts']:
        path = Path(item['path']).resolve()
        assert str(path) not in artifacts
        artifacts[str(path)] = evidence.file(path, item['sha256'])
    preparer = load(evidence_path := PREPARER, 'frozen_v16_reset_preparer')
    evidence.file(evidence_path, PREPARER_SHA)
    evidence.file(QUALIFIER, QUALIFIER_SHA)
    qualifier = load(QUALIFIER, 'frozen_v16_reset_qualifier')
    assert manifest['helper_sha256'] == PREPARER_SHA
    assert preparer.OLD == OLD and preparer.NEW == NEW and preparer.ATTRIBUTE == ATTRIBUTE
    assert preparer.transform(old) == new and preparer.reverse(new) == old
    assert old == evidence.file(EDGE / 'oracle' / TOP, OLD_TOP_SHA)
    assert new == evidence.file(EDGE / 'candidate' / TOP, NEW_TOP_SHA)
    old_block, new_block = preparer.producer(old), preparer.producer(new)
    assert new_block.replace(ATTRIBUTE, b'') == old_block
    assert sha(old_block) == manifest['old_producer_sha256'] and sha(new_block) == manifest['new_producer_sha256']
    assert manifest['init'] == {'reset': 1, 'fg_ddr_ready_sys': 0, 'reset_mem': 1, 'fg_ddr_clear_init_n': 0}
    bench_path = EDGE / 'proof/reset_maxfan_tb.sv'
    bench = evidence.file(bench_path)
    # The executed native Windows write_text serialization also translates LF
    # already preceded by the original CR producer bytes. Preserve exact bytes.
    assert bench == qualifier.bench(old_block, new_block).replace('\n', '\r\n').encode()
    coverage = {'sys_edges': 66699, 'mem_edges': 133397, 'assertions': 483, 'releases': 484,
                'held': 65732, 'coincident': 66699, 'off_edge_holds': 65667,
                'directed_input_tuples': 128, 'random_input_tuples': 65536, 'initial_scope_comparisons': 2}
    assert proof['coverage'] == coverage
    run_log = evidence.file(EDGE / 'proof/run.log')
    marker = re.search(rb'PASS RESET_MAXFAN sys_edges=(\d+) mem_edges=(\d+) assertions=(\d+) releases=(\d+) held=(\d+) coincident=(\d+) off_edge_holds=(\d+) tuples=128 random_tuples=65536 init_checks=2', run_log)
    assert marker and tuple(map(int, marker.groups())) == tuple(coverage[key] for key in ('sys_edges', 'mem_edges', 'assertions', 'releases', 'held', 'coincident', 'off_edge_holds'))
    no_failure(run_log); no_failure(evidence.file(EDGE / 'proof/compile.log'))
    assert proof['version'] in evidence.file(EDGE / 'proof/version.log').decode()
    assert proof['commands']['compile'][-1] == 'build/reset_maxfan_v15_v1/proof/reset_maxfan_tb.sv'
    assert proof['commands']['run'][-1] == './build/reset_maxfan_v15_v1/proof/obj/Vreset_maxfan_tb'
    report = evidence.file(manifest['fit_evidence']['path'], manifest['fit_evidence']['sha256'])
    assert report == evidence.file(EDGE / 'evidence/v15-corner1-setup.txt', manifest['fit_evidence']['sha256'])
    controls = []
    reject('missing reset attribute', lambda: inverse(old), controls)
    reject('foreign reset fanout value', lambda: inverse(new.replace(b'maxfan = 32', b'maxfan = 64', 1)), controls)
    reject('changed initialized reset', lambda: inverse(new.replace(b"reg reset = 1'b1;", b"reg reset = 1'b0;", 1)), controls)
    reject('added reset capture gate', lambda: inverse(new.replace(b'clk_sys) reset <=', b'clk_sys) if (locked) reset <=', 1)), controls)
    reject('changed MEM capture latency', lambda: inverse(new.replace(b'reset_mem <= reset;', b'reset_mem <= RESET;', 1)), controls)
    reject('unrelated downstream top change', lambda: inverse(new + b'// foreign top edit\n'), controls)
    reject('foreign full top parent', lambda: preparer.transform(old + b'\n'), controls)
    bad = json.loads(json.dumps(inventory)); bad['sources']['rtl/TMS34020/TMS34020_MC.sv'] = '0' * 64
    reject('undeclared MC input change', lambda: validate_inventory(bad, old_inventory), controls)
    bad = json.loads(json.dumps(inventory)); del bad['sources']['rtl/fg_vram.sv']
    reject('missing consumed input', lambda: validate_inventory(bad, old_inventory), controls)
    reject('changed retained collision/source graph', lambda: same(PARENT.read_bytes() + b'\n', PARENT_SHA), controls)
    reject('changed executed log with preserved counts', lambda: same(run_log + b'\n', sha(run_log)), controls)
    reject('changed actual compiled chronology model', lambda: same(bench + b'\n', sha(bench)), controls)
    reject('changed guarded reset helper', lambda: same(PREPARER.read_bytes() + b'\n', PREPARER_SHA), controls)
    reject('false PASS log with failure', lambda: no_failure(run_log + b'\nFAIL unreviewed\n'), controls)
    preserved = {'reset_actual_proof': proof['negative_controls'],
                 'v15_source_composition': parent['new_negative_controls'],
                 'locator_actual_proof': parent['preserved_CPU_proof_negative_controls'],
                 'v13_current_input_composition': parent['preserved_v13_negative_controls']}
    assert [len(preserved[key]) for key in preserved] == [9, 12, 9, 9]
    assert all(item['rejected'] for items in preserved.values() for item in items)
    # This live-root observation is contextual, not a future raw-root identity
    # requirement; immutable selected sources and baseline blobs are bound above.
    observed_head = subprocess.check_output([GIT, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    root_context = {name: sha((ROOT / name).read_bytes()) for name in (TOP, 'rtl/BT.sv', 'rtl/TMS34020/TMS34020.sv', 'rtl/TMS34020/TMS34020_MC.sv', 'rtl/fg_vram.sv', 'Arcade-Battletoads.qsf')}
    evidence.recheck()
    result = {'schema': SCHEMA, 'status': STATUS, 'helper_sha256': sha(Path(__file__).read_bytes()),
              'source_root': str(current), 'snapshot': str(inventory_path), 'snapshot_sha256': V16_SNAPSHOT_SHA,
              'all144_source_inventory_entries_verified': True, 'only_changed_sources': sorted(changed), 'unchanged_sources': 143,
              'parent_v15_receipt': {'path': str(PARENT), 'sha256': PARENT_SHA, 'untouched': True},
              'parent_v15_snapshot': {'path': str(V15_SNAPSHOT), 'sha256': V15_SNAPSHOT_SHA},
              'reset_edge': {'parent_sha256': OLD_TOP_SHA, 'candidate_sha256': NEW_TOP_SHA,
                             'manifest': str(EDGE / 'manifest.json'), 'manifest_sha256': MANIFEST_SHA,
                             'actual_chronology_proof': str(EDGE / 'proof/receipt.json'), 'actual_chronology_proof_sha256': PROOF_SHA,
                             'raw_full_top_inverse_identical': True, 'producer_without_attribute_byte_identical': True,
                             'all_original_consumer_tokens_unchanged': True, 'declaration_init': "1'b1",
                             'registers_added': 0, 'capture_latency_edges_added': 0, 'coverage': coverage,
                             'regenerated_actual_compiled_bench_byte_identical': True,
                             'compiled_test_scope': 'Two-state actual old/new producer blocks plus an independent NBA model; unchanged four-state producer/declaration tokens established by full raw inverse.'},
              'composed_scopes': {'retained_v15_graph': parent['composed_scopes'],
                                  'CPU_MC_fields_opcodes_ALU_shift_palette_pause_NVRAM_DDR_RAM_and_models': 'All 143 non-top consumed sources are raw identical to v15. The retained 31fc graph, executed source/fixtures/logs and immutable Git oracles were rehashed; no monitor or collision predicate changed.',
                                  'reset_and_every_consumer': 'Exactly one synthesis fanout attribute on the existing reset declaration. Raw full-top inverse preserves every original clock, initialization, reset contributor, CDC/MEM capture, consumer, pin and enable priority.',
                                  'native128': 'Preserved only at its actual parent execution source identity; not retagged as a v15 or v16 board replay.'},
              'baseline_git_head': inventory['git_head'], 'observed_root_context': {'git_head': observed_head, 'raw_core_sha256': root_context, 'context_only_not_selected_or_compiled_source_claim': True},
              'bound_evidence_files': evidence.files, 'immutable_git_oracles': evidence.oracles,
              'new_negative_controls': controls, 'preserved_negative_controls': preserved,
              'new_compiler_or_simulator_run': False, 'new_Quartus_run': False, 'new_whole_board_native_run': False,
              'mapped_resource_claim': False, 'timing_accepted': False, 'mister_hardware_qualified': False,
              'eligible_for_RBF': False, 'legacy_verify_timing_modified': False,
              'scope': 'Independent exact v15 to v16 functional source composition only. Failed parent timing remains failed. Retained executions remain immutable; actual fitted duplication, all-corner timing/hold, completed release pads and hardware acceptance are separate gates.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    verified = verify_composition_receipt(output)
    print(json.dumps({**verified, 'receipt_sha256': sha(output.read_bytes()), 'snapshot_sha256': V16_SNAPSHOT_SHA,
                      'new_negative_controls': len(controls), 'reset_sys_edges': coverage['sys_edges'], 'reset_mem_edges': coverage['mem_edges']}))


if __name__ == '__main__':
    main()
