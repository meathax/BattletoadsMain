"""Reuse a proven mapped netlist for constraint-only fitting; never assemble."""
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
p.add_argument('parent',type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
parent=a.parent.resolve()
manifest=json.loads((parent/'snapshot.json').read_text())
receipt=json.loads((parent/'receipt.json').read_text())
if receipt['exit_code'] != 0 or not (parent/'db').is_dir():
    raise SystemExit('Successful parent map/fit snapshot required.')
allowed={'rtl/bt_ddr_phase.sdc'}
changed=[]
for name,digest in manifest.items():
    if name=='build_id.v': continue
    source=root/name
    if not source.is_file(): raise SystemExit('Missing source: '+name)
    if hashlib.sha256(source.read_bytes()).hexdigest()!=digest:
        changed.append(name)
if not set(changed).issubset(allowed):
    raise SystemExit('Netlist or other settings changed; use synthesize.py: '+', '.join(changed))
if not changed: raise SystemExit('No constraint-only changes to fit.')
target=Path('D:/vibes/fpga/temp')/('bt-graphics-'+uuid.uuid4().hex)
shutil.copytree(root,target,ignore=shutil.ignore_patterns('.git','tests','docs','build',
    '.pytest_cache','__pycache__','output_files','db','incremental_db'))
shutil.copyfile(parent/'build_id.v',target/'build_id.v')
new_manifest={str(f.relative_to(target)):hashlib.sha256(f.read_bytes()).hexdigest()
              for f in target.rglob('*') if f.is_file()}
# New/untracked synthesis sources also invalidate reuse.
extra=set(new_manifest)-set(manifest)
if extra: raise SystemExit('Source inventory changed; full map required: '+', '.join(sorted(extra)))
(target/'snapshot.json').write_text(json.dumps(new_manifest,indent=2))
for name in ('db','incremental_db'):
    if (parent/name).is_dir(): shutil.copytree(parent/name,target/name)
(target/'output_files').mkdir()
for source in (parent/'output_files').glob('Arcade-Battletoads.map.*'):
    shutil.copyfile(source,target/'output_files'/source.name)
print('snapshot='+str(target),flush=True)
commands=[['D:/vibes/fpga/bin/quartus-safe.cmd',tool,'Arcade-Battletoads']
          for tool in ('quartus_fit','quartus_sta')]
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
executed=[]
with (target/'compile.log').open('w') as log:
    for command in commands:
        executed.append(command)
        result=subprocess.run(command,cwd=target,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        if result.returncode: break
proof={'source_snapshot':str(target),'sources':new_manifest,'commands':executed,
       'rbf_requested':False,'exit_code':result.returncode,
       'reused_map_parent':str(parent),'reused_map_manifest_sha256':hashlib.sha256((parent/'snapshot.json').read_bytes()).hexdigest(),
       'constraint_only_changes':changed}
(target/'receipt.json').write_text(json.dumps(proof,indent=2))
retained=root/'tests/graphics/evidence/quartus'/target.name
retained.mkdir(parents=True,exist_ok=True)
for name in ('receipt.json','compile.log'): shutil.copyfile(target/name,retained/name)
for source in (target/'output_files').glob('*'):
    if source.suffix in ('.rpt','.summary'):shutil.copyfile(source,retained/source.name)
print((target/'compile.log').read_text(errors='replace')[-2800:])
sys.exit(result.returncode)
