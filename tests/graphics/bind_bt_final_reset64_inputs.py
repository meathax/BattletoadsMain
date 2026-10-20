"""Compose private v17 maxfan64 with the frozen v16 functional proof graph.

This verifies retained inputs/artifacts and declared source edges. It never
starts a compiler, simulator, Quartus, Git mutation or hardware operation.
"""
import argparse
import ast
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
TOP = 'Arcade-Battletoads.sv'
V16 = ROOT / 'build/timing_closure_20261011/reset_fanout_v16_private'
V16_SNAPSHOT = V16.parent / (V16.name + '-snapshot.json')
V16_SNAPSHOT_SHA = '2db7810663dafc319f1463fd11576487b269542dc3346b8f625afaa6d1a9c50b'
V17_SNAPSHOT_SHA = 'ac3d3002057fbcd742266306847ab49d52322fa5023abd1772b2f7a5ea66e172'
PARENT = ROOT / 'build/final_v16_current_input_qualification/receipt.json'
PARENT_SHA = '241cf5ae79c999023c8b2646bb23fb4b7854a6388218db9caea06cf27bf7d045'
PARENT_HELPER = ROOT / 'tests/graphics/bind_bt_final_reset_inputs.py'
PARENT_HELPER_SHA = '2a689b29c7c672d796b08531049ec58fdadc4ed6d8d32a9e9aae8650843b1cd7'
EDGE = ROOT / 'build/reset_maxfan64_v15_v1'
MANIFEST_SHA = 'a66a98711af2129aed5c4a2f53886355d1922dab88ea392903ee021d19573b4f'
PROOF_SHA = 'b07a45778dd54acb891929d06656cacf15927b631b0a047b6437c2c44e179b1f'
PRESERVATION_SHA = 'f8c1bd8b2761c0fe57bf2fe7f141649a38d8f1d18555bcad0a78d7a3ee2e15f1'
PREPARER = ROOT / 'tests/graphics/prepare_bt_reset_maxfan64.py'
PREPARER_SHA = '4a18d669855788a14b0619f195e8f0e8738c53bcc97b2d557a26bb435bcc5c83'
QUALIFIER = ROOT / 'tests/graphics/qualify_bt_reset_maxfan64.py'
QUALIFIER_SHA = '3912ae3ce588b52364a8859ef7b94653a3df0d2336e863e9623121d549fdf8c1'
ORIGINAL_TOP_SHA = 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf'
OLD_TOP_SHA = '618da541646cf5a902a3d8e8cc94ac7a047f8bd0636282293d970b90f83ca92c'
NEW_TOP_SHA = '83a3fd9dc63a86028a5cd8bdcde61bdd9fe3949211036bbac2c5b2d66350bbbb'
ORIGINAL = b"\treg reset = 1'b1;\r\n"
OLD = b"\t(* maxfan = 32 *) reg reset = 1'b1;\r\n"
NEW = b"\t(* maxfan = 64 *) reg reset = 1'b1;\r\n"
ATTRIBUTE = b'(* maxfan = 64 *) '
SCHEMA = 'bt-v17-current-input-reset64-composition-v1'
STATUS = 'PASS_SCOPED_COMPOSITION'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def parent_helper():
    import hashlib
    assert hashlib.sha256(PARENT_HELPER.read_bytes()).hexdigest() == PARENT_HELPER_SHA
    return load(PARENT_HELPER, 'frozen_v16_reset64_composition_parent')


def validate_inventory(current, parent):
    assert len(current['sources']) == len(parent['sources']) == 144
    assert set(current['sources']) == set(parent['sources'])
    changed = {name for name in current['sources'] if current['sources'][name] != parent['sources'][name]}
    assert changed == {TOP}, 'Only the declared reset maxfan32 to maxfan64 edge may change'
    assert current['sources'][TOP] == NEW_TOP_SHA and parent['sources'][TOP] == OLD_TOP_SHA
    assert current['original_qsf_sha256'] == parent['original_qsf_sha256']
    assert current['build_date'] == parent['build_date'] == '261011'
    assert current['constraints_changed'] is False and current['timing_budgets_changed'] is False
    return changed


