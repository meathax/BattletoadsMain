"""Prove current CPU zero flags without changing its clocks, captures or RTL.

The fixed immutable v22 parent and guarded candidate are compiled verbatim into
actual ALU/operand/DS_Z/status/pixel slices. Existing fixture assertions remain
intact. Separate source-parsed ROBDD and four-state runs qualify the new cones.
"""
from pathlib import Path
import argparse
from functools import reduce
import hashlib
import importlib.util
import json
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PREPARER = ROOT / 'tests/graphics/prepare_bt_cpu_zero_flags.py'
BDD_HELPER = ROOT / 'tests/bt_sv_bool_proof.py'
EDGE = ROOT / 'build/cpu_zero_flags_v22_v1'
MSIM = Path('D:/q17/modelsim_ase/win32aloem')
CPU = 'rtl/TMS34020/TMS34020.sv'
PKG = 'rtl/TMS34020/TMS34020_pkg.sv'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def function(text, name):
    matches = re.findall(r'\tfunction (?:automatic )?bit(?:\s+\[[^\]]+\])?\s+' + name + r'\(.*?\tendfunction', text, re.S)
    assert len(matches) == 1, name
    return matches[0]


def unroll_shift_zero(text):
    text = re.sub(r'//[^\n]*', '', text)
    loop = re.search(r'for \(int n = 0; n < 32; n = n \+ 1\)\s+(kept\[n\]\s*=.*?;)', text, re.S)
    assert loop and len(re.findall(r'for \(', text)) == 1
    statement = loop[1]
    rows = []
    for n in range(32):
        row = statement.replace("6'(32 - n)", f"6'd{32-n}")
        row = re.sub(r'\bn\b', str(n), row)
        # Exact unsigned complement lemma; the six-bit threshold is [1,32].
        row, count = re.subn(r"\{1'b0,sa\} < (6'd\d+)", r"!({1'b0,sa} >= \1)", row)
        assert count == 1
        rows.append(row)
    return text[:loop.start()] + '\n'.join(rows) + text[loop.end():]


def logger_case(text, code):
    text = re.sub(r'//[^\n]*', '', text)
    match = re.search(r'case(?:x)?\s*\(code\[2:1\]\)(.*?)endcase', text, re.S)
    assert match
    branches = re.findall(r"2'b([01]{2}):\s*([^;]+;)", match[1])
    assert len(branches) == 4 and {x for x, _ in branches} == {'00', '01', '10', '11'}
    chosen = dict(branches)[f'{(code >> 1) & 3:02b}']
    result = text[:match.start()] + chosen + text[match.end():]
    mask = re.search(r"bmask\s*=\s*32'h00000001\s*<<\s*b2\[4:0\];", result)
    assert mask
    decoder = '\n'.join(f"bmask[{n}] = (b2[4:0] == 5'd{n});" for n in range(32))
    return result[:mask.start()] + decoder + result[mask.end():]


def prove_functions(parent, candidate, pkg, helper):
    old_shift = function(parent, 'BtCarryShifter')
    new_shift = function(candidate, 'BtShiftZero')
    names = [f'code[{i}]' for i in range(3, -1, -1)] + [f'sa[{i}]' for i in range(4, -1, -1)] + [f'val[{i}]' for i in range(31, -1, -1)]
    bdd = helper.BDD(names)
    inputs = {name: [bdd.var(f'{name}[{i}]') for i in range(width)] for name, width in (('val', 32), ('sa', 5), ('code', 4))}
    word = helper.execute(old_shift, inputs, bdd)[:32]
    expected = bdd.neg(reduce(lambda a, b: bdd.op('|', a, b), word, 0))
    got = helper.execute(unroll_shift_zero(new_shift), inputs, bdd)
    assert got == [expected], 'Universal shift zero mismatch'
    shift_nodes = len(bdd.nodes)
    old_logger = function(pkg, 'Logger')
    new_logger = function(candidate, 'BtLoggerZero')
    logger_nodes = []
    for code in range(16):
        names = [f'b[{i}]' for i in range(5)]
        names += [name for i in range(32) for name in (f'a[{i}]', f'b[{i}]') if name not in names]
        bdd = helper.BDD(names)
        inputs = {name: [bdd.var(f'{name}[{i}]') for i in range(32)] for name in ('a', 'b')}
        inputs['code'] = helper.const(code, 4)
        inputs['a_zero'] = [bdd.neg(reduce(lambda a, b: bdd.op('|', a, b), inputs['a'], 0))]
        word = helper.execute(logger_case(old_logger, code), inputs, bdd)
        expected = bdd.neg(reduce(lambda a, b: bdd.op('|', a, b), word, 0))
        got = helper.execute(logger_case(new_logger, code), inputs, bdd)
        assert got == [expected], ('Universal logger zero mismatch', code)
        assert len(bdd.nodes) < 2_000_000
        logger_nodes.append(len(bdd.nodes))
    return {'method': 'Canonical ROBDD over parsed actual immutable and candidate SV expressions',
            'shift_input_bits': 41, 'shift_input_assignments': 2**41, 'shift_nodes': shift_nodes,
            'logger_input_bits': 68, 'logger_input_assignments': 2**68, 'logger_all16_codes': True,
            'logger_nodes_by_code': logger_nodes, 'all_miter_bits_identically_zero': True,
            'source_adapter_scope': 'Exact fixed32 loop unroll, representable six-bit constant evaluation, unsigned < complement, fixed two-bit case selection, 32-bit one-hot decoder expansion; raw shipped functions separately compiled.'}


