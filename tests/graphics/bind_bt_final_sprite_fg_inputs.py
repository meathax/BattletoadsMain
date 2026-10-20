"""Strict v18 -> v20 source composition. Frozen scoped composition for the actual v20 inputs.

This helper reads immutable execution artifacts. It starts no simulator, Quartus
job, board replay, Git write or build. Fresh setup r2 proof inputs are pinned and regenerated before qualification.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = 'bt-v20-current-input-sprite-foreground-composition-v1'
STATUS = 'PASS_SCOPED_COMPOSITION'
BT, SPR, FG = 'rtl/BT.sv', 'rtl/spr_vram.sv', 'rtl/fg_vram.sv'
CHANGED = {BT, SPR, FG}
PARENT = ROOT / 'build/final_v18_current_input_qualification/receipt.json'
PARENT_SHA = 'a7f8af180aaabfe7257229d43b15698ab32b19d2b92c5c5c7df8e401c25412a7'
PARENT_HELPER = ROOT / 'tests/graphics/bind_bt_final_partition_inputs.py'
PARENT_HELPER_SHA = 'b76973dee89f809a43a05286dcb2c963cde1a58161c9163c7b36fa2f2900a4e2'
PARENT_SNAPSHOT = ROOT / 'build/timing_closure_20261011/reset_partition_v18_private-snapshot.json'
PARENT_SNAPSHOT_SHA = 'd4f54c0fb3b6a076177fc2382105c664d740d82482a6ca612e0418c5282880d8'
LOCAL = ROOT / 'build/sprite_fg_local_q_v18_v1'
LOCAL_MANIFEST_SHA = 'df784f6114e44a561bcaf877b5ad947a79b68781fa9d040cef36d360af8b2b62'
LOCAL_PROOF_SHA = 'ed5eb483ab2e4884c1beb8b2378dcf24c60a07525e7111c65f27f08faf7c940e'
LOCAL_RETENTION_SHA = 'b5270d1f9488c850225b83885eb9e8a72b08622d07d55ca0e005fedf352b9356'
TOGGLE = ROOT / 'build/fg_toggle_lcell_v18_v1'
TOGGLE_MANIFEST_SHA = '12b75f06d59786045cad85ca6d3bd5ed16a3b60374f965036ad5238898a8fbb2'
TOGGLE_PROOF_SHA = 'f75940d923977b7f0586b27f0838e78ac3be1b7a863455794064f034613f98db'
TOGGLE_RETENTION_SHA = '1603a399ca84c0492fa1d5b4d00fc471b4451d938b801bf3a19cef8ca149c7d1'
SETUP = ROOT / 'build/fg_setup_v18_v2'
SETUP_MANIFEST_SHA = '2ef2ff7f2f47c07c53262c4306b945f5aac54e79794e3b0b39a13921e43c5f12'
SETUP_SOURCE_PROOF_SHA = '7cdc50e8fd8c4ff695bc531a3089bde6944f7b26805e2fd5461d9ff26b2ca074'
HELPERS = {
    'prepare_bt_sprite_local_q.py': '5b534a75fda3b30ffaa418f23432b563e4d501423be4aa103af38e0a41a9b931',
    'qualify_bt_sprite_local_q.py': '77220d31eae38541066fbfd5a6c652e1de55dd16681b9aecd6f1fdf5044ad489',
    'prepare_bt_fg_toggle_lcell.py': '7b503b64e0e6d0e4106af73afe4e7ec692fc88a69d35203e0a8197b84f4638c2',
    'qualify_bt_fg_toggle_lcell.py': 'd8de8640c637fc591aa76e86b7df76d1844a3eb223153c37554e2ded3698c1c5',
    'prepare_bt_fg_setup_q17.py': '9732622cccc8c8b80feed16756e71faa741d4386716b1f57aea8873b0614c360',
    'prepare_bt_fg_setup.py': '89cfad6b211e57af69307f6e3731fbbcf5c4c70a5cd1c628c660fcf031567d1e',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def no_failure(data):
    assert not re.search(rb'%Error|Assertion failed|\*\*\s+(?:Error|Fatal):|\b(?:FAIL|FATAL|Aborting)\b', data), 'Failure in retained log'


def json_file(evidence, path, digest=None):
    return json.loads(evidence.file(path, digest))


def exact_marker(data, pattern, expected):
    matches = re.findall(pattern, data)
    assert len(matches) == 1, ('Missing/duplicate coverage marker', pattern)
    matched = matches[0] if isinstance(matches[0], tuple) else (matches[0],)
    values = tuple(int(x) for x in matched)
    assert values == expected, ('Changed coverage', values, expected)
    return values


def validate_inventory(current, parent):
    assert len(current['sources']) == len(parent['sources']) == 144
    assert set(current['sources']) == set(parent['sources'])
    changed = {name for name in current['sources'] if current['sources'][name] != parent['sources'][name]}
    assert changed == CHANGED, 'Only the three reviewed files may change'
    assert current['original_qsf_sha256'] == parent['original_qsf_sha256']
    assert current['build_date'] == parent['build_date'] == '261011'
    assert current['constraints_changed'] is False and current['timing_budgets_changed'] is False
    return changed


def verify_sources(evidence, source_root, snapshot, parent_snapshot):
    validate_inventory(snapshot, parent_snapshot)
    parent_root = Path(parent_snapshot['project']).parent
    assert Path(snapshot['project']).parent.resolve() == source_root.resolve()
    files = {}
    for name, digest in snapshot['sources'].items():
        files[name] = evidence.file(source_root / name, digest)
    old = {name: evidence.file(parent_root / name, parent_snapshot['sources'][name]) for name in CHANGED}
    mods = {}
    for name, wanted in HELPERS.items():
        path = ROOT / 'tests/graphics' / name
        evidence.file(path, wanted)
        mods[name] = load(path, 'v20_' + Path(name).stem)
    local = mods['prepare_bt_sprite_local_q.py']
    local_manifest = json_file(evidence, LOCAL / 'manifest.json', LOCAL_MANIFEST_SHA)
    assert local.verify_edge(LOCAL) == local_manifest
    for name in (BT, SPR):
        item = local_manifest['sources'][name]
        assert sha(files[name]) == item['candidate_sha256']
        assert local.inverse(files[name], item['operations']) == old[name]
        evidence.file(LOCAL / 'oracle' / name, item['parent_sha256'])
        evidence.file(LOCAL / 'candidate' / name, item['candidate_sha256'])
    toggle = mods['prepare_bt_fg_toggle_lcell.py']
    toggle_manifest = json_file(evidence, TOGGLE / 'source-edge/manifest.json', TOGGLE_MANIFEST_SHA)
    toggle_old, toggle_new, observed_toggle = toggle.verify_edge(TOGGLE / 'source-edge')
    assert toggle_old == old[FG] and observed_toggle == toggle_manifest
    setup = mods['prepare_bt_fg_setup_q17.py']
    setup_manifest = json_file(evidence, SETUP / 'manifest.json', SETUP_MANIFEST_SHA)
    setup_old = evidence.file(SETUP / 'immutable_parent' / FG, setup_manifest['parent_sha256'])
    setup_new = evidence.file(SETUP / 'candidate' / FG, setup_manifest['candidate_sha256'])
    assert setup_old == old[FG]
    source_coverage = setup.verify_source(old[FG], setup_new, setup_manifest['edits'])
    source_receipt = json_file(evidence, SETUP / 'source-receipt.json', SETUP_SOURCE_PROOF_SHA)
    assert source_receipt['status'] == 'PASS' and source_receipt['coverage'] == source_coverage
    assert source_receipt['manifest_sha256'] == SETUP_MANIFEST_SHA
    assert setup.reverse(files[FG], setup_manifest['edits']) == toggle_new, 'Combined setup inverse not exact standalone toggle'
    assert toggle.reverse(files[FG]) == setup_new, 'Combined toggle inverse not exact standalone setup'
    assert toggle.reverse(setup.reverse(files[FG], setup_manifest['edits'])) == old[FG]
    assert setup.reverse(toggle.reverse(files[FG]), setup_manifest['edits']) == old[FG]
    assert sha(files[FG]) == snapshot['sources'][FG]
    for label in ('oracle', 'candidate'):
        evidence.file(TOGGLE / 'source-edge' / label / FG)
    evidence.file(Path(setup_manifest['v1_manifest']), setup_manifest['v1_manifest_sha256'])
    evidence.file(SETUP / 'immutable_v1' / FG, setup_manifest['v1_candidate_sha256'])
    return files, old, mods, local_manifest, setup_manifest, source_coverage


def bind_local_proof(evidence, files, old, mods, manifest):
    directory = LOCAL / 'proof-r3'
    proof = json_file(evidence, directory / 'receipt.json', LOCAL_PROOF_SHA)
    assert proof['schema'] == 'bt-v18-sprite-local-q-qualification-v1'
    assert proof['status'] == 'PASS_VENDOR_4STATE_AND_SPRITE_CONSUMERS'
    assert proof['source_edge']['sha256'] == LOCAL_MANIFEST_SHA and proof['sources'] == manifest['sources']
    assert proof['x_exclusions'] == [] and proof['collision_exclusions'] == []
    assert not any(proof[k] for k in ('root_modified', 'timing_accepted', 'mapped_replication_proven', 'fresh_native_replay', 'rbf_generated'))
    retention = json_file(evidence, directory / 'helper_provenance.json', LOCAL_RETENTION_SHA)
    assert retention['status'] == 'PASS_REHASH_AND_REPARSE'
    retained = {}
    for original, item in retention['executed_helpers_and_original_fixtures'].items():
        retained[Path(original).name] = evidence.file(item['path'], item['sha256'])
    for name, digest in proof['helpers'].items():
        assert sha(retained[Path(name).name]) == digest
    for name, digest in proof['fixtures'].items():
        assert sha(retained[Path(name).name]) == digest
    qualifier = mods['qualify_bt_sprite_local_q.py']
    normalized = qualifier.normalized_text(files[SPR])
    assert normalized.count('SPR_VRAM') == 1 and normalized.count('BT_SPR_POST_NONZERO_MIRROR') == 2
    compiled_spr = normalized.replace('SPR_VRAM', 'SPR_VRAM_SYNC').replace('BT_SPR_POST_NONZERO_MIRROR', 'BT_SPR_POST_NONZERO_MIRROR_LOCAL').encode()
    expected = {
        'spr_oracle.sv': old[SPR], 'spr_candidate.sv': compiled_spr,
        'BT_mem.sv': files['rtl/BT_mem.sv'],
        'sprite_local_q_vendor_tb.sv': retained['sprite_local_q_vendor_tb.sv'],
        'sprite_read_equivalence_tb.sv': qualifier.adapted_read_fixture(qualifier.normalized_text(retained['sprite_read_equivalence_tb.sv'])).encode(),
        'sprite_packet_tb.sv': qualifier.adapted_packet_fixture(qualifier.normalized_text(retained['sprite_packet_tb.sv'])).encode(),
    }
    assert len(proof['compiled_sources']) == len(expected) == 6
    for name, digest in proof['compiled_sources'].items():
        assert evidence.file(name, digest) == expected[Path(name).name], 'Actual source/fixture regeneration mismatch'
    evidence.file(proof['native_vendor']['path'], proof['native_vendor']['sha256'])
    for command in proof['compile_commands']:
        assert command['exit_code'] == 0
    assert Path(proof['compile_commands'][0]['command'][0]).name == 'vlib.exe'
    assert Path(proof['compile_commands'][1]['command'][0]).name == 'vlog.exe'
    no_failure(evidence.file(proof['compile_log']['path'], proof['compile_log']['sha256']))
    assert [x['top'] for x in proof['results']] == ['sprite_local_q_vendor_tb', 'sprite_read_equivalence_tb', 'sprite_packet_tb']
    counts = {}
    for result in proof['results']:
        assert result['exit_code'] == 0 and Path(result['command'][0]).name == 'vsim.exe'
        data = evidence.file(result['log'], result['log_sha256']); no_failure(data)
        if result['top'] == 'sprite_local_q_vendor_tb':
            counts['mirror'] = exact_marker(data, rb'SPRITE_LOCAL_VENDOR_PASS pre=(\d+) post=(\d+) old_data=(\d+) mask_cases=(\d+) collisions=(\d+) offedge=(\d+) unknown=(\d+)', (33695, 33695, 128, 32768, 16384, 16, 7))
        elif result['top'] == 'sprite_read_equivalence_tb':
            exact_marker(data, rb'PASS sprite transaction equivalence: transfers=(\d+) comparisons=(\d+)', (16, 15424))
            counts['sprite_full_outputs'] = exact_marker(data, rb'SPRITE_LOCAL_FULL_OUTPUTS checks=(\d+) ports=(\d+)', (286232, 15))
        else:
            exact_marker(data, rb'SPRITE_PACKET_PASS packets=(\d+) readbacks=(\d+) completion_checks=(\d+)', (512, 512, 528))
            counts['packet_local_outputs'] = exact_marker(data, rb'SPRITE_LOCAL_PACKET_OUTPUTS checks=(\d+)', (3109,))
    controls = qualifier.negative_controls(mods['prepare_bt_sprite_local_q.py'], LOCAL, manifest)
    assert controls == proof['negative_controls_rejected'] and len(controls) == 12
    return {'receipt': str(directory / 'receipt.json'), 'sha256': LOCAL_PROOF_SHA,
            'counts_reparsed': counts, 'compiled_artifacts_regenerated': 6,
            'same_raw_q_same_MEM_edge_init_zero_induction': True, 'register_bits_added': 128,
            'memory_bits_added': 0, 'existing_outputs_unchanged': True,
            'new_full_FG_or_board_replay': False, 'mapped_replication_proven': False}


def bind_toggle_proof(evidence, old, mods):
    directory = TOGGLE / 'proof-r3'
    proof = json_file(evidence, directory / 'receipt.json', TOGGLE_PROOF_SHA)
    assert proof['schema'] == 'bt-fg-toggle-lcell-full-pin-fourstate-v1' and proof['status'] == 'PASS'
    prep = json_file(evidence, ROOT / proof['preparation'], proof['preparation_sha256'])
    assert prep['source_edge_sha256'] == TOGGLE_MANIFEST_SHA
    assert prep['parent_sha256'] == sha(old[FG]) and prep['candidate_sha256'] == proof['candidate_sha256']
    assert proof['original_assertions_preserved'] and proof['current_source_stability']
    assert proof['case_equality_exclusions'] == proof['collision_masks_added'] == 0
    assert not proof['actual_intel_physical_ram_rerun'] and not proof['mapped_or_timing_claim'] and not proof['rbf_or_hardware_claim']
    qualifier = mods['qualify_bt_fg_toggle_lcell.py']
    oracle = old[FG]
    names = re.findall(rb'(?m)^module\s+(\w+)', oracle)
    assert [x.decode() for x in names] == prep['oracle_module_names']
    for name in sorted(names, key=len, reverse=True):
        oracle = re.sub(rb'\b' + re.escape(name) + rb'\b', name + b'_REFERENCE', oracle)
    vendor = evidence.file(prep['vendor_file'], prep['vendor_file_sha256'])
    primitive = re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule', vendor, re.S)[0]
    assert sha(primitive) == prep['lcell_actual_module_sha256']
    retained = evidence.file(prep['retained_bench_path'], prep['retained_bench_sha256'])
    expected = {
        'fg_vram.sv': evidence.file(TOGGLE / 'source-edge/candidate' / FG, proof['candidate_sha256']),
        'reference-fg_vram.sv': oracle,
        'intel_lcell.v': b'`timescale 1ps/1ps\n' + primitive + b'\n',
        'item4_foreground_equivalence_tb.sv': qualifier.pin_bench(retained.decode().replace('\r\n', '\n')).encode(),
        'toggle_lcell_fourstate_tb.sv': qualifier.fourstate_bench().encode(),
    }
    for path, digest in prep['current_shared_inputs'].items():
        expected[Path(path).name] = evidence.file(path, digest)
    assert set(expected) == set(prep['compiled_inputs'])
    workspace = Path(proof['compiler_workspace'])
    for name, digest in prep['compiled_inputs'].items():
        assert evidence.file(directory / 'compiled-inputs' / name, digest) == expected[name]
        assert evidence.file(workspace / name, digest) == expected[name]
    assert len(proof['stages']) == 8
    logs = []
    for stage in proof['stages']:
        assert stage['exit_code'] == 0 and stage['command'][0].lower().endswith('wsl.exe')
        data = evidence.file(ROOT / stage['log'], stage['log_sha256']); no_failure(data); logs.append(data)
    exact_marker(logs[3], rb'PASS shipped LCELL four-state identity: mem_edges=(\d+) each_01XZ=(\d+) resets=(\d+) coincident_SYS_MEM=(\d+)', (8195, 1024, 241, 4098))
    exact_marker(logs[5], rb'PASS toggle complete packet/sync state: pre=(\d+) post=(\d+) write_states=(\d+) original_states=(\d+) RAM_pin_fields=(\d+) case_exclusions=(\d+)', (2527818, 2527818, 11, 31, 13, 0))
    assert b'restart_collisions=8 abort_collisions=8 reset_collects=2' in logs[5]
    controls = qualifier.source_controls(mods['prepare_bt_fg_toggle_lcell.py'], old[FG], expected['fg_vram.sv'], primitive, retained)
    assert controls == proof['source_negative_controls'] == prep['source_negative_controls'] and len(controls) == 8
    retention = json_file(evidence, TOGGLE / 'native-retention.json', TOGGLE_RETENTION_SHA)
    assert retention['status'] == 'PASS_SCOPED_RETENTION_AND_FUNCTIONAL_BINDING'
    assert retention['functional_receipt_sha256'] == TOGGLE_PROOF_SHA
    for path, digest in retention['files'].items():
        evidence.file(path, digest)
    assert len(retention['actual_routed_pair_paths']) == 4
    assert retention['tiny_probe_timing_accepted'] is False and retention['core_eight_corner_timing_acceptance'] is False
    return {'receipt': str(directory / 'receipt.json'), 'sha256': TOGGLE_PROOF_SHA,
            'compiled_artifacts_regenerated': len(expected), 'full_write_packet_state_fields': 11,
            'original_local_state_fields': 31, 'RAM_fields_per_bank': 13, 'banks': 4,
            'four_state_shipped_primitive_identity': True, 'core_mapped_timing_claim': False,
            'tiny_native_retention_receipt': {'path': str(TOGGLE / 'native-retention.json'), 'sha256': TOGGLE_RETENTION_SHA}}


import ast
import copy

SELECTED = ROOT / 'build/timing_closure_20261011/fg_sprite_controls_v20_private'
SELECTED_SNAPSHOT_SHA = 'e889eac9badb82a3ab654cf7b6b22c05235849300c70b45734b5bc8725064ab4'
COMBINED_FG_SHA = 'ddf9c579f24837042d1eb0e700f4e6f7f27896d0e93f4538525d66bfa1efbdd9'
PRESERVATION = ROOT / 'build/evidence_path_preservation_v20/manifest.json'
PRESERVATION_SHA = '3e7d38f9e4a625081a9c0fb13a9d631003e1948a2f00e502d210bb58a2fb544c'
PRESERVATION_HELPER = ROOT / 'tests/graphics/preserve_bt_fg_evidence_paths.py'
PRESERVATION_HELPER_SHA = 'bdb83732c56dfce72a74b8bdd5a9201f0f903296cb16daa372944ab8942cd947'
SETUP_NATIVE_SHA = 'c8071ade70ac4a18d3aad12ec144b84406c8e8c834d795d088a59a123dce382e'
SETUP_FOUR_SHA = '790bf06502d04404171970ffe0a92feaba0b1d180ab8fafe863ddc1aea3be09e'
SETUP_ARCHIVE_SHA = 'b93188d2221bcd375d538746dcb721f2b2c43fbfa9c845c5ec9e67ffcb244152'
HELPERS.update({
    'qualify_bt_fg_setup_q17.py': '5c474a569acbdc60576806fa0d1a5bad14bc5ae622e7616c74772a61465ee2e4',
    'qualify_bt_fg_setup_q17_four_state_r3.py': '3a29728f6f5ad978d25731a528fc8fa90ef0df24665adb0b8fdd8ab7bd1eb32f',
})
NEGATIVE_COUNT = 20


def assignment_expression(source, name):
    tree = ast.parse(source)
    functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    assert len(functions) == 1
    values = [n.value for n in ast.walk(functions[0]) if isinstance(n, ast.Assign)
              and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name) and n.targets[0].id == name]
    assert len(values) == 1, ('Nonunique fixture assignment', name)
    return values[0]


def constant_string_expression(node, names):
    """Regenerate a pinned literal fixture using only strings, replace and join."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        assert node.id in names
        return names[node.id]
    assert isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not node.keywords
    assert node.func.attr in ('replace', 'join'), 'Only pure fixture string construction is allowed'
    target = constant_string_expression(node.func.value, names)
    assert isinstance(target, str)
    args = [constant_string_expression(x, names) for x in node.args]
    if node.func.attr == 'replace':
        assert len(args) == 2 and all(isinstance(x, str) for x in args)
        return target.replace(*args)
    assert len(args) == 1 and isinstance(args[0], list) and all(isinstance(x, str) for x in args[0])
    return target.join(args[0])


