"""Exhaustively compare the actual BT sprite RAS expression with immutable RTL.

Extract both expressions from source, compile them as SystemVerilog, and check
every controlling address bit and RAS value before and after the original
memory-clock capture. This qualifies the Boolean factor, not physical timing.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ROOT = Path(__file__).resolve().parents[2]
BASELINE_REF = '6b66897664bda6cace6da60752fe57f5dc4f3e76'
VERILATOR = Path('D:/vibes/fpga/bin/verilator.exe')
COMPILER = Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe')


def sprite_ras(source):
    instance = source.index('SPR_VRAM SPR_VRAM (')
    start = source.index('.RAS_N(', instance) + len('.RAS_N(')
    depth = 1
    end = start
    while depth:
        depth += (source[end] == '(') - (source[end] == ')')
        end += 1
    return source[start:end-1]


def main():
    original = subprocess.check_output(['git', 'show', f'{BASELINE_REF}:rtl/BT.sv'], cwd=ROOT)
    candidate = (ROOT/'rtl/BT.sv').read_bytes()
    sources = {'baseline:rtl/BT.sv': hashlib.sha256(original).hexdigest(),
        'rtl/BT.sv': hashlib.sha256(candidate).hexdigest(),
        'helper:'+Path(__file__).name: hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    old_text = original.decode('utf-8')
    new_text = candidate.decode('utf-8')
    old_select = re.search(r'\bwire\s+SPR_SEL\s*=\s*(.*?);', old_text, re.S).group(1)
    new_select = re.search(r'\bwire\s+SPR_SERIAL_SEL\s*=\s*(.*?);', new_text, re.S).group(1)
    old_ras = sprite_ras(old_text)
    new_ras = sprite_ras(new_text)
    name = 'item4-sprite-ras-'+uuid.uuid4().hex
    workspace = Path('R:/Verilator/BT')/name
    workspace.mkdir(parents=True)
    retained = ROOT/'build'/name
    retained.mkdir(parents=True)
    (workspace/'baseline-BT.sv').write_bytes(original)
    (workspace/'candidate-BT.sv').write_bytes(candidate)
    shutil.copyfile(__file__, workspace/Path(__file__).name)
    top = 'item4_sprite_ras_tb'
    tb = workspace/(top+'.sv')
    tb.write_text('''`timescale 1ns/1ps
module item4_sprite_ras_tb;
  logic CLK=0, RAS_N=1;
  logic [31:0] LA=0;
  bit original_capture=1, candidate_capture=1;
  integer checks=0;
  wire SPR_SEL = '''+old_select+''';
  wire SPR_SERIAL_SEL = '''+new_select+''';
  wire original_ras = '''+old_ras+''';
  wire candidate_ras = '''+new_ras+''';
  always #3 CLK=~CLK;
  always @(posedge CLK) begin
    original_capture <= original_ras;
    candidate_capture <= candidate_ras;
  end
  initial begin
    assert(original_capture==1 && candidate_capture==1) else $fatal(1,"initial RAS changed");
    for(integer region=0;region<512;region++)
      for(integer nibble=0;nibble<16;nibble++)
        for(integer ras=0;ras<2;ras++) begin
          @(negedge CLK);
          LA={9'(region),19'((region*271+nibble*13)&19'h7ffff),4'(nibble)};
          RAS_N=1'(ras);#0.1;
          assert(original_ras===candidate_ras) else $fatal(1,"RAS decode changed LA=%h ras=%b",LA,RAS_N);
          @(posedge CLK);#0.1;
          assert(original_capture===candidate_capture && candidate_capture===candidate_ras)
            else $fatal(1,"RAS capture changed edge LA=%h ras=%b",LA,RAS_N);
          checks++;
        end
    assert(checks==16384) else $fatal(1,"missing exhaustive cases");
    $display("PASS sprite RAS source-bound equivalence: %0d cases; all 9 region bits, 4 low bits, both RAS values, same memory-clock capture",checks);
    $finish;
  end
endmodule
''')
    command = [str(VERILATOR), '--binary', '--assert', '--timing', '-j', '4', '--threads', '1',
        '--x-initial', 'unique', '--x-assign', 'unique', '--top-module', top,
        '--Mdir', str(workspace/'obj'), '-Wno-fatal',
        '-MAKEFLAGS', f'CXX={COMPILER.as_posix()} LINK={COMPILER.as_posix()}',
        '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17', '-LDFLAGS', '-static-libstdc++ -static-libgcc', str(tb)]
    env = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
        VERILATOR_WORKSPACE=str(workspace), VERILATOR_RAM_WORKSPACE=str(workspace))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (workspace/'build.log').open('w') as log:
        result = subprocess.run(command, cwd=workspace, env=env, stdout=log,
            stderr=subprocess.STDOUT, creationflags=flags)
    if result.returncode == 0:
        with (workspace/'run.log').open('w') as log:
            result = subprocess.run([str(workspace/'obj'/('V'+top+'.exe'))], cwd=workspace,
                env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    receipt = {'baseline_ref': BASELINE_REF, 'snapshot': str(workspace), 'sources': sources,
        'extracted': {'baseline_select': old_select, 'candidate_select': new_select,
            'baseline_ras': old_ras, 'candidate_ras': new_ras}, 'command': command,
        'exit_code': result.returncode, 'all_passed': result.returncode == 0,
        'scope': 'Boolean source-bound exhaustive sprite serial RAS decode and original capture edge; no timing/full-core/hardware qualification'}
    (workspace/'receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    for filename in ('receipt.json', 'build.log', 'run.log', Path(__file__).name, tb.name):
        path = workspace/filename
        if path.exists():
            shutil.copyfile(path, retained/filename)
    log = workspace/('run.log' if (workspace/'run.log').exists() else 'build.log')
    print(log.read_text(errors='replace')[-2500:])
    print('receipt='+str(retained/'receipt.json'))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
