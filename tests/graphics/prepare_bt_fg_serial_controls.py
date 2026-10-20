"""Prepare pin-identical same-edge serial data controls from frozen v12 FG."""
import argparse
import hashlib
import importlib.util
import itertools
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE_ROOT = ROOT / 'build/timing_closure_20261011/vram_request_v12_private'
SOURCE = 'rtl/fg_vram.sv'
BASE_SHA = '233061bcfdcb986e250a204ce488f2171372250baac073a28086065529d64fec'
PHYSICAL = {
    'rtl/BT_mem.sv': '903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'rtl/bg_vram.sv': 'ba42376b22889cf0dc0f1b55203e21e1cf121daa7b4ab690ad24eb8586ba31d1',
    'tests/graphics/ram_models.sv': '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
}
sha = lambda data: hashlib.sha256(data).hexdigest()


def transform(before):
    assert sha(before) == BASE_SHA, 'Exact fitted v12 FG required'
    text = before.decode().replace('\r\n', '\n')
    assert '\r' not in text, 'Only the original LF/CRLF newline contract is supported'
    edits = [
        ('\twire [3:0][3:0] CPU_COPY_MODE_B4 = {{4{CPU_COPY_MODE_T[3]}}, {4{CPU_COPY_MODE_T[2]}}, {4{CPU_COPY_MODE_T[1]}}, {4{CPU_COPY_MODE_T[0]}}};',
         '\twire [3:0][3:0] CPU_COPY_MODE_B4;'),
        ('.SADDR_V(SADDR_V_BK[vb]), .COPY_MODE(CPU_COPY_MODE_T[vb]));',
         '.SADDR_V(SADDR_V_BK[vb]), .COPY_MODE(CPU_COPY_MODE_T[vb]),\n\t\t\t.COPY_MODE_CHUNKS(CPU_COPY_MODE_B4[vb]));'),
        ('\toutput        COPY_MODE\n);',
         '\toutput        COPY_MODE,\n\toutput [3:0]  COPY_MODE_CHUNKS\n);'),
        ("\tbit       mrt = 1'b0, rmt = 1'b0, copy_mode = 1'b0;",
         "\tbit       mrt = 1'b0, rmt = 1'b0, copy_mode = 1'b0;\n\t// Capture the original D at the original edge; each 16-bit RAM mux has its own control.\n\t(* preserve, dont_merge *) bit [3:0] copy_mode_chunks = 4'b0;"),
        ("ras_old <= 1'b1; mrt <= 0; rmt <= 0; copy_mode <= 0; ddr_state <= '0; pos <= '0; row <= '0;",
         "ras_old <= 1'b1; mrt <= 0; rmt <= 0; copy_mode <= 0; copy_mode_chunks <= '0; ddr_state <= '0; pos <= '0; row <= '0;"),
        ("copy_mode <= cpu_shift; row <= a_row; mrt <= !cpu_shift; pos <= '0;",
         "copy_mode <= cpu_shift; copy_mode_chunks <= {4{cpu_shift}}; row <= a_row; mrt <= !cpu_shift; pos <= '0;"),
        ("copy_mode <= cpu_shift; row <= a_row; rmt <= !se_n; pos <= '0;",
         "copy_mode <= cpu_shift; copy_mode_chunks <= {4{cpu_shift}}; row <= a_row; rmt <= !se_n; pos <= '0;"),
        ('\tassign COPY_MODE = copy_mode;\nendmodule',
         '\tassign COPY_MODE = copy_mode;\n\tassign COPY_MODE_CHUNKS = copy_mode_chunks;\n`ifndef SYNTHESIS\n\talways @(posedge CLK) if (RST_N)\n\t\tassert (copy_mode_chunks == {4{copy_mode}})\n\t\t\telse $fatal(1,"foreground serial mux control changed capture edge");\n`endif\nendmodule'),
    ]
    result = text
    for old, new in edits:
        assert result.count(old) == 1, ('Exact declaration/control statement required', old)
        result = result.replace(old, new, 1)
    restored = result
    for old, new in reversed(edits):
        assert restored.count(new) == 1
        restored = restored.replace(new, old, 1)
    assert restored == text
    newline = '\r\n' if b'\r\n' in before else '\n'
    return result.replace('\n', newline).encode(), [{'before': old, 'after': new} for old, new in edits]