def validate_setup_claim(proof, profile):
    assert proof['status'] == 'PASS'
    assert proof['case_equality_exclusions'] == proof['collision_masks_added'] == 0
    assert proof['intel_primitive_claim'] is False
    if profile == 'native':
        assert proof['schema'] == 'bt-fg-setup-v18-current-parent-replay-v1' and proof['profile'] == 'native'
        assert proof['original_assertions_preserved'] and not proof['mapped_or_timing_claim']
    else:
        assert proof['schema'] == 'bt-fg-setup-v18-four-state-reset-v2'
        assert not proof['mapped_timing_or_hardware_claim']
    coverage = proof['coverage']
    for key, expected in [('states', 31), ('ram_banks', 4), ('ram_pin_fields', 13),
                          ('state_edges', 1263909), ('bank_edge_checks', 10111272),
                          ('same_edge_predicate_checks', 1262137)]:
        assert coverage[key] == expected
    if profile == 'four':
        for key, expected in [('four_state_read_command_tuples', 256), ('address_pre_edges', 2527818),
                              ('address_post_edges', 2527818), ('address_reset_edges', 3544),
                              ('asynchronous_reset_assertions', 229), ('startup_checked', True)]:
            assert coverage[key] == expected


def original_fixture_regenerated(tb, extra):
    normalized = tb.decode().replace('\r\n', '\n')
    assert normalized.count('  initial begin\n') >= 1
    candidate = normalized.replace('  initial begin\n', extra + '  initial begin\n', 1)
    marker = '    $display("PASS serial chunk complete pins/state:'
    report = '    $display("PASS FG setup same-edge predicates: checks=%0d",setup_predicate_checks);\n'
    assert candidate.count(marker) == 1
    candidate = candidate.replace(marker, report + marker, 1)
    assert candidate.replace(extra, '', 1).replace(report, '', 1) == normalized
    return candidate.encode()


