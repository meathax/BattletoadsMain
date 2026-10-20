"""Qualify a same-edge BG port-A address register against immutable b537.

Checks actual original/candidate BG RTL, every RAM input before each capture,
the complete line cache and video state, both coincident clock phases, and
four intermediate CPU clock phases. RAM geometry/modes remain untouched.
The byte-memory adapter is behavioral evidence; Intel qualification is separate.
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

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
ORACLE = 'b53726397822b9dbebb02d36411294056fd08649'
VERILATOR = Path('D:/vibes/fpga/bin/verilator.exe')
COMPILER = Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe')

BENCH = r'''`timescale 1ns/1ps
module bt_bg_port_address_tb;
  bit CLK=0, CPU_CLK=0, RST_N=0;
  bit [15:0] A=0, D=0;
  bit [14:0] CPU_A=0;
  bit RAS_N=1, WE_N=1, OE_N=1, TRANSFER=0, SC=0, SE_N=0;
  bit [1:0] CAS_N=3;
  wire [15:0] Q, QR;
  wire [7:0] SQ, SQR;
  wire RDY, RDYR, GRID, GRIDR;
  integer phase=0;
  integer comparisons=0, consuming_writes=0, resets=0, refreshes=0;
  integer segment_writes[16][2];
  integer masks[4];
  bit [31:0] rng=32'h487194ab;
  BG_VRAM candidate(.CLK(CLK),.CPU_CLK(CPU_CLK),.RST_N(RST_N),.A(A),.CPU_A(CPU_A),.D(D),.Q(Q),
    .RAS_N(RAS_N),.CAS_N(CAS_N),.WE_N(WE_N),.OE_N(OE_N),.TRANSFER(TRANSFER),.RDY(RDY),
    .SC(SC),.SE_N(SE_N),.SQ(SQ),.GRID(GRID));
  BG_VRAM_REFERENCE reference(.CLK(CLK),.CPU_CLK(CPU_CLK),.RST_N(RST_N),.A(A),.CPU_A(CPU_A),.D(D),.Q(QR),
    .RAS_N(RAS_N),.CAS_N(CAS_N),.WE_N(WE_N),.OE_N(OE_N),.TRANSFER(TRANSFER),.RDY(RDYR),
    .SC(SC),.SE_N(SE_N),.SQ(SQR),.GRID(GRIDR));
  always #5 CLK=~CLK;
  initial begin
    if(!$value$plusargs("phase=%d",phase)) phase=0;
    #(5+phase);
    forever begin CPU_CLK=1;#10;CPU_CLK=0;#10;end
  end
  // These are the actual compiled wrapper pins, checked before the RAM edge.
  // Address/data identity is unconditional, including inactive/zero-mask writes.
  task automatic pins;
    assert({candidate.mem.ADDR,candidate.mem.DATA,candidate.mem.WREN,candidate.mem.BE,
            candidate.mem.SADDR,candidate.mem.SDATA,candidate.mem.SWREN} ===
           {reference.mem.ADDR,reference.mem.DATA,reference.mem.WREN,reference.mem.BE,
            reference.mem.SADDR,reference.mem.SDATA,reference.mem.SWREN})
      else $fatal(1,"BG RAM capture pins differ phase=%0d time=%0t pending=%0b addr=%h/%h",
        phase,$time,reference.WRITE_PENDING,candidate.mem.ADDR,reference.mem.ADDR);
  endtask
  task automatic state;
    assert({Q,SQ,RDY,GRID} === {QR,SQR,RDYR,GRIDR})
      else $fatal(1,"BG interface differs phase=%0d time=%0t",phase,$time);
    assert({candidate.SREG_ROW,candidate.SREG_COL,candidate.MRT_EXEC,candidate.RMT_EXEC,
            candidate.COPY_NEXT,candidate.COPY_WADDR,candidate.COPY_RUN,candidate.COPY_VALID,
            candidate.COPY_VALID2,candidate.COPY_WADDR2,candidate.RAM_SQ_R,candidate.LINE_CACHE_RA,
            candidate.VIDEO_WORD,candidate.VIDEO_LANE,candidate.VIDEO_LANE_OH,
            candidate.WRITE_ADDR,candidate.WRITE_DATA,candidate.WRITE_BE,candidate.WRITE_TOGGLE,
            candidate.WRITE_TOGGLE_M,candidate.WRITE_SEEN,candidate.CPU_RST_N} ===
           {reference.SREG_ROW,reference.SREG_COL,reference.MRT_EXEC,reference.RMT_EXEC,
            reference.COPY_NEXT,reference.COPY_WADDR,reference.COPY_RUN,reference.COPY_VALID,
            reference.COPY_VALID2,reference.COPY_WADDR2,reference.RAM_SQ_R,reference.LINE_CACHE_RA,
            reference.VIDEO_WORD,reference.VIDEO_LANE,reference.VIDEO_LANE_OH,
            reference.WRITE_ADDR,reference.WRITE_DATA,reference.WRITE_BE,reference.WRITE_TOGGLE,
            reference.WRITE_TOGGLE_M,reference.WRITE_SEEN,reference.CPU_RST_N})
      else $fatal(1,"BG internal state differs phase=%0d time=%0t",phase,$time);
    for(integer i=0;i<32;i++)
      assert(candidate.LINE_CACHE[i] === reference.LINE_CACHE[i])
        else $fatal(1,"BG line cache differs phase=%0d word=%0d",phase,i);
  endtask
  always @(posedge CLK) begin
    pins();
    comparisons++;
    if(reference.mem.WREN) begin
      masks[reference.mem.BE]++;
      if(|reference.mem.BE) consuming_writes++;
      for(integer lane=0;lane<2;lane++)
        if(reference.mem.BE[lane]) segment_writes[reference.mem.ADDR[15:12]][lane]++;
    end
    #0.001;state();pins();
  end
  always @(posedge CPU_CLK) begin #0.002;state();pins();end
  always @(negedge CLK) begin #0.001;state();pins();end
  initial begin
    for(integer s=0;s<16;s++) for(integer l=0;l<2;l++) segment_writes[s][l]=0;
    for(integer m=0;m<4;m++) masks[m]=0;
    repeat(4) @(negedge CPU_CLK);
    RST_N=1;
    // Fill all ordinary addresses with independent masks; interleave serial
    // refresh/scan, stopped write strobes and resets at active pending windows.
    for(integer n=0;n<147456;n++) begin
      @(negedge CPU_CLK);
      rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
      CPU_A=n<131072 ? 15'(n>>2) : rng[14:0];
      D=rng[31:16]^16'(n);
      CAS_N=~2'(n>>2);
      RAS_N=0;OE_N=1;WE_N=(n%4!=0);TRANSFER=0;
      if(n%64==10 || n%64==11) begin
        A=16'(n*37)^rng[15:0];TRANSFER=1;OE_N=0;WE_N=1;
        if(n%64==10) refreshes++;
      end else if(n%64==9 || n%64==12) RAS_N=1;
      if(n%4==0) SC=~SC;
      if(n>=131072) begin
        if(n%257==13) begin RST_N=0;resets++;end
        if(n%257==17) RST_N=1;
        if(n%29<4) begin RAS_N=1;WE_N=1;end
        if(n%71<6) begin WE_N=0;OE_N=1;end
      end
    end
    @(negedge CPU_CLK);RST_N=1;RAS_N=1;WE_N=1;OE_N=1;TRANSFER=0;
    repeat(32) @(negedge CPU_CLK);
    assert(comparisons>290000 && consuming_writes>20000 && resets>60 && refreshes>2000)
      else $fatal(1,"BG workload coverage incomplete");
    for(integer s=0;s<16;s++) for(integer l=0;l<2;l++)
      assert(segment_writes[s][l]>400) else $fatal(1,"missing BG physical segment/lane coverage %0d/%0d",s,l);
    for(integer m=0;m<4;m++) assert(masks[m]>2000) else $fatal(1,"missing BG mask %0d",m);
    $display("PASS BG same-edge address: phase=%0d comparisons=%0d writes=%0d resets=%0d refreshes=%0d; all 16 segments/two lanes/four masks, actual RAM capture pins, complete line-cache/video state",phase,comparisons,consuming_writes,resets,refreshes);
    $finish;
  end
endmodule
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path,
        default=ROOT / 'build' / 'bg_port_address_b537_v1')
    args = parser.parse_args()
    private = args.private_root.resolve()
    if not private.is_relative_to((ROOT / 'build').resolve()) or private == (ROOT / 'build').resolve():
        raise ValueError('private-root must be a child of build')
    if private.exists():
        raise ValueError('refusing to overwrite retained candidate')
    hashes = {'helper:qualify_bg_port_address.py': sha(Path(__file__).read_bytes())}
    inputs = {}
    for name in ('rtl/bg_vram.sv','rtl/BT_mem.sv','tests/graphics/ram_models.sv'):
        data = (ROOT / name).read_bytes()
        oracle = subprocess.check_output(['git','show',ORACLE+':'+name],cwd=ROOT)
        if data.replace(b'\r\n',b'\n') != oracle.replace(b'\r\n',b'\n'):
            raise ValueError('root differs from immutable oracle: '+name)
        inputs[name] = data
        hashes['root:'+name] = sha(data)
        hashes['oracle:'+name] = sha(oracle)
    old = inputs['rtl/bg_vram.sv'].decode('utf-8').replace('\r\n','\n')
    sentinel = '\twire WRITE_PENDING = WRITE_TOGGLE_M != WRITE_SEEN;'
    if old.count(sentinel)!=1 or old.count('.ADDR(WRITE_PENDING ? WRITE_ADDR : CPU_A_M)')!=1:
        raise ValueError('BG address source contract differs')
    new = old.replace(sentinel, sentinel+'\n'
        '\t// Capture the address the ordinary RAM mux selects after this edge.\n'
        '\t// A qualified CPU write is already stable before its pending window.\n'
        '\t// Reset selects the same newly captured CPU read address.\n'
        '\t(* preserve, maxfan = 16 *) bit [14:0] RAM_ADDR_M;\n'
        '\talways @(posedge CLK) begin\n'
        '\t\tif (!RST_N) RAM_ADDR_M <= CPU_A;\n'
        '\t\telse RAM_ADDR_M <= (WRITE_TOGGLE != WRITE_TOGGLE_M) ? WRITE_ADDR : CPU_A;\n'
        '\tend',1)
    new = new.replace('.ADDR(WRITE_PENDING ? WRITE_ADDR : CPU_A_M)', '.ADDR(RAM_ADDR_M)',1)
    candidate = private/'candidate/rtl/bg_vram.sv'
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(new.replace('\n','\r\n').encode('utf-8'))
    hashes['candidate:rtl/bg_vram.sv'] = sha(candidate.read_bytes())
    workspace = Path('R:/Verilator/BT')/('bg-port-address-'+uuid.uuid4().hex)
    workspace.mkdir(parents=True)
    (workspace/'bg_vram.sv').write_bytes(candidate.read_bytes())
    (workspace/'bg_vram_reference.sv').write_text(old.replace('module BG_VRAM (','module BG_VRAM_REFERENCE (',1))
    (workspace/'ram_models.sv').write_bytes(inputs['tests/graphics/ram_models.sv'])
    (workspace/'bt_bg_port_address_tb.sv').write_text(BENCH)
    hashes['fixture:bt_bg_port_address_tb.sv'] = sha((workspace/'bt_bg_port_address_tb.sv').read_bytes())
    hashes['fixture:bg_vram_reference.sv'] = sha((workspace/'bg_vram_reference.sv').read_bytes())
    command = [str(VERILATOR),'--binary','--assert','--timing','-j','4','--threads','1',
        '--x-initial','unique','--x-assign','unique','--top-module','bt_bg_port_address_tb',
        '--Mdir',str(workspace/'obj'),'-Wno-fatal',
        '-MAKEFLAGS',f'CXX={COMPILER.as_posix()} LINK={COMPILER.as_posix()}',
        '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',
        str(workspace/'bg_vram.sv'),str(workspace/'bg_vram_reference.sv'),
        str(workspace/'ram_models.sv'),str(workspace/'bt_bg_port_address_tb.sv')]
    env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
        VERILATOR_WORKSPACE=str(workspace),VERILATOR_RAM_WORKSPACE=str(workspace))
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with (workspace/'build.log').open('w') as log:
        compiled=subprocess.run(command,cwd=workspace,env=env,creationflags=flags,
            stdout=log,stderr=subprocess.STDOUT)
    results=[]
    if compiled.returncode==0:
        for phase in (0,1,4,5,6,9):
            logpath=workspace/('phase_'+str(phase)+'.log')
            with logpath.open('w') as log:
                result=subprocess.run([str(workspace/'obj/Vbt_bg_port_address_tb.exe'),
                    '+phase='+str(phase)],cwd=workspace,env=env,creationflags=flags,
                    stdout=log,stderr=subprocess.STDOUT)
            text=logpath.read_text(errors='replace')
            passed=result.returncode==0 and 'PASS BG same-edge address:' in text and '%Error' not in text
            results.append({'phase':phase,'exit_code':result.returncode,'passed':passed,'log_sha256':sha(logpath.read_bytes())})
            print(text[-1600:],flush=True)
            if not passed: break
    else:
        print((workspace/'build.log').read_text(errors='replace')[-6000:],flush=True)
    receipt={'oracle_ref':ORACLE,'candidate_path':str(candidate),'sources':hashes,
        'compile_exit_code':compiled.returncode,'command':command,'results':results,
        'all_passed':compiled.returncode==0 and len(results)==6 and all(r['passed'] for r in results),
        'scope':'same-edge BG ordinary-port address including coincident/offset 2:1 CPU/MEM clocks, all RAM pins at consuming and settled edges, full video/line-cache/controller state, reset/refresh/write/read/held-strobe/mask/segment/lane coverage; actual BT_mem unchanged; behavioral RAM adapter does not qualify Intel unknown collision masks or physical timing'}
    (workspace/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    for path in workspace.glob('*.sv'):
        shutil.copyfile(path,private/path.name)
    for path in workspace.glob('*.log'):
        shutil.copyfile(path,private/path.name)
    shutil.copyfile(workspace/'receipt.json',private/'receipt.json')
    print('candidate='+str(candidate)+' sha256='+hashes['candidate:rtl/bg_vram.sv'])
    print('receipt='+str(private/'receipt.json'))
    return 0 if receipt['all_passed'] else 1


if __name__=='__main__':
    sys.exit(main())