def inverse_to32(data, sha):
    assert data.count(NEW) == data.count(ATTRIBUTE) == 1 and data.count(OLD) == 0
    restored = data.replace(NEW, OLD, 1)
    assert sha(restored) == OLD_TOP_SHA, 'Foreign top byte outside one fanout value'
    return restored


def function_bytes(data, name):
    source = data.decode('utf-8')
    nodes = [node for node in ast.parse(source).body if isinstance(node, ast.FunctionDef) and node.name == name]
    assert len(nodes) == 1
    return ast.get_source_segment(source, nodes[0]).encode('utf-8')


def serialized_function_edge(old, new):
    """Require one exact LF-to-CRLF serialization, without ignoring other bytes."""
    assert b'\r' not in old and b'\r' not in new.replace(b'\r\n', b'')
    assert new == old.replace(b'\n', b'\r\n'), 'Change outside reviewed helper line-ending serialization'


def verify_composition_receipt(path):
    helper = parent_helper()
    result = json.loads(Path(path).read_bytes())
    assert result['schema'] == SCHEMA and result['status'] == STATUS
    assert result['helper_sha256'] == helper.sha(Path(__file__).read_bytes())
    assert result['snapshot_sha256'] == V17_SNAPSHOT_SHA and result['parent_v16_receipt']['sha256'] == PARENT_SHA
    assert result['all144_source_inventory_entries_verified'] is True and result['unchanged_sources'] == 143
    assert result['only_changed_sources'] == [TOP]
    assert result['new_compiler_or_simulator_run'] is False and result['new_whole_board_native_run'] is False
    assert result['timing_accepted'] is False and result['eligible_for_RBF'] is False
    evidence = helper.Evidence()
    for name, expected in result['bound_evidence_files'].items():
        evidence.file(name, expected)
    for key, expected in result['immutable_git_oracles'].items():
        evidence.git(key, expected)
    assert len(evidence.oracles) == 10 and len(result['new_negative_controls']) == 14
    assert all(item['rejected'] for item in result['new_negative_controls'])
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
    helper = parent_helper()
    evidence = helper.Evidence()
    evidence.file(Path(__file__))
    parent = json.loads(evidence.file(PARENT, PARENT_SHA))
    assert helper.verify_composition_receipt(PARENT)['status'] == STATUS
    assert len(parent['bound_evidence_files']) == 830
    for name, expected in parent['bound_evidence_files'].items():
        evidence.files[str(Path(name).resolve())] = expected
    evidence.file(PARENT_HELPER, PARENT_HELPER_SHA)
    for key, expected in parent['immutable_git_oracles'].items():
        evidence.git(key, expected)
    old_inventory = json.loads(evidence.file(V16_SNAPSHOT, V16_SNAPSHOT_SHA))
    inventory_path = current.parent / (current.name + '-snapshot.json')
    inventory = json.loads(evidence.file(inventory_path, V17_SNAPSHOT_SHA))
    assert Path(inventory['project']).resolve().parent == current
    assert Path(inventory['parent_manifest']).resolve() == V16_SNAPSHOT and inventory['parent_manifest_sha256'] == V16_SNAPSHOT_SHA
    changed = validate_inventory(inventory, old_inventory)
    for name, digest in inventory['sources'].items():
        (current / name).resolve().relative_to(current)
        evidence.file(current / name, digest)
    old = evidence.file(V16 / TOP, OLD_TOP_SHA)
    new = evidence.file(current / TOP, NEW_TOP_SHA)
    assert inverse_to32(new, helper.sha) == old
    original = evidence.file(EDGE / 'oracle' / TOP, ORIGINAL_TOP_SHA)
    assert new.replace(NEW, ORIGINAL, 1) == old.replace(OLD, ORIGINAL, 1) == original
    assert new == evidence.file(EDGE / 'candidate' / TOP, NEW_TOP_SHA)
    manifest = json.loads(evidence.file(EDGE / 'manifest.json', MANIFEST_SHA))
    proof = json.loads(evidence.file(EDGE / 'proof-r2/receipt.json', PROOF_SHA))
    preservation = json.loads(evidence.file(EDGE / 'harness-preservation.json', PRESERVATION_SHA))
    assert manifest['schema'] == 'bt-v15-reset-maxfan64-edge-v1' and manifest['attribute'] == 'maxfan = 64'
    assert manifest['parent_sha256'] == proof['parent_sha256'] == ORIGINAL_TOP_SHA
    assert manifest['candidate_sha256'] == proof['candidate_sha256'] == NEW_TOP_SHA
    assert manifest['raw_full_top_inverse_identical'] and manifest['producer_behavior_without_attribute_byte_identical']
    assert manifest['registers_added'] == manifest['reset_latency_edges_added'] == 0
    assert proof['schema'] == 'bt-reset-maxfan64-qualification-v1' and proof['status'] == 'PASS'
    assert proof['raw_full_top_inverse_identical'] and proof['attribute_only_infinite_trace_identity']
    assert proof['compiled_actual_original_and_candidate_producer_scopes'] and proof['independent_nba_chronology_model']
    assert proof['producer_original_edges_initial_values_rhs_and_every_consumer_unchanged']
    assert proof['clock_periods_ps'] == {'clk_sys': 12500, 'clk_mem': 6250}
    assert proof['return_codes'] == {'version': 0, 'compile': 0, 'run': 0} and proof['timing_accepted'] is False
    assert manifest['timing_accepted'] is False
    for item in proof['artifacts']:
        evidence.file(item['path'], item['sha256'])
    prepare_bytes = evidence.file(PREPARER, PREPARER_SHA)
    qualifier_bytes = evidence.file(QUALIFIER, QUALIFIER_SHA)
    preparer = load(PREPARER, 'frozen_reset64_edge')
    qualifier = load(QUALIFIER, 'frozen_reset64_actual_qualification')
    assert preparer.OLD == ORIGINAL and preparer.NEW == NEW and preparer.ATTRIBUTE == ATTRIBUTE
    assert preparer.transform(original) == new and preparer.reverse(new) == original
    old_block, new_block = preparer.producer(original), preparer.producer(new)
    assert new_block.replace(ATTRIBUTE, b'') == old_block
    assert helper.sha(old_block) == manifest['old_producer_sha256'] and helper.sha(new_block) == manifest['new_producer_sha256']
    assert manifest['init'] == {'reset': 1, 'fg_ddr_ready_sys': 0, 'reset_mem': 1, 'fg_ddr_clear_init_n': 0}
    assert preservation['schema'] == 'bt-reset-maxfan64-reviewed-harness-edge-v1' and preservation['status'] == 'PASS'
    assert preservation['reviewed32_receipt']['sha256'] == helper.PROOF_SHA
    assert preservation['fresh64_proof']['sha256'] == PROOF_SHA and Path(preservation['fresh64_proof']['path']).resolve() == EDGE / 'proof-r2/receipt.json'
    assert preservation['wrapper_bench_reject_load_functions_byte_identical'] and preservation['old_receipts_unchanged']
    reviewed32_qualifier = evidence.file(helper.QUALIFIER, helper.QUALIFIER_SHA)
    reviewed32_preparer = evidence.file(helper.PREPARER, helper.PREPARER_SHA)
    helper_eol_edges = {}
    for label, names, before_bytes, after_bytes in (
            ('qualifier', ('wrapper', 'bench', 'reject', 'load'), reviewed32_qualifier, qualifier_bytes),
            ('preparer', ('transform', 'reverse', 'producer'), reviewed32_preparer, prepare_bytes)):
        assert b'\r' not in before_bytes and b'\r' not in after_bytes.replace(b'\r\n', b'')
        assert after_bytes.count(b'\n') == after_bytes.count(b'\r\n')
        for name in names:
            before_function, after_function = function_bytes(before_bytes, name), function_bytes(after_bytes, name)
            serialized_function_edge(before_function, after_function)
            helper_eol_edges[label + '.' + name] = {
                'old_raw_function_sha256': helper.sha(before_function),
                'new_raw_function_sha256': helper.sha(after_function),
                'raw_function_bytes_identical': before_function == after_function,
                'strict_reversible_LF_to_CRLF_serialization': True,
                'Python_universal_newline_function_body_identical': True}
    assert preservation['new64_helpers'] == {PREPARER.name: PREPARER_SHA, QUALIFIER.name: QUALIFIER_SHA}
    assert preservation['reviewed32_helpers'] == {helper.PREPARER.name: helper.PREPARER_SHA, helper.QUALIFIER.name: helper.QUALIFIER_SHA}
    bench = evidence.file(EDGE / 'proof-r2/reset_maxfan_tb.sv')
    assert bench == qualifier.bench(old_block, new_block).replace('\n', '\r\n').encode()
    coverage = {'sys_edges': 66699, 'mem_edges': 133397, 'assertions': 483, 'releases': 484,
                'held': 65732, 'coincident': 66699, 'off_edge_holds': 65667,
                'directed_input_tuples': 128, 'random_input_tuples': 65536, 'initial_scope_comparisons': 2}
    assert proof['coverage'] == coverage
    run_log = evidence.file(EDGE / 'proof-r2/run.log')
    marker = re.search(rb'PASS RESET_MAXFAN sys_edges=(\d+) mem_edges=(\d+) assertions=(\d+) releases=(\d+) held=(\d+) coincident=(\d+) off_edge_holds=(\d+) tuples=128 random_tuples=65536 init_checks=2', run_log)
    assert marker and tuple(map(int, marker.groups())) == tuple(coverage[key] for key in ('sys_edges', 'mem_edges', 'assertions', 'releases', 'held', 'coincident', 'off_edge_holds'))
    helper.no_failure(run_log); helper.no_failure(evidence.file(EDGE / 'proof-r2/compile.log'))
    assert proof['version'] in evidence.file(EDGE / 'proof-r2/version.log').decode()
    assert proof['commands']['compile'][-1] == 'build/reset_maxfan64_v15_v1/proof-r2/reset_maxfan_tb.sv'
    assert proof['commands']['run'][-1] == './build/reset_maxfan64_v15_v1/proof-r2/obj/Vreset_maxfan_tb'
    assert len(proof['negative_controls']) == 9 and all(item['rejected'] for item in proof['negative_controls'])
    for name, digest in inventory['qualification_evidence'].items():
        evidence.file(name, digest)
    controls = []
    helper.reject('wrong64 candidate uses32', lambda: inverse_to32(old, helper.sha), controls)
    helper.reject('changed declaration init', lambda: inverse_to32(new.replace(b"reg reset = 1'b1;", b"reg reset = 1'b0;", 1), helper.sha), controls)
    helper.reject('helper serialization includes foreign token', lambda: serialized_function_edge(function_bytes(reviewed32_qualifier, 'wrapper'), function_bytes(qualifier_bytes, 'wrapper') + b' '), controls)
    helper.reject('added reset capture gate', lambda: inverse_to32(new.replace(b'clk_sys) reset <=', b'clk_sys) if (locked) reset <=', 1), helper.sha), controls)
    helper.reject('changed MEM copy edge', lambda: inverse_to32(new.replace(b'reset_mem <= reset;', b'reset_mem <= RESET;', 1), helper.sha), controls)
    helper.reject('unrelated downstream edit', lambda: inverse_to32(new + b'// foreign top edit\n', helper.sha), controls)
    helper.reject('foreign original parent', lambda: preparer.transform(original + b'\n'), controls)
    bad = json.loads(json.dumps(inventory)); del bad['sources']['rtl/fg_vram.sv']
    helper.reject('missing consumed input', lambda: validate_inventory(bad, old_inventory), controls)
    bad = json.loads(json.dumps(inventory)); bad['sources']['rtl/bt_platform_io.sdc'] = '0' * 64
    helper.reject('undeclared timing constraint change', lambda: validate_inventory(bad, old_inventory), controls)
    helper.reject('changed log with preserved counts', lambda: helper.same(run_log + b'\n', helper.sha(run_log)), controls)
    helper.reject('false PASS plus failure', lambda: helper.no_failure(run_log + b'\nFAIL unreviewed\n'), controls)
    helper.reject('changed actual compiled bench', lambda: helper.same(bench + b'\n', helper.sha(bench)), controls)
    helper.reject('changed harness preservation graph', lambda: helper.same((EDGE / 'harness-preservation.json').read_bytes() + b'\n', PRESERVATION_SHA), controls)
    helper.reject('changed reset contributor', lambda: inverse_to32(new.replace(b'reset <= RESET |', b'reset <= !RESET |', 1), helper.sha), controls)
    preserved = {'reset64_actual_proof': proof['negative_controls'], 'v16_source_composition': parent['new_negative_controls'], **parent['preserved_negative_controls']}
    assert all(item['rejected'] for values in preserved.values() for item in values)
    evidence.recheck()
    result = {'schema': SCHEMA, 'status': STATUS, 'helper_sha256': helper.sha(Path(__file__).read_bytes()),
              'source_root': str(current), 'snapshot': str(inventory_path), 'snapshot_sha256': V17_SNAPSHOT_SHA,
              'all144_source_inventory_entries_verified': True, 'only_changed_sources': sorted(changed), 'unchanged_sources': 143,
              'parent_v16_receipt': {'path': str(PARENT), 'sha256': PARENT_SHA, 'untouched': True},
              'parent_v16_snapshot': {'path': str(V16_SNAPSHOT), 'sha256': V16_SNAPSHOT_SHA},
              'reset64_edge': {'original_top_sha256': ORIGINAL_TOP_SHA, 'previous32_top_sha256': OLD_TOP_SHA, 'candidate_top_sha256': NEW_TOP_SHA,
                               'manifest': str(EDGE / 'manifest.json'), 'manifest_sha256': MANIFEST_SHA,
                               'actual_chronology_proof': str(EDGE / 'proof-r2/receipt.json'), 'actual_chronology_proof_sha256': PROOF_SHA,
                               'harness_preservation': str(EDGE / 'harness-preservation.json'), 'harness_preservation_sha256': PRESERVATION_SHA,
                               'raw_full_top_inverse_to_original_and32': True, 'producer_without_attribute_byte_identical': True,
                               'all_consumer_tokens_unchanged': True, 'declaration_init': "1'b1", 'added_registers': 0, 'added_capture_edges': 0,
                               'regenerated_actual_compiled_bench_byte_identical': True,
                               'retained_wrapper_bench_reject_load_raw_function_identity': False,
                               'helper_function_line_ending_edges': helper_eol_edges,
                               'retained_harness_receipt_claim_review': 'The unchanged f8c1 receipt says byte-identical functions. Their raw bytes are LF versus uniform CRLF; this binder independently proves the exact reversible serialization and unchanged Python function bodies, without relabeling that raw-byte claim.',
                               'coverage': coverage, 'compiled_scope': 'Two-state actual old/64 producers and unchanged independent NBA model; four-state declaration/body identity is established by both complete raw inverses.',
                               'earlier_attempt': 'The initial sandbox-denied version probe remains separately retained in proof/. This graph accepts only the distinct actual Ubuntu proof-r2 compilation/execution and does not relabel the failed probe.'},
              'composed_scopes': {'retained_v16_graph': parent['composed_scopes'],
                                  'ordinary143_consumed_inputs': 'Raw identical to v16. The original CPU/MC/DDR/FG/BG/Intel/collision/pause/NVRAM/function/stage/ABI graph and all executed source/bench/log hashes remain unchanged.',
                                  'top_reset': 'Only one synthesis fanout request value changes32 to64. Complete raw inverses preserve every original init, contributor, clock, enable, CDC/MEM edge, consumer and pin.',
                                  'native128': 'Retained only at its actual parent source execution. No new board-native run or retag as v16/v17 is claimed.'},
              'baseline_git_head': inventory['git_head'], 'bound_evidence_files': evidence.files, 'immutable_git_oracles': evidence.oracles,
              'new_negative_controls': controls, 'preserved_negative_controls': preserved,
              'new_compiler_or_simulator_run': False, 'new_Quartus_run': False, 'new_whole_board_native_run': False,
              'mapped_resource_claim': False, 'timing_accepted': False, 'mister_hardware_qualified': False,
              'eligible_for_RBF': False, 'legacy_verify_timing_modified': False,
              'scope': 'Separate exact v16 to v17 functional source composition. Previous receipts/executions and timing failures remain immutable. Actual fitted fanout/replicas, all8 setup/hold and remaining timing, release pads and hardware acceptance are independent gates.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({**verify_composition_receipt(output), 'receipt_sha256': helper.sha(output.read_bytes()),
                      'new_negative_controls': len(controls), 'snapshot_sha256': V17_SNAPSHOT_SHA,
                      'reset_sys_edges': coverage['sys_edges'], 'reset_mem_edges': coverage['mem_edges']}))


if __name__ == '__main__':
    main()