def bind_setup_proofs(evidence, old, mods, manifest):
    native_dir, four_dir = SETUP / 'native-proof-r1', SETUP / 'four-state-proof-r3'
    native = json_file(evidence, native_dir / 'receipt.json', SETUP_NATIVE_SHA)
    four = json_file(evidence, four_dir / 'receipt.json', SETUP_FOUR_SHA)
    validate_setup_claim(native, 'native'); validate_setup_claim(four, 'four')
    prep = json_file(evidence, native['preparation'], native['preparation_sha256'])
    fp = json_file(evidence, four['preparation'], four['preparation_sha256'])
    assert prep['manifest_sha256'] == SETUP_MANIFEST_SHA
    assert prep['candidate_sha256'] == manifest['candidate_sha256']
    assert prep['original_assertion_workload_inverse'] and prep['case_equality_exclusions'] == prep['collision_masks_added'] == 0
    assert fp['native_receipt_sha256'] == SETUP_NATIVE_SHA and fp['native_preparation_sha256'] == native['preparation_sha256']
    assert fp['source_parent_sha256'] == sha(old[FG]) and fp['source_candidate_sha256'] == manifest['candidate_sha256']
    assert all(fp[k] for k in ('original_fixture_inverse', 'original_addresses_clk_only', 'original_reset_dominates_commands', 'canonical_ram_only'))
    assert fp['case_equality_exclusions'] == fp['collision_masks_added'] == 0
    native_helper = evidence.file(prep['helper_path'], HELPERS['qualify_bt_fg_setup_q17.py'])
    four_helper = evidence.file(fp['helper_path'], HELPERS['qualify_bt_fg_setup_q17_four_state_r3.py'])
    assert prep['helper_sha256'] == sha(native_helper) and fp['helper_sha256'] == sha(four_helper)
    expected = {}
    for name, digest in prep['parent_sources'].items():
        raw = evidence.file(prep['source_paths'][name], digest)
        expected[Path(name).name] = raw
    assert expected['fg_vram.sv'] == old[FG]
    expected['fg_vram.sv'] = evidence.file(SETUP / 'candidate' / FG, manifest['candidate_sha256'])
    reference = old[FG]
    modules = re.findall(rb'(?m)^module\s+(\w+)', reference)
    assert prep['oracle_namespace_modules'] == [x.decode() for x in modules]
    for name in sorted(modules, key=len, reverse=True):
        reference = re.sub(rb'\b' + re.escape(name) + rb'\b', name + b'_REFERENCE', reference)
    expected['reference-fg_vram.sv'] = reference
    original_tb = evidence.file(prep['original_tb_path'], prep['original_tb_sha256'])
    extra = ast.literal_eval(assignment_expression(native_helper, 'extra'))
    assert extra == prep['new_assertions']
    expected['item4_foreground_equivalence_tb.sv'] = original_fixture_regenerated(original_tb, extra)
    assert len(expected) == len(prep['compiled_inputs']) == 8
    for path, digest in prep['compiled_inputs'].items():
        assert evidence.file(path, digest) == expected[Path(path).name], 'Fresh native fixture/source did not regenerate'
    fexpected = dict(expected)
    address_extra = ast.literal_eval(assignment_expression(four_helper, 'extra'))
    report = ast.literal_eval(assignment_expression(four_helper, 'report'))
    assert address_extra == fp['added_address_monitor']
    tb = expected['item4_foreground_equivalence_tb.sv'].decode()
    tb = tb.replace('  initial begin\n', address_extra + '  initial begin\n', 1)
    marker = '    $display("PASS FG setup same-edge predicates:'
    assert tb.count(marker) == 1
    tb = tb.replace(marker, report + marker, 1)
    assert tb.replace(address_extra, '', 1).replace(report, '', 1).encode() == expected['item4_foreground_equivalence_tb.sv']
    fexpected['item4_foreground_equivalence_tb.sv'] = tb.encode()
    raw_candidate = expected['fg_vram.sv'].decode().replace('\r\n', '\n')
    raw_parent = old[FG].decode().replace('\r\n', '\n')
    old_capture = ['\t\t' + name + '_M <= ' + name + ';' for name in ('RAS_N', 'OE_N', 'WE_N', 'TRANSFER')]
    assert old_capture == fp['exact_original_capture_statements']
    assert all(raw_parent.count(line) == raw_candidate.count(line) == 1 for line in old_capture)
    start = raw_candidate.index('\t// Bit-valued automatic arguments')
    end = raw_candidate.index('\tendfunction\n', start) + len('\tendfunction\n')
    actual_function = raw_candidate[start:end]
    assert actual_function == fp['actual_argument_coercion_function']
    declaration = actual_function + "\t(* preserve, dont_merge *) bit [7:0] COPY_READ_REQUEST_M = '0;"
    new_capture = '\t\tCOPY_READ_REQUEST_M <= {8{FG_READ_COMMAND(RAS_N, OE_N, WE_N, TRANSFER)}};'
    assert new_capture == fp['exact_candidate_capture_statement'] and raw_candidate.count(new_capture) == 1
    command_tb = constant_string_expression(assignment_expression(four_helper, 'command_tb'),
                                             {'declaration': declaration, 'old_capture': old_capture, 'new_capture': new_capture})
    fexpected['fg_setup_capture_x_tb.sv'] = command_tb.encode()
    four_module = mods['qualify_bt_fg_setup_q17_four_state_r3.py']
    selected = ['MEM_ROW', 'SREG_POS', 'COPY_ADDR', 'RDY_NEXT_COPY_WE', 'HOLE_NEXT_ADDR',
                'COPY_ADDR_STEP_VALUE', 'COPY_ADDR_START_VALUE', 'CPU_CACHE_READY', 'CPU_PAIR_POS', 'SQ_D']
    for filename, names in [('fg_vram.sv', selected), ('reference-fg_vram.sv', selected),
                            ('item4_foreground_equivalence_tb.sv', ['DRAW_ADDR'])]:
        adapted, record = four_module.declaration_order(fexpected[filename], names)
        assert record == fp['compiler_input_order_adapters'][filename]
        assert record['raw_inverse'] and record['continuous_driver_expression_and_site_preserved']
        assert not record['variable_initialization_dependencies_changed'] and not record['assertions_or_workload_removed']
        fexpected[filename] = adapted
    assert len(fexpected) == len(fp['compiled_inputs']) == 9
    for path, digest in fp['compiled_inputs'].items():
        assert evidence.file(path, digest) == fexpected[Path(path).name], 'Fresh four-state fixture/source did not regenerate'
    assert len(native['records']) == len(four['records']) == 4
    logs = {}
    for profile, proof in [('native', native), ('four', four)]:
        logs[profile] = []
        for index, record in enumerate(proof['records']):
            assert record['exit_code'] == 0
            data = evidence.file(record['log'], record['log_sha256']); no_failure(data)
            logs[profile].append(data)
            executable = Path(record['command'][0]).name.lower()
            if profile == 'native':
                assert executable == 'wsl.exe' and 'Ubuntu' in record['command']
                if index in (0, 2):
                    assert all(flag in record['command'] for flag in ('verilator', '--binary', '--assert', '--timing', '--top-module'))
            else:
                assert executable == ('vlib.exe' if index == 0 else 'vlog.exe' if index == 1 else 'vsim.exe')
                if index in (2, 3):
                    assert '-assertdebug' in record['command'] and b'Errors: 0, Warnings: 0' in data
    for data in (logs['native'][1], logs['four'][3]):
        exact_marker(data, rb'PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+) states=(\d+) pin_fields=(\d+)', (1263909, 10111272, 31, 13))
        exact_marker(data, rb'PASS FG setup same-edge predicates: checks=(\d+)', (1262137,))
        exact_marker(data, rb'PASS foreground transaction equivalence: transactions=(\d+) comparisons=(\d+)', (262, 107750))
        assert b'restart_collisions=8 abort_collisions=8 reset_collects=2' in data and b'PASS item4 RMT/control corners:' in data
    assert b'PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure' in logs['native'][3]
    exact_marker(logs['four'][2], rb'PASS FG setup original/new raw capture: four_state_tuples=(\d+) replica_bits=(\d+) startup_checked=(\d+)', (256, 8, 1))
    exact_marker(logs['four'][3], rb'PASS FG setup reset addresses: pre=(\d+) post=(\d+) reset_edges=(\d+) asynchronous_resets=(\d+)', (2527818, 2527818, 3544, 229))
    archives = [path for path in SETUP.glob('*.json') if sha(path.read_bytes()) == SETUP_ARCHIVE_SHA]
    assert len(archives) == 1, 'Missing pinned executed-helper archive'
    archive_raw = evidence.file(archives[0], SETUP_ARCHIVE_SHA)
    helpers = list((SETUP / 'executed-helpers').glob('*.py'))
    assert len(helpers) == 8
    for path in helpers:
        raw = evidence.file(path)
        assert sha(raw).encode() in archive_raw and path.name.encode() in archive_raw, 'Archived helper is not declared by pinned archive'
    for directory, top in [(native_dir / 'fg', 'item4_foreground_equivalence_tb'), (native_dir / 'fg-ddr', 'foreground_ddr_tb')]:
        elf = evidence.file(directory / 'obj' / ('V' + top))
        assert elf[:4] == b'\x7fELF'
    return {'native_receipt': {'path': str(native_dir / 'receipt.json'), 'sha256': SETUP_NATIVE_SHA},
            'four_state_receipt': {'path': str(four_dir / 'receipt.json'), 'sha256': SETUP_FOUR_SHA},
            'executed_helpers_archive': {'path': str(archives[0]), 'sha256': SETUP_ARCHIVE_SHA},
            'native_coverage_reparsed': native['coverage'], 'four_state_coverage_reparsed': four['coverage'],
            'raw_native_compiled_inputs_regenerated': 8, 'four_state_compiled_inputs_regenerated': 9,
            'declaration_only_full_raw_inverses_verified': 3, 'all_original_fixture_bytes_and_assertions_retained': True,
            'spelling_edge': 'Four scalar automatic bit arguments preserve original capture-edge coercion',
            'actual_vendor_RAM_rerun': False, 'core_mapped_timing_claim': False}


