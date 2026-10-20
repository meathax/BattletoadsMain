"""Replay the exact v12 FG to minimal serial-control edge without weakening assertions."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
CREATOR = ROOT / 'build/fg_serial_segments_b537_v3/fg_serial_segments_proof.py'
CREATOR_SHA = '4a6ec10e809c9fd68348b7294b5d677206220dda49a4fad96923c17d935f5a39'
BASE_ROOT = ROOT / 'build/timing_closure_20261011/vram_request_v12_private'
EDGE = ROOT / 'build/fg_serial_controls_v12_v2'
FINAL_FG = 'f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b'
BOUND = {
    'rtl/fg_vram.sv': '233061bcfdcb986e250a204ce488f2171372250baac073a28086065529d64fec',
    'rtl/BT_mem.sv': '903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'rtl/ddram.sv': 'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'rtl/bt_fg_ddr_clear.sv': 'bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1',
    'tests/graphics/ram_models.sv': '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
    'tests/foreground_read_equivalence_tb.sv': '684b4cc42c88d5216292eab1fee2cb2c37deaecc0c3cc778e396c291663487c1',
    'tests/foreground_ddr_tb.sv': 'fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c',
}
STATES = ['A_M', 'RAS_N_M', 'OE_N_M', 'WE_N_M', 'TRANSFER_M', 'CPU_SHIFT_M', 'SE_N_M',
          'CPU_COPY_MODE', 'CPU_COPY_MODE_B', 'SREG_POS', 'MEM_ROW', 'RMT_EXEC', 'MRT_EXEC',
          'RMT_DDR_STATE', 'COPY_WORD', 'COPY_ADDR', 'COPY_ADDR_N', 'COPY_POS', 'COPY_STATE',
          'UNALIGNED_EXEC', 'HOLE_A_FF', 'HOLE_SEL_FF', 'HOLE_RD_FF', 'COPY_PREFETCH_B',
          'CPU_RAM_WREN_SEG_B2', 'CPU_RAM_WREN_B2', 'CPU_RAM_A_B2', 'CPU_RAM_WE_B2',
          'RDY_RAS_N_OLD', 'CPU_SHIFT_DATA_Q', 'CPU_SHIFT_WE_Q']
sha = lambda data: hashlib.sha256(data).hexdigest()


def exact_replace(text, before, after):
    assert text.count(before) == 1, ('Exactly one creator statement required', before[:180])
    return text.replace(before, after, 1)


def assert_bound(path, expected):
    data = path.read_bytes()
    assert sha(data) == expected, ('Bound source changed', str(path))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Do not rewrite accepted receipts or failed run evidence'
    creator = assert_bound(CREATOR, CREATOR_SHA).decode().replace('\r\n', '\n')
    preparer_path = ROOT / 'tests/graphics/prepare_bt_fg_serial_controls.py'
    spec = importlib.util.spec_from_file_location('fg_control_preparer', preparer_path)
    preparer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(preparer)
    manifest = json.loads((EDGE / 'manifest.json').read_text())
    induction = json.loads((EDGE / 'receipt.json').read_text())
    assert manifest['helper_sha256'] == sha(preparer_path.read_bytes())
    assert induction['status'] == 'PASS' and induction['sha256'] == FINAL_FG
    parent = assert_bound(BASE_ROOT / 'rtl/fg_vram.sv', BOUND['rtl/fg_vram.sv'])
    candidate = assert_bound(EDGE / 'candidate/rtl/fg_vram.sv', FINAL_FG)
    generated, edits = preparer.transform(parent)
    assert generated == candidate and edits == manifest['edits']
    preparer.verify_source(parent, candidate, edits)
    source_data, source_paths = {}, {}
    for name, expected in BOUND.items():
        path = (ROOT if name.startswith('tests/') else BASE_ROOT) / name
        source_data[name] = assert_bound(path, expected)
        source_paths[name] = str(path)
    output.mkdir(parents=True)
    overlay = output / 'candidate'
    oracle = output / 'oracle'
    for name, data in source_data.items():
        for target_root in (overlay, oracle):
            path = target_root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(candidate if target_root == overlay and name == 'rtl/fg_vram.sv' else data)
    run_name = 'fg-serial-controls-' + uuid.uuid4().hex
    reference_function = '''    def reference_bytes(name):
        data = (Path({oracle!r}) / name).read_bytes()
        expected = {bound!r}[name]
        assert hashlib.sha256(data).hexdigest() == expected, 'Exact frozen current parent required'
        return data
'''.format(oracle=str(oracle), bound=BOUND)
    start, end = creator.index('    def reference_bytes(name):'), creator.index('    def freeze(', creator.index('    def reference_bytes(name):'))
    worker = creator[:start] + reference_function + '\n' + creator[end:]
    worker = exact_replace(worker, "BASELINE_REF = 'b53726397822b9dbebb02d36411294056fd08649'",
                           "BASELINE_REF = 'frozen-v12-fg-233061bcfdcb986e'" )
    worker = exact_replace(worker, "name = 'item4-equivalence-'+uuid.uuid4().hex", 'name = ' + repr(run_name))
    worker = exact_replace(worker, "'immutable b537 FG control/interface", "'exact frozen current-v12 FG control/interface")
    # The original strict capture tuple is retained and strengthened with
    # segment enables and every bank output; there are no exclusions/masks.
    for prefix in ('candidate', 'reference'):
        old = prefix + '.mem.banks[segment_pin_bank].ram.SWREN,' + prefix + '.mem.banks[segment_pin_bank].ram.SADDR_W}'
        new = old[:-1] + ',' + prefix + '.mem.banks[segment_pin_bank].ram.SWREN_SEGMENT,' + prefix + '.mem.banks[segment_pin_bank].ram.Q,' + prefix + '.mem.banks[segment_pin_bank].ram.SQ}'
        worker = exact_replace(worker, old, new)
    signal_tuple = lambda prefix: '{' + ','.join(prefix + '.' + state for state in STATES) + '}'
    extra = '\n  integer serial_control_state_edges=0,serial_control_pin_edges=0;\n'
    extra += '  always @(negedge CLK) begin\n    #0.1;\n    serial_control_state_edges++;\n'
    extra += '    assert (' + signal_tuple('candidate') + ' === ' + signal_tuple('reference') + ')\n'
    extra += '      else $fatal(1,"serial control changed an original complete state/capture edge");\n  end\n'
    extra += '  genvar chunk_check_bank;\n  generate for(chunk_check_bank=0;chunk_check_bank<4;chunk_check_bank++) begin: serial_chunk_edge_check\n'
    extra += '    always @(posedge CLK or negedge CLK) begin\n      serial_control_pin_edges++;\n'
    extra += '      assert(candidate.CPU_COPY_MODE_B4[chunk_check_bank] === reference.CPU_COPY_MODE_B4[chunk_check_bank])\n'
    extra += '        else $fatal(1,"foreground serial chunks changed before/after RAM edge bank=%0d",chunk_check_bank);\n'
    pin_names = ['ADDR','DATA','WREN','BE','WREN_LANE','QGATE_D','SADDR','SDATA','SWREN','SADDR_W','SWREN_SEGMENT','Q','SQ']
    pin_tuple = lambda prefix: '{' + ','.join(prefix + '.mem.banks[chunk_check_bank].ram.' + pin for pin in pin_names) + '}'
    extra += '      assert(' + pin_tuple('candidate') + ' === ' + pin_tuple('reference') + ')\n'
    extra += '        else $fatal(1,"full RAM capture/output pins differ before/after edge bank=%0d",chunk_check_bank);\n'
    extra += '    end\n  end endgenerate\n'
    sentinel = "        tb = workspace/'item4_foreground_equivalence_tb.sv'\n"
    inserted = "        original = original.replace('  initial begin\\n', " + repr(extra + '  initial begin\n') + ", 1)\n"
    inserted += "        original = original.replace('    $display(\"PASS foreground transaction equivalence', '    $display(\"PASS serial chunk complete pins/state: state_edges=%0d bank_edge_checks=%0d states=31 pin_fields=13; case equality before/after every RAM edge\",serial_control_state_edges,serial_control_pin_edges);\\n    $display(\"PASS foreground transaction equivalence', 1)\n"
    worker = exact_replace(worker, sentinel, inserted + sentinel)
    worker_path = output / 'worker.py'
    worker_path.write_text(worker, newline='\n')
    compile(worker, str(worker_path), 'exec')
    preparation = {'schema':'bt-fg-control-full-pin-replay-preparation-v1','creator_path':str(CREATOR),
                   'creator_sha256':CREATOR_SHA,'helper_sha256':sha(Path(__file__).read_bytes()),
                   'worker_sha256':sha(worker_path.read_bytes()),'creator_outer_line_ending_normalization':'LF only',
                   'source_paths':source_paths,
                   'parent_sources':BOUND,'candidate_fg_sha256':FINAL_FG,
                   'induction_receipt':str(EDGE/'receipt.json'),'induction_receipt_sha256':sha((EDGE/'receipt.json').read_bytes()),
                   'run_name':run_name,'original_assertions_preserved':True,'additional_original_state_names':STATES,
                   'RAM_case_equality_field_names':pin_names,'RAM_collision_masks_added':0}
    (output/'preparation.json').write_text(json.dumps(preparation,indent=2)+'\n')
    command = [sys.executable,'-B','-X','utf8',str(worker_path),'--candidate-dir',str(overlay),'--tests','fg','fg-ddr']
    flags = subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    result = subprocess.run(command,cwd=ROOT,creationflags=flags)
    retained = ROOT/'build'/run_name
    run_receipt_path = retained/'receipt.json'
    assert run_receipt_path.is_file(), ('Retained compiler/runtime failure',str(retained),result.returncode)
    run_receipt = json.loads(run_receipt_path.read_text())
    assert result.returncode==0 and run_receipt['all_passed'] and [x['test'] for x in run_receipt['results']]==['fg','fg-ddr']
    logs, coverage = {}, {}
    for record in run_receipt['results']:
        for name in ('build.log','run.log'):
            path=retained/record['test']/name
            data=path.read_bytes()
            logs[str(path)] = sha(data)
            if name=='run.log':
                text=data.decode(errors='replace')
                assert not re.search(r'\b(fatal|fail|error)\b',text,re.I), 'Retain failure; do not relabel PASS'
                assert 'PASS' in text
                if record['test']=='fg':
                    match=re.search(r'PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)',text)
                    assert match and int(match[1])>100000
                    coverage['state_edges']=int(match[1]);coverage['bank_edge_checks']=int(match[2])
                    assert 'restart_collisions=8 abort_collisions=8 reset_collects=2' in text
                    assert 'PASS item4 RMT/control corners:' in text
                    for marker in ('PASS foreground transaction equivalence','PASS serial chunk complete pins/state'):
                        assert marker in text
                else:
                    assert 'PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure' in text
    for name,path in source_paths.items():
        assert_bound(Path(path),BOUND[name])
    assert_bound(EDGE/'candidate/rtl/fg_vram.sv',FINAL_FG)
    receipt={'schema':'bt-fg-serial-controls-current-parent-full-pin-v1','status':'PASS',
             'preparation':str(output/'preparation.json'),'preparation_sha256':sha((output/'preparation.json').read_bytes()),
             'executed_receipt':str(run_receipt_path),'executed_receipt_sha256':sha(run_receipt_path.read_bytes()),
             'source_paths':source_paths,'parent_sources':BOUND,'candidate_fg_sha256':FINAL_FG,
             'helper_sha256':sha(Path(__file__).read_bytes()),'creator_sha256':CREATOR_SHA,
             'worker_sha256':sha(worker_path.read_bytes()),'coverage':coverage,'retained_logs':logs,
             'original_assertions_preserved':True,'case_equality_exclusions':0,'collision_masks_added':0,
             'source_stability_passed':True,'vendor_simulator_rerun':False,'mapped_or_timing_claim':False,
             'scope':'Fresh complete foreground/current-parent pin and state replay plus actual current DDR workload, '
                     'with every retained assertion and added 31 original states/13 RAM pin fields on all banks before/after edges. '
                     'Canonical behavioral RAM; strict Intel data/X collision qualification is a separate typed applicability composition.'}
    path=output/'receipt.json';path.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':str(path),'sha256':sha(path.read_bytes()),'status':'PASS','coverage':coverage}))


if __name__=='__main__':
    main()
