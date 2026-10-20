"""Compose the exact v15 locator/FG attribute edges with immutable v13 proofs.

This performs source, certificate and retained-artifact verification. It does
not launch a compiler, simulator or FPGA build, and grants no timing, new
whole-board replay or hardware acceptance.
"""
import argparse
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
CPU = 'rtl/TMS34020/TMS34020.sv'
PACKAGE = 'rtl/TMS34020/TMS34020_pkg.sv'
FG = 'rtl/fg_vram.sv'
V13 = ROOT / 'build/timing_closure_20261011/fg_controls_v13_private'
PARENT = ROOT / 'build/final_v13_current_input_qualification/receipt.json'
PARENT_SHA = 'd6e51a25915d92145fda9291b8523cf6cc506e31f403b2b46da501e84a42c5ea'
LOCATOR = ROOT / 'build/cpu_onelocate_v13_v1'
PROOF_SHA = '5d345a38d92d835b117fd360da80bb7e0269265bd7a0e47f5500c101744ad2b6'
MANIFEST_SHA = '1a20e2560f4b21304c765c0cfc02b47f948e20bd45bed95302ba96e6e6f69874'
FG_EDGE = ROOT / 'build/fg_lane_maxfan_v13_v1'
FG_MANIFEST_SHA = '50016c81a8a541aaf758ef116c1a159cbfe47f8b7e9fb46b3ea673cbff856189'
OLD_CPU_SHA = '41aa8a3284515162c605048ae5b479e07eed11efb58a2fdf4e9e19f89e4f2183'
CPU_SHA = '48172b42c38a657f1a798783e8c68b1b7eb26dbe6527f5f9ec488c4705f616ee'
OLD_FG_SHA = 'f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b'
FG_SHA = '15ca6106299cebaa05e7651b340c4c908b692385af89a75498bf0d60674cf6ae'
PACKAGE_SHA = '699ca3d9131296edf0116f051e7271f5be54ea500d06b69966155b18711e2c65'


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def validate_inventory(current, parent):
    assert len(current['sources']) == len(parent['sources']) == 144
    assert set(current['sources']) == set(parent['sources'])
    changed = {name for name in current['sources'] if current['sources'][name] != parent['sources'][name]}
    assert changed == {CPU, FG}, 'Only the proved locator and existing FG-register attribute may change'
    assert current['sources'][CPU] == CPU_SHA and parent['sources'][CPU] == OLD_CPU_SHA
    assert current['sources'][FG] == FG_SHA and parent['sources'][FG] == OLD_FG_SHA
    assert current['sources'][PACKAGE] == parent['sources'][PACKAGE] == PACKAGE_SHA
    return changed


