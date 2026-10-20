"""Strict v11 applicability edge for unchanged physical foreground/background RAM.

Additive to the immutable r2 proof. No simulator, Quartus job, vendor receipt
retagging, collision-mask widening or release-validator changes occur here.
"""
import argparse
import copy
import difflib
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
V9 = ROOT / 'build/timing_closure_20261011/integrated_v9_private'
R2 = ROOT / 'build/timing_closure_20261011/address_classes_v10/candidate_r2'
DDR = ROOT / 'build/ddr_parallel_sources_v9_v2/candidate'
COMBINED = ROOT / 'build/timing_closure_20261011/address_ddr_v11_private'
ORIGINAL_R2 = ROOT / 'build/timing_closure_20261011/address_classes_v10/independent_review_r2_composition.json'
R2_HELPER = ROOT / 'tests/graphics/qualify_bt_address_class_r2.py'
DDR_HELPER = ROOT / 'tests/graphics/prepare_bt_parallel_ddr_write.py'
DDR_MANIFEST = DDR.parent / 'manifest.json'
DDR_HASHES = {
    'rtl/BT.sv': '575060dae2abf4deb5713589c172d82331d63dab19ef2df4c6f125e09a8283a9',
    'Arcade-Battletoads.sv': 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf',
    'rtl/ddram.sv': 'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
}
V11_HASHES = dict(DDR_HASHES, **{
    'rtl/BT.sv': '4d01a2fcc84ea12ab800c420f5107b26cd6b373fd5a154deb4cdba7639db66e6',
    'rtl/TMS34020/TMS34020.sv': '46f0743c4b3186796c19d6fe1a2d1a3a5fa4750763f5890ff95e87789a057d1c',
    'rtl/TMS34020/TMS34020_MC.sv': '165a7d5a0265c8c98822b3771fcdf62b9a51d2bcd85cc45abbf1fb6bdd8d650a',
})
sha = lambda data: hashlib.sha256(data).hexdigest()


def load_module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_digest(data, expected, label):
    assert sha(data) == expected, (label, 'exact source/log identity changed', expected, sha(data))


def lf(data):
    """Normalize only CRLF; do not strip spaces, comments or any other byte."""
    text = data.decode('utf-8')
    result = text.replace('\r\n', '\n')
    assert '\r' not in result, 'Unsupported lone CR normalization'
    return result


def line_edits(before, after, owner):
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return [(first, last, b[p:q], owner) for operation, first, last, p, q in matcher.get_opcodes() if operation != 'equal']


def overlap(a, b):
    ai, aj, _, _ = a
    bi, bj, _, _ = b
    if ai == aj and bi == bj:
        return ai == bi
    if ai == aj:
        return bi <= ai < bj
    if bi == bj:
        return ai <= bi < aj
    return max(ai, bi) < min(aj, bj)


def independently_recompose(baseline, parents):
    base = lf(baseline)
    edits = []
    for owner, data in parents:
        edits.extend(line_edits(base, lf(data), owner))
    for index, left in enumerate(edits):
        for right in edits[index + 1:]:
            assert not overlap(left, right), ('Overlapping parent deltas', left[:2], right[:2])
    lines = base.splitlines(keepends=True)
    for first, last, replacement, owner in sorted(edits, key=lambda edit: (edit[0], edit[1]), reverse=True):
        lines[first:last] = replacement
    return ''.join(lines), [{'start_line': first + 1, 'end_line_exclusive': last + 1, 'parent': owner, 'replacement_lf_sha256': sha(''.join(replacement).encode())} for first, last, replacement, owner in edits]


def wire_statement(text, name):
    matches = re.findall(r'\bwire(?:\s*\[[^\]]+\])?\s+' + re.escape(name) + r'\s*=\s*.*?;', text, re.S)
    assert len(matches) == 1, ('Expected one selector', name)
    return matches[0]


def vram_scope(r2, combined, library):
    names = ['FG_CPU_ADDR_MATCH', 'FG_DISP_SEL', 'FG_DRAW_SEL', 'FG0_SEL', 'FG1_SEL', 'FG0_SCRN', 'FG1_SCRN', 'BG0_SEL', 'BG1_SEL']
    selectors = {}
    for name in names:
        before, after = wire_statement(r2, name), wire_statement(combined, name)
        assert before == after, ('r2 selector changed', name)
        selectors[name] = sha(after.encode())
    bindings = {}
    for module, instance in [('FG_VRAM', 'FG0_VRAM'), ('FG_VRAM', 'FG1_VRAM'), ('BG_VRAM', 'BG0_VRAM_0'), ('BG_VRAM', 'BG0_VRAM_1'), ('BG_VRAM', 'BG1_VRAM_0'), ('BG_VRAM', 'BG1_VRAM_1')]:
        before = library.instance_ports(r2, module, instance)
        after = library.instance_ports(combined, module, instance)
        assert before == after, ('Complete r2 VRAM binding changed', instance)
        pattern = r'\b' + module + r'\s+' + instance + r'\s*\('
        spans = []
        for text in (r2, combined):
            matches = list(re.finditer(pattern, text))
            assert len(matches) == 1
            begin = matches[0].start()
            end = library.balanced_end(text, matches[0].end() - 1) + 1
            spans.append(text[begin:end])
        assert spans[0] == spans[1], ('Byte-exact instance body changed', instance)
        bindings[instance] = {'module': module, 'ports': sorted(after), 'body_lf_sha256': sha(spans[1].encode()), 'transfer_expression': after.get('TRANSFER')}
    return selectors, bindings


