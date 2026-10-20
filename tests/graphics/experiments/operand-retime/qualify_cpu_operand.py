"""Check complete operand register retiming against its original output cycle."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('cpu-operand-'+uuid.uuid4().hex)
target.mkdir(parents=True)
names=['rtl/TMS34020/TMS34020_pkg.sv','rtl/TMS34020/TMS34020_OPERAND_STAGE.sv','tests/cpu_operand_stage_tb.sv']
hashes={}
files=[]
for name in names:
    source=root/name
    destination=target/source.name
    shutil.copyfile(source,destination)
    files.append(str(destination))
    hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
for name in ('rtl/TMS34020/TMS34020.sv','tests/graphics/predecode_opcode.py','tests/graphics/qualify_cpu_operand.py'):
    hashes[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--top-module','cpu_operand_stage_tb','--Mdir',str(target/'obj'),
    '-Wno-fatal','-MAKEFLAGS',
    'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17',
    '-LDFLAGS','-static-libstdc++ -static-libgcc',*files]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
    VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (target/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=target,env=environment,stdout=log,
        stderr=subprocess.STDOUT,creationflags=flags)
if not result.returncode:
    with (target/'run.log').open('w') as log:
        result=subprocess.run([str(target/'obj/Vcpu_operand_stage_tb.exe')],cwd=target,
            env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
receipt={'snapshot':str(target),'sources':hashes,'command':command,
    'exit_code':result.returncode,'scope':'operand register retiming: exhaustive control tuple and reset preservation'}
retained=root/'tests/graphics/evidence/cpu-operand'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print((target/('run.log' if (target/'run.log').exists() else 'build.log')).read_text(errors='replace')[-1800:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
