"""Verify normal CPU writes across the related SYS/MEM clock boundary."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('vram-write-'+uuid.uuid4().hex)
hashes={};files=[]
for name in ('rtl/bg_vram.sv','rtl/fg_vram.sv','tests/graphics/ram_models.sv','tests/vram_write_tb.sv'):
    data=(root/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
    out=target/Path(name).name;out.parent.mkdir(parents=True,exist_ok=True)
    out.write_bytes(data);files.append(str(out))
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4','--threads','1',
         '--x-initial','unique','--x-assign','unique','--top-module','vram_write_tb','--Mdir',str(target/'obj'),
         '-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD','-Wno-PINMISSING','-Wno-CASEINCOMPLETE',
         '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
         '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17 -O3','-LDFLAGS','-static-libstdc++ -static-libgcc',*files]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
                 VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (target/'build.log').open('w') as log:
    r=subprocess.run(command,cwd=target,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if not r.returncode:
    with (target/'run.log').open('w') as log:
        r=subprocess.run([str(target/'obj/Vvram_write_tb.exe')],cwd=target,env=environment,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
name='run.log' if (target/'run.log').exists() else 'build.log'
print((target/name).read_text(errors='replace')[-2200:])
receipt={'scope':'shipping VRAM normal writes; complete CPU packets with early bus changes and held strobes',
         'snapshot':str(target),'sources':hashes,'command':command,'exit_code':r.returncode}
retained=root/'tests/graphics/evidence/vram-write'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for f in ('build.log','run.log'):
    if (target/f).exists():shutil.copyfile(target/f,retained/f)
print('receipt='+str(retained/'receipt.json'))
sys.exit(r.returncode)