def verify_source(before, candidate, edits):
    expected, exact_edits = transform(before)
    assert candidate == expected and edits == exact_edits
    original = before.decode().replace('\r\n', '\n')
    changed = candidate.decode().replace('\r\n', '\n')
    physical_module = 'module BT_FG_BANKED_VRAM'
    original_bank = original[original.index(physical_module):original.index('// Per-bank replica')]
    changed_bank = changed[changed.index(physical_module):changed.index('// Per-bank replica')]
    assert original_bank == changed_bank, 'Every RAM address/data/enable/mux/geometry expression must remain unchanged'
    tracker = changed[changed.index('module BT_FG_VIDEO_ADDR_TRACK'):]
    # Each original mode NBA remains in place with its adjacent exact-D copy.
    assignments = re.findall(r'copy_mode\s*<=\s*([^;]+);\s*copy_mode_chunks\s*<=\s*([^;]+);', tracker)
    assert assignments == [('0', "'0"), ('cpu_shift', '{4{cpu_shift}}'), ('cpu_shift', '{4{cpu_shift}}')]
    assert len(re.findall(r'\bcopy_mode_chunks\s*<=', tracker)) == 3
    assert "bit [3:0] copy_mode_chunks = 4'b0;" in tracker
    assert '(* preserve, dont_merge *) bit [3:0] copy_mode_chunks' in tracker
    assert '.SCSEL4(CPU_COPY_MODE_B4)' in changed
    assert '.COPY_MODE_CHUNKS(CPU_COPY_MODE_B4[vb])' in changed
    assert 'copy_mode_chunks <= {4{copy_mode}}' not in changed, 'Q copying would add a cycle'
    return {'banked_ram_body_sha256': sha(original_bank.encode()),
            'adjacent_original_and_copy_assignments': assignments,
            'init_and_async_reset_identical': True, 'unchanged_original_mode_NBA_order': True,
            'all_original_controller_statements_recovered_by_inverse': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Preserve immutable candidates and receipts'
    before = (BASE_ROOT / SOURCE).read_bytes()
    candidate, edits = transform(before)
    proof = verify_source(before, candidate, edits)
    spec = importlib.util.spec_from_file_location('sv_selector', ROOT / 'tests/graphics/qualify_bt_address_class_r2.py')
    library = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(library)
    old_tracker = before.decode().replace('\r\n', '\n').split('module BT_FG_VIDEO_ADDR_TRACK', 1)[1]
    patterns = [r'if \((!ras_n && ras_old)\)', r'if \((!oe_n && we_n && transfer)\)',
                r'else if \((!oe_n && !we_n && transfer)\)']
    guards = []
    for pattern in patterns:
        matches = re.findall(pattern, old_tracker)
        assert len(matches) == 1
        guards.append(matches[0])
    parsed = [library.SVExpression(value).tree for value in guards]
    checks, pin_bits = 0, 0
    for values in itertools.product((0, 1), repeat=8):
        signals = dict(zip(['RST_N', 'ras_n', 'ras_old', 'oe_n', 'we_n', 'transfer', 'cpu_shift', 'old_mode'], values))
        original_next = signals['old_mode']
        shadows_next = [signals['old_mode']] * 4
        if not signals['RST_N']:
            original_next, shadows_next = 0, [0] * 4
        elif library.evaluate(parsed[0], lambda key: (1, signals[key]))[1]:
            if library.evaluate(parsed[1], lambda key: (1, signals[key]))[1]:
                original_next, shadows_next = signals['cpu_shift'], [signals['cpu_shift']] * 4
            elif library.evaluate(parsed[2], lambda key: (1, signals[key]))[1]:
                original_next, shadows_next = signals['cpu_shift'], [signals['cpu_shift']] * 4
        assert shadows_next == [original_next] * 4
        # A single bit spans every arbitrary sprite/shift word bit. All data
        # combinations are tested; geometry and slicing are byte-identical.
        for cpu_bit, serial_bit in itertools.product((0, 1), repeat=2):
            reference_data = cpu_bit if original_next else serial_bit
            for copy in shadows_next:
                assert (cpu_bit if copy else serial_bit) == reference_data
                pin_bits += 1
        checks += 1
    controls = []
    for label, bad in [
        ('delayed_Q_copy', candidate.replace(b'copy_mode_chunks <= {4{cpu_shift}};', b'copy_mode_chunks <= {4{copy_mode}};', 1)),
        ('incorrect_async_reset', candidate.replace(b"copy_mode_chunks <= '0;", b"copy_mode_chunks <= '1;", 1)),
        ('changed_RAM_mux_pin', candidate.replace(b'SCSEL4[bank][3] ?', b'SCSEL4[bank][2] ?', 1)),
        ('changed_chunk_binding', candidate.replace(b'.COPY_MODE_CHUNKS(CPU_COPY_MODE_B4[vb])', b'.COPY_MODE_CHUNKS(CPU_COPY_MODE_B4[0])', 1)),
        ('lost_preservation_attribute', candidate.replace(b'(* preserve, dont_merge *) bit [3:0] copy_mode_chunks', b'bit [3:0] copy_mode_chunks', 1)),
    ]:
        assert bad != candidate
        try:
            verify_source(before, bad, edits)
        except AssertionError:
            controls.append({'name': label, 'rejected': True})
        else:
            raise AssertionError('Negative control accepted: ' + label)
    output.mkdir(parents=True)
    for folder, data in [('oracle', before), ('candidate', candidate)]:
        path = output / folder / SOURCE
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    physical, physical_paths = {}, {}
    for name, expected_hash in PHYSICAL.items():
        path = (ROOT if name.startswith('tests/') else BASE_ROOT) / name
        data = path.read_bytes()
        assert sha(data) == expected_hash
        physical[name] = expected_hash
        physical_paths[name] = str(path)
    manifest = {'schema': 'bt-fg-serial-chunk-controls-edge-v1', 'source': SOURCE,
                'parent_source_root': str(BASE_ROOT), 'before_sha256': BASE_SHA,
                'sha256': sha(candidate), 'lf_sha256': sha(candidate.replace(b'\r\n', b'\n')),
                'helper_sha256': sha(Path(__file__).read_bytes()), 'edits': edits,
                'unchanged_physical_sources': physical, 'physical_source_paths': physical_paths}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    receipt = {'schema': 'bt-fg-serial-chunk-controls-induction-v1', 'status': 'PASS',
               'manifest_sha256': sha((output / 'manifest.json').read_bytes()),
               'helper_sha256': manifest['helper_sha256'], 'source': manifest['source'],
               'before_sha256': BASE_SHA, 'sha256': sha(candidate), 'proof': proof,
               'source_parsed_original_guards': guards, 'transition_cases': checks,
               'arbitrary_data_bit_mux_comparisons': pin_bits,
               'induction': 'All four copies initialize/reset with original mode and each assignment uses its exact D in the same branch/edge; holds preserve equality. Therefore every serial RAM input bit equals the original on every edge, including reset/collisions and EN0.',
               'negative_controls': controls, 'root_modified': False, 'simulated': False,
               'mapped_or_timing_claim': False, 'vendor_rerun': False,
               'scope': 'New control register induction plus byte-identical complete physical RAM mux/body. '
                        'This does not retag any vendor receipt or claim routed timing improvement.'}
    receipt_path = output / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'candidate': str(output / 'candidate'), 'sha256': sha(candidate),
                      'receipt': str(receipt_path), 'receipt_sha256': sha(receipt_path.read_bytes()),
                      'transition_cases': checks, 'data_bit_comparisons': pin_bits,
                      'negative_controls_rejected': len(controls)}))


if __name__ == '__main__':
    main()
