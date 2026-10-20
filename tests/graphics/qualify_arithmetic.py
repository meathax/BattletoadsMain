"""Compare the production multiply/divide block with its pinned pre-optimization RTL."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
baseline_ref='4a55b0e'
workspace=Path('R:/Verilator/BT')/('arithmetic-'+uuid.uuid4().hex)
source_dir=workspace/'src'
source_dir.mkdir(parents=True)
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
hashes={}
def load(relative, baseline=False):
    if baseline:
        data=subprocess.check_output(['git','show',baseline_ref+':'+relative],cwd=root)
    else:
        data=(root/relative).read_bytes()
    hashes[('baseline:' if baseline else '')+relative]=hashlib.sha256(data).hexdigest()
    return data.decode()

def wrapper(source,name,package):
    start=source.index('\talways_comb begin',source.index('//DIV unit'))
    end=source.index('\n\talways @(posedge CLK or negedge RST_N)',start)
    return f'''module {name}(
    input bit [63:0] MD_ACC,MD_SHIFT,
    input bit [31:0] RF_RA_Q,ALU_R,
    input bit [5:0] MD_STEP,
    input bit MD_NEG,
    input bit [2:0] accs,shs,
    output bit [63:0] MDALU_R,MDSHT_R,
    output bit MDALU_C,MDALU_Z);
    import {package}::*;
    DecInstr_t DECI;
    bit [63:0] MDALU_A,MDALU_B;
    always_comb begin
        DECI='0;
        DECI.MDC.ACCS=MulDivACC_t'(accs);
        DECI.MDC.SHS=MulDivSh_t'(shs);
    end
'''+source[start:end]+'\nendmodule\n'

current=load('rtl/TMS34020/TMS34020.sv')
old=load('rtl/TMS34020/TMS34020.sv',True)
package=load('rtl/TMS34020/TMS34020_pkg.sv')
old_package=load('rtl/TMS34020/TMS34020_pkg.sv',True).replace('TMS34020_PKG','TMS34020_PKG_BASELINE')
sources=[]
for name,content in [('current_pkg.sv',package),('baseline_pkg.sv',old_package),
    ('md_candidate.sv',wrapper(current,'md_candidate','TMS34020_PKG')),
    ('md_baseline.sv',wrapper(old,'md_baseline','TMS34020_PKG_BASELINE')),
    ('tms_arithmetic_tb.sv',load('tests/tms_arithmetic_tb.sv'))]:
    path=source_dir/name
    path.write_text(content)
    sources.append(str(path))
obj=workspace/'obj'
obj.mkdir()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--x-initial','unique','--x-assign','unique',
    '--top-module','tms_arithmetic_tb','--Mdir',str(obj),
    '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',
    '-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD',
    '-Wno-COMBDLY','-Wno-CASEINCOMPLETE',*sources]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
    VERILATOR_WORKSPACE=str(workspace),VERILATOR_RAM_WORKSPACE=str(workspace))
with (workspace/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if not result.returncode:
    with (workspace/'run.log').open('w') as log:
        result=subprocess.run([str(obj/'Vtms_arithmetic_tb.exe')],cwd=root,env=environment,
            stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
log_name='run.log' if (workspace/'run.log').exists() else 'build.log'
print((workspace/log_name).read_text(errors='replace')[-2300:])
receipt={'scope':'production arithmetic block equivalence; not native CPU/frame equivalence',
    'baseline_ref':baseline_ref,'snapshot':str(workspace),'sources':hashes,
    'command':command,'exit_code':result.returncode}
(workspace/'receipt.json').write_text(json.dumps(receipt,indent=2))
retained=root/'tests/graphics/evidence/arithmetic'/workspace.name
retained.mkdir(parents=True,exist_ok=True)
for name in ('receipt.json','build.log','run.log'):
    source=workspace/name
    if source.exists(): shutil.copyfile(source,retained/name)
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
