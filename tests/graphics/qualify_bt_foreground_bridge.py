"""Source-bound live BT foreground return/ready regression; CPU bus stimulus."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[2]
workspace = Path('R:/Verilator/BT') / ('bt-fg-bridge-' + uuid.uuid4().hex)
sources = ['rtl/BT.sv', 'rtl/bg_vram.sv', 'rtl/fg_vram.sv', 'rtl/spr_vram.sv',
           'rtl/sprite_blitter.sv', 'tests/graphics/ram_models.sv',
           'tests/graphics/graphics_sim.sv', 'tests/bt_foreground_bridge_tb.sv',
           'tests/graphics/qualify_bt_foreground_bridge.py']
frozen, hashes = [], {}
for name in sources:
    data = (root / name).read_bytes()
    hashes[name] = hashlib.sha256(data).hexdigest()
    target = workspace / 'src' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    if name not in ('tests/graphics/graphics_sim.sv', 'tests/graphics/qualify_bt_foreground_bridge.py'):
        frozen.append(str(target))
# Reuse the unchanged graphics CPU bus-stimulus stub, without its wrapper.
stub = (root / 'tests/graphics/graphics_sim.sv').read_text()
stub = stub[stub.index('module TMS34020 ('):]
stub_path = workspace / 'cpu_stub.sv'
stub_path.write_text(stub)
frozen.append(str(stub_path))
obj = workspace / 'obj'
obj.mkdir()
command = ['D:/vibes/fpga/bin/verilator.exe', '--binary', '--assert', '--timing',
           '-j', '4', '--threads', '1', '--x-initial', 'unique', '--x-assign', 'unique',
           '--top-module', 'BT_GRAPHICS_SIM', '--Mdir', str(obj),
           '-MAKEFLAGS', 'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
           '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17', '-LDFLAGS', '-static-libstdc++ -static-libgcc',
           '-Wno-fatal', *frozen]
environment = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
                   VERILATOR_WORKSPACE=str(workspace), VERILATOR_RAM_WORKSPACE=str(workspace))
flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
with (workspace / 'build.log').open('w') as log:
    compile_result = subprocess.run(command, cwd=root, env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, creationflags=flags)
run_command = [str(obj / 'VBT_GRAPHICS_SIM.exe')]
run_exit = None
if compile_result.returncode == 0:
    with (workspace / 'run.log').open('w') as log:
        run_result = subprocess.run(run_command, cwd=root, env=environment, stdout=log,
                                    stderr=subprocess.STDOUT, creationflags=flags)
    run_exit = run_result.returncode
    print((workspace / 'run.log').read_text(errors='replace')[-1800:])
else:
    print((workspace / 'build.log').read_text(errors='replace')[-2200:])
exit_code = compile_result.returncode if compile_result.returncode else run_exit
receipt = {'scope': 'production BT selected-busy ready and raw foreground DDR bridge; CPU bus stimulus, not instruction/native frame equivalence',
           'snapshot': str(workspace), 'sources': hashes, 'command': command,
           'run_command': run_command, 'compile_exit_code': compile_result.returncode,
           'run_exit_code': run_exit, 'exit_code': exit_code,
           'testbench_passed': exit_code == 0}
(workspace / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
retained = root / 'tests/graphics/evidence/bt-fg-bridge' / workspace.name
retained.mkdir(parents=True, exist_ok=True)
for name in ('receipt.json', 'build.log', 'run.log'):
    source = workspace / name
    if source.exists():
        shutil.copyfile(source, retained / name)
print('receipt=' + str(retained / 'receipt.json'))
sys.exit(exit_code)