def composition_negatives(files, old, mods, setup_manifest, snapshot, parent_snapshot):
    controls = []
    def reject(name, operation):
        try:
            operation()
        except (AssertionError, ValueError, KeyError):
            controls.append({'name': name, 'rejected': True}); return
        raise AssertionError('Composition negative accepted: ' + name)
    toggle, setup, local = (mods[n] for n in ('prepare_bt_fg_toggle_lcell.py', 'prepare_bt_fg_setup_q17.py', 'prepare_bt_sprite_local_q.py'))
    def inverse_fg(raw):
        assert toggle.reverse(setup.reverse(raw, setup_manifest['edits'])) == old[FG]
        assert setup.reverse(toggle.reverse(raw), setup_manifest['edits']) == old[FG]
    local_manifest = json.loads((LOCAL / 'manifest.json').read_bytes())
    def inverse_local(name, raw):
        assert local.inverse(raw, local_manifest['sources'][name]['operations']) == old[name]
    reject('combined FG unrelated raw edit', lambda: inverse_fg(files[FG] + b'foreign'))
    reject('combined FG lost toggle edge', lambda: inverse_fg(toggle.reverse(files[FG])))
    reject('combined FG lost setup edge', lambda: inverse_fg(setup.reverse(files[FG], setup_manifest['edits'])))
    reject('combined FG changed automatic bit predicate', lambda: inverse_fg(files[FG].replace(b'!ras_n && !oe_n', b'!ras_n || !oe_n', 1)))
    reject('combined FG unknown capture source', lambda: inverse_fg(files[FG].replace(b'FG_READ_COMMAND(RAS_N, OE_N, WE_N, TRANSFER)', b'FG_READ_COMMAND(RAS_N, OE_N, WE_N, 1)', 1)))
    reject('local copy samples old Q extra edge', lambda: inverse_local(SPR, files[SPR].replace(b'fg0_q<=raw_q;', b'fg0_q<=Q;', 1)))
    reject('local copy changed initial value', lambda: inverse_local(SPR, files[SPR].replace(b"fg1_q = 64'b0", b"fg1_q = 64'b1", 1)))
    reject('wrong FG0 local consumer', lambda: inverse_local(BT, files[BT].replace(b'.CPU_SHIFT_Q(FG0_SHIFT_Q)', b'.CPU_SHIFT_Q(FG1_SHIFT_Q)', 1)))
    reject('unrelated BT output edit', lambda: inverse_local(BT, files[BT] + b'foreign'))
    missing = copy.deepcopy(snapshot); missing['sources'].pop('rtl/BT_mem.sv')
    reject('missing one of all144 sources', lambda: validate_inventory(missing, parent_snapshot))
    changed = copy.deepcopy(snapshot); changed['sources']['rtl/BT_mem.sv'] = '0' * 64
    reject('unproved memory source edit', lambda: validate_inventory(changed, parent_snapshot))
    changed = copy.deepcopy(snapshot); changed['original_qsf_sha256'] = '0' * 64
    reject('unproved original QSF setting change', lambda: validate_inventory(changed, parent_snapshot))
    changed = copy.deepcopy(snapshot); changed['constraints_changed'] = True
    reject('constraint edit', lambda: validate_inventory(changed, parent_snapshot))
    changed = copy.deepcopy(snapshot); changed['timing_budgets_changed'] = True
    reject('timing budget relaxed', lambda: validate_inventory(changed, parent_snapshot))
    reject('missing fresh log coverage marker', lambda: exact_marker(b'', rb'checks=(\d+)', (1262137,)))
    reject('duplicate fresh log coverage marker', lambda: exact_marker(b'checks=1262137 checks=1262137', rb'checks=(\d+)', (1262137,)))
    reject('reduced fresh fourstate coverage', lambda: exact_marker(b'tuples=255', rb'tuples=(\d+)', (256,)))
    four = json.loads((SETUP / 'four-state-proof-r3/receipt.json').read_bytes())
    changed = copy.deepcopy(four); changed['case_equality_exclusions'] = 1
    reject('new case equality exclusion', lambda: validate_setup_claim(changed, 'four'))
    changed = copy.deepcopy(four); changed['mapped_timing_or_hardware_claim'] = True
    reject('scoped proof promoted to timing acceptance', lambda: validate_setup_claim(changed, 'four'))
    reject('compiler declaration adapter dependent initializer', lambda: mods['qualify_bt_fg_setup_q17_four_state_r3.py'].declaration_order(b'module sample;\n logic other;\n logic dependent = other;\nendmodule\n', ['dependent']))
    assert len(controls) == NEGATIVE_COUNT
    return controls


