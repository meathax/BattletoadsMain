"""Qualify cache retiming against the previously fitted shipping controller."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('ddram-cache-'+uuid.uuid4().hex)
target.mkdir(parents=True)
hashes={};files=[]
for name in ('rtl/ddram.sv','tests/ddram_cache_tb.sv'):
    data=(root/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
    out=target/Path(name).name;out.write_bytes(data);files.append(str(out))
reference=Path('D:/vibes/fpga/temp/bt-graphics-5d15ea75fb454afd9bd373ae2da237f9/rtl/ddram.sv')
baseline=reference.read_bytes();hashes['baseline:ddram.sv']=hashlib.sha256(baseline).hexdigest()
out=target/'baseline.sv';out.write_bytes(baseline.replace(b'module ddram',b'module ddram_baseline'))
files.insert(1,str(out))
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4','--threads','1',
         '--x-initial','unique','--x-assign','unique','--top-module','ddram_cache_tb','--Mdir',str(target/'obj'),
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
        r=subprocess.run([str(target/'obj/Vddram_cache_tb.exe')],cwd=target,env=environment,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
name='run.log' if (target/'run.log').exists() else 'build.log'
print((target/name).read_text(errors='replace')[-2400:])
receipt={'scope':'accepted DDR command/data/handshake equivalence; cache values while busy are not consumed',
         'snapshot':str(target),'baseline':str(reference),'sources':hashes,'command':command,'exit_code':r.returncode}
retained=root/'tests/graphics/evidence/ddram-cache'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print('receipt='+str(retained/'receipt.json'))
sys.exit(r.returncode)