def slices(text):
    a = text.index('\tbit         ADDXY_CX;')
    b = text.index('\t//DIV unit', a)
    c = text.index('\talways @(posedge CLK or negedge RST_N) begin\t\t\n\t\tbit [ 5:0] prest;')
    d = text.index('\t// PATS_B', c)
    e = text.index('\talways @(posedge CLK or negedge RST_N) begin', text.index('\t// Decode and execute are separate'))
    f = text.index('\talways_comb begin', e)
    g = text.index('\talways @(posedge CLK or negedge RST_N) begin', text.index('\t//STATUS register'))
    h = text.index('\t//Pixel unit', g)
    j = text.index('\talways @(posedge CLK or negedge RST_N) begin', text.index('\t//Conditions'))
    k = text.index('\talways_comb begin', j)
    return text[a:b], text[c:d], text[e:f], text[g:h], text[j:k]


def actual_slices(parent, candidate):
    ports = '''(
input bit CLK,RST_N,EN,CE_R,IW_WAIT,MC_WAIT,CACHE_WAIT,
input TMS34020_PKG::DecInstr_t DECI,input TMS34020_PKG::ST_t ST,
input bit[31:0] ALU_A,ALU_B,MC_DIN,RF_RA_Q,RF_RB_Q,PC,ST_RMASK,WSTART,WEND,PATTERN,
input bit[63:0] MD_ACC,input bit[15:0] IC,input bit[4:0] ALU_SA,STATE,
input bit[5:0] PSIZE,input bit[10:0] RF_WRITE_SEL,input bit DIV_V,RF_WA_WE,
input bit[1:0] WINDOW_CONTROL_W,
output bit[31:0] ALU_R,RF_WRITE_D,output bit ALU_N,ALU_Z,ALU_V,ALU_C,
output bit[3:0] ALU_XY_CC,output bit ALU_LINE_GZ,output wire[223:0] PIX_SNAPSHOT);
import TMS34020_PKG::*;
'''
    pixel_names = ('RP_COND', 'PIX_XEND', 'PIX_YEND', 'PIX_BL', 'PIXBLT_PPW', 'PIXBLT_X', 'PIX_POS', 'PIX_BIT', 'LINE_GZ', 'LINE_COND', 'PIX_DOFFS', 'PIX_SOFFS', 'PIX_MOFFS', 'PIX_DYDX', 'PIX_WINCC')
    prefix = parent[:parent.index('\t// BEGIN MC_MEM_RETURN_STAGE')]
    declarations = []
    for name in pixel_names:
        found = re.findall(r'^\t[^\n;]*\b' + name + r'\s*;[^\n]*$', prefix, re.M)
        assert len(found) == 1, name
        declarations.append(found[0])
    old, new = slices(parent), slices(candidate)
    assert old[2:] == new[2:], 'Original capture/status/DS_Z block changed'
    modules = []
    for label, text in (('oracle', parent), ('candidate', candidate)):
        alu, pixel, capture, status, ds = slices(text)
        start = text.index('\tfunction bit [4:0] BtOneLocate')
        helpers = text[start:text.index('\tbit         ADDXY_CX;', start)]
        assert pixel.count('&IO_REGS.CONTROL.W') == 1
        pixel = pixel.replace('&IO_REGS.CONTROL.W', '&WINDOW_CONTROL_W')
        body = helpers + '\n'.join(declarations) + '\n' + alu + pixel + 'assign PIX_SNAPSHOT={' + ','.join(pixel_names) + '};\n'
        modules.append('module bt_line_gz_' + label + ports + body + 'endmodule\n')
        phase_ports = ports.replace(',input TMS34020_PKG::ST_t ST', '').replace('ALU_A,ALU_B,MC_DIN', 'ALU_A_D,ALU_B_D,MC_DIN').replace('ALU_SA,STATE', 'ALU_SA_D,STATE').replace('PIX_SNAPSHOT);', 'PIX_SNAPSHOT,output TMS34020_PKG::ST_t ST_CAPTURED,output bit DS_CAPTURED);')
        local = 'ST_t ST; bit[31:0] ALU_A,ALU_B; bit[4:0] ALU_SA; bit DS_Z;\n'
        modules.append('module bt_shift_phase_' + label + phase_ports + local + body + capture + status + ds + 'assign ST_CAPTURED=ST; assign DS_CAPTURED=DS_Z;\nendmodule\n')
        function_ports = '(input bit[31:0] val,input bit[4:0] sa,input bit[3:0] code,output bit[32:0] carry_result,output bit shift_overflow);\nimport TMS34020_PKG::*;\n'
        modules.append('module bt_shift_function_' + label + function_ports + helpers + 'always_comb begin carry_result=BtCarryShifter(val,sa,code); shift_overflow=BtShiftLeftOvf(val,sa); end\nendmodule\n')
        zero_ports = '(input logic[31:0] val,b,input logic[4:0] sa,input logic[3:0] code,lcode,output bit sz,lz);\nimport TMS34020_PKG::*;\n'
        if label == 'oracle':
            statements = 'sz=~|word; lz=~|Logger(word,b,lcode);'
        else:
            statements = 'sz=BtShiftZero(val,sa,code); lz=BtLoggerZero(word,b,lcode,sz);'
        modules.append('module bt_zero_function_' + label + zero_ports + helpers + 'bit[32:0] full_word; bit[31:0] word; always_comb begin full_word=BtCarryShifter(val,sa,code); word=full_word[31:0]; ' + statements + ' end\nendmodule\n')
    return '\n'.join(modules).encode()