def bind_current(source_root):
    assert source_root.resolve() == SELECTED.resolve(), 'Only the frozen actual v20 source-root is accepted'
    assert sha(PARENT_HELPER.read_bytes()) == PARENT_HELPER_SHA
    parent_module = load(PARENT_HELPER, 'v20_parent_v18')
    assert sha(PRESERVATION_HELPER.read_bytes()) == PRESERVATION_HELPER_SHA
    adapter = load(PRESERVATION_HELPER, 'v20_seven_path_preservation')
    assert sha(PRESERVATION.read_bytes()) == PRESERVATION_SHA
    preservation = adapter.verify_manifest(PRESERVATION)
    parent_check = adapter.verify_original_receipt(parent_module, preservation)
    assert parent_check['status'] == STATUS and parent_check['verified_immutable_git_oracles'] == 10
    evidence = adapter.evidence_callback_class(parent_module.Evidence, preservation)()
    evidence.file(PARENT_HELPER, PARENT_HELPER_SHA)
    evidence.file(PRESERVATION_HELPER, PRESERVATION_HELPER_SHA)
    evidence.file(PRESERVATION, PRESERVATION_SHA)
    parent = json_file(evidence, PARENT, PARENT_SHA)
    for name, digest in parent['bound_evidence_files'].items():
        evidence.file(name, digest)
    for key, digest in parent['immutable_git_oracles'].items():
        evidence.git(key, digest)
    parent_snapshot = json_file(evidence, PARENT_SNAPSHOT, PARENT_SNAPSHOT_SHA)
    snapshot_path = source_root.with_name(source_root.name + '-snapshot.json')
    snapshot = json_file(evidence, snapshot_path, SELECTED_SNAPSHOT_SHA)
    files, old, mods, local_manifest, setup_manifest, source_coverage = verify_sources(evidence, source_root, snapshot, parent_snapshot)
    assert sha(files[FG]) == COMBINED_FG_SHA
    local_scope = bind_local_proof(evidence, files, old, mods, local_manifest)
    toggle_scope = bind_toggle_proof(evidence, old, mods)
    setup_scope = bind_setup_proofs(evidence, old, mods, setup_manifest)
    negatives = composition_negatives(files, old, mods, setup_manifest, snapshot, parent_snapshot)
    adapter_negatives = adapter.negative_controls(preservation)
    assert adapter_negatives == preservation['negative_controls'] and len(adapter_negatives) == 10
    result = {'schema': SCHEMA, 'status': STATUS, 'helper_sha256': sha(Path(__file__).read_bytes()),
              'source_root': str(source_root), 'snapshot': str(snapshot_path), 'snapshot_sha256': SELECTED_SNAPSHOT_SHA,
              'all144_source_inventory_entries_verified': True, 'only_changed_sources': sorted(CHANGED), 'unchanged_sources': 141,
              'parent_v18_receipt': {'path': str(PARENT), 'sha256': PARENT_SHA},
              'parent_v18_snapshot': {'path': str(PARENT_SNAPSHOT), 'sha256': PARENT_SNAPSHOT_SHA},
              'combined_foreground_sha256': COMBINED_FG_SHA,
              'raw_source_composition': {'actual_combined_FG_reverses_both_orders_to_exact_v18': True,
                                        'setup_inverse_recovers_standalone_toggle': True,
                                        'toggle_inverse_recovers_standalone_setup_r2': True,
                                        'actual_BT_and_SPR_full_raw_inverses': True,
                                        'all_original_QSF_SDC_clock_budget_bytes_preserved': True},
              'scoped_proofs': {'sprite_local_q': local_scope, 'toggle_lcell': toggle_scope, 'foreground_setup_r2': setup_scope},
              'foreground_setup_source_coverage': source_coverage,
              'path_preservation_edge': {'manifest': str(PRESERVATION), 'manifest_sha256': PRESERVATION_SHA,
                                         'helper': str(PRESERVATION_HELPER), 'helper_sha256': PRESERVATION_HELPER_SHA,
                                         'substitutions': preservation['substitutions'], 'substitution_count': 7,
                                         'old_ledger_entries_verified': len(parent['bound_evidence_files']),
                                         'unique_retained_parent_files': parent_check['verified_evidence_files'],
                                         'disappearance_cause': preservation['disappearance_cause']},
              'new_negative_controls': negatives, 'path_preservation_negative_controls': adapter_negatives,
              'preserved_source_control_counts': {'sprite_local_q': 12, 'toggle_lcell': 8},
              'new_compiler_or_simulator_run': False, 'new_whole_board_native_run': False,
              'mapped_replication_proven': False, 'core_timing_accepted': False, 'timing_accepted': False,
              'eligible_for_RBF': False, 'root_RTL_SDC_or_old_evidence_modified': False,
              'limits': ['Three fresh independent scoped source/proof edges compose with the immutable v18 functional graph.',
                         'Canonical foreground RAM replays retain original fixture and collision contracts; this binder starts no vendor RAM rerun.',
                         'The local sprite Q induction and exact consuming aliases preserve the same input trace at both foreground ports.',
                         'Tiny native LCELL retention is separately scoped and establishes no core delay or timing acceptance.',
                         'Fresh accepted all-corner timing, physical pads, release-source and artifact gates remain required.']}
    evidence.recheck()
    result['bound_evidence_files'] = dict(evidence.files)
    result['immutable_git_oracles'] = dict(evidence.oracles)
    # The receipt contract is JSON; normalize coverage tuples exactly once so
    # reproducing the strict graph compares the same serialized value types.
    return json.loads(json.dumps(result)), evidence


