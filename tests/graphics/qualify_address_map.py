"""Compare the shipping DDR bank decoder with the original priority mapping."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import uuid

root = Path(__file__).resolve().parents[2]
source = (root / 'Arcade-Battletoads.sv').read_bytes()
text = source.decode()
fragment = text.split('// BEGIN DDR_BANK_MAP', 1)[1].split('// END DDR_BANK_MAP', 1)[0]
target = Path('R:/Verilator/BT') / ('address-map-' + uuid.uuid4().hex)
target.mkdir(parents=True)
bench = '''`timescale 1ns/1ps
module address_map_tb;
bit BT_ERAM, BT_EFG, BT_ENVRAM, BT_ESPR, BT_EROM;
bit [22:0] BT_EADDR;
''' + fragment + '''
function automatic bit [27:0] original_map(input bit [4:0] banks, input bit [22:0] address);
    return banks[4] ? {7'b0000100,address[20:0]} :
           banks[3] ? {7'b0010000,address[20:0]} :
           banks[2] ? {7'b0001000,address[20:0]} :
           banks[1] ? {7'b0001100,address[20:0]} :
           banks[0] ? {5'b00000,address} : 28'b0;
endfunction
integer checks=0;
initial begin
    for(integer banks=0;banks<32;banks++) begin
        {BT_ERAM,BT_EFG,BT_ENVRAM,BT_ESPR,BT_EROM}=5'(banks);
        for(integer high=0;high<4;high++) begin
            for(integer pattern=0;pattern<32;pattern++) begin
                BT_EADDR[22:21]=2'(high);
                BT_EADDR[20:0]=pattern<21 ? 21'(1<<pattern) :
                                 pattern==30 ? 21'h1fffff :
                                 pattern==31 ? 21'b0 : 21'($urandom);
                #1;
                if(ddr_addr!==original_map(5'(banks),BT_EADDR))
                    $fatal(1,"DDR map mismatch banks=%h input=%h got=%h expected=%h",
                           banks,BT_EADDR,ddr_addr,original_map(5'(banks),BT_EADDR));
                checks++;
            end
        end
    end
    $display("PASS DDR bank address map: %0d checks, all 32 bank combinations",checks);
    $finish;
end
endmodule
'''
test = target / 'address_map_tb.sv'
test.write_text(bench)
command = ['D:/vibes/fpga/bin/verilator.exe', '--binary', '--assert', '--timing', '-j', '4',
           '--threads', '1', '--x-initial', 'unique', '--x-assign', 'unique',
           '--top-module', 'address_map_tb', '--Mdir', str(target / 'obj'),
           '-Wno-WIDTHTRUNC', '-Wno-WIDTHEXPAND',
           '-MAKEFLAGS', 'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
           '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17 -O3',
           '-LDFLAGS', '-static-libstdc++ -static-libgcc', str(test)]
environment = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
                   VERILATOR_WORKSPACE=str(target), VERILATOR_RAM_WORKSPACE=str(target))
flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
with (target / 'build.log').open('w') as log:
    result = subprocess.run(command, cwd=target, env=environment, stdout=log,
                            stderr=subprocess.STDOUT, creationflags=flags)
if result.returncode == 0:
    with (target / 'run.log').open('w') as log:
        result = subprocess.run([str(target / 'obj/Vaddress_map_tb.exe')], cwd=target,
                                env=environment, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=flags)
receipt = {'scope': 'shipping DDR decoder vs original bank priority, all flag combinations',
           'snapshot': str(target), 'sources': {'Arcade-Battletoads.sv': hashlib.sha256(source).hexdigest()},
           'fragment_sha256': hashlib.sha256(fragment.encode()).hexdigest(),
           'test_sha256': hashlib.sha256(bench.encode()).hexdigest(),
           'command': command, 'exit_code': result.returncode}
retained = root / 'tests/graphics/evidence/address-map' / target.name
retained.mkdir(parents=True)
(retained / 'receipt.json').write_text(json.dumps(receipt, indent=2))
for name in ('build.log', 'run.log'):
    if (target / name).exists():
        shutil.copyfile(target / name, retained / name)
log_name = 'run.log' if (target / 'run.log').exists() else 'build.log'
print((target / log_name).read_text(errors='replace')[-2000:])
print('receipt=' + str(retained / 'receipt.json'))
sys.exit(result.returncode)
