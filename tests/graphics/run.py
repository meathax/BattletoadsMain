"""Focused graphics proof using the exact pinned MAME row function as oracle."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import struct
import sys
import uuid

ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--mame-source',type=Path,required=True)
    p.add_argument('--verilator',default='verilator.exe')
    p.add_argument('--baseline',action='store_true')
    p.add_argument('--configurations',type=Path)
    p.add_argument('--sprite-sources',type=Path)
    p.add_argument('--baseline-ref',default='ace68a15e944c2090651080a59502ae47ae31b44')
    a=p.parse_args()
    build=HERE/'build'/('before' if a.baseline else 'after-captured' if a.sprite_sources else 'after')
    build.mkdir(parents=True,exist_ok=True)
    source=a.mame_source.read_text(encoding='utf-8')
    begin=source.index('void btoads_state::render_sprite_row(')
    end=source.index('\n}',begin)+2
    fn=source[begin:end].replace('btoads_state::','MameRow::')
    header='''// MAME 0.289, BSD-3-Clause, copyright Aaron Giles.
// Exact render_sprite_row body, with only the class qualifier adapted.
#include <cstdint>
struct MameRow {
    uint32_t control=0, scale[8]{};
    uint32_t* m_sprite_control=&control;
    uint32_t* m_sprite_scale=scale;
    uint16_t m_sprite_source_offs=0, m_sprite_dest_offs=0;
    uint16_t m_misc_control=0;
    uint8_t* m_sprite_dest_base=nullptr;
    void render_sprite_row(uint16_t*,uint32_t);
};
'''+fn+'\n'
    (build/'mame_row.h').write_text(header,encoding='utf-8')
    configurations=[]
    if a.configurations:
        for line in a.configurations.read_text().splitlines():
            if not line.strip(): continue
            values=tuple(map(int,line.split()))
            if len(values)!=5: raise ValueError('expected source-scale destination-scale control shadow display-control')
            if values[0]>=256: raise ValueError('nonpositive source step is not a terminating MAME row configuration')
            configurations.append(values)
    config_header='static const std::vector<std::array<unsigned,5>> gameplay_configurations = {\n'
    config_header+=''.join('{'+','.join(map(str,v))+'},\n' for v in configurations)+'};\n'
    (build/'gameplay_configurations.h').write_text(config_header,encoding='utf-8')
    selected_row=None
    captured_source=[0]*512
    if a.sprite_sources:
        blocks=a.sprite_sources.read_bytes()
        if len(blocks)!=512*1024: raise ValueError('expected 512 captured 1024-byte source blocks')
        words=[struct.unpack('<512H',blocks[i*1024:(i+1)*1024]) for i in range(512)]
        selected_row=max(range(512),key=lambda i:len(set(words[i])))
        captured_source=list(words[selected_row])
        if not any(captured_source): raise ValueError('captured sprite memory is entirely zero')
    (build/'gameplay_source.h').write_text(
        'static constexpr bool has_captured_source = '+('true' if a.sprite_sources else 'false')+';\n'
        +'static const std::array<uint16_t,512> captured_source = {'
        +','.join(map(str,captured_source))+'};\n',encoding='utf-8')
    files=[HERE/'graphics_sim.sv',HERE/'ram_models.sv',ROOT/'rtl/BT.sv',
           ROOT/'rtl/bg_vram.sv',ROOT/'rtl/fg_vram.sv',ROOT/'rtl/spr_vram.sv']
    if a.baseline:
        originals=[]
        for f in files:
            if f.parent==ROOT/'rtl':
                data=subprocess.check_output(['git','--no-pager','show',f'{a.baseline_ref}:{f.relative_to(ROOT).as_posix()}'],cwd=ROOT)
                # Quartus historically accepts procedural output nets. Make
                # only their implicit variable kind explicit for strict SV;
                # preserve the original producer behavior in the baseline.
                if f.name in ('bg_vram.sv','fg_vram.sv','spr_vram.sv'):
                    data=data.replace(b'output [ 7: 0] SQ',b'output logic [ 7: 0] SQ')
                    data=data.replace(b'output [15: 0] SQ',b'output logic [15: 0] SQ')
                    data=data.replace(b'output         GRID',b'output logic   GRID')
                    data=data.replace(b'GRID <=',b'GRID =')
                original=build/f.name
                original.write_bytes(data)
                originals.append(original)
            elif f.name=='graphics_sim.sv':
                # The original core predates the independent foreground DDR
                # window. Adapt only the testbench's added interface pin.
                data=f.read_bytes().replace(b', .EFG(EFG)',b'')
                data=data.replace(b', .FG_DDR_Q(EQ)',b'')
                data=data.replace(b'    BT ',b'    assign EFG = 1\'b0;\n    BT ',1)
                original=build/f.name
                original.write_bytes(data)
                originals.append(original)
            elif f.name=='graphics_sim.sv':
                # The original core predates the independent foreground DDR
                # window. Adapt only the testbench's added interface pin.
                data=f.read_bytes().replace(b', .EFG(EFG)',b'')
                data=data.replace(b', .FG_DDR_Q(EQ)',b'')
                data=data.replace(b'    BT ',b'    assign EFG = 1\'b0;\n    BT ',1)
                original=build/f.name
                original.write_bytes(data)
                originals.append(original)
            else: originals.append(f)
        files=originals
    elif (ROOT/'rtl/sprite_blitter.sv').exists(): files.append(ROOT/'rtl/sprite_blitter.sv')
    bt_file=next(f for f in files if f.name=='BT.sv')
    bt_source=bt_file.read_bytes()
    mixer=bt_source.decode('utf-8')
    mixer=mixer[mixer.index('\tbit [ 7:0] PIX_OUT;'):mixer.index('\t//Misc/sound control')]
    mixer=mixer.replace('\tbit [ 7:0] PIX_OUT;','')
    (build/'mixer_probe.sv').write_text('''// Exact production compositor block, generated for exhaustive input checks.
module BT_MIXER_PROBE(input CLK,RST_N,VCE_DIV,HBL_N, input [15:0] DISP_CONTROL,
    input [7:0] FG0_SQ,FG1_SQ, input [15:0] BG0_SQ,BG1_SQ,
    input [2:0] BG_EN, output logic [7:0] PIX_OUT);
'''+mixer+'\nendmodule\n',encoding='utf-8')
    files.append(build/'mixer_probe.sv')
    workspace=Path('R:/Verilator/BT')/('graphics-'+uuid.uuid4().hex)
    obj=workspace/'obj'
    obj.mkdir(parents=True,exist_ok=True)
    # Keep the compiled source bytes immutable during concurrent repository work.
    snapshot=workspace/'src'
    original_files=files+[HERE/'check.cpp',build/'mame_row.h',
        build/'gameplay_configurations.h',build/'gameplay_source.h']
    frozen_files=[]
    source_hashes={}
    for f in original_files:
        data=bt_source if f==bt_file else f.read_bytes()
        relative=f.relative_to(ROOT)
        frozen=snapshot/relative
        frozen.parent.mkdir(parents=True,exist_ok=True)
        frozen.write_bytes(data)
        frozen_files.append(frozen)
        source_hashes[relative.as_posix()]=hashlib.sha256(data).hexdigest()
    frozen_build=snapshot/build.relative_to(ROOT)
    cmd=[a.verilator,'--cc','--exe','--build','--assert','--timing',
         '--threads','1','--x-initial','unique','--x-assign','unique','-j','4',
         '--top-module','BT_GRAPHICS_SIM','--Mdir',str(obj),
         '-MAKEFLAGS','CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
         '-Wno-PINMISSING','-Wno-WIDTHTRUNC','-Wno-WIDTHEXPAND',
         '-Wno-CASEINCOMPLETE','-Wno-TIMESCALEMOD','-CFLAGS',f'-I{frozen_build.as_posix()} -DVL_TIME_CONTEXT -std=c++17',
         '-LDFLAGS','-static-libstdc++ -static-libgcc',
         *map(str,frozen_files[:len(files)]),str(frozen_files[len(files)])]
    env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
             VERILATOR_WORKSPACE=str(workspace),VERILATOR_RAM_WORKSPACE=str(workspace))
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (build/'build.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(cmd,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                              creationflags=flags)
    if result.returncode:
        print((build/'build.log').read_text(encoding='utf-8')[-7000:])
        return result.returncode
    exe=obj/('VBT_GRAPHICS_SIM.exe' if os.name=='nt' else 'VBT_GRAPHICS_SIM')
    if not exe.exists(): raise RuntimeError('build returned success without expected executable')
    with (build/'run.log').open('w',encoding='utf-8') as log:
        result=subprocess.run([str(exe)]+(['--baseline'] if a.baseline else []),
                              cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                              creationflags=flags)
    print((build/'run.log').read_text(encoding='utf-8')[-2600:])
    receipt={'scope':'CPU-bus-stimulated production graphics; not whole-core equivalence',
             'mame_source':str(a.mame_source),'mame_source_sha256':sha(a.mame_source),
             'oracle_sha256':sha(build/'mame_row.h'),
              'sources':source_hashes,'source_snapshot':str(snapshot),
             'command':cmd,'executable_sha256':sha(exe),'exit_code':result.returncode,
              'run_log_sha256':sha(build/'run.log')}
    receipt['gameplay_configurations_sha256']=sha(a.configurations) if a.configurations else None
    receipt['gameplay_configurations_count']=len(configurations)
    receipt['sprite_sources_sha256']=sha(a.sprite_sources) if a.sprite_sources else None
    receipt['captured_sprite_row']=selected_row
    receipt['source_profile']='captured MAME gameplay row' if a.sprite_sources else 'xorshift32 seed 0x42f01937'
    (build/'receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    return result.returncode

if __name__=='__main__': sys.exit(main())
