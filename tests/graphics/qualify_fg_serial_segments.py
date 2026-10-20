"""Prove same-edge foreground serial segment enables against immutable b537.

Creates one isolated candidate under build, preserves the actual RAM geometry,
and reuses the frozen foreground/control and DDR transaction workloads. The
simulation adapter checks all four segment enables at every RAM edge. This
does not claim mapped Intel collision behavior, routed timing, or release readiness.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
ORACLE = 'b53726397822b9dbebb02d36411294056fd08649'
FG_SHA = 'dda03dea94d898a9037b9d0f3b79fda4b421fe6657ac4750b2fe5a4a36e6709c'
CONTROL_HELPER_SHA = 'd53f86f30ba08202d32d916bbbabf5ef9b48f0af9e58d0ed954b6cdcff13093e'


def replace_one(text, old, new):
    if text.count(old) != 1:
        raise ValueError('source guard failed: ' + repr(old[:110]))
    return text.replace(old, new, 1)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path,
        default=ROOT / 'build' / 'fg_serial_segments_b537_v3')
    parser.add_argument('--prepare-only', action='store_true',
        help='regenerate and verify the frozen candidate without starting a simulation')
    args = parser.parse_args()
    private = args.private_root.resolve()
    if not private.is_relative_to((ROOT / 'build').resolve()) or private == (ROOT / 'build').resolve():
        raise ValueError('private-root must be a child of the project build directory')
    candidate = private / 'candidate'
    if private.exists():
        raise ValueError('refusing to overwrite a retained candidate: ' + str(private))
    sources = {}
    oracle_bytes = {}

    def original(name):
        current = (ROOT / name).read_bytes()
        frozen = subprocess.check_output(['git', 'show', ORACLE + ':' + name], cwd=ROOT)
        oracle_bytes[name] = frozen
        sources['oracle:' + name] = digest(frozen)
        sources['root:' + name] = digest(current)
        return frozen.decode('utf-8').replace('\r\n', '\n')

    fg = original('rtl/fg_vram.sv')
    oracle_fg_lf = oracle_bytes['rtl/fg_vram.sv'].replace(b'\r\n', b'\n')
    if FG_SHA not in {digest(oracle_bytes['rtl/fg_vram.sv']), digest(oracle_fg_lf),
            digest(oracle_fg_lf.replace(b'\n', b'\r\n'))}:
        raise ValueError('FG is not the reviewed dda03dea source')
    memory = original('rtl/BT_mem.sv')
    model = original('tests/graphics/ram_models.sv')
    helper_bytes = (ROOT / 'tests/graphics/qualify_fg_local_controls.py').read_bytes()
    if digest(helper_bytes) != CONTROL_HELPER_SHA:
        raise ValueError('retained control helper differs from reviewed proof helper')

    fg = replace_one(fg,
        '\t(* preserve *) bit [3:0] CPU_RAM_WREN_B2;',
        '\t(* preserve *) bit [3:0] CPU_RAM_WREN_B2;\n'
        '\t// The same write-stage edge also decodes each physical 5-bit segment.\n'
        '\t// Keep these enables local; no read address enters the write cone.\n'
        '\t(* preserve, dont_merge *) bit [3:0][3:0] CPU_RAM_WREN_SEG_B2;')
    fg = replace_one(fg, '\t\t\tCPU_RAM_WREN_B2 <= \'0;',
        '\t\t\tCPU_RAM_WREN_B2 <= \'0;\n\t\t\tCPU_RAM_WREN_SEG_B2 <= \'0;')
    bank_d = '\t\t\tfor (integer b = 0; b < 4; b = b + 1) CPU_RAM_WREN_B2[b] <= CPU_RAM_WE_B[b] && CPU_RAM_A_B[b][12:11] == b;'
    segment_d = 'CPU_RAM_WE_B[b] && CPU_RAM_A_B[b][12:11] == b && CPU_RAM_A_B[b][10:9] == s'
    fg = replace_one(fg, bank_d,
        '\t\t\tfor (integer b = 0; b < 4; b = b + 1) begin\n'
        '\t\t\t\tCPU_RAM_WREN_B2[b] <= CPU_RAM_WE_B[b] && CPU_RAM_A_B[b][12:11] == b;\n'
        '\t\t\t\tfor (integer s = 0; s < 4; s = s + 1)\n'
        '\t\t\t\t\tCPU_RAM_WREN_SEG_B2[b][s] <= ' + segment_d + ';\n'
        '\t\t\tend')
    fg = replace_one(fg,
        'BT_FG_BANKED_VRAM #(.QA_REG(1), .COPY_PREFETCH_LOCAL(1), .BANK_WRITE_PREDECODED(1)) mem',
        'BT_FG_BANKED_VRAM #(.QA_REG(1), .COPY_PREFETCH_LOCAL(1), .BANK_WRITE_PREDECODED(1), .SERIAL_SEGMENT_PRE(1)) mem')
    fg = replace_one(fg, '.SRSEL(UNALIGNED_B), .SWSEL(CPU_RAM_WE_B2), .SWREN_B(CPU_RAM_WREN_B2),',
        '.SRSEL(UNALIGNED_B), .SWSEL(CPU_RAM_WE_B2), .SWREN_B(CPU_RAM_WREN_B2), .SWREN_SEG_B(CPU_RAM_WREN_SEG_B2),')
    fg = replace_one(fg,
        'module BT_FG_BANKED_VRAM #(parameter QA_REG = 0, parameter COPY_PREFETCH_LOCAL = 0, parameter BANK_WRITE_PREDECODED = 0) (',
        'module BT_FG_BANKED_VRAM #(parameter QA_REG = 0, parameter COPY_PREFETCH_LOCAL = 0, parameter BANK_WRITE_PREDECODED = 0, parameter SERIAL_SEGMENT_PRE = 0) (')
    fg = replace_one(fg, '    input [3:0][1:0] BANK_LANE_WREN_PRE\n',
        '    input [3:0][1:0] BANK_LANE_WREN_PRE,\n    input [3:0][3:0] SWREN_SEG_B\n')
    fg = replace_one(fg,
        '.SERIAL_WRITE_DECODE(1), .LANE_WREN_PRE(BANK_WRITE_PREDECODED), .QSEL_EN(1)) ram',
        '.SERIAL_WRITE_DECODE(1), .LANE_WREN_PRE(BANK_WRITE_PREDECODED), .QSEL_EN(1), .SERIAL_SEGMENT_PRE(SERIAL_SEGMENT_PRE)) ram')
    fg = replace_one(fg, '.SWREN(SWREN_B[bank]),.SQ(bank_sq[bank]),',
        '.SWREN(SWREN_B[bank]), .SWREN_SEGMENT(SWREN_SEG_B[bank]),.SQ(bank_sq[bank]),')

    # The serial next-address registers originally re-used the large shared
    # HOLE_NEXT_ADDR_N priority cone. Use the already-proved collect/start/hold
    # priority, with a separate original-edge RAS history for each bank.
    serial_capture = ('\talways @(posedge CLK) begin\n'
        '\t\tfor (integer b = 0; b < 4; b = b + 1) begin\n'
        '\t\t\tSADDR_C_BK[b]  <= {HOLE_NEXT_ADDR[15:10], HOLE_NEXT_ADDR[7:3]};\n'
        '\t\t\tSADDR_CN_BK[b] <= {HOLE_NEXT_ADDR_N[15:10], HOLE_NEXT_ADDR_N[7:3]};\n'
        '\t\tend\n\tend')
    fg = replace_one(fg, serial_capture,
        '\talways @(posedge CLK) begin\n'
        '\t\tfor (integer b = 0; b < 4; b = b + 1)\n'
        '\t\t\tSADDR_C_BK[b] <= {HOLE_NEXT_ADDR[15:10], HOLE_NEXT_ADDR[7:3]};\n'
        '\tend\n'
        '\t(* preserve, dont_merge *) bit [3:0] SERIAL_COPY_RAS_OLD_B;\n'
        '\talways @(posedge CLK or negedge RST_N) begin\n'
        '\t\tif (!RST_N) SERIAL_COPY_RAS_OLD_B <= \'1;\n'
        '\t\telse SERIAL_COPY_RAS_OLD_B <= {4{RAS_N_M}};\n'
        '\tend\n'
        '\tgenvar serial_copy_bank;\n'
        '\tgenerate for (serial_copy_bank=0; serial_copy_bank<4; serial_copy_bank=serial_copy_bank+1) begin : serial_copy_address\n'
        '\t\t(* keep *) wire read_start = !RAS_N_M && SERIAL_COPY_RAS_OLD_B[serial_copy_bank] &&\n'
        '\t\t\t!OE_N_M && WE_N_M && TRANSFER_M;\n'
        '\t\t(* keep *) wire advance_copy = UNALIGNED_B[serial_copy_bank] && COPY_PREFETCH_B[serial_copy_bank];\n'
        '\t\t(* keep *) wire start_copy = read_start && !advance_copy;\n'
        '\t\t(* keep *) wire hold_copy = !read_start && !advance_copy;\n'
        '\t\twire [17:0] next_copy_addr = ({18{advance_copy}} & COPY_ADDR_STEP_VALUE) |\n'
        '\t\t\t({18{start_copy}} & COPY_ADDR_START_VALUE) | ({18{hold_copy}} & COPY_ADDR_N);\n'
        '\t\talways @(posedge CLK) begin\n'
        '\t\t\tif (!RST_N) SADDR_CN_BK[serial_copy_bank] <= \'0;\n'
        '\t\t\telse SADDR_CN_BK[serial_copy_bank] <= {next_copy_addr[15:10],next_copy_addr[7:3]};\n'
        '\t\tend\n'
        '`ifndef SYNTHESIS\n'
        '\t\talways @(posedge CLK) if (RST_N)\n'
        '\t\t\tassert (SERIAL_COPY_RAS_OLD_B[serial_copy_bank] == RDY_RAS_N_OLD && next_copy_addr == HOLE_NEXT_ADDR_N)\n'
        '\t\t\t\telse $fatal(1,"foreground serial next-address priority/history differs");\n'
        '`endif\n'
        '\tend endgenerate')

    # These guarded edits leave every primitive address/data/clock/mode and
    # both read output/register paths exactly as in the immutable oracle.
    for module in ('VRAM_MEM_64Kx8', 'VRAM_MEM_SLICE'):
        start = memory.index('module ' + module + ' #(')
        end = memory.index('endmodule', start)
        body = memory[start:end]
        body = replace_one(body, 'parameter QSEL_EN = 0)',
            'parameter QSEL_EN = 0, parameter SERIAL_SEGMENT_PRE = 0)')
        body = replace_one(body, 'input         QGATE_D\n' if module == 'VRAM_MEM_64Kx8' else 'input [AW-1:3] SADDR_W\n',
            ('input         QGATE_D,\n\tinput [3:0]   SWREN_SEGMENT\n' if module == 'VRAM_MEM_64Kx8' else
             'input [AW-1:3] SADDR_W,\n\tinput [3:0]   SWREN_SEGMENT\n'))
        if module == 'VRAM_MEM_64Kx8':
            body = replace_one(body, '.SERIAL_WRITE_DECODE(SERIAL_WRITE_DECODE), .QSEL_EN(QSEL_EN)) ram',
                '.SERIAL_WRITE_DECODE(SERIAL_WRITE_DECODE), .QSEL_EN(QSEL_EN), .SERIAL_SEGMENT_PRE(SERIAL_SEGMENT_PRE)) ram')
            body = replace_one(body, '.SWREN(SWREN), .SQ(qb),',
                '.SWREN(SWREN), .SWREN_SEGMENT(SWREN_SEGMENT), .SQ(qb),')
        else:
            body = replace_one(body, '.wren_b (SWREN && SADDR_W[AW-1:B_BITS+3] == segment),',
                '.wren_b (SERIAL_SEGMENT_PRE ? SWREN_SEGMENT[segment] : (SWREN && SADDR_W[AW-1:B_BITS+3] == segment)),')
        memory = memory[:start] + body + memory[end:]

    # For the functional workload use the reviewed byte-memory adapter, with
    # every new physical segment-enable pin checked before its capture edge.
    model = replace_one(model, '    parameter QSEL_EN = 0\n',
        '    parameter QSEL_EN = 0,\n    parameter SERIAL_SEGMENT_PRE = 0\n')
    model = replace_one(model, '    input QGATE_D\n',
        '    input QGATE_D,\n    input [3:0] SWREN_SEGMENT\n')
    model = replace_one(model, '    reg qg = 1\'b0;',
        '    reg qg = 1\'b0;\n'
        '    wire swren_exact = SERIAL_SEGMENT_PRE ? (|SWREN_SEGMENT) : SWREN;\n'
        '    always @(posedge CLK) if (SERIAL_SEGMENT_PRE)\n'
        '      for (integer seg=0; seg<4; seg++)\n'
        '        assert(SWREN_SEGMENT[seg] == (SWREN && SADDR_W[ADDR_WIDTH-1:ADDR_WIDTH-2] == seg))\n'
        '          else $fatal(1,"same-edge physical serial enable differs seg=%0d",seg);')
    model = replace_one(model, '        if (SWREN) begin', '        if (swren_exact) begin')
    if (ROOT / 'tests/graphics/ram_models.sv').read_bytes().replace(b'\r\n', b'\n') != model.encode('utf-8'):
        raise ValueError('shipping simulation adapter differs from the guarded immutable-b537 segment-interface extension')

    control = helper_bytes.decode('utf-8').replace('\r\n', '\n')
    control = replace_one(control, "BASELINE_REF = '8f048ee518f3062506e80d5f5a64585450d062f5'", "BASELINE_REF = '" + ORACLE + "'")
    old_rename = "            data = data.replace(b'module FG_VRAM', b'module FG_VRAM_REFERENCE', 1)\n            data = data.replace(b'BT_FG_VIDEO_ADDR_TRACK', b'BT_FG_VIDEO_ADDR_TRACK_REFERENCE')"
    control = replace_one(control, old_rename,
        "            text = data.decode('utf-8')\n"
        "            modules = re.findall(r'^module\\s+(\\w+)', text, re.M)\n"
        "            for module in sorted(modules, key=len, reverse=True):\n"
        "                text = re.sub(r'\\b'+re.escape(module)+r'\\b',module+'_REFERENCE',text)\n"
        "            data = text.encode('utf-8')")
    control = replace_one(control,
        "data = reference_bytes(name) if reference else ((args.candidate_dir if name.startswith('rtl/') else ROOT)/name).read_bytes()",
        "data = reference_bytes(name) if reference else ((args.candidate_dir if name.startswith('rtl/') or name == 'tests/graphics/ram_models.sv' else ROOT)/name).read_bytes()")
    control = replace_one(control, "    ram = freeze('tests/graphics/ram_models.sv')",
        "    freeze('rtl/BT_mem.sv')\n    freeze('rtl/BT_mem.sv', True)\n    ram = freeze('tests/graphics/ram_models.sv')")
    pin_check = r'''  genvar segment_pin_bank;
  generate for(segment_pin_bank=0;segment_pin_bank<4;segment_pin_bank++) begin: full_ram_pin_check
    always @(posedge CLK)
      assert({candidate.mem.banks[segment_pin_bank].ram.ADDR,candidate.mem.banks[segment_pin_bank].ram.DATA,
              candidate.mem.banks[segment_pin_bank].ram.WREN,candidate.mem.banks[segment_pin_bank].ram.BE,
              candidate.mem.banks[segment_pin_bank].ram.WREN_LANE,candidate.mem.banks[segment_pin_bank].ram.QGATE_D,
              candidate.mem.banks[segment_pin_bank].ram.SADDR,candidate.mem.banks[segment_pin_bank].ram.SDATA,
              candidate.mem.banks[segment_pin_bank].ram.SWREN,candidate.mem.banks[segment_pin_bank].ram.SADDR_W} ===
             {reference.mem.banks[segment_pin_bank].ram.ADDR,reference.mem.banks[segment_pin_bank].ram.DATA,
              reference.mem.banks[segment_pin_bank].ram.WREN,reference.mem.banks[segment_pin_bank].ram.BE,
              reference.mem.banks[segment_pin_bank].ram.WREN_LANE,reference.mem.banks[segment_pin_bank].ram.QGATE_D,
              reference.mem.banks[segment_pin_bank].ram.SADDR,reference.mem.banks[segment_pin_bank].ram.SDATA,
              reference.mem.banks[segment_pin_bank].ram.SWREN,reference.mem.banks[segment_pin_bank].ram.SADDR_W})
        else $fatal(1,"foreground RAM capture pins differ bank=%0d",segment_pin_bank);
  end endgenerate
'''
    control = replace_one(control,
        "        tb = workspace/'item4_foreground_equivalence_tb.sv'\n        tb.write_text(original)",
        "        original = original.replace('  initial begin\\n', " + repr(pin_check) + " + '  initial begin\\n', 1)\n"
        "        tb = workspace/'item4_foreground_equivalence_tb.sv'\n        tb.write_text(original)")
    control = replace_one(control,
        "'scope': 'exact existing memory interface and complete 64-bit copy-word cycles, original DDR controller priority, all foreground banks/lanes and transfer boundaries, CPU pause, eight byte-lane DDR restart/capture and RAM abort/capture collisions, reset at DDR collect, clear-only restart and DDR wait abort, retained memory reset and actual DDR backpressure protocol; no physical timing or full-core/frame/hardware qualification'",
        "'scope': 'immutable b537 FG control/interface and every-bank complete RAM capture-pin equality, exact serial segment-enable assertion every RAM edge, local serial-next-address priority/history identity, complete copy and hole/address state comparisons, reset/restart/abort/CPU pause and actual DDR transaction workload; guarded unchanged actual BT_mem primitive geometry/clock/address/data/modes; behavioral adapter is not mapped Intel collision or physical timing/hardware qualification'")
    proof = private / 'fg_serial_segments_proof.py'

    truth_cases = 0
    for reset_n in range(2):
        for bank in range(4):
            for enabled in range(2):
                for address_high in range(16):
                    old_bank_enable = bool(reset_n and enabled and (address_high >> 2) == bank)
                    for segment in range(4):
                        old_pin = old_bank_enable and (address_high & 3) == segment
                        new_pin = bool(reset_n and enabled and (address_high >> 2) == bank and (address_high & 3) == segment)
                        assert old_pin == new_pin
                        truth_cases += 1
    outputs = {
        candidate / 'rtl/fg_vram.sv': fg,
        candidate / 'rtl/BT_mem.sv': memory,
        candidate / 'rtl/ddram.sv': (ROOT / 'rtl/ddram.sv').read_text(),
        candidate / 'rtl/bt_fg_ddr_clear.sv': (ROOT / 'rtl/bt_fg_ddr_clear.sv').read_text(),
        candidate / 'tests/graphics/ram_models.sv': model,
        proof: control,
    }
    for name, content in [('rtl/fg_vram.sv', fg), ('rtl/BT_mem.sv', memory)]:
        current = (ROOT / name).read_bytes().replace(b'\r\n', b'\n')
        baseline = oracle_bytes[name].replace(b'\r\n', b'\n')
        if current not in (baseline, content.encode('utf-8')):
            raise ValueError('root is neither the immutable baseline nor the exact guarded final candidate: ' + name)
    for path, content in outputs.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.replace('\r\n', '\n').replace('\n', '\r\n').encode('utf-8'))
        sources[str(path.relative_to(ROOT))] = digest(path.read_bytes())
    sources['helper:qualify_fg_serial_segments.py'] = digest(Path(__file__).read_bytes())
    prepare_receipt = {'oracle': ORACLE, 'candidate_dir': str(candidate), 'sources': sources,
        'exhaustive_same_edge_segment_cases': truth_cases,
        'ram_body_scope': 'Only optional default-off serial predecoded enable input/parameter/propagation and equivalent explicit AW14/K5 wren_b expression changed. All geometry, both read paths, address/data/clock/mode assignments unchanged.',
        'physical_vendor_qualification': False}
    (private / 'prepare_receipt.json').write_text(json.dumps(prepare_receipt, indent=2) + '\n')
    print('candidate_fg=' + sources[str((candidate / 'rtl/fg_vram.sv').relative_to(ROOT))], flush=True)
    print('candidate_memory=' + sources[str((candidate / 'rtl/BT_mem.sv').relative_to(ROOT))], flush=True)
    print('same_edge_exhaustive_cases=' + str(truth_cases), flush=True)
    if args.prepare_only:
        prepare_receipt['simulation_started'] = False
        (private / 'prepare_receipt.json').write_text(json.dumps(prepare_receipt, indent=2) + '\n')
        return 0
    result = subprocess.run([sys.executable, '-B', '-X', 'utf8', str(proof),
        '--candidate-dir', str(candidate), '--tests', 'fg', 'fg-ddr'], cwd=ROOT)
    prepare_receipt['proof_exit_code'] = result.returncode
    (private / 'prepare_receipt.json').write_text(json.dumps(prepare_receipt, indent=2) + '\n')
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