def verify_composition_receipt(path):
    """Recreate the source/proof bindings without relabeling any old execution."""
    result = json.loads(Path(path).read_bytes())
    assert result['schema'] == SCHEMA and result['status'] == STATUS
    assert result['helper_sha256'] == sha(Path(__file__).read_bytes())
    recomputed, evidence = bind_current(Path(result['source_root']))
    helper = result['executed_helper']
    assert helper['sha256'] == result['helper_sha256']
    evidence.file(helper['path'], helper['sha256'])
    recomputed['executed_helper'] = helper
    recomputed['bound_evidence_files'] = dict(evidence.files)
    assert recomputed == result, 'Receipt did not reproduce the strict current source/evidence graph'
    evidence.recheck()
    return {'status': STATUS, 'receipt': str(Path(path).resolve()), 'verified_evidence_files': len(evidence.files),
            'verified_immutable_git_oracles': len(evidence.oracles), 'sources': 144, 'unchanged_sources': 141,
            'new_negative_controls': NEGATIVE_COUNT, 'path_preservation_negative_controls': 10,
            'path_substitutions': 7, 'new_board_replay_or_timing_claim': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=SELECTED)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite original or failed evidence'
    result, evidence = bind_current(args.source_root.resolve())
    output.mkdir(parents=True)
    helper_path = output / 'executed_helper.py'
    helper_path.write_bytes(Path(__file__).read_bytes())
    result['executed_helper'] = {'path': str(helper_path), 'sha256': result['helper_sha256']}
    evidence.file(helper_path, result['helper_sha256'])
    evidence.recheck()
    result['bound_evidence_files'] = dict(evidence.files)
    receipt = output / 'receipt.json'
    receipt.write_bytes((json.dumps(result, indent=2) + '\n').encode())
    verification = verify_composition_receipt(receipt)
    print(json.dumps({'receipt': str(receipt), 'sha256': sha(receipt.read_bytes()),
                      'helper_sha256': result['helper_sha256'], 'verification': verification}))


if __name__ == '__main__':
    main()