def reject(name, operation, controls):
    try:
        operation()
    except AssertionError as error:
        controls.append({'name': name, 'rejected': True, 'reason': str(error)[:350]})
    else:
        raise AssertionError('Negative control was accepted: ' + name)


def validate_log(data, expected, markers):
    check_digest(data, expected, 'retained transcript')
    text = data.decode(errors='replace')
    assert not re.search(r'\b(?:fatal|fail|error)\b', text, re.I), 'Retained transcript failure'
    assert all(marker in text for marker in markers), 'Retained transcript PASS marker absent'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-root', type=Path, default=COMBINED)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    recheck_path = output.with_name(output.stem + '-r2-input-recheck.json')
    assert not output.exists() and not recheck_path.exists(), 'Retained proof outputs are immutable'
    original_r2_data = ORIGINAL_R2.read_bytes()
    original_r2 = json.loads(original_r2_data)
    assert original_r2['passed'] and original_r2['schema'] == 'bt-address-class-r2-vram-composition-v1'
    check_digest(R2_HELPER.read_bytes(), original_r2['helper_sha256'], 'unchanged r2 proof helper')
    library = load_module(R2_HELPER, 'strict_r2_vram_library')
    check_digest(DDR_HELPER.read_bytes(), 'cb61d4ce35648066f6c31a463f64420ed4f08bae0ecbdf0e7810a8b1cdaf1f57', 'guarded DDR parent preparer')
    ddr_library = load_module(DDR_HELPER, 'ddr_parent_preparer')
    ddr_manifest_data = DDR_MANIFEST.read_bytes()
    ddr_manifest = json.loads(ddr_manifest_data)
    assert ddr_manifest['schema'] == 'bt-parallel-ddr-private-transform-v1' and ddr_manifest['status'] == 'PASS'
    assert ddr_manifest['base_sources'] == ddr_library.BASE and ddr_manifest['candidate_sources'] == DDR_HASHES
    assert ddr_manifest['transform_source'] == sha(DDR_HELPER.read_bytes())
    assert ddr_manifest['edits']['rtl/BT.sv'] == [
        {'before': '`endif\n);\n\n\tbit [31: 0] LA;', 'after': '`endif\n\t, output [3:0][31:0] EDATA_CANDIDATES\n\t, output [3:0] EDATA_SELECT\n);\n\n\tbit [31: 0] LA;'},
        {'before': "\tassign EDATA = SPR_DDR_REQ ? {8'b0,SPR_DRAW_DATA,8'b0,SPR_DRAW_DATA} :", 'after': ddr_library.PARALLEL + "\tassign EDATA = SPR_DDR_REQ ? {8'b0,SPR_DRAW_DATA,8'b0,SPR_DRAW_DATA} :"},
    ]
    # Reconstruct every DDR parent from full v9 bytes and unique source anchors.
    for name, expected in DDR_HASHES.items():
        base_data = library.file_pin(V9 / name, ddr_library.BASE[name])
        parent_data = library.file_pin(DDR / name, expected)
        text = lf(base_data)
        for edit in ddr_manifest['edits'][name]:
            assert text.count(edit['before']) == 1, (name, 'nonunique DDR transform anchor')
            text = text.replace(edit['before'], edit['after'], 1)
        assert text == lf(parent_data), (name, 'guarded DDR parent reconstruction')
    composition_path = args.candidate_root.parent / (args.candidate_root.name + '-composition.json')
    snapshot_path = args.candidate_root.parent / (args.candidate_root.name + '-snapshot.json')
    composition_data, snapshot_data = composition_path.read_bytes(), snapshot_path.read_bytes()
    composition, snapshot = json.loads(composition_data), json.loads(snapshot_data)
    assert composition['schema'] == 'bt-address-ddr-composition-v1' and set(composition['files']) == set(V11_HASHES)
    assert composition['constraints_changed'] is False and composition['root_modified'] is False
    assert snapshot['schema'] == 'bt-isolated-source-v1' and snapshot['git_head'] == library.ORACLE
    recomposition = {}
    for name, expected in V11_HASHES.items():
        baseline_hash = library.BASE.get(name, ddr_library.BASE.get(name))
        baseline = library.file_pin(V9 / name, baseline_hash)
        parents = []
        if name in library.FINAL:
            parents.append(('address-r2', library.file_pin(R2 / name, library.FINAL[name])))
        if name in DDR_HASHES:
            parents.append(('parallel-ddr', library.file_pin(DDR / name, DDR_HASHES[name])))
        target = library.file_pin(args.candidate_root / name, expected)
        assert snapshot['sources'][name] == expected and composition['files'][name]['sha256'] == expected
        result, edits = independently_recompose(baseline, parents)
        assert result == lf(target), (name, 'independent combined recomposition')
        if name != 'rtl/BT.sv':
            assert len(parents) == 1 and target == parents[0][1], (name, 'unchanged frozen parent bytes')
        recomposition[name] = {'baseline_sha256': baseline_hash, 'parent_sha256': {label: sha(data) for label, data in parents}, 'combined_sha256': expected, 'independently_derived_disjoint_edits': edits}
    r2_bt = lf(library.file_pin(R2 / 'rtl/BT.sv', library.FINAL['rtl/BT.sv']))
    combined_bt = lf(library.file_pin(args.candidate_root / 'rtl/BT.sv', V11_HASHES['rtl/BT.sv']))
    selectors, bindings = vram_scope(r2_bt, combined_bt, library)
    for name, expected in library.PHYSICAL.items():
        if name.startswith('rtl/'):
            library.file_pin(args.candidate_root / name, expected)
            assert snapshot['sources'][name] == expected
        library.file_pin(ROOT / name, expected)
    constraints = {}
    for name in snapshot['sources']:
        if name.endswith('.sdc'):
            baseline, current = (V9 / name).read_bytes(), (args.candidate_root / name).read_bytes()
            assert baseline == current and sha(current) == snapshot['sources'][name], (name, 'changed constraint')
            constraints[name] = sha(current)
    assert constraints

    # Run the unchanged source-bound verifier, not a simulator or vendor compile.
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(R2_HELPER), '--output', str(recheck_path)], cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    assert result.returncode == 0, ('Strict r2 input recheck', result.stdout[-1000:], result.stderr[-2000:])
    recheck_data = recheck_path.read_bytes()
    recheck = json.loads(recheck_data)
    assert recheck['passed'] and recheck['source_edge'] == original_r2['source_edge']
    assert recheck['collision_contract_unchanged'] == original_r2['collision_contract_unchanged']
    assert recheck['collision_contract_sha256'] == original_r2['collision_contract_sha256']
    assert recheck['retained_vendor_receipt'] == original_r2['retained_vendor_receipt']
    assert not recheck['new_vendor_simulation_performed'] and not recheck['mapped_atoms_verified']

    # Fault injection only in memory; source/fixture/log bytes on disk never change.
    controls = []
    old_pin = '.RAS_N(RAS_N | ~(FG0_SEL | FG0_SCRN))'
    assert combined_bt.count(old_pin) == 1
    bad_pin = combined_bt.replace(old_pin, '.RAS_N(1\'b1)', 1)
    reject('changed actual FG0 request pin', lambda: vram_scope(r2_bt, bad_pin, library), controls)
    assert combined_bt.count('CPU_ADDR_CLASS[0]') == 1
    bad_selector = combined_bt.replace('CPU_ADDR_CLASS[0]', 'CPU_ADDR_CLASS[1]', 1)
    reject('changed normal/serial selector', lambda: vram_scope(r2_bt, bad_selector, library), controls)
    memory = (args.candidate_root / 'rtl/BT_mem.sv').read_bytes()
    bad_geometry, geometry_count = re.subn(rb'(parameter\s+(?:integer\s+)?ADDR_WIDTH\s*=\s*)16\b', rb'\g<1>15', memory, count=1)
    assert geometry_count == 1, 'Expected actual RAM geometry parameter'
    reject('changed physical RAM address geometry', lambda: check_digest(bad_geometry, library.PHYSICAL['rtl/BT_mem.sv'], 'BT_mem geometry'), controls)
    vendor = json.loads(library.VENDOR_RECEIPT.read_bytes())
    fixture_name = next(name for name in vendor['fixtures'] if name.endswith('/current_vram_vendor_tb.sv'))
    fixture = (ROOT / fixture_name).read_bytes()
    bad_mask, mask_count = re.subn(rb'(wire\s+\[63:0\]\s+canonical_sq_mask_now\s*=\s*).*?;', rb'\g<1>64\'hffffffffffffffff;', fixture, count=1, flags=re.S)
    assert mask_count == 1
    reject('widened canonical serial collision mask', lambda: check_digest(bad_mask, vendor['fixtures'][fixture_name], 'collision predicate fixture'), controls)
    source_path, source_hash = next(iter(vendor['external_sources'].items()))
    intel = library.native_path(source_path).read_bytes()
    bad_intel = intel.replace(b'module altsyncram', b'module changed_altsyncram', 1)
    assert bad_intel != intel
    reject('changed actual Intel vendor source', lambda: check_digest(bad_intel, source_hash, 'Intel model'), controls)
    ram_run = next(result for result in vendor['results'] if result['test'] == 'ram')['runs'][0]
    log_hash = ram_run['log_sha256']
    log_entry = next(entry for entry in recheck['retained_vendor_receipt']['original_logs_rehashed'] if entry['sha256'] == log_hash)
    transcript = Path(log_entry['path']).read_bytes()
    validate_log(transcript, log_hash, ram_run['markers'])
    bad_log = transcript.replace(b'PASS', b'FAIL', 1)
    assert bad_log != transcript
    reject('changed retained vendor transcript', lambda: validate_log(bad_log, log_hash, ram_run['markers']), controls)
    reject('failure transcript with freshly computed digest', lambda: validate_log(bad_log, sha(bad_log), ram_run['markers']), controls)
    missing_pass = transcript.replace(ram_run['markers'][0].encode(), b'completion without qualification', 1)
    assert missing_pass != transcript
    reject('missing PASS marker with freshly computed digest', lambda: validate_log(missing_pass, sha(missing_pass), ram_run['markers']), controls)
    assert len(controls) == 8 and all(control['rejected'] for control in controls)
    assert ORIGINAL_R2.read_bytes() == original_r2_data, 'Original r2 receipt changed'
    check_digest(R2_HELPER.read_bytes(), original_r2['helper_sha256'], 'r2 helper stayed unchanged')
    receipt = {
        'schema': 'bt-v11-unchanged-physical-vram-applicability-v1',
        'passed': True, 'exit_code': 0,
        'scope': 'Independently guarded disjoint-parent recomposition, exact r2 VRAM decode/binding preservation and strict unchanged physical RAM/vendor-evidence applicability to frozen v11. No simulation or compiled/mapped/timing/hardware qualification is performed.',
        'helper_sha256': sha(Path(__file__).read_bytes()),
        'candidate_root': str(args.candidate_root.resolve()),
        'independent_recomposition': recomposition,
        'normalization': 'LF/CRLF only; lone CR rejected; no whitespace, comments, expressions or other bytes ignored. Non-BT combined sources retain exact parent bytes.',
        'source_snapshot': {'path': str(snapshot_path), 'sha256': sha(snapshot_data)},
        'source_composition_manifest': {'path': str(composition_path), 'sha256': sha(composition_data)},
        'ddr_parent_preparation_manifest': {'path': str(DDR_MANIFEST), 'sha256': sha(ddr_manifest_data), 'scope': 'Preparation identity only; DDR behavior remains independently qualified by its owner.'},
        'preserved_r2_receipt': {'path': str(ORIGINAL_R2), 'sha256': sha(original_r2_data), 'helper_sha256': original_r2['helper_sha256'], 'unchanged': True},
        'strict_input_recheck': {'path': str(recheck_path), 'sha256': sha(recheck_data), 'new_vendor_simulation_performed': False, 'truth_table_cases': recheck['truth_table_cases'], 'selector_comparisons': recheck['selector_comparisons'], 'actual_pin_comparisons': recheck['actual_pin_comparisons']},
        'byte_exact_r2_selector_statements_lf_sha256': selectors,
        'byte_exact_all_six_vram_instances': bindings,
        'physical_current_sources': copy.deepcopy(recheck['unchanged_current_module_sources']),
        'frozen_physical_module_root': str(args.candidate_root.resolve()),
        'retained_vendor_receipt': recheck['retained_vendor_receipt'],
        'collision_contract_unchanged': recheck['collision_contract_unchanged'],
        'collision_contract_sha256': recheck['collision_contract_sha256'],
        'strict_physical_data_x_z_comparison_exclusions': 0,
        'unchanged_constraint_sources': constraints,
        'negative_controls': controls,
        'new_vendor_simulation_performed': False, 'mapped_atoms_verified': False,
        'routed_timing_qualified': False, 'mister_hardware_qualified': False,
        'release_validators_modified': False,
        'limits': 'This edge applies retained actual Intel physical geometry/output-edge/collision qualification to byte-identical modules and preserved VRAM inputs in combined v11. Activated DDR, complete CPU/MC stage, native replay, fresh fitted timing/mapped atoms and hardware qualification remain separate current-source proofs.',
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'passed': True, 'receipt': str(output), 'combined_bt_sha256': V11_HASHES['rtl/BT.sv'], 'preserved_vram_instances': len(bindings), 'negative_controls_rejected': len(controls), 'new_simulations': 0}))


if __name__ == '__main__':
    main()
