"""Render the exact MAME scanline function through shipping video timing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid

p=argparse.ArgumentParser()
p.add_argument('--mame-source',type=Path,default=Path('D:/Arcade/AI/mame289/src/mame/rare/btoads.cpp'))
p.add_argument('--capture',type=Path,help='Replay immutable MAME video-state captures instead of synthetic patterns.')
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
target=Path('R:/Verilator/BT')/('raster-'+uuid.uuid4().hex)
target.mkdir(parents=True)
driver=a.mame_source.read_text()
start=driver.index('TMS340X0_SCANLINE_RGB32_CB_MEMBER(btoads_state::scanline_update)')
body=driver[driver.index('{',start):driver.index('\n}',start)+2]
header='''// MAME 0.289, BSD-3-Clause, copyright Aaron Giles.
#include <cstdint>
using pen_t=uint32_t;
struct Palette {uint32_t data[256]{};const pen_t* pens(){return data;}};
struct bitmap_rgb32 {uint32_t data[1024]{};uint32_t& pix(int){return data[0];}};
struct Params {uint32_t rowaddr,coladdr;unsigned heblnk,hsblnk;};
struct MameScanline {
 uint16_t* m_vram_bg[2];uint8_t* m_vram_fg_display;Palette* m_tlc34076;
 uint16_t m_xscroll[2]{},m_yscroll[2]{};unsigned m_screen_control=0;
 void draw(bitmap_rgb32& bitmap,int scanline,const Params* params)
'''+body+'\n};\n'
(target/'mame_scanline.h').write_text(header)
board=(root/'Arcade-Battletoads.sv').read_text()
start=board.index('\twire DCLK = VCE_R;')
enable_end=board.index('\n\tend',start)+len('\n\tend')
enable=board[start:enable_end]
ce=re.search(r'\.ce_pix\(([^\n]+)\)',board).group(1).rstrip(',')
(target/'mixer_enable.svh').write_text(enable+'\nassign MIX_CE='+ce+';\n')
files=[];hashes={}
names=['rtl/TMS34020/TMS34020_pkg.sv','tests/graphics/raster_sim.sv',
       'tests/graphics/ram_models.sv','rtl/BT.sv','rtl/bg_vram.sv','rtl/fg_vram.sv',
       'rtl/spr_vram.sv','rtl/sprite_blitter.sv','rtl/TMS34020/TMS34020_IO.sv','rtl/bt_clock_enables.sv',
       'tests/graphics/raster.cpp']
for name in names:
    data=(root/name).read_bytes();hashes[name]=hashlib.sha256(data).hexdigest()
    out=target/'src'/name;out.parent.mkdir(parents=True,exist_ok=True);out.write_bytes(data);files.append(str(out))
hashes['Arcade-Battletoads.sv']=hashlib.sha256((root/'Arcade-Battletoads.sv').read_bytes()).hexdigest()
hashes['MAME:scanline_update']=hashlib.sha256(body.encode()).hexdigest()
if a.capture:
    state=target/'state';state.mkdir()
    for source in sorted(a.capture.glob('state-*')):
        if source.is_file():
            data=source.read_bytes();(state/source.name).write_bytes(data)
            hashes['MAME:'+source.name]=hashlib.sha256(data).hexdigest()
    for source in [a.capture/'display_events.txt',*sorted(a.capture.glob('mame_*.png'))]:
        if source.is_file():
            data=source.read_bytes();(state/source.name).write_bytes(data)
            hashes['MAME:'+source.name]=hashlib.sha256(data).hexdigest()
    if not list(state.glob('state-*-meta.txt')):raise SystemExit('No captured video states.')
command=['D:/vibes/fpga/bin/verilator.exe','--cc','--exe','--build','--assert','--timing','-j','4','--threads','1',
         '--x-initial','unique','--x-assign','unique','--top-module','BT_RASTER_SIM','--Mdir',str(target/'obj'),
         '-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD','-Wno-PINMISSING','-Wno-CASEINCOMPLETE',
         '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
         '-I'+str(target),'-CFLAGS','-I'+target.as_posix()+' -DVL_TIME_CONTEXT -std=c++17 -O3',
         '-LDFLAGS','-static-libstdc++ -static-libgcc',*files]
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
                 VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (target/'build.log').open('w') as log:
    r=subprocess.run(command,cwd=root,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if not r.returncode:
    with (target/'run.log').open('w') as log:
        r=subprocess.run([str(target/'obj/VBT_RASTER_SIM.exe')]+([str(target/'state')] if a.capture else []),cwd=target,env=environment,
                         stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
name='run.log' if (target/'run.log').exists() else 'build.log'
print((target/name).read_text(errors='replace')[-2500:])
png_results={}
if not r.returncode and a.capture and (target/'state/display_events.txt').exists():
    from PIL import Image
    for n in (350,600,900,1500,1800):
        native=Image.open(target/f'native-{n}.ppm').convert('RGB')
        mame=Image.open(target/'state'/f'mame_{n:04d}.png').convert('RGB')
        if native.size!=mame.size:raise RuntimeError('Completed-frame dimensions differ.')
        png_results[str(n)]=sum(x!=y for x,y in zip(native.get_flattened_data(),mame.get_flattened_data()))
    print('completed_MAME_frame_pixel_mismatches='+json.dumps(png_results))
    if any(png_results.values()):r.returncode=1
receipt={'scope':'captured VRAM and recorded display writes; real video I/O and actual MiSTer mixer input enable; excludes CPU/audio execution',
         'completed_frame_pixel_mismatches':png_results,
         'snapshot':str(target),'sources':hashes,'command':command,'exit_code':r.returncode}
retained=root/'tests/graphics/evidence/raster'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for f in ('build.log','run.log','mame_scanline.h','mixer_enable.svh'):
    if (target/f).exists():shutil.copyfile(target/f,retained/f)
for f in target.glob('*.ppm'):shutil.copyfile(f,retained/f.name)
print('receipt='+str(retained/'receipt.json'))
sys.exit(r.returncode)
