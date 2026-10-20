"""Add a typed v14 replica edge to the immutable v13 functional composition.

Only the two declared FG/SPR sources may differ. Retained source, simulation,
vendor-model and native mapped-store evidence remain distinct; this helper
never grants timing, whole-board execution, RBF or hardware acceptance.
"""
import argparse
import copy
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
FG = 'rtl/fg_vram.sv'
SPR = 'rtl/spr_vram.sv'
V13 = ROOT / 'build/timing_closure_20261011/fg_controls_v13_private'
PARENT = ROOT / 'build/final_v13_current_input_qualification/receipt.json'
PARENT_SHA = 'd6e51a25915d92145fda9291b8523cf6cc506e31f403b2b46da501e84a42c5ea'
V1 = ROOT / 'build/fg_serial_replicas_v12_v1'
V2 = ROOT / 'build/fg_serial_replicas_v12_v2'
PROOF_SHA = 'e50621d4b1ab6481f1ab8ab0c695b586fe128fde1d808624057b66aedec7a066'
VENDOR = ROOT / 'tests/graphics/evidence/vram-physical/vram-current-75b60b4efa42477695a599e3c07c45ac/receipt.json'
VENDOR_SHA = 'c5a2e4d7375f54d2e3afcf0a7c085a7f40082899547f751b55beb2ba1c95390c'
APPLICABILITY_SHA = '9f729db4543f4e0ca401a651f7ade9a3a97abe5bf5b9f92522bbe2905253cc56'
QUICK = Path('C:/Users/meath/QuartusFast/runs/v2-20261011-072535-39828-quick_check/result.json')
MAP_RUN = Path('C:/Users/meath/QuartusFast/runs/v2-20261011-072709-29240-turbo_fit')


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_names(mapping):
    result = {name.replace('\\', '/').replace('//', '/'): value for name, value in mapping.items()}
    assert len(result) == len(mapping)
    return result


def mapped_rows(text):
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if re.search(r'FG_VRAM:FG[01]_VRAM\|VRAM_SHIFTREG:(?:shiftreg|serial_write_replicas\[[123]\]\.shiftreg)\|', line):
            fields = [item.strip() for item in line.split(';') if item.strip()]
            rows.append({'line': number, 'fields': fields})
    validate_rows(rows)
    return rows


