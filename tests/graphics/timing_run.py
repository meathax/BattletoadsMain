"""Retain an all-corner timing audit without invoking the assembler."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

parser=argparse.ArgumentParser()
parser.add_argument('snapshot',type=Path)
parser.add_argument('--extra-sdc',type=Path,
                    help='Provisional constraints for diagnosis; never eligible for RBF assembly.')
args=parser.parse_args()
root=Path(__file__).resolve().parents[2]
snapshot=args.snapshot.resolve()
summary=snapshot/'output_files/Arcade-Battletoads.fit.summary'
if not summary.exists() or 'Fitter Status : Successful' not in summary.read_text():
    raise SystemExit('A successfully fitted snapshot is required.')
script=root/'tests/graphics/timing_audit.tcl'
command=['D:/vibes/fpga/bin/quartus-safe.cmd','quartus_sta','-t',str(script),'Arcade-Battletoads']
hashes={str(script):hashlib.sha256(script.read_bytes()).hexdigest()}
project_sha=hashlib.sha256((snapshot/'Arcade-Battletoads.qsf').read_bytes()).hexdigest()
if args.extra_sdc:
    path=args.extra_sdc.resolve()
    command.append(str(path))
    hashes[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (snapshot/'timing_audit.log').open('w') as log:
    result=subprocess.run(command,cwd=snapshot,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
receipt={'snapshot':str(snapshot),'command':command,'audit_sources':hashes,
         'fitted_project_sha256':project_sha,
         'provisional_constraints':bool(args.extra_sdc),'exit_code':result.returncode,
         'assembled':False}
(snapshot/'timing_receipt.json').write_text(json.dumps(receipt,indent=2))
retained=root/'tests/graphics/evidence/quartus'/snapshot.name
retained.mkdir(parents=True,exist_ok=True)
for name in ('timing_receipt.json','timing_audit.log'):
    shutil.copyfile(snapshot/name,retained/name)
shutil.copytree(snapshot/'timing_audit',retained/'timing_audit',dirs_exist_ok=True)
print((snapshot/'timing_audit.log').read_text(errors='replace')[-2200:])
print('receipt='+str(retained/'timing_receipt.json'))
sys.exit(result.returncode)
