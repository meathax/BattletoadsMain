"""TMS34020_IO raster sync contract (sync survives DPYCTL.ENV=0, totals wrap promptly).

usage: qualify_raster_sync.py [--io PATH]   (PATH defaults to rtl/TMS34020/TMS34020_IO.sv)
Pass --io with a baseline copy to run the negative control; the baseline must FAIL.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

parser = argparse.ArgumentParser()
parser.add_argument('--io', type=Path, default=None)
args = parser.parse_args()
root = Path(__file__).resolve().parents[2]
io_source = (args.io or root / 'rtl/TMS34020/TMS34020_IO.sv').resolve()
workspace = Path('R:/Verilator/BT') / ('raster-sync-' + uuid.uuid4().hex)
sources = {'pkg': root / 'rtl/TMS34020/TMS34020_pkg.sv', 'io': io_source,
           'tb': root / 'tests/raster_sync_tb.sv'}
frozen = []
hashes = {}
for key, source in sources.items():
    target = workspace / 'src' / source.name
    target.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    target.write_bytes(data)
    hashes[str(source)] = hashlib.sha256(data).hexdigest()
    frozen.append(str(target))
obj = workspace / 'obj'
obj.mkdir()
command = ['D:/vibes/fpga/bin/verilator.exe', '--binary', '--assert', '--timing', '-j', '4',
    '--threads', '1', '--x-initial', 'unique', '--x-assign', 'unique',
    '--top-module', 'raster_sync_tb', '--Mdir', str(obj),
    '-MAKEFLAGS', 'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
    '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17', '-LDFLAGS', '-static-libstdc++ -static-libgcc',
    '-Wno-PINMISSING', '-Wno-WIDTHTRUNC', '-Wno-WIDTHEXPAND', '-Wno-TIMESCALEMOD',
    '-Wno-CASEINCOMPLETE', '-Wno-UNOPTFLAT', '-Wno-MULTIDRIVEN', *frozen]
environment = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
    VERILATOR_WORKSPACE=str(workspace), VERILATOR_RAM_WORKSPACE=str(workspace))
flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
with (workspace / 'build.log').open('w') as log:
    result = subprocess.run(command, cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
if result.returncode:
    print((workspace / 'build.log').read_text(errors='replace')[-2300:])
else:
    with (workspace / 'run.log').open('w') as log:
        result = subprocess.run([str(obj / 'Vraster_sync_tb.exe')], cwd=root, env=environment,
            stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    print((workspace / 'run.log').read_text(errors='replace')[-2300:])
receipt = {'scope': 'TMS34020_IO raster sync contract; not native CPU/frame equivalence',
    'snapshot': str(workspace), 'sources': hashes, 'command': command, 'exit_code': result.returncode}
(workspace / 'receipt.json').write_text(json.dumps(receipt, indent=2))
retained = root / 'tests/graphics/evidence/raster-sync' / workspace.name
retained.mkdir(parents=True, exist_ok=True)
for name in ('receipt.json', 'build.log', 'run.log'):
    source = workspace / name
    if source.exists():
        shutil.copyfile(source, retained / name)
print('receipt=' + str(retained / 'receipt.json'))
sys.exit(result.returncode)
