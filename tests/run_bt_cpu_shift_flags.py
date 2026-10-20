"""Prove the complete CPU shift candidate against immutable 8f048ee."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from bt_sv_bool_proof import prove

DEFAULT_ROOT=Path(__file__).resolve().parents[1]
TESTS=Path(__file__).resolve().parent
REF='8f048ee518f3062506e80d5f5a64585450d062f5'
GIT='D:/vibes/fpga/bin/git.EXE'
CPU='rtl/TMS34020/TMS34020.sv'
PKG='rtl/TMS34020/TMS34020_pkg.sv'
BASE_SHA='8891de69ea68af5ce87567fe9eb7883a391b6eee7438a2317139465b8f36b9b5'
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root',type=Path,default=DEFAULT_ROOT,
                    help='Repository root; defaults to the parent of tests/.')
parser.add_argument('--candidate',type=Path,
                    help='Explicit CPU candidate; defaults to ROOT/rtl/TMS34020/TMS34020.sv.')
parser.add_argument('--out',type=Path,
                    help='New evidence directory under ROOT/build or ROOT/tests/graphics/evidence.')
args=parser.parse_args()
ROOT=args.root.resolve()
candidate_input=(args.candidate or ROOT/CPU).resolve()
OUT=(args.out or ROOT/'tests/graphics/evidence'/('cpu_shift_flags_'+time.strftime('%Y%m%d_%H%M%S'))).resolve()
allowed=((ROOT/'build').resolve(),(ROOT/'tests/graphics/evidence').resolve())
assert any(OUT.is_relative_to(p) for p in allowed) and not OUT.exists()
OUT.mkdir(parents=True)
def sha(v):return hashlib.sha256(v).hexdigest()
def norm(v):return v.decode().replace('\r\n','\n')
def blob(path):
    r=subprocess.run([GIT,'-C',str(ROOT),'show',REF+':'+path],capture_output=True)
    assert r.returncode==0,r.stderr.decode(errors='replace')
    return r.stdout
oracle_cpu,oracle_pkg=blob(CPU),blob(PKG)
assert norm((ROOT/PKG).read_bytes())==norm(oracle_pkg),'CPU package differs from immutable oracle'
source,pkg=norm(oracle_cpu),norm(oracle_pkg)
root_before=(ROOT/CPU).read_bytes()
base = source.replace('\tbit          LINE_GZ;', '\tbit          LINE_GZ;\n\tbit          ALU_LINE_GZ;')
assert base != source
anchor = '\t\tendcase\n\t\tRF_WRITE_D ='
assert base.count(anchor) == 1
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
base = base.replace(anchor, '\t\tendcase\n' + predicate + '\t\tRF_WRITE_D =')
old_capture = 'PLN_COND: LINE_GZ <= ~ALU_N | (ALU_Z & ~IC[7]);'
assert base.count(old_capture) == 1
base = base.replace(old_capture, 'PLN_COND: LINE_GZ <= ALU_LINE_GZ;')
assert sha(base.encode())==BASE_SHA,'Immutable line-factored base identity changed'

def function(text,name):
    m=re.search(r'\tfunction bit(?:\s+\[[^\]]+\])?\s+'+name+r'\(.*?\tendfunction',text,re.S)
    assert m,name
    return m[0]
old_carry,old_ovf=function(pkg,'CarryShifter'),function(pkg,'ShiftLeftOvf')
new_carry=old_carry.replace('CarryShifter(', 'BtCarryShifter(')
count='\t\ts = (sa ^ {5{code[0]}}) + {4\'b0000,code[0]};'
assert new_carry.count(count)==1
new_carry=new_carry.replace(count,'''\t\t// Negating the five-bit amount does not need a serial carry chain.
\t\t// A negative count flips bit k exactly when a lower bit is set.
\t\ts[0] = sa[0];
\t\ts[1] = sa[1] ^ (code[0] & sa[0]);
\t\ts[2] = sa[2] ^ (code[0] & |sa[1:0]);
\t\ts[3] = sa[3] ^ (code[0] & |sa[2:0]);
\t\ts[4] = sa[4] ^ (code[0] & |sa[3:0]);''')
new_ovf='''\tfunction bit BtShiftLeftOvf(input bit [31:0] val, input bit [4:0] sa);
\t\tbit [29:0] terms;
\t\t// Preserve the original detector: compare only the top sa bits with
\t\t// the original sign. Counts zero/one and bit zero never overflow.
\t\t// Constant threshold comparisons replace the detector's barrel chain.
\t\tfor (int n = 1; n < 31; n = n + 1)
\t\t\tterms[n - 1] = (val[n] ^ val[31]) & (sa >= 5'(32 - n));
\t\treturn |terms;
\tendfunction'''
anchor='\tbit         ADDXY_CX;';assert base.count(anchor)==1
candidate=base.replace(anchor,new_carry+'\n\n'+new_ovf+'\n\n'+anchor)
assert candidate.count('= CarryShifter(ALU_A, ALU_SA, DECI.SHC.SHOP);')==1
assert candidate.count('= ShiftLeftOvf(ALU_A, ALU_SA);')==1
candidate=candidate.replace('= CarryShifter(ALU_A, ALU_SA, DECI.SHC.SHOP);','= BtCarryShifter(ALU_A, ALU_SA, DECI.SHC.SHOP);')
candidate=candidate.replace('= ShiftLeftOvf(ALU_A, ALU_SA);','= BtShiftLeftOvf(ALU_A, ALU_SA);')
candidate_bytes=candidate_input.read_bytes()
assert norm(candidate_bytes)==candidate,'Candidate contains changes beyond the proved immutable-8f line/shift factoring'
candidate=norm(candidate_bytes)
candidate_path=OUT/'TMS34020.sv'
candidate_path.write_bytes(candidate_bytes)
(OUT/'TMS34020_oracle.sv').write_bytes(oracle_cpu)
(OUT/'TMS34020_pkg.sv').write_bytes(oracle_pkg)
receipt={'oracle_commit':REF,'oracle_cpu_sha256':sha(oracle_cpu),'oracle_pkg_sha256':sha(oracle_pkg),
         'integrated_base_origin':'Immutable-8f CPU with the previously proved LINE_GZ factoring','integrated_base_sha256':BASE_SHA,
         'candidate_input_path':str(candidate_input),
         'candidate_path':str(candidate_path),'candidate_sha256':sha(candidate_path.read_bytes()),
         'root_cpu_sha256_at_start':sha(root_before),'runner_sha256':sha(Path(__file__).read_bytes()),
         'symbolic_interpreter_sha256':sha((TESTS/'bt_sv_bool_proof.py').read_bytes()),
         'testbench_sha256':sha((TESTS/'bt_cpu_shift_flags_tb.sv').read_bytes()),
         'function_sha256':{n:sha(s.encode())for n,s in [('oracle_carry',old_carry),('candidate_carry',new_carry),('oracle_overflow',old_ovf),('candidate_overflow',new_ovf)]},
         'scope':'Private CPU-local combinational functions only. No clock, register, enable, reset, stall, CPU decode, package, root source or SDC change. Full native replay and physical fit remain required.',
         'commands':[]}
started=time.monotonic()
receipt['universal_function_proof']=prove(old_carry,new_carry,old_ovf,new_ovf)
(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2))
print('Universal actual-function ROBDD proof PASS',flush=True)

def slices(text):
    a=text.index('\tbit         ADDXY_CX;');b=text.index('\t//DIV unit',a)
    c=text.index('\talways @(posedge CLK or negedge RST_N) begin\t\t\n\t\tbit [ 5:0] prest;')
    d=text.index('\t// PATS_B',c)
    e=text.index('\talways @(posedge CLK or negedge RST_N) begin',text.index('\t// Decode and execute are separate'))
    f=text.index('\talways_comb begin',e)
    g=text.index('\talways @(posedge CLK or negedge RST_N) begin',text.index('\t//STATUS register'))
    h=text.index('\t//Pixel unit',g)
    return text[a:b],text[c:d],text[e:f],text[g:h]
sa,sp,sc,ss=slices(source);ca,cp,cc,cs=slices(candidate)
assert sc==cc and ss==cs,'Actual operand/status clocked RTL changed'
pixel_names=('RP_COND','PIX_XEND','PIX_YEND','PIX_BL','PIXBLT_PPW','PIXBLT_X','PIX_POS','PIX_BIT','LINE_GZ','LINE_COND','PIX_DOFFS','PIX_SOFFS','PIX_MOFFS','PIX_DYDX','PIX_WINCC')
prefix=source[:source.index('\t// BEGIN MC_MEM_RETURN_STAGE')]
decl=[]
for name in pixel_names:
    hits=re.findall(r'^\t[^\n;]*\b'+name+r'\s*;[^\n]*$',prefix,re.M);assert len(hits)==1,(name,hits)
    decl.append(hits[0])
ports='''(
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
modules=[]
for label,text in (('oracle',source),('candidate',candidate)):
    alu,pixel,capture,status=slices(text)
    assert pixel.count('&IO_REGS.CONTROL.W')==1
    pixel=pixel.replace('&IO_REGS.CONTROL.W','&WINDOW_CONTROL_W')
    helpers=new_carry+'\n'+new_ovf+'\n' if label=='candidate' else ''
    extra='always_comb ALU_LINE_GZ = ~ALU_N | (ALU_Z & ~IC[7]);\n' if label=='oracle' else ''
    body=helpers+'\n'.join(decl)+'\n'+alu+pixel+extra+'assign PIX_SNAPSHOT={'+','.join(pixel_names)+'};\n'
    modules.append('module bt_line_gz_'+label+ports+body+'endmodule\n')
    phase_ports=ports.replace(',input TMS34020_PKG::ST_t ST','').replace('ALU_A,ALU_B,MC_DIN','ALU_A_D,ALU_B_D,MC_DIN').replace('ALU_SA,STATE','ALU_SA_D,STATE').replace('PIX_SNAPSHOT);','PIX_SNAPSHOT,output TMS34020_PKG::ST_t ST_CAPTURED);')
    local='ST_t ST; bit[31:0] ALU_A,ALU_B; bit[4:0] ALU_SA;\n'
    modules.append('module bt_shift_phase_'+label+phase_ports+local+body+capture+status+'assign ST_CAPTURED=ST;\nendmodule\n')
    function_ports='(input bit[31:0] val,input bit[4:0] sa,input bit[3:0] code,output bit[32:0] carry_result,output bit shift_overflow);\nimport TMS34020_PKG::*;\n'
    functions=helpers if label=='candidate' else ''
    carry_name='BtCarryShifter' if label=='candidate' else 'CarryShifter'
    overflow_name='BtShiftLeftOvf' if label=='candidate' else 'ShiftLeftOvf'
    modules.append('module bt_shift_function_'+label+function_ports+functions+'always_comb begin carry_result='+carry_name+'(val,sa,code); shift_overflow='+overflow_name+'(val,sa); end\nendmodule\n')
actual_slices='\n'.join(modules).encode();(OUT/'actual_slices.sv').write_bytes(actual_slices)
line_tb=(ROOT/'tests/bt_cpu_line_gz_tb.sv').read_text()
assert line_tb.count('module bt_cpu_line_gz_tb;')==1 and line_tb.count('$finish;')==1
line_tb=line_tb.replace('module bt_cpu_line_gz_tb;','module bt_cpu_line_gz_tb(output bit done);').replace('$finish;','done=1\'b1;')
(OUT/'line_testbench.sv').write_text(line_tb)
receipt['actual_slices_sha256']=sha(actual_slices)
receipt['base_line_testbench_sha256']=sha((ROOT/'tests/bt_cpu_line_gz_tb.sv').read_bytes())
receipt['line_testbench_compatibility']='Expose completion bit instead of $finish so both actual-slice tests complete; no stimulus/assertion alteration.'
def wsl(p):
    p=Path(p).resolve();return '/mnt/'+p.drive[0].lower()+p.as_posix()[2:]
build=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','/usr/bin/verilator','--binary','--assert','--timing','-j','2',
       '--top-module','bt_cpu_shift_flags_tb','-Wno-fatal','-Wno-BLKANDNBLK','--Mdir',wsl(OUT/'obj'),wsl(OUT/'TMS34020_pkg.sv'),
       wsl(OUT/'actual_slices.sv'),wsl(OUT/'line_testbench.sv'),wsl(TESTS/'bt_cpu_shift_flags_tb.sv')]
run=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec',wsl(OUT/'obj/Vbt_cpu_shift_flags_tb')]
for label,command in (('build',build),('run',run)):
    receipt['commands'].append(command)
    with(OUT/(label+'.log')).open('w')as log:r=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT)
    receipt[label+'_exit_code']=r.returncode;(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2))
    if r.returncode:
        print((OUT/(label+'.log')).read_text(errors='replace')[-7000:]);sys.exit(r.returncode)
log=(OUT/'run.log').read_text(errors='replace')
line=re.search(r'PASS line predicate combin=(\d+) phase=(\d+) zero_sign=(\d+)',log)
fun=re.search(r'PASS shift functions comparisons=(\d+) all16codes/all32amounts/all66basispatterns',log)
phase=re.search(r'PASS actual operand/status phases=(\d+) reset=(\d+) en_hold=(\d+) ce_hold=(\d+) stalls=(\d+) actions=(\d+) overflow_writes=(\d+) all8statusclasses',log)
assert line and fun and phase,'Missing required PASS coverage'
counts=dict(zip(('alu_combinational_comparisons','pixel_phase_cycles','zero_sign_witnesses'),map(int,line.groups())))
counts['direct_function_comparisons']=int(fun[1])
counts.update(dict(zip(('actual_operand_status_cycles','status_resets','status_enable_holds','status_ce_holds','status_stalls','status_actions','overflow_flag_writes'),map(int,phase.groups()))))
assert counts['alu_combinational_comparisons']==9469952 and counts['pixel_phase_cycles']==32768
assert counts['direct_function_comparisons']==1082368 and counts['actual_operand_status_cycles']==65536
assert all(v>0 for v in counts.values())
counts.update({'all_16_alu_encodings':True,'all_16_function_shift_codes':True,'all_32_shift_amounts':True,'all_8_status_update_classes':True})
receipt['pass_coverage']=counts;receipt['root_cpu_sha256_at_end']=sha((ROOT/CPU).read_bytes())
assert candidate_input.read_bytes()==candidate_bytes,'Candidate changed during proof'
assert candidate_path.read_bytes()==candidate_bytes
receipt['wall_seconds']=time.monotonic()-started;(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2))
print('receipt='+str(OUT/'receipt.json'));print(log[-4500:])
