#!/usr/bin/env python3
"""Four-state Intel Quartus17 primitive proof in a private ModelSim library."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'tests'/'graphics'/'evidence'/'bt_ordinary_doubler'/'native_ram'
OUT.mkdir(parents=True,exist_ok=True)
BIN=Path('D:/q17/modelsim_ase/win32aloem')
VENDOR=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
rtl=(ROOT/'rtl'/'bt_scandoubler.sv').read_text(encoding='utf-8')
extract=OUT/'bt_sd_ram_extract.sv'
extract.write_text(rtl[rtl.index('module bt_sd_ram'):],encoding='utf-8')
commands=[
  [str(BIN/'vlib.exe'),'work'],
  [str(BIN/'vlog.exe'),'-work','work',str(VENDOR)],
  [str(BIN/'vlog.exe'),'-sv','-work','work','+define+BT_SD_NATIVE_PRIMITIVE',
   str(extract),str(ROOT/'tests'/'bt_ordinary_sd_native_ram.sv'),
   str(ROOT/'tests'/'bt_ordinary_sd_ram_tb.sv')],
  [str(BIN/'vsim.exe'),'-c','-lib','work','bt_ordinary_sd_ram_tb','-do',
   'onerror {quit -code 1 -f}; run -all; quit -code 0 -f']]
rc=1
for index,command in enumerate(commands):
  path=OUT/f'step_{index}.log'
  with path.open('w',encoding='utf-8') as log:
    result=subprocess.run(command,cwd=OUT,stdout=log,stderr=subprocess.STDOUT)
  rc=result.returncode
  print(path.read_text(encoding='utf-8',errors='replace')[-5000:])
  if rc:
    break
if not rc and 'PASS ordinary 24-bit RAM:' not in (OUT/'step_3.log').read_text(errors='replace'):
  rc=1
receipt={'exit_code':rc,'vendor_source':str(VENDOR),
         'vendor_sha256':hashlib.sha256(VENDOR.read_bytes()).hexdigest(),
         'source_sha256':{str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
                          for path in [ROOT/'rtl'/'bt_scandoubler.sv',
                                       ROOT/'tests'/'bt_ordinary_sd_native_ram.sv',
                                       ROOT/'tests'/'bt_ordinary_sd_ram_tb.sv',
                                       Path(__file__).resolve()]}}
(OUT/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
sys.exit(rc)
