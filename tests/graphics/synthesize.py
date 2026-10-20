import hashlib
from datetime import datetime
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
import argparse

root=Path(__file__).resolve().parents[2]
parser=argparse.ArgumentParser(description='Frozen map/fit/STA only; never assembles an RBF.')
parser.add_argument('--source-overlay',type=Path,
                    help='Explicit hash-bound private RTL candidates to copy into the snapshot.')
parser.add_argument('--validate-overlay',action='store_true',
                    help='Validate all private candidates and current baselines without running Quartus.')
args=parser.parse_args()
overlay=None
overlay_bytes={}
if args.source_overlay:
    overlay=json.loads(args.source_overlay.read_text(encoding='utf-8'))
    if overlay.get('schema')!=1 or not isinstance(overlay.get('files'),dict) or not overlay['files']:
        raise ValueError('Unsupported or empty source overlay')
    for key,entry in overlay['files'].items():
        relative=Path(key)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0]!='rtl' or relative.suffix!='.sv':
            raise ValueError('Overlay is restricted to existing relative RTL .sv inputs: '+key)
        baseline=(root/relative).read_bytes()
        candidate=Path(entry['path']).resolve()
        if not candidate.is_relative_to((root/'build').resolve()):
            raise ValueError('Private source must be retained under this project build directory')
        data=candidate.read_bytes()
        if hashlib.sha256(baseline).hexdigest()!=entry['baseline_sha256']:
            raise ValueError('Current baseline changed: '+key)
        if hashlib.sha256(data).hexdigest()!=entry['sha256']:
            raise ValueError('Frozen private source changed: '+key)
        overlay_bytes[key]=data
if args.validate_overlay:
    if overlay is None: parser.error('--validate-overlay requires --source-overlay')
    print(json.dumps({'validated':True,'files':list(overlay_bytes),'quartus_run':False}))
    sys.exit(0)
target=Path('D:/vibes/fpga/temp')/('bt-graphics-'+uuid.uuid4().hex)
shutil.copytree(root,target,ignore=shutil.ignore_patterns('.git','tests','docs','build','.pytest_cache',
    '__pycache__','output_files','db','incremental_db'))
for key,data in overlay_bytes.items():
    (target/key).write_bytes(data)
# Standalone quartus_map does not run sys/build_id.tcl's pre-flow hook.
# Reproduce its BUILD_DATE header without invoking a flow or assembler.
(target/'build_id.v').write_text('`define BUILD_DATE "'+datetime.now().strftime('%y%m%d')+'"')
manifest={str(f.relative_to(target)):hashlib.sha256(f.read_bytes()).hexdigest()
          for f in target.rglob('*') if f.is_file()}
(target/'snapshot.json').write_text(json.dumps(manifest,indent=2))
if overlay is not None:
    # Provenance is receipt metadata, not an additional synthesis input.
    (target/'source_overlay.json').write_text(json.dumps(overlay,indent=2))
print('snapshot='+str(target), flush=True)
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
commands=[['D:/vibes/fpga/bin/quartus-safe.cmd',tool,'Arcade-Battletoads']
          for tool in ('quartus_map','quartus_fit','quartus_sta')]
with (target/'compile.log').open('w') as log:
    executed=[]
    for cmd in commands:
        print('stage='+cmd[1], flush=True)
        executed.append(cmd)
        result=subprocess.run(cmd,cwd=target,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
        if result.returncode: break
receipt={'source_snapshot':str(target),'sources':manifest,'commands':executed,'rbf_requested':False,
          'exit_code':result.returncode}
if overlay is not None:
    receipt['source_overlay']=overlay
(target/'receipt.json').write_text(json.dumps(receipt,indent=2))
retained=root/'tests/graphics/evidence/quartus'/target.name
retained.mkdir(parents=True,exist_ok=True)
shutil.copyfile(target/'receipt.json',retained/'receipt.json')
shutil.copyfile(target/'compile.log',retained/'compile.log')
for f in (target/'output_files').glob('*'):
    if f.suffix in ('.rpt','.summary'): shutil.copyfile(f,retained/f.name)
print('snapshot='+str(target))
print((target/'compile.log').read_text(errors='replace')[-3000:])
sys.exit(result.returncode)