def validate_rows(rows):
    assert len(rows) == 8
    names = set()
    for row in rows:
        fields = row['fields']
        match = re.search(r'FG_VRAM:(FG[01]_VRAM)\|VRAM_SHIFTREG:(shiftreg|serial_write_replicas\[[123]\]\.shiftreg)\|', fields[0])
        assert match
        names.add(match.groups())
        assert fields[1:8] == ['M10K block', 'Simple Dual Port', '64', '64', '64', '64', '4096']
    assert names == {(bank, name) for bank in ('FG0_VRAM', 'FG1_VRAM')
                     for name in ('shiftreg', 'serial_write_replicas[1].shiftreg',
                                  'serial_write_replicas[2].shiftreg', 'serial_write_replicas[3].shiftreg')}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    current, output = args.source_root.resolve(), args.output.resolve()
    current.relative_to(ROOT / 'build'); output.relative_to(ROOT / 'build'); assert not output.exists()
    parent_data = PARENT.read_bytes()
    parent = json.loads(parent_data)
    builder_path = ROOT / 'tests/graphics/bind_bt_final_current_inputs.py'
    builder = load(builder_path, 'immutable_v13_builder')
    assert builder.sha(parent_data) == PARENT_SHA
    assert builder.sha(builder_path.read_bytes()) == parent['helper_sha256']
    builder.verify_retained_receipt(PARENT)
    e = builder.Evidence()
    e.file(PARENT, PARENT_SHA); e.file(builder_path, parent['helper_sha256'])
    for name, expected in parent['bound_evidence_files'].items():
        e.file(builder.native(name), expected)
    inventory, inventory_path = builder.snapshot(e, current)
    old_inventory, old_inventory_path = builder.snapshot(e, V13)
    assert set(inventory['sources']) == set(old_inventory['sources'])
    changes = {name for name in inventory['sources'] if inventory['sources'][name] != old_inventory['sources'][name]}
    assert changes == {FG, SPR}, 'Only explicitly proved FG replicas/SPR attributes may change'
    transform = json.loads(e.file(V1 / 'manifest.json', 'cce03f1cdade6a6e1ab69bef6b3a6fe144b93dcc2501e2f8e93ec97909299e5f'))
    syntax = json.loads(e.file(V2 / 'manifest.json', 'e0a4b2a844c6e7895f1bc6a08a9e017a144fe659e267c03f452433c88396934d'))
    assert transform['status'] == syntax['status'] == 'PASS'
    e.file(ROOT / 'tests/graphics/prepare_bt_fg_serial_replicas.py', transform['transform_source_sha256'])
    e.file(builder.native(syntax['helper']), syntax['helper_sha256'])
    before_sources, first_sources, final_sources = {}, {}, {}
    for name in (FG, SPR):
        before = e.file(V13 / name, transform['parent_sources'][name])
        expected = builder.lf(before)
        for edit in transform['edits'][name]:
            assert expected.count(edit['before']) == 1
            expected = expected.replace(edit['before'], edit['after'], 1)
        first = e.file(V1 / 'candidate' / name, transform['candidate_sources'][name])
        assert expected.encode() == first
        reverse = expected
        for edit in reversed(transform['edits'][name]):
            assert reverse.count(edit['after']) == 1
            reverse = reverse.replace(edit['after'], edit['before'], 1)
        assert reverse == builder.lf(before)
        final = e.file(current / name, syntax['candidate_sources'][name])
        assert final == e.file(V2 / 'candidate' / name, syntax['candidate_sources'][name])
        if name == FG:
            edge = syntax['edge']
            assert first.count(edge['before'].encode()) == final.count(edge['after'].encode()) == 1
            assert final.replace(edge['after'].encode(), edge['before'].encode(), 1) == first
        else:
            assert final == first
        before_sources[name], first_sources[name], final_sources[name] = before, first, final
    # Independent attribute-only proof, including all register initializers and
    # original producer reset/update/hold expressions in the complete module.
    attr = '(* preserve, maxfan = 4 *) '
    old_sprite, new_sprite = builder.lf(before_sources[SPR]), builder.lf(final_sources[SPR])
    assert new_sprite.count(attr) == 1 and new_sprite.replace(attr, '', 1) == old_sprite
    module_library = load(ROOT / 'tests/graphics/qualify_current_vram_vendor.py', 'v14_vendor_module')
    old_mirror = module_library.module(old_sprite, 'BT_SPR_POST_NONZERO_MIRROR')
    new_mirror = module_library.module(new_sprite, 'BT_SPR_POST_NONZERO_MIRROR')
    assert new_mirror.replace(attr, '', 1) == old_mirror
    assert 'output reg [63:0] Q=64\'b0,output reg [15:0] NZ=16\'b0' in old_mirror
    assert '(* preserve, maxfan = 4 *) output reg [63:0] Q=64\'b0' in new_mirror
    assert old_mirror.split(');', 1)[1] == new_mirror.split(');', 1)[1]
    proof = json.loads(e.file(V2 / 'proof/receipt.json', PROOF_SHA))
    vendor = json.loads(e.file(VENDOR, VENDOR_SHA))
    applicability = json.loads(e.file(V2 / 'applicability.json', APPLICABILITY_SHA))
    checker = load(ROOT / 'tests/graphics/verify_bt_fg_serial_replica_edges.py', 'v14_strict_edges')
    checker.validate(vendor, syntax, proof)
    assert applicability['status'] == 'PASS'
    assert applicability['focused_receipt_sha256'] == PROOF_SHA
    assert applicability['vendor_receipt_sha256'] == VENDOR_SHA
    assert len(applicability['rejected_controls']) == 8
    assert proof['candidate_fg_sha256'] == inventory['sources'][FG]
    assert proof['no_collision_or_x_masks']
    e.file(builder.native(proof['helper']), proof['helper_sha256'])
    for name, expected in proof['captured_sources'].items():
        e.file((current if name in inventory['sources'] else ROOT) / name, expected)
    e.file(builder.native(proof['vendor_path']), proof['vendor_sha256'])
    old_worker = e.file(builder.native(proof['worker_parent']), proof['worker_parent_sha256'])
    new_worker = e.file(V2 / 'proof/worker.py', proof['worker_sha256'])
    old_name = 'fg-serial-controls-26bcf762d3d84a4ca07212ede6b3b824'
    new_name = proof['worker_run_name']
    assert old_worker.count(old_name.encode()) == new_worker.count(new_name.encode()) == 1
    assert new_worker.replace(new_name.encode(), old_name.encode(), 1) == old_worker
    native_path = builder.native(proof['native_receipt'])
    native = json.loads(e.file(native_path, proof['native_receipt_sha256']))
    assert native['all_passed'] and native['sources'][FG] == inventory['sources'][FG]
    for test, markers in proof['native_markers'].items():
        log_path = native_path.parent / test / 'run.log'
        log = e.file(log_path)
        assert all(marker in log.decode(errors='replace') for marker in markers)
        builder.assert_log_failure(log)
    for result in proof['results']:
        assert result['exit_code'] == 0
        e.file(builder.native(result['log']), result['log_sha256'])
    intel_folder = V2 / 'proof/intel'
    e.file(intel_folder / 'bt_fg_serial_replicas_intel_tb.sv', proof['generated_tb_sha256'])
    e.file(intel_folder / 'VRAM_SHIFTREG_REFERENCE.sv', proof['oracle_module_sha256'])
    e.file(intel_folder / 'BT_mem.sv', proof['compiled_leaf_sha256'])
    # Exact default=0 banked Intel fixture and the activated full-pin/replica
    # fixture are separate edges. The default-only suite is never retagged as
    # a direct run with SERIAL_DATA_LOCAL=1.
    assert applicability['default_path_only_in_original_vendor_suite']
    assert applicability['activated_full_fg_and_explicit_intel_replicas_proved_by_v2_fixture']
    for name, expected in vendor['fixtures'].items():
        e.file(ROOT / name, expected)
    for name, expected in vendor['external_sources'].items():
        e.file(builder.native(name), expected)
    for name, expected in vendor['sources'].items():
        target = builder.native(vendor['actual_source_paths'].get(name, str(ROOT / name)))
        e.file(target, expected)
    old_banked = module_library.module(builder.lf(first_sources[FG]), 'BT_FG_BANKED_VRAM')
    current_banked = module_library.module(builder.lf(final_sources[FG]), 'BT_FG_BANKED_VRAM')
    assert current_banked == old_banked
    fixture = next(name for name in vendor['fixtures'] if name.endswith('/fg_banked.sv'))
    assert current_banked == builder.lf(e.file(ROOT / fixture, vendor['fixtures'][fixture]))
    old_physical = json.loads(e.file(ROOT / parent['composed_proofs']['physical_VRAM_and_BG']['receipt'][0],
                                   parent['composed_proofs']['physical_VRAM_and_BG']['receipt'][1]))
    assert vendor['canonical_comparison_contract'] == old_physical['collision_contract']
    for result in vendor['results']:
        assert result['compile_exit_code'] == 0
        folder = builder.native(vendor['workspace']) / result['test']
        e.file(folder / 'compile.log', result['compile_log_sha256'])
        for run in result['runs']:
            assert run['exit_code'] == 0 and run['passed']
            filename = 'run.log' if run['phase'] is None else 'run_' + str(run['phase']) + '.log'
            data = e.file(folder / filename, run['log_sha256'])
            assert all(marker in data.decode(errors='replace') for marker in run['markers'])
            builder.assert_log_failure(data)
    quick = json.loads(e.file(QUICK))
    assert quick['accepted'] and quick['level'] == 'QUICK_CHECK' and not quick['full']
    assert canonical_names(quick['source_hashes']) == inventory['sources']
    report_path = builder.native(applicability['native_map']['path'])
    report = e.file(report_path, applicability['native_map']['sha256'])
    rows = mapped_rows(report.decode(errors='replace'))
    assert rows == applicability['native_map']['ram_rows']
    workspace = report_path.parent.parent
    e.file(workspace / FG, inventory['sources'][FG])
    e.file(workspace / SPR, inventory['sources'][SPR])
    e.file(MAP_RUN / 'map.telemetry.json')
    map_log = e.file(MAP_RUN / 'map.log')
    assert re.search(rb'Analysis & Synthesis was successful\.\s*0 errors', map_log)
    controls = []
    bad_sprite = new_sprite.replace("Q=64'b0", "Q=64'b1", 1)
    builder.reject('changed sprite register initialization', lambda: builder.same(bad_sprite.replace(attr, '', 1).encode(), builder.sha(old_sprite.encode())), controls)
    bad_sprite_body = new_sprite + '\n// unreviewed producer edit'
    builder.reject('changed complete sprite producer source', lambda: builder.same(bad_sprite_body.replace(attr, '', 1).encode(), builder.sha(old_sprite.encode())), controls)
    bad_fg = final_sources[FG].replace(b'.WREN(SRW_E)', b'.WREN(1\'b0)', 1)
    assert bad_fg != final_sources[FG]
    builder.reject('changed serial store capture enable', lambda: builder.same(bad_fg, inventory['sources'][FG]), controls)
    bad_rows = copy.deepcopy(rows); bad_rows[0]['fields'][6] = '32'
    builder.reject('changed mapped RAM geometry', lambda: validate_rows(bad_rows), controls)
    builder.reject('missing mapped replica', lambda: validate_rows(rows[:-1]), controls)
    bad_proof = copy.deepcopy(proof); bad_proof['no_collision_or_x_masks'] = False
    builder.reject('added collision or X masks', lambda: checker.validate(vendor, syntax, bad_proof), controls)
    bad_proof = copy.deepcopy(proof); bad_proof['candidate_fg_sha256'] = vendor['sources'][FG]
    builder.reject('relabelled v1 simulator source as v2', lambda: checker.validate(vendor, syntax, bad_proof), controls)
    assert len(controls) == 7
    for name, expected in e.files.items():
        assert builder.sha(builder.native(name).read_bytes()) == expected
    result = {'schema': 'bt-v14-current-input-replica-composition-v1', 'status': 'PASS_SCOPED_COMPOSITION',
              'helper_sha256': builder.sha(Path(__file__).read_bytes()), 'source_root': str(current),
              'snapshot': str(inventory_path), 'snapshot_sha256': builder.sha(inventory_path.read_bytes()),
              'all144_inputs_verified': True, 'parent_v13_receipt': {'path': str(PARENT), 'sha256': PARENT_SHA, 'untouched': True},
              'parent_v13_snapshot': str(old_inventory_path), 'only_changed_sources': sorted(changes), 'unchanged_sources': 142,
              'inherited_CPU_MC_field_opcode_ALU_palette_pause_NVRAM_DDR_scopes': 'All consumed files are byte-identical to the accepted v13 source inventory and its explicit preserved proof graph.',
              'FG_edge': {'v13_sha256': transform['parent_sources'][FG], 'v1_sha256': transform['candidate_sources'][FG],
                          'v2_sha256': syntax['candidate_sources'][FG], 'all_source_edits_and_genvar_edge_reversible': True,
                          'actual_v2_pin_and_Intel_receipt': {'path': str(V2 / 'proof/receipt.json'), 'sha256': PROOF_SHA},
                          'pin_coverage': parent['composed_proofs']['read_storage']['FG_full_state_and_actual_pins_coverage'],
                          'explicit_Intel_replica_coverage': proof['intel_coverage'], 'actual_data_X_comparison_exclusions': 0},
              'SPR_attribute_edge': {'before_sha256': transform['parent_sources'][SPR], 'after_sha256': syntax['candidate_sources'][SPR],
                  'only_attribute_after_LF_normalization': True, 'Q_initialization': "64'b0", 'NZ_initialization': "16'b0",
                  'original_full_module_reset_update_and_hold_body_identical': True,
                  'producer_body_sha256': builder.sha(old_mirror.split(');', 1)[1].encode())},
              'physical_vendor_composition': {'original_receipt': str(VENDOR), 'original_sha256': VENDOR_SHA,
                  'accepted_applicability': str(V2 / 'applicability.json'), 'accepted_applicability_sha256': APPLICABILITY_SHA,
                  'original_default_path_only': True, 'activated_path_covered_by_separate_actual_v2_proof': True,
                  'canonical_collision_contract_unchanged': True, 'all_receipts_untouched': True},
              'native_syntax_and_mapped_store_evidence': {'quick_check': str(QUICK), 'quick_check_scope': 'Syntax/elaboration only',
                  'map_report': str(report_path), 'map_sha256': applicability['native_map']['sha256'], 'eight_distinct_mapped_M10K_stores': rows,
                  'total_logical_serial_store_bits': 32768, 'new_store_bits_vs_v13': 24576,
                  'final_fitter_packing_or_timing_claimed': False},
              'bound_evidence_files': e.files, 'negative_controls': controls,
              'inherited_v13_negative_controls': parent['negative_controls'], 'preserved_replica_applicability_controls': applicability['rejected_controls'],
              'new_simulator_or_Quartus_run': False, 'new_whole_board_native_run': False,
              'timing_accepted': False, 'mister_hardware_qualified': False, 'eligible_for_RBF': False,
              'scope': 'Separate exact v13-to-v14 FG/SPR typed applicability edge. The preserved native128 parent is not retagged as a v14 execution; resource store retention is native MAP evidence only. Root all-corner final fit and release gates remain independent.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'receipt': str(output), 'sha256': builder.sha(output.read_bytes()),
                      'all144_inputs': True, 'bound_files': len(e.files), 'mapped_stores': len(rows), 'negative_controls': len(controls), 'timing_accepted': False}))


if __name__ == '__main__':
    main()
