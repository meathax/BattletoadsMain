"""Qualify shipping sprite consumers and transactions against the frozen pipeline."""
import hashlib,json,os,re,shutil,subprocess,sys,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('sprite-read-'+uuid.uuid4().hex)
target.mkdir(parents=True)
names=['rtl/spr_vram.sv','tests/graphics/ram_models.sv','tests/sprite_read_equivalence_tb.sv']
hashes={}
files=[]
for name in names:
    src=root/name;dst=target/src.name
    shutil.copyfile(src,dst)
    hashes[name]=hashlib.sha256(src.read_bytes()).hexdigest()
    files.append(str(dst))
source=(root/'rtl/spr_vram.sv').read_text()
candidate=source.replace('module SPR_VRAM','module SPR_VRAM_SYNC',1)
reference=Path('D:/vibes/fpga/temp/bt-graphics-67ed1dd1b6024cdd943b69f762a29dbe/rtl/spr_vram.sv')
baseline=reference.read_bytes()
(target/'spr_vram.sv').write_bytes(baseline)
hashes['baseline:spr_vram.sv']=hashlib.sha256(baseline).hexdigest()
hashes['rtl/BT_mem.sv']=hashlib.sha256((root/'rtl/BT_mem.sv').read_bytes()).hexdigest()
hashes['tests/graphics/qualify_sprite_read.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
(target/'spr_vram_sync.sv').write_text(candidate)
files.append(str(target/'spr_vram_sync.sv'))
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4','--threads','1',
    '--top-module','sprite_read_equivalence_tb','--Mdir',str(target/'obj'),'-Wno-fatal',
    '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',*files]
env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (target/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if result.returncode==0:
    with (target/'run.log').open('w') as log:
        result=subprocess.run([str(target/'obj/Vsprite_read_equivalence_tb.exe')],cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
retained=root/'tests/graphics/evidence/sprite-read'/target.name
retained.mkdir(parents=True,exist_ok=True)
receipt={'snapshot':str(target),'baseline':str(reference),'sources':hashes,'exit_code':result.returncode,'command':command,
    'scope':'sprite packet, four-memory-clock blitter consumer, foreground cache consumer, serial read/write and serial pixel equivalence against an untouched frozen reference; independent DDR completion adapters; physical primitive qualification is separate'}
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log','spr_vram_sync.sv','vram_shiftreg_sync.sv'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print((target/('run.log' if (target/'run.log').exists() else 'build.log')).read_text(errors='replace')[-2000:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
