"""Frozen native game-board execution; no CPU or DDR-controller stubs.

Produces raw raster frames and source-bound receipts. Frame equality with MAME
is a separate acceptance check; a successful run alone does not prove it.
"""
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
import zipfile
from bt_native_mc_scope import expose_launch_scope

p=argparse.ArgumentParser()
p.add_argument('--frames',type=int,default=10)
p.add_argument('--rom',type=Path,default=Path('D:/Arcade/AI/MAME 0.289 ROMs (merged)/btoads.zip'))
p.add_argument('--input-journal',type=Path)
p.add_argument('--source-overlay',type=Path,
               help='Explicit hash-bound private RTL candidates; source receipts retain actual candidate hashes.')
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
overlay=None
overlay_bytes={}
if a.source_overlay:
    overlay=json.loads(a.source_overlay.read_text(encoding='utf-8'))
    if overlay.get('schema')!=1 or not isinstance(overlay.get('files'),dict) or not overlay['files']:
        raise ValueError('Unsupported or empty native source overlay')
    for key,entry in overlay['files'].items():
        relative=Path(key)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='rtl' or relative.suffix!='.sv':
            raise ValueError('Native overlay is restricted to existing relative RTL .sv inputs: '+key)
        candidate=Path(entry['path']).resolve()
        if not candidate.is_relative_to((root/'build').resolve()):
            raise ValueError('Private native source must be retained under this project build directory')
        if hashlib.sha256((root/relative).read_bytes()).hexdigest()!=entry['baseline_sha256']:
            raise ValueError('Current native baseline changed: '+key)
        data=candidate.read_bytes()
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('Frozen private native source changed: '+key)
        overlay_bytes[key]=data
target=Path('R:/Verilator/BT')/('native-'+uuid.uuid4().hex)
target.mkdir(parents=True)
shutil.copytree(root/'rtl',target/'rtl')
sources={str(f.relative_to(root)):hashlib.sha256(f.read_bytes()).hexdigest()
         for f in (root/'rtl').rglob('*') if f.is_file()}
for key,data in overlay_bytes.items():
    (target/key).write_bytes(data)
    # Match the Windows path spelling used by the initial source inventory.
    # Each physical input must have one source hash after the overlay.
    sources[str(Path(key))]=hashlib.sha256(data).hexdigest()
if overlay is not None:
    (target/'source_overlay.json').write_text(json.dumps(overlay,indent=2))