def fg_inverse(data, edge):
    before, after = edge['before'].encode(), edge['after'].encode()
    assert before == b'(* preserve *) bit [3:0][1:0] BANK_LANE_WREN_R;'
    assert after == b'(* preserve, maxfan = 4 *) bit [3:0][1:0] BANK_LANE_WREN_R;'
    assert data.count(after) == 1 and data.count(before) == 0
    return data.replace(after, before, 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    current, output = args.source_root.resolve(), args.output.resolve()
    current.relative_to(ROOT / 'build'); output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite an accepted or failed qualification record'
    builder_path = ROOT / 'tests/graphics/bind_bt_final_current_inputs.py'
    builder = load(builder_path, 'frozen_v13_final_builder')
    parent = json.loads(PARENT.read_bytes())
    assert builder.sha(PARENT.read_bytes()) == PARENT_SHA
    assert builder.sha(builder_path.read_bytes()) == parent['helper_sha256']
    builder.verify_retained_receipt(PARENT)
    evidence = builder.Evidence()
    evidence.file(PARENT, PARENT_SHA)
    evidence.file(builder_path, parent['helper_sha256'])
    for name, expected in parent['bound_evidence_files'].items():
        evidence.file(builder.native(name), expected)
    inventory, inventory_path = builder.snapshot(evidence, current)
    old_inventory, old_inventory_path = builder.snapshot(evidence, V13)
    changed = validate_inventory(inventory, old_inventory)
    manifest = json.loads(evidence.file(LOCATOR / 'manifest.json', MANIFEST_SHA))
    proof = json.loads(evidence.file(LOCATOR / 'proof/receipt.json', PROOF_SHA))
    assert proof['status'] == 'PASS' and proof['full_cpu_raw_inverse_identical']
    assert manifest['source_sha256'] == proof['source_sha256'] == {CPU: OLD_CPU_SHA, PACKAGE: PACKAGE_SHA}
    assert manifest['candidate_sha256'] == proof['candidate_sha256'] == {CPU: CPU_SHA}
    assert manifest['raw_full_cpu_inverse_identical'] and manifest['registers_added'] == manifest['latency_cycles_added'] == 0
    for item in proof['artifacts']:
        evidence.file(builder.native(item['path']), item['sha256'])
    preparer_path = ROOT / 'tests/graphics/prepare_bt_parallel_onelocate.py'
    qualifier_path = ROOT / 'tests/graphics/qualify_bt_parallel_onelocate.py'
    evidence.file(preparer_path, manifest['helper_sha256'])
    preparer = load(preparer_path, 'frozen_locator_edge')
    qualifier = load(qualifier_path, 'frozen_locator_function_proof')
    old_cpu = evidence.file(V13 / CPU, OLD_CPU_SHA)
    package = evidence.file(current / PACKAGE, PACKAGE_SHA)
    new_cpu = evidence.file(current / CPU, CPU_SHA)
    assert new_cpu == evidence.file(LOCATOR / 'candidate' / CPU, CPU_SHA)
    assert old_cpu == evidence.file(LOCATOR / 'oracle' / CPU, OLD_CPU_SHA)
    assert package == evidence.file(LOCATOR / 'oracle' / PACKAGE, PACKAGE_SHA)
    assert preparer.transform(old_cpu) == new_cpu and preparer.reverse(new_cpu) == old_cpu
    # The reversible full-file edge removes precisely one pure function and
    # restores precisely one combinational call. Every old CPU state/port,
    # operand, CE/EN/reset edge, DEBUG ABI and checker byte is preserved.
    old_function = preparer.extract_function(package.decode(), 'OneLocate')
    new_function = preparer.extract_function(new_cpu.decode(), 'BtOneLocate')
    assert builder.sha(old_function.encode()) == manifest['old_function_sha256']
    assert builder.sha(new_function.encode()) == manifest['new_function_sha256']
    assert re.search(r'function bit \[4:0\] OneLocate\(input bit \[31:0\] val, input bit dir\)', old_function)
    assert re.search(r'function bit \[4:0\] BtOneLocate\(input bit \[31:0\] val, input bit dir\)', new_function)
    bdd, old_bits, new_bits, old_count, new_count = qualifier.compare_functions(old_function, new_function)
    assert old_bits == new_bits == tuple(proof['proof']['old_output_node_ids']) == tuple(proof['proof']['new_output_node_ids'])
    assert (old_count, new_count, len(bdd.nodes)) == (10, 35, 5721)
    assert proof['proof']['inputs'] == 33 and proof['proof']['outputs'] == 5 and proof['proof']['universal_input_count'] == 2**33
    certificate_path = LOCATOR / 'proof/bdd-certificate.json'
    certificate = json.loads(evidence.file(certificate_path))
    regenerated_certificate = json.loads(json.dumps(bdd.certificate(old_bits, new_bits)))
    assert certificate == regenerated_certificate
    bench = evidence.file(LOCATOR / 'proof/cpu_onelocate_tb.sv')
    generated_bench = qualifier.testbench(old_function, new_function, bdd, old_bits)
    # The retained qualifier used native Windows write_text. It translated
    # every LF, including those already preceded by package-source CR bytes.
    # Reproduce that serialization exactly; do not normalize stray CR away.
    assert bench == generated_bench.replace('\n', '\r\n').encode()
    assert proof['return_codes'] == {'version': 0, 'compile': 0, 'run': 0}
    run_log = evidence.file(LOCATOR / 'proof/run.log')
    marker = re.search(rb'PASS CPU_ONELOCATE checks=(\d+) bdd_checks=(\d+) random_words=(\d+) windows=(\d+) zero_cases=(\d+)', run_log)
    assert marker and tuple(map(int, marker.groups())) == (2754628, 2048, 1048576, 327680, 4)
    builder.assert_log_failure(run_log)
    builder.assert_log_failure(evidence.file(LOCATOR / 'proof/compile.log'))
    assert len(proof['negative_controls']) == 9 and all(item['rejected'] for item in proof['negative_controls'])
    fg_edge = json.loads(evidence.file(FG_EDGE / 'manifest.json', FG_MANIFEST_SHA))
    assert fg_edge['status'] == 'PASS' and fg_edge['parent_fg_sha256'] == OLD_FG_SHA and fg_edge['candidate_fg_sha256'] == FG_SHA
    evidence.file(builder.native(fg_edge['helper']), fg_edge['helper_sha256'])
    before_fg = evidence.file(V13 / FG, OLD_FG_SHA)
    after_fg = evidence.file(current / FG, FG_SHA)
    assert after_fg == evidence.file(FG_EDGE / 'candidate' / FG, FG_SHA)
    assert fg_inverse(after_fg, fg_edge) == before_fg
    # The changed declaration precedes the physical module. Thus the complete
    # tested banked module, all leaf geometry/ports/collision behavior, and the
    # default/activated vendor fixtures remain byte identical independently.
    anchor = b'module BT_FG_BANKED_VRAM'
    assert before_fg.count(anchor) == after_fg.count(anchor) == 1
    assert before_fg.split(anchor, 1)[1] == after_fg.split(anchor, 1)[1]
    controls = []
    builder.reject('CPU unrelated body change', lambda: preparer.reverse(new_cpu + b'// unreviewed\n'), controls)
    builder.reject('CPU redirected call missing', lambda: preparer.reverse(new_cpu.replace(preparer.NEW_CALL.encode(), b'LOC_RES = 0;', 1)), controls)
    builder.reject('locator wrong zero direction', lambda: qualifier.compare_functions(old_function, new_function.replace('~dir | (|val)', 'dir | (|val)', 1)), controls)
    builder.reject('locator dropped highest nibble', lambda: qualifier.compare_functions(old_function, new_function.replace('high_group[7] = present[7];', "high_group[7] = 1'b0;", 1)), controls)
    builder.reject('changed package/oracle', lambda: builder.same(package + b'\n', PACKAGE_SHA), controls)
    builder.reject('FG unrelated geometry or producer change', lambda: builder.same(fg_inverse(after_fg + b'// foreign RTL\n', fg_edge), OLD_FG_SHA), controls)
    builder.reject('FG declaration width changed', lambda: fg_inverse(after_fg.replace(b'bit [3:0][1:0] BANK_LANE_WREN_R;', b'bit [3:0][2:0] BANK_LANE_WREN_R;', 1), fg_edge), controls)
    builder.reject('FG attribute moved to another register', lambda: fg_inverse(after_fg.replace(fg_edge['after'].encode(), b'(* preserve, maxfan = 4 *) bit [3:0][1:0] BANK_LANE_WREN_FOREIGN;', 1), fg_edge), controls)
    bad_inventory = json.loads(json.dumps(inventory)); bad_inventory['sources']['rtl/bg_vram.sv'] = '0' * 64
    builder.reject('undeclared third source change', lambda: validate_inventory(bad_inventory, old_inventory), controls)
    bad_inventory = json.loads(json.dumps(inventory)); del bad_inventory['sources'][PACKAGE]
    builder.reject('missing inventory input', lambda: validate_inventory(bad_inventory, old_inventory), controls)
    expected_run_sha = next(item['sha256'] for item in proof['artifacts'] if builder.native(item['path']) == (LOCATOR / 'proof/run.log'))
    builder.reject('changed executed log with preserved counts', lambda: builder.same(run_log + b'\n', expected_run_sha), controls)
    builder.reject('changed retained vendor collision proof', lambda: builder.same(PARENT.read_bytes() + b'\n', PARENT_SHA), controls)
    assert len(controls) == 12
    for name, expected in evidence.files.items():
        assert builder.sha(builder.native(name).read_bytes()) == expected
    result = {
        'schema': 'bt-v15-current-input-locator-composition-v1', 'status': 'PASS_SCOPED_COMPOSITION',
        'helper_sha256': builder.sha(Path(__file__).read_bytes()), 'source_root': str(current),
        'snapshot': str(inventory_path), 'snapshot_sha256': builder.sha(inventory_path.read_bytes()),
        'all144_source_inventory_entries_verified': True, 'unchanged_sources': 142, 'only_changed_sources': sorted(changed),
        'parent_v13_receipt': {'path': str(PARENT), 'sha256': PARENT_SHA, 'untouched': True},
        'parent_v13_snapshot': str(old_inventory_path),
        'CPU_edge': {'before_sha256': OLD_CPU_SHA, 'after_sha256': CPU_SHA, 'package_sha256': PACKAGE_SHA,
            'manifest': str(LOCATOR / 'manifest.json'), 'manifest_sha256': MANIFEST_SHA,
            'actual_function_proof': str(LOCATOR / 'proof/receipt.json'), 'actual_function_proof_sha256': PROOF_SHA,
            'full_original_CPU_raw_inverse_identity': True, 'pure_function_and_one_call_only': True,
            'universal_inputs': 2**33, 'outputs': 5, 'regenerated_certificate_nodes': len(bdd.nodes),
            'regenerated_testbench_matches_actual_compiled_input': True,
            'testbench_serialization': 'Exact native Windows write_text LF→CRLF serialization, including retained package CR bytes; no normalization or ignored bytes.',
            'actual_compiled_checks': proof['compiled_checks'],
            'new_function_input_local_result_2state_coercion_preserved': True, 'new_registers': 0, 'added_cycles': 0},
        'FG_edge': {'before_sha256': OLD_FG_SHA, 'after_sha256': FG_SHA,
            'manifest': str(FG_EDGE / 'manifest.json'), 'manifest_sha256': FG_MANIFEST_SHA,
            'only_existing_BANK_LANE_WREN_R_maxfan4_attribute': True, 'raw_full_source_inverse_identity': True,
            'entire_physical_banked_module_raw_identity': True,
            'init_reset_capture_hold_priority_ports_geometry_data_and_clock_edges_unchanged': True},
        'composed_scopes': {
            'CPU_fields_opcodes_shift_flags_ALU_and_palette': 'The immutable v13 proof graph plus a pure locator equality for every input; all other raw CPU bytes, package, bindings and functions are restored by the exact inverse.',
            'MC_pause_NVRAM_DDR_BG_SPR_models_and_adapters': 'All consumed source inventory entries are identical to v13. Existing exact compiled fixtures/logs and declared stage/ABI edges are preserved by the revalidated v13 proof graph.',
            'FG_full_state_and_actual_pins': parent['composed_proofs']['read_storage']['FG_full_state_and_actual_pins_coverage'],
            'Intel_vendor_and_collision_predicates': 'Identical tested module bodies, ports, geometry, adapter and actual Intel model/fixture/log hashes via v13; strict data/X equality and original narrow canonical collision predicates are unchanged.',
            'old_native128': 'Preserved as its actual parent execution only; this receipt does not retag it as a v15 board replay.'},
        'bound_evidence_files': evidence.files, 'new_negative_controls': controls,
        'preserved_CPU_proof_negative_controls': proof['negative_controls'],
        'preserved_v13_negative_controls': parent['negative_controls'],
        'new_source_BDD_and_certificate_verification': True, 'new_compiler_or_simulator_run': False,
        'new_Quartus_run': False, 'new_whole_board_native_run': False, 'mapped_resource_claim': False,
        'timing_accepted': False, 'mister_hardware_qualified': False, 'eligible_for_RBF': False,
        'legacy_verify_timing_modified': False,
        'scope': 'Separate exact v13→v15 functional source composition. Raw identities of original receipts are preserved. Every fitted timing corner, native release check and hardware gate remains independent.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'receipt': str(output), 'sha256': builder.sha(output.read_bytes()),
                      'bound_files': len(evidence.files), 'all144_inputs': True, 'new_negative_controls': len(controls),
                      'universal_locator_inputs': 2**33, 'timing_accepted': False}))


if __name__ == '__main__':
    main()
