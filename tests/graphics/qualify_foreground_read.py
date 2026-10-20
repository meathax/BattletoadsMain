"""Compare accepted foreground transactions against the untouched frozen pipeline."""
import hashlib,json,os,re,shutil,subprocess,sys,uuid
from pathlib import Path
root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('foreground-read-'+uuid.uuid4().hex)
target.mkdir(parents=True)
names=['rtl/fg_vram.sv','tests/graphics/ram_models.sv','tests/foreground_read_equivalence_tb.sv']
hashes={}
files=[]
for name in names:
    src=root/name;dst=target/src.name
    shutil.copyfile(src,dst)
    hashes[name]=hashlib.sha256(src.read_bytes()).hexdigest()
    files.append(str(dst))
reference=Path('D:/vibes/fpga/temp/bt-graphics-7d58bf03c5c741ab8a0021818e48b19e/rtl/fg_vram.sv')
baseline=reference.read_bytes()
(target/'fg_vram_reference.sv').write_text(baseline.decode().replace('module FG_VRAM','module FG_VRAM_REFERENCE',1))
hashes['baseline:fg_vram.sv']=hashlib.sha256(baseline).hexdigest()
hashes['rtl/BT_mem.sv']=hashlib.sha256((root/'rtl/BT_mem.sv').read_bytes()).hexdigest()
hashes['tests/graphics/qualify_foreground_read.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
files.append(str(target/'fg_vram_reference.sv'))
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4','--threads','1',
    '--top-module','foreground_read_equivalence_tb','--Mdir',str(target/'obj'),'-Wno-fatal',
    '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',*files]
env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (target/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if result.returncode==0:
    with (target/'run.log').open('w') as log:
        result=subprocess.run([str(target/'obj/Vforeground_read_equivalence_tb.exe')],cwd=target,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
retained=root/'tests/graphics/evidence/foreground-read'/target.name
retained.mkdir(parents=True,exist_ok=True)
receipt={'snapshot':str(target),'baseline':str(reference),'sources':hashes,'exit_code':result.returncode,'command':command,
    'scope':'foreground transaction/consumer equivalence against an untouched frozen reference; complete copy packets and DDR requests, visible readback and serial samples; independent one/two-clock cache adapters; physical primitive timing is qualified by fitting'}
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log','fg_vram_reference.sv','fg_vram.sv'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print((target/('run.log' if (target/'run.log').exists() else 'build.log')).read_text(errors='replace')[-2000:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
