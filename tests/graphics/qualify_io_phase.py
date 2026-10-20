"""Qualify phase-dependent I/O constraints against the shipping RTL."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

parser=argparse.ArgumentParser()
parser.add_argument('case',choices=['audio','sdram','cpu_fields','ddr_tags','cpu_opcodes'])
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
top={'audio':'hdmi_audio_phase_tb','sdram':'sdram_phase_tb','cpu_fields':'cpu_field_timing_tb','ddr_tags':'ddr_tag_compare_tb','cpu_opcodes':'cpu_opcode_equivalence_tb'}[args.case]
names=(['sys/audio_out.sv','sys/i2s.v','sys/spdif.v','sys/sigma_delta_dac.v',
        'sys/iir_filter.v','tests/hdmi_audio_phase_tb.sv'] if args.case=='audio'
       else ['rtl/sdram.sv','tests/sdram_phase_tb.sv'] if args.case=='sdram'
       else ['rtl/bt_ddr_tag_compare.sv','tests/ddr_tag_compare_ref.sv','tests/ddr_tag_compare_tb.sv'] if args.case=='ddr_tags'
       else ['rtl/TMS34020/TMS34020_PKG.sv','rtl/TMS34020/TMS34020_ID.sv','tests/cpu_opcode_equivalence_tb.sv'] if args.case=='cpu_opcodes'
       else ['tests/cpu_field_timing_tb.sv'])
target=Path('R:/Verilator/BT')/('io-'+args.case+'-'+uuid.uuid4().hex)
target.mkdir(parents=True)
hashes={}
files=[]
for name in names:
    source=root/name
    destination=target/source.name
    shutil.copyfile(source,destination)
    files.append(str(destination))
    hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
if args.case=='audio':
    hashes['rtl/bt_audio_io.sdc']=hashlib.sha256((root/'rtl/bt_audio_io.sdc').read_bytes()).hexdigest()
if args.case=='cpu_fields':
    reference_root=Path('D:/vibes/fpga/temp/bt-graphics-42e58efb450d4e86865a6c946ad6b709')
    functions=[]
    for prefix,folder in [('candidate',root),('reference',reference_root)]:
        for name,function in [('rtl/TMS34020/TMS34020_MC.sv','FastDataWriteBE'),
                              ('rtl/TMS34020/TMS34020_pkg.sv','Ext')]:
            source=folder/name
            key=name if prefix=='candidate' else str(source)
            hashes[key]=hashlib.sha256(source.read_bytes()).hexdigest()
            pattern=r'^[ \t]*function[^\n]*\b'+function+r'\s*\(.*?\bendfunction'
            match=re.search(pattern,source.read_text(),re.M|re.S)
            if not match:raise RuntimeError('Missing helper: '+str(source)+':'+function)
            functions.append(re.sub(r'\b'+function+r'\b',prefix+'_'+function,match.group(0)))
    (target/'field_functions.svh').write_text('\n\n'.join(functions))
if args.case=='cpu_opcodes':
    from predecode_opcode import BASE, ID, expected_files
    expected, details=expected_files()
    for name, text in expected.items():
        # The decoder/package are generated artifacts. The CPU and SDC have
        # independently qualified bus/cache/phase changes and are not outputs
        # of this decoder-equivalence proof. Bind them, and require their
        # production identity assertions, rather than reverting those changes.
        if name in (ID, 'rtl/TMS34020/TMS34020_PKG.sv') and (root/name).read_text()!=text:
            raise RuntimeError('Generated opcode predecode is stale: '+name)
        hashes[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    cpu=(root/'rtl/TMS34020/TMS34020.sv').read_text()
    for identity in ('assert (IC_MATCHES == DecodeICMatches(IC))',
                     'assert (IC_RF_ADDR == DecodeICRFAddress(IC,STATE,0) && IC_RF_ADDR_POS == DecodeICRFAddress(IC,STATE,1))',
                     'assert (IC_RS_STATIC == DecodeICRS(IC))'):
        if identity not in cpu:
            raise RuntimeError('Shipping CPU opcode identity assertion missing: '+identity)
    hashes['tests/graphics/predecode_opcode.py']=hashlib.sha256((root/'tests/graphics/predecode_opcode.py').read_bytes()).hexdigest()
    hashes[str(BASE/ID)]=hashlib.sha256((BASE/ID).read_bytes()).hexdigest()
    reference=target/'TMS34020_ID_REFERENCE.sv'
    reference.write_text((BASE/ID).read_text().replace('module TMS34020_ID','module TMS34020_ID_REFERENCE',1))
    files.append(str(reference))
if args.case=='sdram':
    for name in ('rtl/pll.v','rtl/pll/pll_0002.v','rtl/bt_sdram_io.sdc'):
        hashes[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    assert '.phase_shift2("8750 ps")' in (root/'rtl/pll/pll_0002.v').read_text(), \
        'Update the test receive clock when the shipping PLL phase changes.'
    reference=Path('D:/vibes/fpga/temp/bt-graphics-ddd2ebf5c0f8409db96253dd3b5f1263/rtl/sdram.sv')
    hashes[str(reference)]=hashlib.sha256(reference.read_bytes()).hexdigest()
    saved=target/'legacy_sdram.sv'
    saved.write_text(reference.read_text().replace('module sdram','module legacy_sdram',1))
    files.append(str(saved))
    late_reference=Path('D:/vibes/fpga/temp/bt-graphics-c036dac59690474faff563209eafc766/rtl/sdram.sv')
    hashes[str(late_reference)]=hashlib.sha256(late_reference.read_bytes()).hexdigest()
    late=target/'late_sdram.sv'
    late.write_text(late_reference.read_text().replace('module sdram','module late_sdram',1))
    files.append(str(late))
command=['D:/vibes/fpga/bin/verilator.exe','--binary','--assert','--timing','-j','4',
    '--threads','1','--top-module',top,'--Mdir',str(target/'obj'),
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
        result=subprocess.run([str(target/('obj/V'+top+'.exe'))],cwd=target,
            env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
scope=('48/96 kHz serializer phase and rate changes after reset settling' if args.case=='audio'
       else 'SDRAM CL2 read windows, all banks, byte/word writes, cache hits and original completion cycles' if args.case=='sdram'
       else 'CPU field helpers against frozen original functions, all field sizes/byte offsets/operations/sign positions' if args.case=='cpu_fields'
       else 'Factored DDR tag comparison versus complete address mapping, all region priorities and address alternatives' if args.case=='ddr_tags'
       else 'Complete generated instruction decoder equivalence for all opcodes, all states, three condition profiles; shipping CPU identity ownership is checked by the separately required native run')
receipt={'snapshot':str(target),'sources':hashes,'command':command,
         'exit_code':result.returncode,'scope':scope}
retained=root/'tests/graphics/evidence/io-phase'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
for name in ('build.log','run.log'):
    if (target/name).exists():shutil.copyfile(target/name,retained/name)
print((target/('run.log' if (target/'run.log').exists() else 'build.log')).read_text(errors='replace')[-1800:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(result.returncode)
