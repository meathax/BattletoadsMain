import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

p=argparse.ArgumentParser()
p.add_argument('--mame',type=Path,required=True)
p.add_argument('--rompath',type=Path,required=True)
a=p.parse_args()
here=Path(__file__).resolve().parent
d=here/'evidence'/('mame-'+uuid.uuid4().hex)
d.mkdir(parents=True)
lua=d/'capture_mame.lua'
lua.write_bytes((here/'capture_mame.lua').read_bytes())
args=[str(a.mame),'btoads','-rompath',str(a.rompath),'-noreadconfig',
      '-video','none','-sound','none','-nothrottle','-frameskip','0','-skip_gameinfo',
      '-autoboot_script',str(lua),'-autoboot_delay','0',
      '-snapshot_directory',str(d),'-cfg_directory',str(d/'cfg'),
      '-nvram_directory',str(d/'nvram'),'-seconds_to_run','45']
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (d/'rom-audit.log').open('w') as log:
    audit=subprocess.run([str(a.mame),'btoads','-rompath',str(a.rompath),'-verifyroms'],
        cwd=d,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if audit.returncode: raise RuntimeError('ROM verification failed: '+str(d/'rom-audit.log'))
with (d/'mame.log').open('w') as log:
    result=subprocess.run(args,cwd=d,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
coverage=d/'coverage.txt'
receipt={'scope':'diagnostic MAME reference coverage; no paired RTL execution',
         'argv':args,'exit_code':result.returncode,
         'mame_sha256':hashlib.sha256(a.mame.read_bytes()).hexdigest(),
         'lua_sha256':hashlib.sha256(lua.read_bytes()).hexdigest(),
         'rom_sha256':hashlib.sha256((a.rompath/'btoads.zip').read_bytes()).hexdigest()}
receipt['artifacts']={f.name:hashlib.sha256(f.read_bytes()).hexdigest()
    for f in sorted(d.iterdir()) if f.is_file() and f.suffix in ('.png','.txt','.log','.bin')}
(d/'receipt.json').write_text(json.dumps(receipt,indent=2))
print('capture='+str(d))
print(coverage.read_text() if coverage.exists() else (d/'mame.log').read_text()[-2000:])
sys.exit(result.returncode if coverage.exists() else 2)
