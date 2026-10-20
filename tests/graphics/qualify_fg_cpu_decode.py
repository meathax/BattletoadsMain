"""Source-bound BT foreground decode and actual MC-to-memory capture proof.

The oracle is immutable. All controlling address, code, display-bank and RAS
bits are exhausted; actual production MC traffic then uses the extracted CPU
bus wiring and foreground capture code. This does not qualify routed timing.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import uuid


ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / '.git').exists() and (p / 'rtl/BT.sv').is_file())
BASELINE_REF = '8f048ee518f3062506e80d5f5a64585450d062f5'
VERILATOR = Path('D:/vibes/fpga/bin/verilator.exe')
COMPILER = Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def port(source, instance, name):
    instance_name = instance.split()[1]
    match = re.search(r'\b' + instance_name + r'\s*\(', source)
    assert match is not None, 'missing actual BT instance: ' + instance_name
    start = source.index('.' + name + '(', match.end()) + len(name) + 2
    depth = 1
    end = start
    while depth:
        depth += (source[end] == '(') - (source[end] == ')')
        end += 1
    return source[start:end - 1]


def wire(source, name):
    match = re.search(r'\bwire\s*(?:\[[^\]]+\]\s*)?' + name + r'\s*=\s*(.*?);', source, re.S)
    if match is None:
        raise ValueError('missing actual BT wire: ' + name)
    return match.group(1)


def decode(source, module):
    names = ['FG_DISP_SEL', 'FG_DRAW_SEL', 'FG_DISP_SC', 'FG_DISP_SE_N',
             'FG_DRAW_SC', 'FG_DRAW_SE_N', 'FG0_SEL', 'FG0_SCRN', 'FG0_SC',
             'FG0_SE_N', 'FG1_SEL', 'FG1_SCRN', 'FG1_SC', 'FG1_SE_N']
    if re.search(r'\bwire\s+FG_CPU_ADDR_MATCH\s*=', source):
        names.insert(0, 'FG_CPU_ADDR_MATCH')
    expressions = {name: wire(source, name) for name in names}
    expressions['FG_A'] = wire(source, 'FG_A')
    text = f'''module {module}(input [31:0] LA, BIT_ADDR,
      input [15:0] DISP_CONTROL, input RAS_N, SC,
      output [1:0] ras, transfer, selected, scan, serial_enable,
      output [17:0] address, output shift);
'''
    for name in names:
        text += '  wire ' + name + ' = ' + expressions[name] + ';\n'
    text += '  wire [17:0] FG_A = ' + expressions['FG_A'] + ';\n'
    for bank in range(2):
        instance = f'FG_VRAM FG{bank}_VRAM ('
        for name, output in [('RAS_N', 'ras'), ('TRANSFER', 'transfer')]:
            value = port(source, instance, name)
            expressions[f'FG{bank}.{name}'] = value
            text += f'  assign {output}[{bank}] = {value};\n'
        for name, output in [('SEL', 'selected'), ('SC', 'scan'), ('SE_N', 'serial_enable')]:
            text += f'  assign {output}[{bank}] = FG{bank}_{name};\n'
    shift = port(source, 'FG_VRAM FG0_VRAM (', 'CPU_SHIFT')
    assert shift == port(source, 'FG_VRAM FG1_VRAM (', 'CPU_SHIFT')
    expressions['CPU_SHIFT'] = shift
    text += '  assign shift = ' + shift + ';\n  assign address = FG_A;\nendmodule\n'
    return text, expressions


def prepare(candidate_dir, original):
    current = (ROOT / 'rtl/BT.sv').read_bytes()
    assert current.replace(b'\r\n', b'\n') == original.replace(b'\r\n', b'\n'), 'BT source changed beyond immutable oracle'
    text = current.decode('utf-8').replace('\r\n', '\n')
    old0 = "wire FG0_SEL = DISP_CONTROL[15] ? FG_DISP_SEL : FG_DRAW_SEL;"
    new0 = '''// The display/draw regions differ only in address bit 26. Decode the
\t// common class before routing it to the selected physical foreground bank.
\twire FG_CPU_ADDR_MATCH = LA[3:0] == 4'b0101 ?
\t\t(LA[31:27] & 5'b10111) == 5'b10100 :
\t\tLA[31:27] == 5'b10100 && LA[25:22] == 4'b0000;
\twire FG0_SEL = FG_CPU_ADDR_MATCH && (LA[26] ^ DISP_CONTROL[15]);'''
    old1 = "wire FG1_SEL = DISP_CONTROL[15] ? FG_DRAW_SEL : FG_DISP_SEL;"
    new1 = "wire FG1_SEL = FG_CPU_ADDR_MATCH && !(LA[26] ^ DISP_CONTROL[15]);"
    transfer0 = "(LA[3:0] == 4'b0101 && FG_DISP_SEL) || LA[3:0] == 4'b0100"
    transfer1 = "(LA[3:0] == 4'b0101 && (LA[31:26] & 6'b101111) == 6'b101000) || LA[3:0] == 4'b0100"
    assert text.count(old0) == text.count(old1) == 1
    assert text.count(transfer0) == 2
    text = text.replace(old0, new0).replace(old1, new1).replace(transfer0, transfer1)
    target = candidate_dir / 'rtl/BT.sv'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(text.encode('utf-8'))
    return target


TB = r'''
`timescale 1ns/1ps
module fg_cpu_decode_tb;
  bit SYSCLK=0, MEMCLK=1, reset_n=0, use_mc=0, enable=1;
  always #6.25 SYSCLK=~SYSCLK;
  always #3.125 MEMCLK=~MEMCLK;
  wire ce_f,ce_r,vce;
  bt_clock_enables phases(.clk(SYSCLK),.reset(!reset_n),.ce_f(ce_f),.ce_r(ce_r),.vce(vce));
  bit [31:0] addr=0,data=0,pc=0,bus_data=0,mask=0,screen_addr=0;
  bit [5:0] size=0,field0=0,field1=0;
  bit field_select=0,read_req=0,write_req=0,pixel=0,cache=0,vector_req=0,ready=0,screen_run=0,cst=0;
  wire [31:0] DBUS_A,DBUS_DO;
  wire [3:0] DBUS_CODE,DBUS_BE;
  wire DBUS_RAS,DBUS_RD,DBUS_WE,wait_cpu,rd_ext;
  TMS34020_MC mc(.CLK(SYSCLK),.RST_N(reset_n),.EN(enable),.CE_F(ce_f),.CE_R(ce_r),.RES_N(1'b1),
    .ADDR(addr),.DOUT(data),.DIN(),.DIN_F(),.FS(size),.FS0(field0),.FS1(field1),.FIELD_SELECT(field_select),
    .READ(read_req),.WRITE(write_req),.WRITE_PRE(write_req),.PIX(pixel),.PC(pc),.CACHE(cache),.CACHE_WR(),
    .VECT(vector_req),.WAIT(wait_cpu),.PIX_WMASK(mask),.SCRREF_ADDR(screen_addr),.SCRREF_RUN(screen_run),
    .DBUS_A(DBUS_A),.DBUS_DI(bus_data),.DBUS_DI_E(bus_data),.DBUS_DO(DBUS_DO),.DBUS_RAS(DBUS_RAS),
    .DBUS_WE(DBUS_WE),.DBUS_RD(DBUS_RD),.DBUS_RD_EXT(rd_ext),.DBUS_BE(DBUS_BE),.DBUS_CODE(DBUS_CODE),
    .DBUS_RDY(ready),.CST(cst),.DBUS_ANY_BE(),.DBUS_ANY_BE_FG());
  bit [31:0] manual_la=0;
  bit manual_ras=1;
  bit [15:0] DISP_CONTROL=0;
  bit SC=0;
  // These four expressions are copied from the actual production CPU wiring.
  wire [31:0] LA = use_mc ? (@LA@) : manual_la;
  wire [31:0] BIT_ADDR = use_mc ? (@BIT_ADDR@) : manual_la;
  wire RAS_N = use_mc ? (@RAS_N@) : manual_ras;
  wire WE_N = use_mc ? (@WE_N@) : 1'b1;
  wire QE_N = use_mc ? (@QE_N@) : 1'b1;
  wire [1:0] old_ras,new_ras,old_transfer,new_transfer,old_sel,new_sel,old_sc,new_sc,old_se,new_se;
  wire [17:0] old_a,new_a;
  wire old_shift,new_shift;
  original_decode original(.LA(LA),.BIT_ADDR(BIT_ADDR),.DISP_CONTROL(DISP_CONTROL),.RAS_N(RAS_N),.SC(SC),
    .ras(old_ras),.transfer(old_transfer),.selected(old_sel),.scan(old_sc),.serial_enable(old_se),.address(old_a),.shift(old_shift));
  candidate_decode candidate(.LA(LA),.BIT_ADDR(BIT_ADDR),.DISP_CONTROL(DISP_CONTROL),.RAS_N(RAS_N),.SC(SC),
    .ras(new_ras),.transfer(new_transfer),.selected(new_sel),.scan(new_sc),.serial_enable(new_se),.address(new_a),.shift(new_shift));
  wire [22:0] old_capture[2],new_capture[2];
  for(genvar b=0;b<2;b++) begin: bank
    qualified_fg_capture old_input(.CLK(MEMCLK),.A(old_a),.RAS_N(old_ras[b]),.OE_N(QE_N),.WE_N(WE_N),
      .SC(old_sc[b]),.SE_N(old_se[b]),.TRANSFER(old_transfer[b]),.CPU_SHIFT(old_shift),.capture(old_capture[b]));
    qualified_fg_capture new_input(.CLK(MEMCLK),.A(new_a),.RAS_N(new_ras[b]),.OE_N(QE_N),.WE_N(WE_N),
      .SC(new_sc[b]),.SE_N(new_se[b]),.TRANSFER(new_transfer[b]),.CPU_SHIFT(new_shift),.capture(new_capture[b]));
    BT_FG_VIDEO_ADDR_TRACK old_track(.CLK(MEMCLK),.RST_N(reset_n),.A_ROW(old_a[15:10]),
      .RAS_N(old_ras[b]),.OE_N(QE_N),.WE_N(WE_N),.TRANSFER(old_transfer[b]),.CPU_SHIFT(old_shift),.SE_N(old_se[b]),
      .MEM_CE(ce_r),.HOLE_RDY(ready),.CPU_CACHE_A(6'd0),.SADDR_V(),.COPY_MODE());
    BT_FG_VIDEO_ADDR_TRACK new_track(.CLK(MEMCLK),.RST_N(reset_n),.A_ROW(new_a[15:10]),
      .RAS_N(new_ras[b]),.OE_N(QE_N),.WE_N(WE_N),.TRANSFER(new_transfer[b]),.CPU_SHIFT(new_shift),.SE_N(new_se[b]),
      .MEM_CE(ce_r),.HOLE_RDY(ready),.CPU_CACHE_A(6'd0),.SADDR_V(),.COPY_MODE());
    always @(posedge MEMCLK) begin
      bit [22:0] expected;
      expected={old_ras[b],old_transfer[b],old_sc[b],old_se[b],old_shift,old_a};
      #0.001;
      assert(old_capture[b]===new_capture[b])
        else $fatal(1,"main FG capture changed bank=%0d LA=%h old/new=%h/%h",b,LA,old_capture[b],new_capture[b]);
      assert(old_capture[b]===expected)
        else $fatal(1,"capture oracle edge mismatch bank=%0d LA=%h captured/expected=%h/%h",b,LA,old_capture[b],expected);
      assert({old_track.ras_n,old_track.oe_n,old_track.we_n,old_track.transfer,old_track.cpu_shift,
              old_track.se_n,old_track.a_row,old_track.ras_old,old_track.mrt,old_track.rmt,old_track.copy_mode,
              old_track.ddr_state,old_track.pos,old_track.row,old_track.cache_a2,old_track.pair_pos}===
             {new_track.ras_n,new_track.oe_n,new_track.we_n,new_track.transfer,new_track.cpu_shift,
              new_track.se_n,new_track.a_row,new_track.ras_old,new_track.mrt,new_track.rmt,new_track.copy_mode,
              new_track.ddr_state,new_track.pos,new_track.row,new_track.cache_a2,new_track.pair_pos})
        else $fatal(1,"local video control/state changed bank=%0d LA=%h",b,LA);
    end
  end
  integer exhaustive_checks=0,capture_cycles=0,mc_capture_cycles=0,words=0,commands=0;
  integer code4_cycles=0,code5_cycles=0,codef_cycles=0,selected0_cycles=0,selected1_cycles=0,reset_cases=0;
  task automatic check_decode;
    assert({old_ras,old_transfer,old_sel,old_sc,old_se,old_a,old_shift}===
           {new_ras,new_transfer,new_sel,new_sc,new_se,new_a,new_shift})
      else $fatal(1,"BT foreground decode changed LA=%h DISP=%h RAS=%b",LA,DISP_CONTROL,RAS_N);
  endtask
  always @(posedge MEMCLK) begin
    check_decode();capture_cycles++;
    if(use_mc) begin
      mc_capture_cycles++;
      if(DBUS_CODE==4'h4)code4_cycles++;
      if(DBUS_CODE==4'h5)code5_cycles++;
      if(DBUS_CODE==4'hf)codef_cycles++;
      if(old_sel[0])selected0_cycles++;
      if(old_sel[1])selected1_cycles++;
    end
  end
  initial begin
    repeat(4)@(negedge MEMCLK);
    for(integer region=0;region<1024;region++)
      for(integer nibble=0;nibble<16;nibble++)
        for(integer bank_select=0;bank_select<2;bank_select++)
          for(integer ras=0;ras<2;ras++)begin
            @(negedge MEMCLK);
            manual_la={10'(region),18'((region*271+nibble*13)&18'h3ffff),4'(nibble)};
            DISP_CONTROL=bank_select?16'h8000:16'h0000;manual_ras=1'(ras);SC=1'(region);
            #0.01;check_decode();
            @(posedge MEMCLK);#0.01;
            exhaustive_checks++;
          end
    assert(exhaustive_checks==65536) else $fatal(1,"incomplete exhaustive source-bound cases");
    @(negedge SYSCLK);#0.01;use_mc=1;reset_n=1;reset_cases=1;
    for(integer i=0;i<65536;i++)begin
      @(negedge SYSCLK);#0.01;
      check_decode();ready=(i%13>=4);
      if(ce_r)bus_data=$urandom;
      enable=i>=16;
      screen_run=enable&&ce_r&&i%257==0;
      screen_addr=32'ha0000000|((i%2)<<26)|($urandom&32'h003ffff0);
      DISP_CONTROL=i%7<3?16'h8000:16'h0000;SC=1'(i%5);
      if(ce_f&&!wait_cpu&&enable)begin
        addr=words%4==3?$urandom:(32'ha0000000|((words%2)<<26)|($urandom&32'h003fffff));
        data=$urandom;pc=32'ha0000000|($urandom&32'h003ffff0);
        size=(words%32)+1;addr[4:0]=(words/32)%32;
        field_select=words%2;field0=field_select?6'($urandom):size;field1=field_select?size:6'($urandom);
        cache=words%7==0;read_req=!cache&&words%3==0;write_req=!cache&&words%3==1;
        pixel=!cache&&words%4==0;vector_req=read_req&&words%11==0;mask=$urandom;cst=words%5==0;words++;
      end
      if(ce_r&&ready&&(DBUS_RD||DBUS_WE))commands++;
    end
    @(negedge MEMCLK);#0.01;check_decode();
    assert(mc_capture_cycles>131000&&commands>1000&&code4_cycles>0&&code5_cycles>0&&codef_cycles>0
           &&selected0_cycles>0&&selected1_cycles>0&&reset_cases==1)
      else $fatal(1,"missing actual MC bridge coverage: captures=%0d commands=%0d code4/5/f=%0d/%0d/%0d bank0/1=%0d/%0d resets=%0d",
                  mc_capture_cycles,commands,code4_cycles,code5_cycles,codef_cycles,selected0_cycles,selected1_cycles,reset_cases);
    $display("PASS FG source-bound decode: %0d exhaustive cases; %0d memory capture cycles; actual MC %0d captures/%0d commands, code4/5/f=%0d/%0d/%0d, selected banks=%0d/%0d, resets=%0d",
             exhaustive_checks,capture_cycles,mc_capture_cycles,commands,code4_cycles,code5_cycles,codef_cycles,selected0_cycles,selected1_cycles,reset_cases);
    $finish;
  end
endmodule
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-dir', type=Path, default=ROOT)
    parser.add_argument('--prepare-private', action='store_true')
    args = parser.parse_args()
    original = subprocess.check_output(['git', 'show', f'{BASELINE_REF}:rtl/BT.sv'], cwd=ROOT)
    if args.prepare_private:
        private_dir = args.candidate_dir.resolve()
        assert (ROOT / 'build').resolve() in private_dir.parents, '--prepare-private requires an isolated candidate directory inside build/'
        target = prepare(args.candidate_dir, original)
        print(json.dumps({'candidate': str(target), 'sha256': sha(target.read_bytes())}))
    candidate = (args.candidate_dir / 'rtl/BT.sv').read_bytes()
    old_decode, old_expressions = decode(original.decode('utf-8'), 'original_decode')
    new_decode, new_expressions = decode(candidate.decode('utf-8'), 'candidate_decode')
    name = 'item4-fg-cpu-decode-' + uuid.uuid4().hex
    workspace = Path('R:/Verilator/BT') / name
    retained = ROOT / 'build' / name
    workspace.mkdir(parents=True)
    retained.mkdir(parents=True)
    sources = {'baseline:rtl/BT.sv': sha(original), 'candidate:rtl/BT.sv': sha(candidate),
               'helper:' + Path(__file__).name: sha(Path(__file__).read_bytes())}
    (workspace / 'baseline-BT.sv').write_bytes(original)
    (workspace / 'candidate-BT.sv').write_bytes(candidate)
    shutil.copyfile(__file__, workspace / Path(__file__).name)
    files = []
    for name in ['rtl/TMS34020/TMS34020_pkg.sv', 'rtl/TMS34020/TMS34020_MC.sv', 'rtl/bt_clock_enables.sv']:
        data = (ROOT / name).read_bytes()
        sources[name] = sha(data)
        target = workspace / Path(name).name
        target.write_bytes(data)
        files.append(str(target))
    fg_data = (ROOT / 'rtl/fg_vram.sv').read_bytes()
    cpu_data = (ROOT / 'rtl/TMS34020/TMS34020.sv').read_bytes()
    sources['rtl/fg_vram.sv'] = sha(fg_data)
    sources['rtl/TMS34020/TMS34020.sv'] = sha(cpu_data)
    fg = fg_data.decode('utf-8')
    cpu = cpu_data.decode('utf-8')
    capture_start = re.search(r'\bbit\s*\[17:\s*0\]\s+A_M;', fg).start()
    capture_end = fg.index('// CPU-clock copy of the VRAM reset:', capture_start)
    capture = fg[capture_start:capture_end]
    tracker_start = fg.index('module BT_FG_VIDEO_ADDR_TRACK (')
    tracker_end = fg.index('endmodule', tracker_start) + len('endmodule')
    tracker = fg[tracker_start:tracker_end]
    capture_module = '''module qualified_fg_capture(input CLK, input [17:0] A,
      input RAS_N, OE_N, WE_N, SC, SE_N, TRANSFER, CPU_SHIFT,
      output [22:0] capture);
      wire DRAW_WE=0; wire [7:0] SD=0,DRAW_DATA=0;
      wire [15:0] DRAW_BANK_WE=0,DRAW_RAM_BANK_WE=0;
      wire [16:0] DRAW_ADDR=0;
''' + capture + '''
      assign capture={RAS_N_M,TRANSFER_M,SC_M,SE_N_M,CPU_SHIFT_M,A_M};
    endmodule
'''
    bench = TB
    cpu_assigns = {}
    for name in ['LA', 'BIT_ADDR', 'RAS_N', 'WE_N', 'QE_N']:
        match = re.search(r'\bassign\s+' + name + r'\s*=\s*(.*?);', cpu, re.S)
        assert match is not None, 'missing actual CPU bus contract: ' + name
        cpu_assigns[name] = match.group(1)
        bench = bench.replace('@' + name + '@', match.group(1))
    assert not re.search(r'@[A-Z_]+@', bench)
    tb = workspace / 'fg_cpu_decode_tb.sv'
    tb.write_text('`timescale 1ns/1ps\n' + old_decode + new_decode + capture_module + tracker + bench)
    files.append(str(tb))
    command = [str(VERILATOR), '--binary', '--assert', '--timing', '-j', '4', '--threads', '1',
               '--x-initial', 'unique', '--x-assign', 'unique', '--top-module', 'fg_cpu_decode_tb',
               '--Mdir', str(workspace / 'obj'), '-Wno-fatal',
               '-MAKEFLAGS', f'CXX={COMPILER.as_posix()} LINK={COMPILER.as_posix()}',
               '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17', '-LDFLAGS', '-static-libstdc++ -static-libgcc', *files]
    env = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
               VERILATOR_WORKSPACE=str(workspace), VERILATOR_RAM_WORKSPACE=str(workspace))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    with (workspace / 'build.log').open('w') as log:
        result = subprocess.run(command, cwd=workspace, env=env, stdout=log,
                                stderr=subprocess.STDOUT, creationflags=flags)
    if result.returncode == 0:
        with (workspace / 'run.log').open('w') as log:
            result = subprocess.run([str(workspace / 'obj/Vfg_cpu_decode_tb.exe')], cwd=workspace,
                                    env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
    receipt = {'baseline_ref': BASELINE_REF, 'candidate_dir': str(args.candidate_dir),
               'snapshot': str(workspace), 'retained': str(retained), 'sources': sources,
               'extracted': {'baseline': old_expressions, 'candidate': new_expressions,
                             'cpu_bus': cpu_assigns, 'foreground_capture': capture, 'video_tracker': tracker},
               'command': command, 'exit_code': result.returncode, 'all_passed': result.returncode == 0,
               'scope': 'source-bound exhaustive FG bank/RAS/TRANSFER selection and exact original memory-edge capture, '
                        'plus actual shipping MC/package/clock-phase traffic through production CPU bus wiring and local '
                        'video capture/state; no routed timing/full-core/frame/hardware qualification'}
    (workspace / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    for filename in ['receipt.json', 'build.log', 'run.log', Path(__file__).name, tb.name]:
        path = workspace / filename
        if path.exists():
            shutil.copyfile(path, retained / filename)
    log = workspace / ('run.log' if (workspace / 'run.log').exists() else 'build.log')
    print(log.read_text(errors='replace')[-3500:])
    print('receipt=' + str(retained / 'receipt.json'))
    return result.returncode


if __name__ == '__main__':
    sys.exit(main())
