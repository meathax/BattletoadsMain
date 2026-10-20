"""Compile actual old/new reset producers, synchronizer and MEM copies.

Complete top inverse identity establishes the attribute-only semantic edge;
this independent chronology model checks retained initialization, NBA capture,
the two SYS foreground synchronizer edges and old-reset MEM capture at coincident
80/160 MHz edges.  No claim that the fitter will honor a physical maxfan bound.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
sha = lambda data: hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def wrapper(name, producer):
    return '''module ''' + name + '''(
 input wire clk_sys, clk_mem, RESET,
 input wire [1:0] buttons, input wire [63:0] status,
 input wire rom_download,rom_ready,fg_ddr_ready,locked,
 output wire reset_o,reset_mem_o,clear_init_n_o,
 output wire [1:0] ready_sync_o);
''' + producer.decode() + '''
 assign reset_o=reset;
 assign reset_mem_o=reset_mem;
 assign clear_init_n_o=fg_ddr_clear_init_n;
 assign ready_sync_o=fg_ddr_ready_sys;
endmodule
'''


def bench(old, new):
    return '''`timescale 1ps/1ps
''' + wrapper('reset_original', old) + wrapper('reset_candidate', new) + '''
module reset_maxfan_tb;
 bit clk_sys=0,clk_mem=1;
 always #6250 clk_sys=~clk_sys;
 always #3125 clk_mem=~clk_mem;
 bit RESET=0,rom_download=0,rom_ready=1,fg_ddr_ready=1,locked=1;
 bit [1:0] buttons=0;
 bit [63:0] status=0;
 wire old_reset,old_mem,old_clear,new_reset,new_mem,new_clear;
 wire [1:0] old_ready,new_ready;
 reset_original original(.clk_sys(clk_sys),.clk_mem(clk_mem),.RESET(RESET),.buttons(buttons),.status(status),
 .rom_download(rom_download),.rom_ready(rom_ready),.fg_ddr_ready(fg_ddr_ready),.locked(locked),
 .reset_o(old_reset),.reset_mem_o(old_mem),.clear_init_n_o(old_clear),.ready_sync_o(old_ready));
 reset_candidate candidate(.clk_sys(clk_sys),.clk_mem(clk_mem),.RESET(RESET),.buttons(buttons),.status(status),
 .rom_download(rom_download),.rom_ready(rom_ready),.fg_ddr_ready(fg_ddr_ready),.locked(locked),
 .reset_o(new_reset),.reset_mem_o(new_mem),.clear_init_n_o(new_clear),.ready_sync_o(new_ready));
 bit model_reset=1,model_mem=1,model_clear=0;
 bit [1:0] model_ready=0;
 bit previous_reset=1;
 longint unsigned sys_edges=0,mem_edges=0,assertions=0,releases=0,held=0,coincident=0,off_edge_holds=0;
 bit [31:0] rng=32'h534e4142;
 integer n;
 always @(posedge clk_sys) begin
   if ((RESET|buttons[1]|status[0]|rom_download|~rom_ready|~model_ready[1]|~locked) && !model_reset) assertions++;
   if (!(RESET|buttons[1]|status[0]|rom_download|~rom_ready|~model_ready[1]|~locked) && model_reset) releases++;
   if (model_reset == (RESET|buttons[1]|status[0]|rom_download|~rom_ready|~model_ready[1]|~locked)) held++;
   model_ready <= {model_ready[0],fg_ddr_ready};
   model_reset <= RESET|buttons[1]|status[0]|rom_download|~rom_ready|~model_ready[1]|~locked;
   sys_edges++;
   if(clk_mem) coincident++;
   #1;
   if ({new_reset,new_ready} !== {model_reset,model_ready} || {old_reset,old_ready} !== {model_reset,model_ready})
     $fatal(1,"SYS old/new/init/NBA/synchronizer reset chronology changed");
 end
 always @(posedge clk_mem) begin
   model_mem <= model_reset;
   model_clear <= locked && rom_ready && !rom_download;
   mem_edges++;
   #1;
   if({new_mem,new_clear} !== {model_mem,model_clear} || {old_mem,old_clear} !== {model_mem,model_clear})
     $fatal(1,"MEM coincident old-reset copy/foreground-clear chronology changed");
 end
 task automatic drive(input bit [6:0] tuple,input integer delay_ps);
   @ (negedge clk_sys);
   previous_reset=new_reset;
   # (delay_ps);
   {fg_ddr_ready,locked,rom_ready,rom_download,status[0],buttons[1],RESET}=tuple;
   #1;
   if (new_reset !== previous_reset || old_reset !== previous_reset)
     $fatal(1,"registered reset changed from a raw input before its SYS edge");
   off_edge_holds++;
 endtask
 initial begin
   #1;
   if ({new_reset,new_ready,new_mem,new_clear} !== {1'b1,2'b00,1'b1,1'b0} ||
       {old_reset,old_ready,old_mem,old_clear} !== {1'b1,2'b00,1'b1,1'b0})
     $fatal(1,"power-up values differ");
   repeat(4) @(posedge clk_sys);
   // Seven reset contributors, including the real two-register foreground CDC.
   for(n=0;n<128;n++) begin
     drive(7'(n),(n%3)*1000);
     repeat(5) @(posedge clk_sys);
   end
   drive(7'b1111001,1000);
   repeat(257) @(posedge clk_sys);
   drive(7'b1110000,1000);
   repeat(257) @(posedge clk_sys);
   for(n=0;n<65536;n++) begin
     rng ^= rng<<13; rng ^= rng>>17; rng ^= rng<<5;
     status[63:1]=63'(rng);
     drive(rng[6:0],(n%3)*1000);
     @(posedge clk_sys);
   end
   drive(7'b1110000,1000);
   repeat(5) @(posedge clk_sys);
   #2;
   if(sys_edges<66000 || mem_edges<132000 || coincident<66000 || assertions<100 || releases<100 || held<50000 || off_edge_holds!=65667)
     $fatal(1,"missing reset/hold/clock chronology coverage");
   $display("PASS RESET_MAXFAN sys_edges=%0d mem_edges=%0d assertions=%0d releases=%0d held=%0d coincident=%0d off_edge_holds=%0d tuples=128 random_tuples=65536 init_checks=2",sys_edges,mem_edges,assertions,releases,held,coincident,off_edge_holds);
   $finish;
 end
endmodule
'''


def reject(name, operation, controls):
    try:
        operation()
    except (AssertionError, ValueError):
        controls.append({'name': name, 'rejected': True})
        return
    raise AssertionError('Negative control accepted: '+name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    edge, output = args.edge.resolve(), args.output.resolve()
    edge.relative_to(ROOT/'build'); output.relative_to(ROOT/'build')
    assert not output.exists()
    output.mkdir(parents=True)
    helper_path = ROOT/'tests/graphics/prepare_bt_reset_maxfan64.py'
    helper = load(helper_path,'reset_maxfan_preparer')
    manifest_path = edge/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['helper_sha256'] == sha(helper_path.read_bytes())
    old_path, new_path = edge/('oracle/'+helper.TOP), edge/('candidate/'+helper.TOP)
    old, new = old_path.read_bytes(), new_path.read_bytes()
    assert sha(old)==helper.PARENT_SHA and sha(new)==manifest['candidate_sha256']
    assert helper.transform(old)==new and helper.reverse(new)==old
    old_block, new_block = helper.producer(old), helper.producer(new)
    assert new_block.replace(helper.ATTRIBUTE,b'')==old_block
    assert sha(old_block)==manifest['old_producer_sha256'] and sha(new_block)==manifest['new_producer_sha256']
    controls=[]
    reject('foreign_full_top_parent',lambda:helper.transform(old+b'\n'),controls)
    reject('missing_attribute',lambda:helper.reverse(old),controls)
    reject('foreign_fanout_value',lambda:helper.reverse(new.replace(b'maxfan = 64',b'maxfan = 32',1)),controls)
    reject('changed_init',lambda:helper.reverse(new.replace(b"reg reset = 1'b1",b"reg reset = 1'b0",1)),controls)
    reject('changed_sys_clock',lambda:helper.reverse(new.replace(b'always @(posedge clk_sys) reset',b'always @(posedge clk_mem) reset',1)),controls)
    reject('changed_reset_cause',lambda:helper.reverse(new.replace(b'reset <= RESET |',b'reset <= !RESET |',1)),controls)
    reject('added_capture_gate',lambda:helper.reverse(new.replace(b'clk_sys) reset <=',b'clk_sys) if (locked) reset <=',1)),controls)
    reject('changed_mem_latency',lambda:helper.reverse(new.replace(b'reset_mem <= reset;',b'reset_mem <= RESET;',1)),controls)
    reject('unrelated_downstream_change',lambda:helper.reverse(new+b'// unrelated top edit\n'),controls)
    bench_path=output/'reset_maxfan_tb.sv'
    bench_path.write_text(bench(old_block,new_block))
    version_cmd=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','verilator','--version']
    version=subprocess.run(version_cmd,capture_output=True,text=True)
    (output/'version.log').write_text(version.stdout+version.stderr)
    assert version.returncode==0
    compile_cmd=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','verilator','--binary','--timing',
                 '--top-module','reset_maxfan_tb','-Wno-fatal','-j','2','--Mdir',output.relative_to(ROOT).as_posix()+'/obj',bench_path.relative_to(ROOT).as_posix()]
    compile_result=subprocess.run(compile_cmd,capture_output=True,text=True)
    (output/'compile.log').write_text(compile_result.stdout+compile_result.stderr)
    assert compile_result.returncode==0,('compile failed',str(output/'compile.log'))
    run_cmd=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','./'+output.relative_to(ROOT).as_posix()+'/obj/Vreset_maxfan_tb']
    result=subprocess.run(run_cmd,capture_output=True,text=True)
    (output/'run.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0,('reset chronology failed',str(output/'run.log'))
    marker=re.search(r'PASS RESET_MAXFAN sys_edges=(\d+) mem_edges=(\d+) assertions=(\d+) releases=(\d+) held=(\d+) coincident=(\d+) off_edge_holds=(\d+) tuples=128 random_tuples=65536 init_checks=2',result.stdout)
    assert marker
    counts=dict(zip(['sys_edges','mem_edges','assertions','releases','held','coincident','off_edge_holds'],map(int,marker.groups())))
    assert counts['sys_edges']>=66000 and counts['mem_edges']>=132000 and counts['coincident']>=66000
    assert counts['assertions']>=100 and counts['releases']>=100 and counts['held']>=50000 and counts['off_edge_holds']==65667
    paths=[manifest_path,old_path,new_path,edge/'evidence/v15-corner1-setup.txt',helper_path,Path(__file__),bench_path,output/'compile.log',output/'run.log',output/'version.log']
    receipt={'schema':'bt-reset-maxfan64-qualification-v1','status':'PASS','parent_sha256':helper.PARENT_SHA,
             'candidate_sha256':sha(new),'raw_full_top_inverse_identical':True,
             'attribute_only_infinite_trace_identity':True,'clock_periods_ps':{'clk_sys':12500,'clk_mem':6250},
             'producer_original_edges_initial_values_rhs_and_every_consumer_unchanged':True,
             'compiled_actual_original_and_candidate_producer_scopes':True,'independent_nba_chronology_model':True,
             'coverage':{**counts,'directed_input_tuples':128,'random_input_tuples':65536,'initial_scope_comparisons':2},
             'negative_controls':controls,'commands':{'version':version_cmd,'compile':compile_cmd,'run':run_cmd},
             'return_codes':{'version':version.returncode,'compile':compile_result.returncode,'run':result.returncode},
             'version':version.stdout.strip(),
             'artifacts':[{'path':str(path),'sha256':sha(path.read_bytes())} for path in paths],
             'timing_accepted':False,
             'limitations':['The HDL attribute requests synthesis fanout reduction; actual fitted clones/fanout/timing and all8 hold/setup still need exact-source fitting.',
                            'No new whole-board native/hardware run; functional applicability is the exact full-top attribute-only inverse, with actual reset/CDC/MEM chronology compiled separately.',
                            'Original four-state declaration and producer tokens are unchanged; compiled directed stimulus is two-state.']}
    receipt_path=output/'receipt.json'
    receipt_path.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':'PASS','receipt':str(receipt_path),'receipt_sha256':sha(receipt_path.read_bytes()),
                      'candidate_sha256':sha(new),'coverage':receipt['coverage'],'negative_controls':len(controls)},indent=2))


if __name__=='__main__':
    main()
