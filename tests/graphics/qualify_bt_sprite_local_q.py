"""Qualify exact same-edge sprite copies with Intel's RAM and retained consumers."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
VENDOR = Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA = 'c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'
MODELSIM = Path('D:/q17/modelsim_ase/win32aloem')
PARENT_FUNCTIONAL = ROOT / 'build/final_v18_current_input_qualification/receipt.json'
PARENT_FUNCTIONAL_SHA = 'a7f8af180aaabfe7257229d43b15698ab32b19d2b92c5c5c7df8e401c25412a7'
FG_PIN_PROOF = ROOT / 'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2.json'
FG_PIN_PROOF_SHA = 'b69b35a83a218444197b7ac7a7629d9e3a71d82c3ffa0d53309b0ffd4fa8d91a'
FG_PIN_BENCH = ROOT / 'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2-compiled-inputs/item4_foreground_equivalence_tb.sv'
FG_PIN_BENCH_SHA = 'af689824790f60bcce1b309cae68071e91fb693281da99a9c672e9e8978bc9aa'
PORTS = ('Q', 'RDY', 'SQ', 'BLIT_Q', 'CPU_SHIFT_BUSY', 'CPU_SHIFT_Q',
         'ESADDR', 'ESDATA', 'ESWR', 'ESRD', 'COMPLETE_RDY', 'COMPLETE_RDY_L',
         'PACKET_IDLE_L', 'PACKET_IDLE', 'BLIT_NONZERO')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def once(text, before, after):
    assert text.count(before) == 1, ('Fixture anchor changed', before)
    return text.replace(before, after)


def normalized_text(data):
    return data.decode('utf-8-sig').replace('\r\n', '\n')


def adapted_read_fixture(text):
    text = once(text, 'SPR_VRAM_SYNC candidate_core(', 'SPR_VRAM_SYNC #(.LOCAL_FG_Q(1)) candidate_core(')
    text = once(text, '.CPU_SHIFT_Q(cpu_q_new),',
                '.CPU_SHIFT_Q(cpu_q_new),.FG0_SHIFT_Q(local_q0),.FG1_SHIFT_Q(local_q1),')
    text = once(text, 'module sprite_read_equivalence_tb;',
                'module sprite_read_equivalence_tb;\n    wire [63:0] local_q0,local_q1;\n    integer full_local_checks=0;')
    before = ','.join('reference_core.' + p for p in PORTS)
    after = ','.join('candidate_core.' + p for p in PORTS)
    monitor = '''
    task automatic check_local_outputs;
        assert ({%s} === {%s}) else $fatal(1,"complete sprite legacy output tuple changed");
        assert (local_q0===cpu_q_old && local_q1===cpu_q_old)
            else $fatal(1,"actual SPR foreground aliases differ from immutable old output");
        full_local_checks++;
    endtask
    always @(posedge clk or negedge clk) begin
        check_local_outputs();#0.1;check_local_outputs();
    end
    final $display("SPRITE_LOCAL_FULL_OUTPUTS checks=%%0d ports=15",full_local_checks);
''' % (before, after)
    first_end = text.index('endmodule')
    return text[:first_end] + monitor + text[first_end:]


def adapted_packet_fixture(text):
    text = once(text, 'SPR_VRAM dut(', 'SPR_VRAM_SYNC #(.LOCAL_FG_Q(1)) dut(')
    text = once(text, '    wire [63:0] read_data;', '    wire [63:0] read_data;\n    integer local_checks=0;')
    monitor = '''
    always @(posedge clk or negedge clk) begin
        #0.1;
        assert(dut.FG0_SHIFT_Q===read_data && dut.FG1_SHIFT_Q===read_data)
            else $fatal(1,"foreground packet local output differs");
        local_checks++;
    end
    final $display("SPRITE_LOCAL_PACKET_OUTPUTS checks=%0d",local_checks);
'''
    return text[:text.index('endmodule')] + monitor + text[text.index('endmodule'):]


def negative_controls(preparer, edge, manifest):
    spr = (edge / 'candidate/rtl/spr_vram.sv').read_bytes()
    bt = (edge / 'candidate/rtl/BT.sv').read_bytes()
    original = {name: (edge / 'oracle' / name).read_bytes() for name in manifest['sources']}
    cases = [
        ('old_Q_pipeline', 'rtl/spr_vram.sv', b'fg0_q<=raw_q;', b'fg0_q<=Q;'),
        ('wrong_copy_edge', 'rtl/spr_vram.sv', b'fg1_q<=raw_q;', b'fg1_q<=fg0_q;'),
        ('new_init', 'rtl/spr_vram.sv', b"fg0_q = 64'b0", b"fg0_q = 64'b1"),
        ('missing_preserve', 'rtl/spr_vram.sv', b'(* preserve, dont_merge *) reg [63:0] fg0_q', b'(* dont_merge *) reg [63:0] fg0_q'),
        ('missing_dont_merge', 'rtl/spr_vram.sv', b'(* preserve, dont_merge *) reg [63:0] fg1_q', b'(* preserve *) reg [63:0] fg1_q'),
        ('wrong_default', 'rtl/spr_vram.sv', b'parameter LOCAL_FG_Q=0', b'parameter LOCAL_FG_Q=1'),
        ('original_Q_changed', 'rtl/spr_vram.sv', b'Q<=raw_q;', b'Q<=~raw_q;'),
        ('RAM_output_mode_changed', 'rtl/spr_vram.sv', b'VRAM_SHIFTREG #(addr_width,1,0)', b'VRAM_SHIFTREG #(addr_width,1,1)'),
        ('FG0_wrong_consumer', 'rtl/BT.sv', b'.CPU_SHIFT_Q(FG0_SHIFT_Q)', b'.CPU_SHIFT_Q(CPU_SHIFT_Q)'),
        ('FG1_wrong_consumer', 'rtl/BT.sv', b'.CPU_SHIFT_Q(FG1_SHIFT_Q)', b'.CPU_SHIFT_Q(FG0_SHIFT_Q)'),
        ('activation_off', 'rtl/BT.sv', b'.LOCAL_FG_Q(1)', b'.LOCAL_FG_Q(0)'),
        ('unrelated_top_edit', 'rtl/BT.sv', b'.CPU_SHIFT_BUSY(CPU_SHIFT_BUSY)', b'.CPU_SHIFT_BUSY()'),
    ]
    rejected = []
    for label, name, old, new in cases:
        source = spr if name == 'rtl/spr_vram.sv' else bt
        assert old in source, ('Negative control anchor missing', label)
        mutated = source.replace(old, new, 1)
        try:
            assert preparer.inverse(mutated, manifest['sources'][name]['operations']) == original[name]
        except AssertionError:
            rejected.append(label)
        else:
            raise AssertionError(('Corrupted source accepted', label))
    return rejected


def run_command(command, cwd, log, timeout):
    result = subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT,
                            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW)
    return dict(command=command, exit_code=result.returncode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    edge, output = args.edge.resolve(), args.output.resolve()
    output.relative_to(ROOT)
    assert not output.exists()
    preparer_path = ROOT / 'tests/graphics/prepare_bt_sprite_local_q.py'
    preparer = load(preparer_path, 'sprite_local_q_source_edge')
    manifest = preparer.verify_edge(edge)
    assert sha(preparer_path) == manifest['helper']['sha256']
    assert sha(PARENT_FUNCTIONAL) == PARENT_FUNCTIONAL_SHA
    assert sha(FG_PIN_PROOF) == FG_PIN_PROOF_SHA and sha(FG_PIN_BENCH) == FG_PIN_BENCH_SHA
    assert sha(VENDOR) == VENDOR_SHA
    snapshot = read_json(preparer.SNAPSHOT)
    parent = Path(snapshot['project']).parent
    memory = parent / 'rtl/BT_mem.sv'
    assert sha(memory) == snapshot['sources']['rtl/BT_mem.sv']
    old_spr = (edge / 'oracle/rtl/spr_vram.sv').read_bytes()
    new_spr = (edge / 'candidate/rtl/spr_vram.sv').read_bytes()
    old_text, new_text = normalized_text(old_spr), normalized_text(new_spr)
    assert 'fg0_q<=raw_q;' in new_text and 'fg1_q<=raw_q;' in new_text
    assert new_text.count('(* preserve, dont_merge *) reg [63:0] fg') == 2
    assert "fg0_q = 64'b0" in new_text and "fg1_q = 64'b0" in new_text
    assert 'always @(posedge CLK) begin\n   fg0_q<=raw_q;\n   fg1_q<=raw_q;\n  end' in new_text
    old_q_block = re.search(r'(?m)^\s*always @\(posedge CLK\) begin\n\s*Q<=raw_q;\n\s*for\(integer nibble=0;nibble<16;nibble=nibble\+1\)\n\s*NZ\[nibble\]<=\|raw_q\[nibble\*4\+:4\];\n\s*end', old_text)
    assert old_q_block is not None and new_text.count(old_q_block.group()) == 1
    compiled_spr = new_text.replace('SPR_VRAM', 'SPR_VRAM_SYNC')
    assert new_text.count('SPR_VRAM') == 1
    assert compiled_spr.count('BT_SPR_POST_NONZERO_MIRROR') == 2
    compiled_spr = compiled_spr.replace('BT_SPR_POST_NONZERO_MIRROR', 'BT_SPR_POST_NONZERO_MIRROR_LOCAL')
    read_fixture = ROOT / 'tests/sprite_read_equivalence_tb.sv'
    packet_fixture = ROOT / 'tests/sprite_packet_tb.sv'
    vendor_fixture = ROOT / 'tests/graphics/sprite_local_q_vendor_tb.sv'
    controls = negative_controls(preparer, edge, manifest)
    output.mkdir(parents=True)
    compiled = output / 'compiled'
    compiled.mkdir()
    artifacts = {
        'spr_oracle.sv': old_spr,
        'spr_candidate.sv': compiled_spr.encode(),
        'BT_mem.sv': memory.read_bytes(),
        'sprite_local_q_vendor_tb.sv': vendor_fixture.read_bytes(),
        'sprite_read_equivalence_tb.sv': adapted_read_fixture(normalized_text(read_fixture.read_bytes())).encode(),
        'sprite_packet_tb.sv': adapted_packet_fixture(normalized_text(packet_fixture.read_bytes())).encode(),
    }
    for name, data in artifacts.items():
        (compiled / name).write_bytes(data)
    commands = []
    with (output / 'compile.log').open('w', encoding='utf-8') as log:
        commands.append(run_command([str(MODELSIM / 'vlib.exe'), 'work'], output, log, 300))
        if commands[-1]['exit_code'] == 0:
            command = [str(MODELSIM / 'vlog.exe'), '-sv', '-work', 'work']
            command += [str(compiled / name) for name in artifacts] + [str(VENDOR)]
            commands.append(run_command(command, output, log, 600))
    assert all(command['exit_code'] == 0 for command in commands), ('Compile failed', str(output / 'compile.log'))
    read_display = re.findall(r'\$display\s*\(\s*"([^"\n]*PASS[^"\n]*)"', normalized_text(read_fixture.read_bytes()))
    assert len(read_display) == 1
    read_marker = re.escape(read_display[0]).replace('%0d', r'\d+')
    patterns = {
        'sprite_local_q_vendor_tb': r'SPRITE_LOCAL_VENDOR_PASS pre=(\d+) post=(\d+) old_data=(\d+) mask_cases=(\d+) collisions=(\d+) offedge=(\d+) unknown=(\d+)',
        'sprite_read_equivalence_tb': read_marker,
        'sprite_packet_tb': r'SPRITE_PACKET_PASS packets=512 readbacks=512 completion_checks=528',
    }
    results = []
    for top, pattern in patterns.items():
        path = output / (top + '.log')
        command = [str(MODELSIM / 'vsim.exe'), '-c', 'work.' + top,
                   '-do', 'onerror {quit -code 1}; run -all; quit -code 0']
        with path.open('w', encoding='utf-8') as log:
            result = run_command(command, output, log, 600)
        text = path.read_text(encoding='utf-8', errors='replace')
        matches = re.findall(pattern, text)
        assert result['exit_code'] == 0 and len(matches) == 1, ('Consumer/vendor run failed', top, str(path))
        assert not re.search(r'\*\*\s+(?:Error|Fatal):', text), ('Simulator error', top)
        local_count = None
        if top == 'sprite_read_equivalence_tb':
            local = re.findall(r'SPRITE_LOCAL_FULL_OUTPUTS checks=(\d+) ports=15', text)
            assert len(local) == 1 and int(local[0]) > 0
            local_count = int(local[0])
        elif top == 'sprite_packet_tb':
            local = re.findall(r'SPRITE_LOCAL_PACKET_OUTPUTS checks=(\d+)', text)
            assert len(local) == 1 and int(local[0]) > 0
            local_count = int(local[0])
        else:
            values = tuple(int(value) for value in matches[0])
            assert values[0] == values[1] and values[2:6] == (128, 32768, 16384, 16) and values[6] >= 2
        result.update(top=top, log=str(path), log_sha256=sha(path), parsed_coverage=matches[0],
                      additional_local_output_checks=local_count)
        results.append(result)
        print(json.dumps(dict(top=top, status='PASS', coverage=matches[0], local_checks=local_count), separators=(',', ':')), flush=True)
    assert preparer.verify_edge(edge) == manifest
    receipt = dict(schema='bt-v18-sprite-local-q-qualification-v1', status='PASS_VENDOR_4STATE_AND_SPRITE_CONSUMERS',
        source_edge=dict(path=str(edge / 'manifest.json'), sha256=sha(edge / 'manifest.json')),
        sources=manifest['sources'],
        source_induction=dict(domain='All four-state input traces including startup, unknowns, holds and collisions',
            rule='Q, fg0_q and fg1_q initialize0 and capture identical raw_q at every identical posedge CLK; neither local Q feeds the old state or RAM',
            unchanged_legacy_Q_NZ_and_RAM_body=True, no_extra_edge=True, default_off_legacy_edge_identical=True,
            full_byte_inverse_passed=True, consumer_mapping=manifest['consumer_mapping']),
        native_vendor=dict(path=str(VENDOR), sha256=VENDOR_SHA, source='Installed exact Intel Quartus17 altera_mf.v'),
        memory=dict(path=str(memory), sha256=sha(memory), mode='Original addr_width10/sync_read1/q_reg0, CLOCK0 address/UNREGISTERED raw Q/OLD_DATA/power_up_uninitialized FALSE',
                    depth=128, width=64, added_memory_bits=0, added_soft_register_bits=128),
        parent_current_source_graph=dict(path=str(PARENT_FUNCTIONAL), sha256=PARENT_FUNCTIONAL_SHA),
        unchanged_FG_pin_applicability=dict(parent_proof=str(FG_PIN_PROOF), parent_proof_sha256=FG_PIN_PROOF_SHA,
            bench=str(FG_PIN_BENCH), bench_sha256=FG_PIN_BENCH_SHA,
            actual_fg_source=str(parent / 'rtl/fg_vram.sv'), actual_fg_sha256=sha(parent / 'rtl/fg_vram.sv'),
            rule='Both actual FG CPU_SHIFT_Q aliases receive an all-trace case-equal original word; all other FG inputs/body remain unchanged by this edge',
            fresh_full_FG_simulation=False, old_receipt_retagged=False),
        fixtures={str(path): sha(path) for path in (read_fixture, packet_fixture, vendor_fixture)},
        compiled_sources={str(compiled / name): sha(compiled / name) for name in artifacts},
        compile_commands=commands, compile_log=dict(path=str(output / 'compile.log'), sha256=sha(output / 'compile.log')),
        results=results, negative_controls_rejected=controls, helpers={str(path): sha(path) for path in (Path(__file__), preparer_path)},
        x_exclusions=[], collision_exclusions=[], root_modified=False, timing_accepted=False,
        mapped_replication_proven=False, fresh_native_replay=False, rbf_generated=False)
    receipt_path = output / 'receipt.json'
    receipt_path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(receipt=str(receipt_path), sha256=sha(receipt_path), status=receipt['status']), separators=(',', ':')))


if __name__ == '__main__':
    main()
