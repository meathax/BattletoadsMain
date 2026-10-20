"""Qualify the entire production decoder against its pinned binary-state RTL."""
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
workspace=Path('R:/Verilator/BT')/('decode-'+uuid.uuid4().hex)
source_dir=workspace/'src'
source_dir.mkdir(parents=True)
hashes={}
mame_source=Path('D:/Arcade/AI/mame289/src/devices/cpu/tms34010/tms34010.cpp')
mame_text=mame_source.read_text()
transparent=mame_text.split('#define WP_T(m1,m2)',1)[1].split('/* Raster Op',1)[0]
if ('data &= m2;' not in transparent or 'if (data)' not in transparent or
    'write_pixel_t_1(offs_t offset, uint32_t data) { WP_T(0x0f, 0x01); }' not in mame_text):
    raise SystemExit('Pinned MAME 1-bit transparency reference changed.')
hashes[str(mame_source)]=hashlib.sha256(mame_source.read_bytes()).hexdigest()
def load(relative,baseline=False):
    data=(subprocess.check_output(['git','show',baseline_ref+':'+relative],cwd=root)
          if baseline else (root/relative).read_bytes())
    hashes[('baseline:' if baseline else '')+relative]=hashlib.sha256(data).hexdigest()
    return data.decode()
contents=[('current_pkg.sv',load('rtl/TMS34020/TMS34020_pkg.sv')),
          ('baseline_pkg.sv',load('rtl/TMS34020/TMS34020_pkg.sv',True).replace('TMS34020_PKG','TMS34020_PKG_BASELINE')),
          ('current_id.sv',load('rtl/TMS34020/TMS34020_ID.sv')),
          ('baseline_id.sv',load('rtl/TMS34020/TMS34020_ID.sv',True)
           .replace('TMS34020_PKG','TMS34020_PKG_BASELINE').replace('module TMS34020_ID','module TMS34020_ID_BASELINE')),
          ('tms_decode_tb.sv',load('tests/tms_decode_tb.sv'))]
sources=[]
for name,content in contents:
    path=source_dir/name
    path.write_text(content)
    sources.append(str(path))
hashes['rtl/TMS34020/TMS34020.sv']=hashlib.sha256((root/'rtl/TMS34020/TMS34020.sv').read_bytes()).hexdigest()
obj=workspace/'obj'
obj.mkdir()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--x-initial','unique','--x-assign','unique','--top-module','tms_decode_tb','--Mdir',str(obj),
    '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',
    '-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD',
    '-Wno-CASEINCOMPLETE','-Wno-CASEX',*sources]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
    VERILATOR_WORKSPACE=str(workspace),VERILATOR_RAM_WORKSPACE=str(workspace))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (workspace/'build.log').open('w') as log:
    result=subprocess.run(command,cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if not result.returncode:
    with (workspace/'run.log').open('w') as log:
        result=subprocess.run([str(obj/'Vtms_decode_tb.exe')],cwd=root,env=environment,
                              stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
log_name='run.log' if (workspace/'run.log').exists() else 'build.log'
print((workspace/log_name).read_text(errors='replace')[-2300:])
receipt={'scope':'full decoder equivalence and lane/aggregate transparency comparison; '
                 '1-bit transparency deliberately follows MAME instead of the broken baseline; '
                 'not native CPU/frame equivalence',
         'baseline_ref':baseline_ref,'snapshot':str(workspace),'sources':hashes,
         'command':command,'exit_code':result.returncode}
(workspace/'receipt.json').write_text(json.dumps(receipt,indent=2))
retained=root/'tests/graphics/evidence/decode'/workspace.name
retained.mkdir(parents=True,exist_ok=True)
for name in ('receipt.json','build.log','run.log'):
    source=workspace/name
    if source.exists(): shutil.copyfile(source,retained/name)
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
