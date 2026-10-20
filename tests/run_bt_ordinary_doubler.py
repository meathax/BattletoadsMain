#!/usr/bin/env python3
"""Cycle equivalence against the unmodified real framework, using Ubuntu WSL."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tests'/'graphics'/'evidence'/'bt_ordinary_doubler'
OUT.mkdir(parents=True,exist_ok=True)
source=ROOT/'sys'/'video_mixer.sv'
ref=source.read_text(encoding='utf-8')
# Syntax-only portability: both Quartus and historical framework allow the
# generated R_in names, while current Verilator resolves implicit 1-bit nets.
start=ref.index('generate\n\tif(GAMMA && HALF_DEPTH)')
end=ref.index('endgenerate',start)+len('endgenerate')
block=ref[start:end]
block=re.sub(r'wire \[7:0\] ([RGB]_in)\s*=',r'assign \1 =',block)
block=re.sub(r'wire \[DWIDTH:0\] ([RGB]_in)\s*=',r'assign \1 =',block)
ref=ref[:start]+'wire [DWIDTH_SD:0] R_in, G_in, B_in;\n'+block+ref[end:]
(OUT/'video_mixer_ref.sv').write_text(ref,encoding='utf-8')
hq=(ROOT/'sys'/'hq2x.sv').read_text(encoding='utf-8')
hq=re.sub(r'output\s+\[23:0\]\s+Result', 'output reg [23:0] Result',hq)
(OUT/'hq2x_ref.sv').write_text(hq,encoding='utf-8')
out_relative=OUT.relative_to(ROOT).as_posix()
files=['tests/bt_ordinary_doubler_tb.sv','rtl/bt_video_mixer.sv',
       'rtl/bt_scandoubler.sv',out_relative+'/video_mixer_ref.sv',
       'sys/scandoubler.v',out_relative+'/hq2x_ref.sv',
       'sys/video_freezer.sv','sys/gamma_corr.sv']
wsl=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec']
build=wsl+['verilator','--binary','--timing','--top-module',
           'bt_ordinary_doubler_tb','-Wno-fatal','-j','2','--Mdir',
           out_relative+'/obj_dir']+files
with (OUT/'compile.log').open('w',encoding='utf-8') as log:
    result=subprocess.run(build,stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((OUT/'compile.log').read_text(encoding='utf-8')[-9000:])
    sys.exit(result.returncode)
with (OUT/'equivalence.log').open('w',encoding='utf-8') as log:
    result=subprocess.run(wsl+['./'+out_relative+'/obj_dir/Vbt_ordinary_doubler_tb'],
                          stdout=log,stderr=subprocess.STDOUT)
print((OUT/'equivalence.log').read_text(encoding='utf-8')[-4000:])
equivalence_exit=result.returncode
if equivalence_exit:
    sys.exit(equivalence_exit)
# Compile the actual RAM module separately: Icarus cannot elaborate the
# historical framework's forward-declared constants, but can run this memory
# contract as genuine four-state RTL, including undefined startup contents.
rtl=(ROOT/'rtl'/'bt_scandoubler.sv').read_text(encoding='utf-8')
(OUT/'bt_sd_ram_extract.sv').write_text(rtl[rtl.index('module bt_sd_ram'):],encoding='utf-8')
binpath=Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin')
with (OUT/'ram_compile.log').open('w',encoding='utf-8') as log:
    result=subprocess.run([str(binpath/'iverilog.exe'),'-g2012','-s','bt_ordinary_sd_ram_tb',
                           '-o',str(OUT/'ram.vvp'),str(ROOT/'tests'/'bt_ordinary_sd_ram_tb.sv'),
                           str(OUT/'bt_sd_ram_extract.sv')],stdout=log,stderr=subprocess.STDOUT)
if result.returncode:
    print((OUT/'ram_compile.log').read_text(encoding='utf-8')[-4000:])
    sys.exit(result.returncode)
with (OUT/'ram.log').open('w',encoding='utf-8') as log:
    result=subprocess.run([str(binpath/'vvp.exe'),str(OUT/'ram.vvp')],
                          stdout=log,stderr=subprocess.STDOUT)
print((OUT/'ram.log').read_text(encoding='utf-8')[-4000:])
receipt={'exit_code':result.returncode,'equivalence_exit_code':equivalence_exit,
         'source_sha256':{
    name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
    for name in ['rtl/bt_video_mixer.sv','rtl/bt_scandoubler.sv',
                 'sys/video_mixer.sv','sys/scandoubler.v','sys/hq2x.sv',
                 'sys/video_freezer.sv','sys/gamma_corr.sv',
                 'tests/bt_ordinary_doubler_tb.sv',
                 'tests/bt_ordinary_sd_ram_tb.sv','tests/run_bt_ordinary_doubler.py']},
    'reference_normalization':['generate nets explicitly named at module scope',
                               'Blend.Result declared reg for procedural assignment']}
(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
sys.exit(result.returncode)
