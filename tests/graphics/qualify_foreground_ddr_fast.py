"""Foreground copy protocol test through the shipping DDR controller."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
workspace=Path('R:/Verilator/BT')/('foreground-ddr-fast-'+uuid.uuid4().hex)
sources=['tests/graphics/intel_lcell_sim.v','rtl/fg_vram.sv','rtl/ddram.sv','rtl/bt_fg_ddr_clear.sv',
         'tests/graphics/ram_models.sv','tests/foreground_ddr_fast_tb.sv']
frozen=[]
hashes={}
for name in sources:
    source=root/name
    target=workspace/'src'/name
    target.parent.mkdir(parents=True,exist_ok=True)
    data=source.read_bytes()
    target.write_bytes(data)
    hashes[name]=hashlib.sha256(data).hexdigest()
    frozen.append(str(target))
obj=workspace/'obj'
obj.mkdir()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--x-initial','unique','--x-assign','unique',
    '--top-module','foreground_ddr_fast_tb','--Mdir',str(obj),
    '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',
    '-Wno-PINMISSING','-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD',
    '-Wno-CASEINCOMPLETE',*frozen]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
    VERILATOR_WORKSPACE=str(workspace),VERILATOR_RAM_WORKSPACE=str(workspace))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (workspace/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if result.returncode:
    print((workspace/'build.log').read_text(errors='replace')[-2300:])
else:
    with (workspace/'run.log').open('w') as log:
        result=subprocess.run([str(obj/'Vforeground_ddr_fast_tb.exe')],cwd=root,env=environment,
            stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    print((workspace/'run.log').read_text(errors='replace')[-2300:])
receipt={'scope':'foreground transfer and shipping DDR protocol; not native CPU/frame equivalence',
    'snapshot':str(workspace),'sources':hashes,'command':command,'exit_code':result.returncode}
(workspace/'receipt.json').write_text(json.dumps(receipt,indent=2))
retained=root/'tests/graphics/evidence/foreground-ddr'/workspace.name
retained.mkdir(parents=True,exist_ok=True)
for name in ('receipt.json','build.log','run.log'):
    source=workspace/name
    if source.exists(): shutil.copyfile(source,retained/name)
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