def phase_bench(raw):
    text = raw.decode()
    replacements = [
        ('wire ST_t OSTATUS,NSTATUS;', 'wire ST_t OSTATUS,NSTATUS;\n  wire ODS,NDS;'),
        ('.ST_CAPTURED(OSTATUS));', '.ST_CAPTURED(OSTATUS),.DS_CAPTURED(ODS));'),
        ('.ST_CAPTURED(NSTATUS));', '.ST_CAPTURED(NSTATUS),.DS_CAPTURED(NDS));'),
        ('task check_phase(input int cycle);', 'task check_phase(input int cycle);\n    assert(NDS===ODS) else $fatal(1,"DS_Z capture mismatch phase=%0d",cycle);'),
    ]
    for old, new in replacements:
        assert text.count(old) == 1
        text = text.replace(old, new)
    recovered = text
    for old, new in reversed(replacements):
        assert recovered.count(new) == 1
        recovered = recovered.replace(new, old)
    assert recovered.encode() == raw
    return text.encode(), replacements


def zero_bench(four_state=False):
    init = '''for(int c=0;c<16;c++)for(int lc=0;lc<16;lc++)for(int s=0;s<32;s++)for(int p=0;p<66;p++)for(int q=0;q<8;q++) begin
      code=4'(c);lcode=4'(lc);sa=5'(s);
      if(p==0)val=0;else if(p==1)val='1;else if(p<34)val=32'd1<<(p-2);else val=~(32'd1<<(p-34));
      case(q) 0:b=0;1:b='1;2:b=32'h55555555;3:b=32'haaaaaaaa;4:b=32'h80000000;5:b=32'h7fffffff;6:b=32'(p);7:b=~32'(p);endcase
      #1;check_zero();
    end
    for(int n=0;n<1048576;n++) begin rng=next_rng(rng);val=rng;rng=next_rng(rng);b=rng;code=4'(n);lcode=4'(n>>4);sa=5'(n>>8);#1;check_zero();end'''
    if four_state:
        init = '''for(int c=0;c<16;c++)for(int lc=0;lc<16;lc++)for(int s=0;s<32;s++)for(int p=0;p<8;p++) begin
      code=4'(c);lcode=4'(lc);sa=5'(s);val=32'h81c35009;b=32'h639ab017;
      case(p) 0:val='x;1:val='z;2:b='x;3:b='z;4:val[s]=1'bx;5:val[s]=1'bz;6:b[s]=1'bx;7:b[s]=1'bz;endcase
      #1;check_zero();
    end
    for(int n=0;n<8192;n++) begin
      rng=next_rng(rng);val=rng;b=~rng;code=4'(n);lcode=4'(n>>4);sa=5'(n>>8);
      case(n%6) 0:code[n%4]=1'bx;1:code[n%4]=1'bz;2:lcode[n%4]=1'bx;3:lcode[n%4]=1'bz;4:sa[n%5]=1'bx;5:sa[n%5]=1'bz;endcase
      #1;check_zero();
    end'''
    return ('''`timescale 1ns/1ps
module bt_cpu_zero_tb;
  logic[31:0] val,b;
  logic[4:0] sa;
  logic[3:0] code,lcode;
  wire osz,nsz,olz,nlz;
  bt_zero_function_oracle O(.*,.sz(osz),.lz(olz));
  bt_zero_function_candidate N(.*,.sz(nsz),.lz(nlz));
  int checks=0;
  bit[31:0] rng=32'hc15a34d7;
  function bit[31:0] next_rng(input bit[31:0] r);r=r^(r<<13);r=r^(r>>17);r=r^(r<<5);return r;endfunction
  task check_zero;
    assert({nsz,nlz}==={osz,olz}) else $fatal(1,"Zero mismatch val=%h B=%h count=%h shiftcode=%h logcode=%h old=%b%b new=%b%b",val,b,sa,code,lcode,osz,olz,nsz,nlz);
    checks++;
  endtask
  initial begin
    ''' + init + '\n    $display("PASS actual zero functions checks=%0d four_state=' + str(int(four_state)) + '",checks);$finish;\n  end\nendmodule\n').encode()


