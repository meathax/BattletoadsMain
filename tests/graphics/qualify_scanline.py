"""Compare shipping TMS34020 scanline stepping with the exact MAME 0.289 code."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

p=argparse.ArgumentParser()
p.add_argument('--baseline',action='store_true')
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('scanline-'+uuid.uuid4().hex)
target.mkdir(parents=True)
reference=Path('D:/Arcade/AI/mame289/src/devices/cpu/tms34010/tms34010.cpp')
text=reference.read_text()
begin=text.index('uint32_t dpynx = IOREG(REG020_DPYNXL)')
end=text.index('IOREG(REG020_DPYNXH) = dpynx >> 16;',begin)+len('IOREG(REG020_DPYNXH) = dpynx >> 16;')
oracle='''// Exact MAME 0.289 display advance; BSD-3-Clause, Aaron Giles et al.
#include <cstdint>
enum {REG020_DPYNXL,REG020_DPYNXH,REG020_DINCL,REG020_DINCH};
extern "C" uint32_t mame_display_advance(uint32_t address,uint32_t increment) {
 uint32_t regs[4]={address & 0xffff,address >> 16,increment & 0xffff,increment >> 16};
 #define IOREG(name) regs[name]
'''+text[begin:end]+'''
 #undef IOREG
 return regs[0] | (regs[1] << 16);
}
'''
(target/'oracle.cpp').write_text(oracle)
hashes={str(reference):hashlib.sha256(reference.read_bytes()).hexdigest()}
files=[]
for name in ('rtl/TMS34020/TMS34020_pkg.sv','rtl/TMS34020/TMS34020_IO.sv','tests/tms_scanline_tb.sv'):
    data=(subprocess.check_output(['git','show','4a55b0e:'+name],cwd=root)
          if a.baseline and name.endswith('TMS34020_IO.sv') else (root/name).read_bytes())
    out=target/Path(name).name;out.write_bytes(data);files.append(str(out))
    hashes[name]=hashlib.sha256(data).hexdigest()
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
         '--threads','1','--x-initial','unique','--x-assign','unique','--top-module','tms_scanline_tb',
         '--Mdir',str(target/'obj'),'-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD',
         '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
         '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17 -O3','-LDFLAGS','-static-libstdc++ -static-libgcc',
         *files,str(target/'oracle.cpp')]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
                 VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (target/'build.log').open('w') as log:
    r=subprocess.run(command,cwd=target,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if not r.returncode:
    with (target/'run.log').open('w') as log:
        r=subprocess.run([str(target/'obj/Vtms_scanline_tb.exe')],cwd=target,env=environment,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
log_name='run.log' if (target/'run.log').exists() else 'build.log'
print((target/log_name).read_text(errors='replace')[-2500:])
receipt={'scope':'native TMS34020 display stepping/prefill and byte writes against exact MAME arithmetic; '
                 'not complete CPU/frame equivalence','snapshot':str(target),'baseline':a.baseline,
         'sources':hashes,'command':command,'exit_code':r.returncode}
retained=root/'tests/graphics/evidence/scanline'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print('receipt='+str(retained/'receipt.json'))
sys.exit(r.returncode)
