"""Create and prove a private CPU line-flag candidate against immutable 8f048ee."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
REF = '8f048ee518f3062506e80d5f5a64585450d062f5'
GIT = 'D:/vibes/fpga/bin/git.EXE'
CPU_PATH = 'rtl/TMS34020/TMS34020.sv'
PKG_PATH = 'rtl/TMS34020/TMS34020_pkg.sv'
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, default=DEFAULT_ROOT,
                    help='Repository root; defaults to the parent of tests/.')
parser.add_argument('--candidate', type=Path,
                    help='Explicit CPU candidate; defaults to ROOT/rtl/TMS34020/TMS34020.sv.')
parser.add_argument('--out', type=Path,
                    help='New evidence directory; defaults to ROOT/tests/graphics/evidence/cpu_line_gz_TIMESTAMP.')
args = parser.parse_args()
ROOT = args.root.resolve()
candidate_input = (args.candidate or ROOT / CPU_PATH).resolve()
out = (args.out or ROOT / 'tests/graphics/evidence' /
       ('cpu_line_gz_' + time.strftime('%Y%m%d_%H%M%S'))).resolve()
allowed = ((ROOT / 'build').resolve(), (ROOT / 'tests/graphics/evidence').resolve())
assert any(out.is_relative_to(p) for p in allowed) and not out.exists()
out.mkdir(parents=True)

def sha(data): return hashlib.sha256(data).hexdigest()
def blob(path):
    r = subprocess.run([GIT, '-C', str(ROOT), 'show', REF + ':' + path], capture_output=True)
    assert r.returncode == 0, r.stderr.decode(errors='replace')
    return r.stdout
def normalized(data): return data.decode('utf-8').replace('\r\n', '\n')

oracle_cpu, oracle_pkg = blob(CPU_PATH), blob(PKG_PATH)
baseline_cpu, baseline_pkg = (ROOT / CPU_PATH).read_bytes(), (ROOT / PKG_PATH).read_bytes()
assert normalized(oracle_pkg) == normalized(baseline_pkg), 'CPU package differs from immutable oracle'
source = normalized(oracle_cpu)
candidate = source.replace('\tbit          LINE_GZ;', '\tbit          LINE_GZ;\n\tbit          ALU_LINE_GZ;')
assert candidate != source
anchor = '\t\tendcase\n\t\tRF_WRITE_D ='
assert candidate.count(anchor) == 1
predicate = '''
		// Factor the line predicate directly from each operation's flags.
		// The five N=0 operations always satisfy it. For ADD/DIV and MOV,
		// zero implies sign=0, so the zero term adds no information.
		// ADDXY uses independent half-word zero flags and keeps IC[7] live.
		case (DECI.ALU.OP)
			ALUOP_ADD, ALUOP_DIV: ALU_LINE_GZ = ~ADDER_RES[31];
			ALUOP_ADDXY: ALU_LINE_GZ = ~ADDXY_Z[0] | (ADDXY_Z[1] & ~IC[7]);
			ALUOP_CPW, ALUOP_LOG, ALUOP_SHIFT, ALUOP_LOC, ALUOP_MUL: ALU_LINE_GZ = 1'b1;
			default: ALU_LINE_GZ = ~MC_DIN[31];
		endcase
'''
candidate = candidate.replace(anchor, '\t\tendcase\n' + predicate + '\t\tRF_WRITE_D =')
old_capture = 'PLN_COND: LINE_GZ <= ~ALU_N | (ALU_Z & ~IC[7]);'
assert candidate.count(old_capture) == 1
candidate = candidate.replace(old_capture, 'PLN_COND: LINE_GZ <= ALU_LINE_GZ;')
candidate_bytes = candidate_input.read_bytes()
assert normalized(candidate_bytes) == candidate, 'Candidate contains changes beyond the proved immutable-8f line factoring'
candidate_path = out / 'TMS34020.sv'
candidate_path.write_bytes(candidate_bytes)
(out / 'TMS34020_oracle.sv').write_bytes(oracle_cpu)
(out / 'TMS34020_pkg.sv').write_bytes(oracle_pkg)

def slices(text):
    alu_start = text.index('\tbit         ADDXY_CX;')
    alu_end = text.index('\t//DIV unit', alu_start)
    seq_start = text.index('\talways @(posedge CLK or negedge RST_N) begin\t\t\n\t\tbit [ 5:0] prest;')
    seq_end = text.index('\t// PATS_B', seq_start)
    return text[alu_start:alu_end], text[seq_start:seq_end]

pixel_names = ('RP_COND','PIX_XEND','PIX_YEND','PIX_BL','PIXBLT_PPW','PIXBLT_X','PIX_POS','PIX_BIT',
               'LINE_GZ','LINE_COND','PIX_DOFFS','PIX_SOFFS','PIX_MOFFS','PIX_DYDX','PIX_WINCC')
declarations = []
prefix = source[:source.index('\t// BEGIN MC_MEM_RETURN_STAGE')]
for name in pixel_names:
    hits = re.findall(r'^\t[^\n;]*\b' + name + r'\s*;[^\n]*$', prefix, re.M)
    assert len(hits) == 1, (name, hits)
    declarations.append(hits[0])

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
modules = []
for label, text in (('oracle', normalized(oracle_cpu)), ('candidate', candidate)):
    alu, seq = slices(text)
    # Bind the original IO field to an explicit wrapper input, preserving width/value.
    assert seq.count('&IO_REGS.CONTROL.W') == 1
    seq = seq.replace('&IO_REGS.CONTROL.W', '&WINDOW_CONTROL_W')
    extra = 'always_comb ALU_LINE_GZ = ~ALU_N | (ALU_Z & ~IC[7]);\n' if label == 'oracle' else ''
    modules.append('module bt_line_gz_' + label + ports + '\n'.join(declarations) + '\n' + alu + seq + extra +
                   'assign PIX_SNAPSHOT={' + ','.join(pixel_names) + '};\nendmodule\n')
slice_bytes = '\n'.join(modules).encode()
(out / 'line_slices.sv').write_bytes(slice_bytes)
tb = ROOT / 'tests/bt_cpu_line_gz_tb.sv'

def wsl_path(p):
    p = Path(p).resolve()
    return '/mnt/' + p.drive[0].lower() + p.as_posix()[2:]

receipt = {'oracle_commit': REF, 'oracle_cpu_sha256': sha(oracle_cpu), 'oracle_pkg_sha256': sha(oracle_pkg),
           'observed_root_cpu_sha256_at_start': sha(baseline_cpu), 'candidate_cpu_sha256': sha(candidate_path.read_bytes()),
           'candidate_input_path': str(candidate_input), 'candidate_path': str(candidate_path), 'runner_sha256': sha(Path(__file__).read_bytes()),
           'testbench_sha256': sha(tb.read_bytes()), 'actual_slices_sha256': sha(slice_bytes),
           'comparison': 'Complete candidate equals the known factored immutable-8f CPU body; package equals oracle after CRLF-to-LF normalization only.',
           'scope': 'Actual ALU and complete pixel/line sequential RTL blocks; no decode reachability assumptions. Full native replay and timing fit remain required.',
           'commands': []}
build = ['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','/usr/bin/verilator','--binary','--assert',
         '--timing','-j','2','--top-module','bt_cpu_line_gz_tb','-Wno-fatal','-Wno-BLKANDNBLK',
         '--Mdir',wsl_path(out / 'obj'),wsl_path(out / 'TMS34020_pkg.sv'),wsl_path(out / 'line_slices.sv'),wsl_path(tb)]
run = ['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec',wsl_path(out / 'obj/Vbt_cpu_line_gz_tb')]
started = time.monotonic()
for label, command in (('build', build), ('run', run)):
    receipt['commands'].append(command)
    with (out / (label + '.log')).open('w') as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    receipt[label + '_exit_code'] = result.returncode
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2))
    if result.returncode:
        print((out / (label + '.log')).read_text(errors='replace')[-5000:])
        sys.exit(result.returncode)
run_text = (out / 'run.log').read_text(errors='replace')
summary = re.search(r'^PASS line predicate combin=(\d+) phase=(\d+) zero_sign=(\d+) all16ops/all8ADDXYflagIC7 cases$', run_text, re.M)
phases = re.search(r'^PASS phases reset=(\d+) en_hold=(\d+) ce_hold=(\d+) stalls=(\d+) line_update=(\d+) line_hold=(\d+)$', run_text, re.M)
assert summary and phases, 'Successful exit lacks required PASS coverage'
counts = dict(zip(('combinational_checks','phase_cycles','zero_implies_sign_zero_witnesses'), map(int, summary.groups())))
counts.update(dict(zip(('resets','enable_holds','clock_enable_holds','stalls','line_updates','other_line_actions'), map(int, phases.groups()))))
assert counts['combinational_checks'] == 9469952 and counts['phase_cycles'] == 32768
assert all(n > 0 for n in counts.values()), 'Required coverage missing'
counts.update({'all_16_operation_encodings': True, 'all_8_addxy_flags_ic7_tuples': True,
               'sign_zero_truth_lemma_cases': 6})
receipt['pass_coverage'] = counts
receipt['wall_seconds'] = time.monotonic() - started
receipt['observed_root_cpu_sha256_at_end'] = sha((ROOT / CPU_PATH).read_bytes())
assert sha(candidate_input.read_bytes()) == sha(candidate_bytes), 'Candidate changed during proof'
(out / 'receipt.json').write_text(json.dumps(receipt, indent=2))
print('receipt=' + str(out / 'receipt.json'))
print(run_text[-4000:])
