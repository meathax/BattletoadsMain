"""Check same-edge sprite page strobes against the frozen implementation."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('sprite-page-'+uuid.uuid4().hex)
target.mkdir(parents=True)
names=['rtl/sprite_blitter.sv','tests/sprite_page_equivalence_tb.sv']
hashes={}
files=[]
for name in names:
    source=root/name
    destination=target/source.name
    shutil.copyfile(source,destination)
    files.append(str(destination))
    hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
baseline=Path('D:/vibes/fpga/temp/bt-graphics-9b251150b9d144d982ec6dfab13d401f/rtl/sprite_blitter.sv')
reference=baseline.read_text()
assert reference.count('module BT_SPRITE_BLITTER (')==1
reference=reference.replace('module BT_SPRITE_BLITTER (','module BT_SPRITE_BLITTER_REFERENCE (')
reference_path=target/'sprite_blitter_reference.sv'
reference_path.write_text(reference)
files.append(str(reference_path))
hashes[str(baseline)]=hashlib.sha256(baseline.read_bytes()).hexdigest()
hashes['tests/graphics/qualify_sprite_page.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--top-module','sprite_page_equivalence_tb','--Mdir',str(target/'obj'),
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
        result=subprocess.run([str(target/'obj/Vsprite_page_equivalence_tb.exe')],cwd=target,
            env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
receipt={'snapshot':str(target),'sources':hashes,'command':command,
    'exit_code':result.returncode,'scope':'same-edge sprite page strobe and all-output preservation'}
retained=root/'tests/graphics/evidence/sprite-page'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print((target/('run.log' if (target/'run.log').exists() else 'build.log')).read_text(errors='replace')[-1800:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