sources['tests/graphics/native_run.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
# Expose a block-local bit for capture-phase assertions. Moving its declaration
# in this private copy preserves its initialization and clocked assignments.
mc=target/'rtl/TMS34020/TMS34020_MC.sv'
mc_text=mc.read_text()
local_latch='\t\tbit         READ_LATCH;'
module_latch='\tbit          FETCH_LATCH;'
if mc_text.count(local_latch)==0 and '\tbit SCRREF_PEND, READ_LATCH, WRITE_LATCH;' in mc_text:
    mc_visible=mc_text  # merged MC: READ_LATCH already at module scope
else:
    assert mc_text.count(local_latch)==1 and mc_text.count(module_latch)==1
    mc_visible=mc_text.replace(local_latch,'').replace(module_latch,
                  module_latch+'\n\tbit          READ_LATCH;')
mc_visible,mc_launch_scope=expose_launch_scope(mc_visible)
mc.write_text(mc_visible)
(target/'mc_launch_scope.json').write_text(json.dumps(mc_launch_scope,indent=2))
sources['tests/graphics/bt_native_mc_scope.py']=hashlib.sha256((root/'tests/graphics/bt_native_mc_scope.py').read_bytes()).hexdigest()
for name in ('native_sim.sv','native.cpp','ram_models.sv'):
    src=root/'tests/graphics'/name
    shutil.copyfile(src,target/name)
    sources[str(src.relative_to(root))]=hashlib.sha256(src.read_bytes()).hexdigest()
video_source=(root/'Arcade-Battletoads.sv').read_text()
begin=video_source.index('\twire DCLK = VCE_R;')
enable_end=video_source.index('\n\tend',begin)+len('\n\tend')
video_enable=video_source[begin:enable_end]
video_ce=re.search(r'\.ce_pix\(([^\n]+)\)',video_source).group(1).rstrip(',')
if video_ce=='crt_ce':
    # CRT Adjust (off in the harness) passes its ce_in source to the mixer.
    video_ce=re.search(r'\.ce_in\(([^)]+)\)',video_source).group(1)
(target/'mixer_enable.svh').write_text(video_enable+'\nassign MIX_CE='+video_ce+';\n')
sources['Arcade-Battletoads.sv']=hashlib.sha256((root/'Arcade-Battletoads.sv').read_bytes()).hexdigest()
with zipfile.ZipFile(a.rom) as archive:
    p0=archive.read('btc0-p0.u120');p1=archive.read('btc0-p1.u121')
    program=bytearray(0x800000)
    program[0::4]=p0[0::2];program[1::4]=p0[1::2]
    program[2::4]=p1[0::2];program[3::4]=p1[1::2]
    (target/'main.bin').write_bytes(program)
    (target/'audio.bin').write_bytes(archive.read('bt.u102'))
    (target/'samples.bin').write_bytes(archive.read('btc0-s.u109'))
mif=(target/'rtl/bsmt2000.mif').read_text()
words=[0]*4096
for offset,value in re.findall(r'^\s*([0-9A-Fa-f]+)\s*:\s*([0-9A-Fa-f]+)\s*;',mif,re.M):
    words[int(offset,16)]=int(value,16)
(target/'rtl/bsmt2000.hex').write_text(''.join(f'{w:04x}\n' for w in words))
bt=target/'rtl/BT.sv'
bt.write_text(bt.read_text().replace('rtl/bsmt2000.mif','rtl/bsmt2000.hex'))
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
                 VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
commands=[]
def run(command,log_name):
    commands.append(command)
    with (target/log_name).open('w') as log:
        result=subprocess.run(command,cwd=target,env=environment,stdout=log,
                              stderr=subprocess.STDOUT,creationflags=flags)
    if result.returncode:
        print((target/log_name).read_text(errors='replace')[-4000:])
        raise RuntimeError(f'{log_name} failed: {result.returncode}')
ghdl=shutil.which('ghdl.exe') or 'D:/vibes/fpga/bin/ghdl.exe'
t80=[str(target/'rtl/T80'/('T80_'+n+'.vhd')) for n in ('ALU','Reg','MCode')]
t80 += [str(target/'rtl/T80/T80.vhd'),str(target/'rtl/T80/T80pa.vhd')]
for name in ('T80.vhd','T80pa.vhd'):
    path=target/'rtl/T80'/name
    text=re.sub(r'(:\s*)work\.(T80\w*)',r'\1entity work.\2',path.read_text())
    # STD_LOGIC_UNSIGNED pads the four-bit constant to the nine-bit operand.
    text=text.replace('ioq and x"7"','ioq and "000000111"')
    path.write_text(text)
try:
    # Convert the actual VHDL Z80; no substitute sound handshake is injected.
    run([ghdl,'-a','--std=08','-fsynopsys',*t80],'ghdl-analyze.log')
    command=[ghdl,'--synth','--std=08','-fsynopsys','--latches','--out=verilog','T80pa']
    commands.append(command)
    with (target/'t80_native.v').open('w') as out,(target/'ghdl-synth.log').open('w') as err:
        r=subprocess.run(command,cwd=target,stdout=out,stderr=err,creationflags=flags)
    if r.returncode:
        print((target/'ghdl-synth.log').read_text(errors='replace')[-4000:])
        raise RuntimeError('T80 synthesis failed')
    files=[target/'rtl/TMS34020/TMS34020_pkg.sv',target/'rtl/TMS320C1X/TMS320C1X_pkg.sv']
    files += sorted(f for f in (target/'rtl/TMS34020').glob('*.sv') if not f.name.endswith('_pkg.sv'))
    files += [target/'rtl/TMS34020_mem.sv',target/'rtl/TMS320C1X/TMS320C1X.sv',
              target/'rtl/TMS320C1X_mem.sv',target/'t80_native.v',target/'ram_models.sv']
    files += [target/'rtl'/name for name in ('BT.sv','bg_vram.sv','fg_vram.sv','spr_vram.sv',
             'sprite_blitter.sv','bt_audio_ram.sv','bt_clock_enables.sv','bt_fg_ddr_clear.sv','ddram.sv','bt_ddr_tag_compare.sv')]
    files += [target/'native_sim.sv']
    command=['D:/vibes/fpga/bin/verilator.exe','--cc','--exe','--build','--assert','-j','4',
             '--threads','1','--x-initial','unique','--x-assign','unique',
             '--top-module','BT_NATIVE_SIM','--Mdir',str(target/'obj'),'-DSOUND_EN=1','-DMISTER_CPU_PHASE_CHECK=1','-DMISTER_ALU_PIPE_CHECK=1',
             '-I'+str(target),
             '-Wno-fatal','-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND','-Wno-TIMESCALEMOD',
             '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
             '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17 -O3','-LDFLAGS','-static-libstdc++ -static-libgcc',
             *map(str,files),str(target/'native.cpp')]
    run(command,'build.log')
    command=[str(target/'obj/VBT_NATIVE_SIM.exe'),str(target/'main.bin'),str(target/'audio.bin'),
             str(target/'samples.bin'),str(target/'frames'),str(a.frames)]
    if a.input_journal:
        shutil.copyfile(a.input_journal.resolve(),target/'inputs.txt')
        command.append(str(target/'inputs.txt'))
    print('native_snapshot='+str(target),flush=True)
    run(command,'run.log')
    exit_code=0
except (RuntimeError,OSError) as error:
    print(error)
    exit_code=1
finally:
    receipt={'scope':'native game-board CPU execution with functional external DDR/RAM adapters; '
                     'not complete MiSTer platform or whole-frame MAME equivalence',
             'snapshot':str(target),'sources':sources,'commands':commands,
             'rom_sha256':hashlib.sha256(a.rom.read_bytes()).hexdigest(),
             'requested_frames':a.frames,'exit_code':exit_code,
             'input_journal':({'path':str(a.input_journal.resolve()),
                               'sha256':hashlib.sha256((target/'inputs.txt').read_bytes()).hexdigest()}
                              if a.input_journal and (target/'inputs.txt').exists() else None),
             'adaptations':['DSP MIF converted to readmemh hexadecimal',
                            'actual VHDL T80 converted with GHDL; explicit entity binding syntax',
                            'external DDR latency/backpressure model; zero-initialized NVRAM',
                            'graphics RAM adapters shared with qualified component regression']}
    retained=root/'tests/graphics/evidence/native'/target.name
    retained.mkdir(parents=True,exist_ok=True)
    (retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
    for name in ('build.log','run.log','ghdl-analyze.log','ghdl-synth.log','inputs.txt'):
        if (target/name).exists():shutil.copyfile(target/name,retained/name)
    shutil.copyfile(target/'mc_launch_scope.json',retained/'mc_launch_scope.json')
    if (target/'frames').exists():shutil.copytree(target/'frames',retained/'frames')
    if (target/'frames-pre').exists():shutil.copytree(target/'frames-pre',retained/'frames-pre')
    print('receipt='+str(retained/'receipt.json'))
    if (target/'run.log').exists():print((target/'run.log').read_text(errors='replace')[-2400:])
sys.exit(exit_code)