def wsl(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def verify_composition_receipt(path):
    receipt = json.loads(Path(path).read_bytes())
    assert receipt['status'] == 'PASS_SCOPED_CPU_ZERO_FLAGS'
    assert receipt['candidate_sha256'] == sha((EDGE / 'candidate' / CPU).read_bytes())
    preparer = load(PREPARER, 'cpu_zero_source_verifier')
    assert preparer.verify_edge(EDGE / 'candidate') == receipt['source_edge']
    for name, wanted in receipt['bound_evidence_files'].items():
        assert sha(Path(name).read_bytes()) == wanted, name
    assert receipt['universal_proof']['all_miter_bits_identically_zero']
    assert receipt['pass_coverage']['alu_combinational_comparisons'] == 9469952
    assert receipt['pass_coverage']['actual_operand_status_cycles'] == 65536
    assert receipt['pass_coverage']['four_state_zero_cases'] == 73728
    assert all(x['rejected'] for x in receipt['negative_controls'])
    return receipt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if args.verify:
        receipt = verify_composition_receipt(args.verify)
        print(json.dumps({'status': receipt['status'], 'receipt': str(args.verify), 'sha256': sha(args.verify.read_bytes())}))
        return
    assert args.output
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / 'build').resolve()) and not output.exists()
    preparer = load(PREPARER, 'cpu_zero_source_edge')
    source_edge = preparer.verify_edge(EDGE / 'candidate')
    parent_raw, pkg_raw, _ = preparer.pinned_parent()
    candidate_raw = (EDGE / 'candidate' / CPU).read_bytes()
    parent, candidate, pkg = [x.decode().replace('\r\n', '\n') for x in (parent_raw, candidate_raw, pkg_raw)]
    helper = load(BDD_HELPER, 'cpu_zero_bdd')
    universal = prove_functions(parent, candidate, pkg, helper)
    phase_raw = (ROOT / 'tests/bt_cpu_shift_flags_tb.sv').read_bytes()
    phase, phase_replacements = phase_bench(phase_raw)
    line_raw = (ROOT / 'tests/bt_cpu_line_gz_tb.sv').read_bytes()
    line = line_raw.decode()
    assert line.count('module bt_cpu_line_gz_tb;') == line.count('$finish;') == 1
    line = line.replace('module bt_cpu_line_gz_tb;', 'module bt_cpu_line_gz_tb(output bit done);').replace('$finish;', "done=1'b1;")
    generated = {'TMS34020_pkg.sv': pkg_raw, 'actual_slices.sv': actual_slices(parent, candidate),
                 'phase_testbench.sv': phase, 'line_testbench.sv': line.encode(),
                 'zero_testbench.sv': zero_bench(False), 'four_state_testbench.sv': zero_bench(True),
                 'TMS34020_before.sv': parent_raw, 'TMS34020_candidate.sv': candidate_raw}
    output.mkdir(parents=True)
    for name, raw in generated.items():
        (output / name).write_bytes(raw)
    commands = [
        ('native-build', ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', '/usr/bin/verilator', '--binary', '--assert', '--timing', '-j', '2', '--top-module', 'bt_cpu_shift_flags_tb', '-Wno-fatal', '-Wno-BLKANDNBLK', '--Mdir', wsl(output / 'phase-obj')] + [wsl(output / x) for x in ('TMS34020_pkg.sv', 'actual_slices.sv', 'line_testbench.sv', 'phase_testbench.sv')]),
        ('native-run', ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', wsl(output / 'phase-obj/Vbt_cpu_shift_flags_tb')]),
        ('zero-build', ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', '/usr/bin/verilator', '--binary', '--assert', '--timing', '-j', '2', '--top-module', 'bt_cpu_zero_tb', '-Wno-fatal', '-Wno-BLKANDNBLK', '--Mdir', wsl(output / 'zero-obj')] + [wsl(output / x) for x in ('TMS34020_pkg.sv', 'actual_slices.sv', 'zero_testbench.sv')]),
        ('zero-run', ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', wsl(output / 'zero-obj/Vbt_cpu_zero_tb')]),
        ('four-state-vlib', [str(MSIM / 'vlib.exe'), 'work']),
        ('four-state-build', [str(MSIM / 'vlog.exe'), '-sv', '-work', 'work', 'TMS34020_pkg.sv', 'actual_slices.sv', 'four_state_testbench.sv']),
        ('four-state-run', [str(MSIM / 'vsim.exe'), '-c', 'work.bt_cpu_zero_tb', '-do', 'run -all; quit -f']),
    ]
    receipt = {'schema': 'bt-current-v22-cpu-zero-flags-qualification-v1', 'status': 'PREPARED_SIMULATION_PENDING',
               'source_edge': source_edge, **source_edge, 'universal_proof': universal,
               'original_phase_fixture_assertions_preserved': True, 'phase_fixture_append_only_DS_Z_monitor': True,
               'phase_fixture_reversible_operations': phase_replacements, 'commands': [],
               'original_line_fixture_finish_only_adapter': True, 'clocks_ports_registers_captures_reset_hold_priority_unchanged': True,
               'four_state_scope': 'Actual zero function cones with shipped bit-input coercion, all counts/codes and X/Z operands/controls; full original captured DS_Z/status behavior is byte-identical and exercised by native complete actual ALU/operand/status fixtures.',
               'scope': 'Actual immutable-v22 versus new CPU combinational zero flags, complete ALU results/NCV/zero plus operand/DS_Z/ST/pixel phase preservation; no full core native replay, physical timing, RBF, hardware or MAME claim.'}
    path = output / 'receipt.json'
    if args.prepare_only:
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        print(json.dumps({'prepared': str(path), 'symbolic': universal, 'source_helper_sha256': sha(PREPARER.read_bytes())}))
        return
    for label, command in commands:
        with (output / (label + '.log')).open('w') as log:
            process = subprocess.run(command, cwd=output, stdout=log, stderr=subprocess.STDOUT)
        receipt['commands'].append({'label': label, 'command': command, 'exit_code': process.returncode})
        path.write_text(json.dumps(receipt, indent=2) + '\n')
        if process.returncode:
            print((output / (label + '.log')).read_text(errors='replace')[-6000:])
            raise SystemExit(process.returncode)
    native = (output / 'native-run.log').read_text()
    line_match = re.search(r'PASS line predicate combin=(\d+) phase=(\d+) zero_sign=(\d+)', native)
    phase_match = re.search(r'PASS actual operand/status phases=(\d+) reset=(\d+) en_hold=(\d+) ce_hold=(\d+) stalls=(\d+) actions=(\d+) overflow_writes=(\d+) all8statusclasses', native)
    assert line_match and phase_match
    coverage = dict(zip(('alu_combinational_comparisons', 'pixel_phase_cycles', 'zero_sign_witnesses'), map(int, line_match.groups())))
    coverage.update(dict(zip(('actual_operand_status_cycles', 'status_resets', 'status_enable_holds', 'status_ce_holds', 'status_stalls', 'status_actions', 'overflow_flag_writes'), map(int, phase_match.groups()))))
    for label, count in (('zero-run', 5373952), ('four-state-run', 73728)):
        log = (output / (label + '.log')).read_text(errors='replace')
        match = re.search(r'PASS actual zero functions checks=(\d+) four_state=(\d+)', log)
        assert match and int(match[1]) == count, (label, log[-1600:])
        coverage['four_state_zero_cases' if label == 'four-state-run' else 'compiled_zero_cases'] = count
        assert not any(x in log for x in ('** Error', '** Fatal', 'Assertion failed', '%Error:', 'Aborting...'))
    assert coverage['alu_combinational_comparisons'] == 9469952 and coverage['pixel_phase_cycles'] == 32768 and coverage['actual_operand_status_cycles'] == 65536
    negatives = []
    for name, old, new in (
        ('changed surviving-bit zero polarity', b'return ~|kept;', b'return |kept;'),
        ('changed logical OR zero predicate', b'zero = a_zero & ~|b2;', b'zero = a_zero | ~|b2;'),
        ('changed threshold boundary', b"6'(32 - n)", b"6'(31 - n)"),
        ('changed DS_Z capture', b'DS_Z <= ALU_Z;', b'DS_Z <= ~ALU_Z;'),
        ('changed DS_Z reset', b'DS_Z <= 0;', b'DS_Z <= 1;'),
        ('changed other flag data', b'ADDER_V      ,ADDER_C', b'~ADDER_V     ,ADDER_C'),
        ('changed result capture data', b',SHIFT_RES};', b',~SHIFT_RES};'),
    ):
        assert candidate_raw.count(old) > 0, old
        mutant = candidate_raw.replace(old, new, 1)
        try:
            preparer.reverse(mutant)
        except AssertionError:
            negatives.append({'name': name, 'rejected': True, 'gate': 'Exact guarded raw inverse'})
        else:
            raise AssertionError('Corrupt source accepted: ' + name)
    receipt.update({'status': 'PASS_SCOPED_CPU_ZERO_FLAGS', 'pass_coverage': coverage, 'negative_controls': negatives,
                    'source_helper_sha256': sha(PREPARER.read_bytes()), 'qualifier_sha256': sha(Path(__file__).read_bytes()),
                    'mapped_timing_RBF_hardware_MAME_claim': False})
    ledger = {str((output / name).resolve()): sha((output / name).read_bytes()) for name in generated}
    for name in ('tests/bt_cpu_shift_flags_tb.sv', 'tests/bt_cpu_line_gz_tb.sv', 'tests/bt_sv_bool_proof.py', 'tests/graphics/prepare_bt_cpu_zero_flags.py'):
        ledger[str((ROOT / name).resolve())] = sha((ROOT / name).read_bytes())
    ledger[str(Path(__file__).resolve())] = sha(Path(__file__).read_bytes())
    ledger[str((EDGE / 'manifest.json').resolve())] = sha((EDGE / 'manifest.json').read_bytes())
    for label, _ in commands:
        ledger[str((output / (label + '.log')).resolve())] = sha((output / (label + '.log')).read_bytes())
    for executable in ('phase-obj/Vbt_cpu_shift_flags_tb', 'zero-obj/Vbt_cpu_zero_tb'):
        ledger[str((output / executable).resolve())] = sha((output / executable).read_bytes())
    receipt['bound_evidence_files'] = ledger
    assert candidate_raw == (EDGE / 'candidate' / CPU).read_bytes() and parent_raw == preparer.pinned_parent()[0]
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    verify_composition_receipt(path)
    print(json.dumps({'receipt': str(path), 'sha256': sha(path.read_bytes()), 'status': receipt['status'], 'counts': coverage, 'negative_controls': len(negatives), 'source_helper_sha256': sha(PREPARER.read_bytes()), 'qualifier_sha256': sha(Path(__file__).read_bytes())}))


if __name__ == '__main__':
    main()
