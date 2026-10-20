"""Compose the four same-edge reset domains directly with the frozen v15 graph.

This reads retained source, executed proof artifacts and immutable Git blobs.
It starts no compiler, simulator, Quartus job, board replay or Git write.
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
V15_SNAPSHOT = V15.with_name(V15.name + '-snapshot.json')
V15_SNAPSHOT_SHA = '40e06ad6b48607845413f1216e39bf180a8659fb8382fd4983cdc64b18f0858e'
V18_SNAPSHOT_SHA = 'd4f54c0fb3b6a076177fc2382105c664d740d82482a6ca612e0418c5282880d8'
PARENT = ROOT / 'build/final_v15_current_input_qualification/receipt.json'
PARENT_SHA = '31fcfe88957ee3cf4e584a15bb3c21968142a77e73e5e15c76d7b39a9aeb742f'
PARENT_HELPER = ROOT / 'tests/graphics/bind_bt_final_locator_inputs.py'
PARENT_HELPER_SHA = '09dc00082afe916287bd512879e4499253aedff4d454ef4172b0066fe1bb0051'
V13_RECEIPT = ROOT / 'build/final_v13_current_input_qualification/receipt.json'
V13_RECEIPT_SHA = 'd6e51a25915d92145fda9291b8523cf6cc506e31f403b2b46da501e84a42c5ea'
EDGE = ROOT / 'build/reset_partition_v15_v1'
MANIFEST_SHA = '25a0bf107b90176c2c2ac69cfcbc946f5438a3989390bbf0c12f07912e2b1423'
PROOF_SHA = '31bffae9494fbab2809e70abd366d43a757d989f13d0c36980f04ba63dae4886'
PREPARER = ROOT / 'tests/graphics/prepare_bt_reset_partition.py'
PREPARER_SHA = '580d3b099099e38dcfaaacafa98fb89894f578ab309cde303da6094e0fd037a0'
QUALIFIER = ROOT / 'tests/graphics/qualify_bt_reset_partition.py'
QUALIFIER_SHA = 'f64cef09e605a690d7af7a5e2389f77b4b800f3efafd6e17c37ed617ef16384d'
CHRONOLOGY = ROOT / 'tests/graphics/qualify_bt_reset_maxfan.py'
CHRONOLOGY_SHA = 'd67067826bc0d34ddaa31e9a7dfb090c0abd7ef5c5716f7cf2ffe06d9a0f0087'
OLD_TOP_SHA = 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf'
NEW_TOP_SHA = '376c0dfe3c09abefe57fe9f195501abc15d29c59843afd0d1e02cbc0212fb7cb'
CLONES = ('reset_bt', 'reset_phase', 'reset_ddr', 'reset_video')
BINDINGS = (
    (b'\t\treset_mem <= reset;\r\n', b'\t\treset_mem <= reset_ddr;\r\n', 'MEM reset copy'),
    (b'\tbt_clock_enables clock_enables(.clk(clk_sys), .reset(reset),\r\n',
     b'\tbt_clock_enables clock_enables(.clk(clk_sys), .reset(reset_phase),\r\n', 'Clock enables'),
    (b'\t\tif (reset) user_pause <= 0;\r\n', b'\t\tif (reset_phase) user_pause <= 0;\r\n', 'User pause'),
    (b'\t    .clk(clk_sys), .reset(reset), .pause_req(pause_cpu),\r\n',
     b'\t    .clk(clk_sys), .reset(reset_phase), .pause_req(pause_cpu),\r\n', 'CPU pause bridge'),
    (b'\t\t.RST_N(~reset),\r\n', b'\t\t.RST_N(~reset_bt),\r\n', 'BT active-low reset'),
    (b'\t\t.reset(reset), .video_clk(clk_sys), .mem_clk(clk_mem),\r\n',
     b'\t\t.reset(reset_video), .video_clk(clk_sys), .mem_clk(clk_mem),\r\n', 'Video DDR bridge'),
)
GIT = 'D:/vibes/fpga/bin/git.EXE'
SCHEMA = 'bt-v18-current-input-reset-partition-composition-v1'
STATUS = 'PASS_SCOPED_COMPOSITION'
NEGATIVE_COUNT = 23


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Evidence:
    def __init__(self):
        self.files, self.oracles = {}, {}

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
    assert changed == {TOP}, 'Only the proved reset partition may change'
    assert parent['sources'][TOP] == OLD_TOP_SHA and current['sources'][TOP] == NEW_TOP_SHA
    assert current['original_qsf_sha256'] == parent['original_qsf_sha256']
    assert current['build_date'] == parent['build_date'] == '261011'
    assert current['constraints_changed'] is False and current['timing_budgets_changed'] is False
    return changed


def original_capture(data):
    matches = re.findall(rb'\talways @\(posedge clk_sys\) reset <= RESET \| buttons\[1\] \| status\[0\] \| rom_download \| ~rom_ready \|\r\n\t +~fg_ddr_ready_sys\[1\] \| ~locked;\r\n', data)
    assert len(matches) == 1, 'Original seven-term SYS reset capture changed'
    return matches[0]


def inverse(data):
    """Independently remove only the exact four clones and six declared aliases."""
    cap = original_capture(data)
    assert data.count(b"\treg reset = 1'b1;\r\n") == 1
    block = b'\t// Same-SYS-edge reset domains: each captures the original D, not the old reset Q.\r\n'
    for name in CLONES:
        block += b"\t(* preserve, dont_merge *) reg " + name.encode() + b" = 1'b1;\r\n"
    for name in CLONES:
        edge = cap.replace(b' reset <=', b' ' + name.encode() + b' <=', 1)
        assert edge.replace(b' ' + name.encode() + b' <=', b' reset <=', 1) == cap
        block += edge
    assert data.count(block) == 1
    restored = data.replace(block, b'', 1)
    for before, after, role in BINDINGS:
        assert restored.count(after) == 1, ('Missing or changed consumer alias', role)
        restored = restored.replace(after, before, 1)
    assert sha(restored) == OLD_TOP_SHA, 'Unreviewed top/source/consumer edit'
    return restored


def same(data, expected):
    assert sha(data) == expected, 'Changed retained artifact/source'


def no_failure(data):
    assert not re.search(rb'%Error|Assertion failed|\b(?:FAIL|FATAL|Aborting)\b', data), 'Failure in retained execution/compiler log'


def reject(name, operation, controls):
    try:
        operation()
    except (AssertionError, ValueError):
        controls.append({'name': name, 'rejected': True})
        return
    raise AssertionError('Negative control accepted: ' + name)


def retained_chronology(original, actual):
    """Check every original chronology body line across the declared additions."""
    before = original.encode().split(b'module reset_maxfan_tb;', 1)[1]
    after = actual.split(b'module reset_partition_tb;', 1)[1]
    changed_connections = 0
    retained_lines = 0
    for line in before.splitlines():
        if not line.strip():
            continue
        if re.search(rb'\.ready_sync_o\((?:old|new)_ready\)\);', line):
            assert line[:-2] in after, 'Original instance prefix changed'
            changed_connections += 1
        else:
            assert line in after, ('Removed original chronology/model/assertion line', line)
            retained_lines += 1
    assert changed_connections == 2
    messages = re.findall(rb'\$fatal\(1,"([^"\r\n]+)"\)', before)
    assert messages and all(message in after for message in messages)
    return {'unchanged_original_chronology_body_lines': retained_lines,
            'declared_appended_instance_connections': changed_connections,
            'original_fatal_assertions_retained': len(messages)}


def verify_composition_receipt(path):
    """Rehash the frozen graph; never rerun or relabel any underlying execution."""
    result = json.loads(Path(path).read_bytes())
    assert result['schema'] == SCHEMA and result['status'] == STATUS
    assert result['helper_sha256'] == sha(Path(__file__).read_bytes())
    assert result['snapshot_sha256'] == V18_SNAPSHOT_SHA
    assert result['parent_v15_receipt']['sha256'] == PARENT_SHA
    assert result['all144_source_inventory_entries_verified'] is True
    assert result['only_changed_sources'] == [TOP] and result['unchanged_sources'] == 143
    assert result['reset_partition_edge']['same_D_init_SYS_edge_four_state_induction'] is True
    assert result['reset_partition_edge']['registers_added'] == 4
    assert result['reset_partition_edge']['capture_latency_edges_added'] == 0
    assert result['new_compiler_or_simulator_run'] is False and result['new_whole_board_native_run'] is False
    assert result['timing_accepted'] is False and result['eligible_for_RBF'] is False
    evidence = Evidence()
    for name, expected in result['bound_evidence_files'].items():
        evidence.file(name, expected)
    for key, expected in result['immutable_git_oracles'].items():
        evidence.git(key, expected)
    assert len(evidence.oracles) == 10
    assert len(result['new_negative_controls']) == NEGATIVE_COUNT
    assert all(item['rejected'] for item in result['new_negative_controls'])
    assert [len(value) for value in result['preserved_negative_controls'].values()] == [15, 12, 9, 9]
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
    inventory_path = current.with_name(current.name + '-snapshot.json')
    inventory = json.loads(evidence.file(inventory_path, V18_SNAPSHOT_SHA))
    assert Path(inventory['project']).resolve().parent == current
    assert Path(inventory['derived_from_snapshot']['path']).resolve() == V15_SNAPSHOT
    assert inventory['derived_from_snapshot']['sha256'] == V15_SNAPSHOT_SHA
    assert inventory['functional_parent'] == {'path': str(PARENT), 'sha256': PARENT_SHA}
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
    assert manifest['schema'] == 'bt-v15-reset-partition-edge-v1'
    assert manifest['parent_sha256'] == proof['parent_sha256'] == OLD_TOP_SHA
    assert manifest['candidate_sha256'] == proof['candidate_sha256'] == NEW_TOP_SHA
    assert manifest['all144_sources'] == inventory['sources']
    assert manifest['functional_parent'] == inventory['functional_parent']
    assert manifest['unchanged_other143_sources'] is True
    assert proof['schema'] == 'bt-reset-partition-qualification-v18' and proof['status'] == 'PASS'
    assert manifest['source_equivalence'] == proof['source_equivalence']
    assert manifest['timing_accepted'] is proof['timing_accepted'] is False
    assert manifest['mapped_copies_proven'] is proof['mapped_copies_proven'] is False
    assert proof['actual_original_chronology_bench_assertions_retained'] is True
    assert proof['all7_consumer_roles_source_bound'] and proof['all5_reset_Qs_case_equal_pre_post_and_off_edge']
    assert proof['actual_compiled_consumer_scopes'] == ['clock_enables', 'user_pause', 'cpu_pause_bridge', 'async_audio_SCE_DIV', 'video_ddr']
    assert proof['clock_periods_ps'] == {'SYS': 12500, 'MEM': 6250}
    assert proof['return_codes'] == {'version': 0, 'compile': 0, 'run': 0, 'fourstate_compile': 0, 'fourstate_run': 0}
    artifacts = {}
    for item in proof['artifacts']:
        path = Path(item['path']).resolve()
        assert str(path) not in artifacts
        artifacts[str(path)] = evidence.file(path, item['sha256'])
    evidence.file(PREPARER, PREPARER_SHA)
    evidence.file(QUALIFIER, QUALIFIER_SHA)
    evidence.file(CHRONOLOGY, CHRONOLOGY_SHA)
    preparer = load(PREPARER, 'frozen_v18_partition_preparer')
    qualifier = load(QUALIFIER, 'frozen_v18_partition_qualifier')
    baseline = load(CHRONOLOGY, 'frozen_original_chronology')
    assert manifest['helper_sha256'] == PREPARER_SHA
    assert preparer.CLONES == CLONES and preparer.BINDINGS == BINDINGS
    assert preparer.transform(old) == new and preparer.reverse(new) == inverse(new) == old
    assert evidence.file(EDGE / 'oracle' / TOP, OLD_TOP_SHA) == old
    assert evidence.file(EDGE / 'candidate' / TOP, NEW_TOP_SHA) == new
    source_equivalence = preparer.source_equivalence(old, new)
    assert source_equivalence == manifest['source_equivalence']
    assert source_equivalence['registers_added'] == 4 and source_equivalence['latency_edges_added'] == 0
    assert source_equivalence['raw_full_top_inverse_identical'] and source_equivalence['original_reset_init_and_capture_bytes_unchanged']
    before, after = preparer.scopes(old), preparer.scopes(new)
    assert before['audio'] == after['audio']
    assert original_capture(old) == original_capture(new) == preparer.capture(old)
    original_bench = baseline.bench(before['producer'], after['producer'])
    bench = evidence.file(EDGE / 'proof/reset_partition_tb.sv')
    assert bench == qualifier.main_bench(baseline, before, after).encode(), 'Actual compiled full-consumer bench changed'
    chronology_scope = retained_chronology(original_bench, bench)
    xbench = evidence.file(EDGE / 'proof/reset_partition_fourstate_tb.sv')
    assert xbench == qualifier.fourstate_bench(before, after).encode(), 'Actual compiled four-state model changed'
    assert b'mr <= RESET|buttons[1]|status[0]|rom_download|~rom_ready|~ms[1]|~locked;' in xbench
    assert b'ms <= {ms[0],fg_ddr_ready};' in xbench and b'mm <= mr;' in xbench
    for name in ('bt_clock_enables.sv', 'bt_pause_bridge.sv', 'bt_video_ddr.sv'):
        key = 'rtl/' + name
        consumer = evidence.file(EDGE / 'proof/compiled' / name, inventory['sources'][key])
        assert consumer == evidence.file(V15 / key) == evidence.file(current / key)
    coverage = {'sys_edges': 66699, 'mem_edges': 133397, 'assertions': 483, 'releases': 484,
                'held': 65732, 'coincident': 66699, 'off_edge_holds': 65667,
                'copy_pre': 133397, 'copy_post': 133396, 'consumer_checks': 133396,
                'directed_tuples': 128, 'random_tuples': 65536, 'consumer_bits': 122}
    xcoverage = {'sys_checks': 149, 'mem_checks': 297, 'unknown_checks': 72,
                 'offedge_checks': 28, 'xz_cases': 28, 'independent_fourstate_nba_model': True}
    assert proof['coverage'] == coverage and proof['fourstate_coverage'] == xcoverage
    run_log = evidence.file(EDGE / 'proof/run.log')
    marker = re.search(rb'PASS RESET_MAXFAN sys_edges=(\d+) mem_edges=(\d+) assertions=(\d+) releases=(\d+) held=(\d+) coincident=(\d+) off_edge_holds=(\d+) tuples=128 random_tuples=65536 init_checks=2', run_log)
    assert marker and tuple(map(int, marker.groups())) == tuple(coverage[key] for key in ('sys_edges', 'mem_edges', 'assertions', 'releases', 'held', 'coincident', 'off_edge_holds'))
    marker = re.search(rb'PASS RESET_PARTITION copy_pre=(\d+) copy_post=(\d+) consumer_checks=(\d+) copies=5 roles=7', run_log)
    assert marker and tuple(map(int, marker.groups())) == tuple(coverage[key] for key in ('copy_pre', 'copy_post', 'consumer_checks'))
    xlog = evidence.file(EDGE / 'proof/fourstate_run.log')
    marker = re.search(rb'PASS RESET_PARTITION_FOURSTATE sys_checks=(\d+) mem_checks=(\d+) unknown_checks=(\d+) offedge_checks=(\d+) xz_cases=28', xlog)
    assert marker and tuple(map(int, marker.groups())) == tuple(xcoverage[key] for key in ('sys_checks', 'mem_checks', 'unknown_checks', 'offedge_checks'))
    for name in ('run.log', 'compile.log', 'fourstate_compile.log', 'fourstate_run.log'):
        no_failure(evidence.file(EDGE / 'proof' / name))
    assert proof['verilator_version'] in evidence.file(EDGE / 'proof/version.log').decode()
    prefix = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec']
    relative = EDGE.relative_to(ROOT).as_posix() + '/proof'
    assert proof['commands'] == {
        'version': prefix + ['verilator', '--version'],
        'compile': prefix + ['verilator', '--binary', '--timing', '--top-module', 'reset_partition_tb', '-Wno-fatal', '-j', '2', '--Mdir', relative + '/obj', relative + '/reset_partition_tb.sv'] + [relative + '/compiled/' + name for name in ('bt_clock_enables.sv', 'bt_pause_bridge.sv', 'bt_video_ddr.sv')],
        'run': prefix + ['./' + relative + '/obj/Vreset_partition_tb'],
        'fourstate_compile': prefix + ['iverilog', '-g2012', '-s', 'reset_partition_fourstate_tb', '-o', relative + '/fourstate.vvp', relative + '/reset_partition_fourstate_tb.sv'],
        'fourstate_run': prefix + ['vvp', relative + '/fourstate.vvp'],
    }
    controls = []
    cap = original_capture(old)
    reject('unpartitioned old reset source', lambda: inverse(old), controls)
    reject('clone samples old Q with extra SYS edge', lambda: inverse(new.replace(cap.replace(b' reset <=', b' reset_bt <='), b'\talways @(posedge clk_sys) reset_bt <= reset;\r\n', 1)), controls)
    reject('clone uses MEM clock', lambda: inverse(new.replace(b'clk_sys) reset_video <=', b'clk_mem) reset_video <=', 1)), controls)
    reject('clone loses initialized one', lambda: inverse(new.replace(b"reg reset_bt = 1'b1", b"reg reset_bt = 1'b0", 1)), controls)
    reject('clone loses dont_merge', lambda: inverse(new.replace(b'preserve, dont_merge', b'preserve', 1)), controls)
    for before_binding, after_binding, role in BINDINGS:
        reject('changed consumer alias: ' + role, lambda a=after_binding, b=before_binding: inverse(new.replace(a, b, 1)), controls)
    reject('changed original asynchronous audio', lambda: inverse(new.replace(b'SCE_DIV <= 0;', b'SCE_DIV <= 1;', 1)), controls)
    reject('unrelated top mutation', lambda: inverse(new + b'// foreign top edit\n'), controls)
    reject('undeclared parent source', lambda: preparer.transform(old + b'\n'), controls)
    bad = json.loads(json.dumps(inventory)); bad['sources']['rtl/TMS34020/TMS34020_MC.sv'] = '0' * 64
    reject('undeclared MC input change', lambda: validate_inventory(bad, old_inventory), controls)
    bad = json.loads(json.dumps(inventory)); del bad['sources']['rtl/fg_vram.sv']
    reject('missing consumed FG input', lambda: validate_inventory(bad, old_inventory), controls)
    reject('changed retained collision/source graph', lambda: same(PARENT.read_bytes() + b'\n', PARENT_SHA), controls)
    reject('changed executed log preserving counts', lambda: same(run_log + b'\n', sha(run_log)), controls)
    reject('changed actual compiled consumer bench', lambda: same(bench + b'\n', sha(bench)), controls)
    reject('changed actual four-state model', lambda: same(xbench + b'\n', sha(xbench)), controls)
    reject('changed original compiled consumer', lambda: same(consumer + b'\n', sha(consumer)), controls)
    reject('changed guarded source helper', lambda: same(PREPARER.read_bytes() + b'\n', PREPARER_SHA), controls)
    reject('false PASS with failure', lambda: no_failure(run_log + b'\nFAIL unreviewed\n'), controls)
    assert len(controls) == NEGATIVE_COUNT
    preserved = {'reset_partition_actual_proof': proof['negative_controls'],
                 'v15_source_composition': parent['new_negative_controls'],
                 'locator_actual_proof': parent['preserved_CPU_proof_negative_controls'],
                 'v13_current_input_composition': parent['preserved_v13_negative_controls']}
    assert [len(value) for value in preserved.values()] == [15, 12, 9, 9]
    assert all(item['rejected'] for values in preserved.values() for item in values)
    observed_head = subprocess.check_output([GIT, 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    root_context = {name: sha((ROOT / name).read_bytes()) for name in (TOP, 'rtl/BT.sv', 'rtl/TMS34020/TMS34020.sv', 'rtl/TMS34020/TMS34020_MC.sv', 'rtl/fg_vram.sv', 'Arcade-Battletoads.qsf')}
    evidence.recheck()
    result = {'schema': SCHEMA, 'status': STATUS, 'helper_sha256': sha(Path(__file__).read_bytes()),
              'source_root': str(current), 'snapshot': str(inventory_path), 'snapshot_sha256': V18_SNAPSHOT_SHA,
              'all144_source_inventory_entries_verified': True, 'only_changed_sources': sorted(changed), 'unchanged_sources': 143,
              'parent_v15_receipt': {'path': str(PARENT), 'sha256': PARENT_SHA, 'untouched': True},
              'parent_v15_snapshot': {'path': str(V15_SNAPSHOT), 'sha256': V15_SNAPSHOT_SHA},
              'reset_partition_edge': {'parent_sha256': OLD_TOP_SHA, 'candidate_sha256': NEW_TOP_SHA,
                  'manifest': str(EDGE / 'manifest.json'), 'manifest_sha256': MANIFEST_SHA,
                  'actual_chronology_proof': str(EDGE / 'proof/receipt.json'), 'actual_chronology_proof_sha256': PROOF_SHA,
                  'raw_full_top_inverse_identical': True, 'same_D_init_SYS_edge_four_state_induction': True,
                  'original_reset_capture_init_and_async_audio_byte_identical': True,
                  'declaration_init': "1'b1", 'registers_added': 4, 'capture_latency_edges_added': 0,
                  'six_consumer_aliases': source_equivalence['consumer_roles'][:6],
                  'coverage': coverage, 'fourstate_coverage': xcoverage,
                  'regenerated_actual_compiled_benches_byte_identical': True,
                  'original_chronology_scope_preservation': chronology_scope,
                  'actual_three_compiled_consumer_sources_raw_identical': True},
              'composed_scopes': {'retained_v15_graph': parent['composed_scopes'],
                  'CPU_MC_fields_opcodes_ALU_shift_palette_pause_NVRAM_DDR_RAM_and_models': 'All 143 non-top consumed sources are raw identical to v15. Rehashed retained31fc graph, actual source/fixtures/logs and ten immutable Git oracles; no monitor/collision predicate or compiled component body changed.',
                  'reset_and_every_consumer': 'Four init1 SYS FFs independently capture the exact original seven-term D and hold between edges. Same-D four-state induction establishes equality of all five reset Qs for every trace; six declared consumer aliases and unchanged audio were verified by full raw-top inverse and the focused actual-consumer executions.',
                  'native128': 'Preserved only at its actual parent execution source identity; not retagged as v15 or v18 whole-board replay.'},
              'baseline_git_head': inventory['git_head'],
              'observed_root_context': {'git_head': observed_head, 'raw_core_sha256': root_context, 'context_only_not_selected_or_compiled_source_claim': True},
              'bound_evidence_files': evidence.files, 'immutable_git_oracles': evidence.oracles,
              'new_negative_controls': controls, 'preserved_negative_controls': preserved,
              'new_compiler_or_simulator_run': False, 'new_whole_board_native_run': False,
              'mapped_copies_proven': False, 'timing_accepted': False, 'eligible_for_RBF': False,
              'limits': ['This composition rehashes actual retained executions and validates the declared source edge; it is not a new native replay, mapped-retention/fanout proof, timing acceptance, RBF assembly or hardware/MAME qualification.', 'Selected sources derive directly from v15; ineffective v16/v17 maxfan branches and their receipts are not inherited.']}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': STATUS, 'receipt': str(output), 'receipt_sha256': sha(output.read_bytes()),
                      'helper_sha256': result['helper_sha256'], 'sources': 144, 'unchanged_v15_sources': 143,
                      'verified_evidence_files': len(evidence.files), 'immutable_git_oracles': len(evidence.oracles),
                      'new_negative_controls': len(controls), 'coverage': coverage, 'fourstate_coverage': xcoverage}, indent=2))


if __name__ == '__main__':
    main()
