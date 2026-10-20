"""Check the shipping sprite copy pipeline and its completion boundary."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('sprite-packet-'+uuid.uuid4().hex)
target.mkdir(parents=True)
names=['rtl/spr_vram.sv','tests/graphics/ram_models.sv','tests/sprite_packet_tb.sv']
hashes={}
files=[]
for name in names:
    source=root/name
    destination=target/source.name
    shutil.copyfile(source,destination)
    files.append(str(destination))
    hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--top-module','sprite_packet_tb','--Mdir',str(target/'obj'),
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
        result=subprocess.run([str(target/'obj/Vsprite_packet_tb.exe')],cwd=target,
            env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
receipt={'snapshot':str(target),'sources':hashes,'command':command,
    'exit_code':result.returncode,'scope':'sprite foreground packet ordering and completion'}
retained=root/'tests/graphics/evidence/sprite-packet'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print((target/('run.log' if (target/'run.log').exists() else 'build.log')).read_text(errors='replace')[-1800:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
