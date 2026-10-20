"""Replay an already compiled, source-bound native checkpoint into a fresh run."""
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
p.add_argument('snapshot',type=Path)
p.add_argument('--frames',type=int,default=1800)
p.add_argument('--input-journal',type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
source=a.snapshot.resolve()
original=root/'tests/graphics/evidence/native'/source.name/'receipt.json'
receipt=json.loads(original.read_text())
for name,digest in receipt['sources'].items():
    if hashlib.sha256((root/name).read_bytes()).hexdigest()!=digest:
        raise SystemExit('Native checkpoint differs from current source: '+name)
if receipt['exit_code']!=0:
    raise SystemExit('Native checkpoint must have compiled and booted successfully.')
target=Path('R:/Verilator/BT')/('native-play-'+uuid.uuid4().hex)
target.mkdir(parents=True)
command=[str(source/'obj/VBT_NATIVE_SIM.exe'),str(source/'main.bin'),str(source/'audio.bin'),
         str(source/'samples.bin'),str(target/'frames'),str(a.frames)]
if a.input_journal:
    shutil.copyfile(a.input_journal.resolve(),target/'inputs.txt')
    command.append(str(target/'inputs.txt'))
environment=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
                 VERILATOR_WORKSPACE=str(source),VERILATOR_RAM_WORKSPACE=str(source))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
print('native_run='+str(target),flush=True)
with (target/'run.log').open('w') as log:
    r=subprocess.run(command,cwd=source,env=environment,stdout=log,stderr=subprocess.STDOUT,
                     creationflags=flags)
receipt.update({'compiled_snapshot':str(source),'snapshot':str(target),
                'command':command,'requested_frames':a.frames,'exit_code':r.returncode})
receipt['compiled_receipt_sha256']=hashlib.sha256(original.read_bytes()).hexdigest()
receipt['input_journal']=({'path':str(a.input_journal.resolve()),
                          'sha256':hashlib.sha256((target/'inputs.txt').read_bytes()).hexdigest()}
                         if a.input_journal else None)
retained=root/'tests/graphics/evidence/native'/target.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'receipt.json').write_text(json.dumps(receipt,indent=2))
shutil.copyfile(target/'run.log',retained/'run.log')
if (target/'inputs.txt').exists():shutil.copyfile(target/'inputs.txt',retained/'inputs.txt')
if (target/'frames').exists():shutil.copytree(target/'frames',retained/'frames')
if (target/'frames-pre').exists():shutil.copytree(target/'frames-pre',retained/'frames-pre')
print((target/'run.log').read_text(errors='replace')[-2400:])
print('receipt='+str(retained/'receipt.json'))
sys.exit(r.returncode)
