"""Source-bound v25 background regression and exact shipped LCELL proof.

This runner preserves the complete qualified background fixtures.  It neither
edits production inputs nor invokes Quartus.  Its verifier runs no simulation.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
PREPARER=ROOT/'tests/graphics/prepare_bt_bg_write_hold_lcell.py'
PREPARER_SHA='152bc1ba0113aef3bddd54e695d2b0ef5cd0e69b091e8592217598e4e1187f0d'
EDGE_SHA='7c9b256f9f5de10f28bb457ed88d6e9b6c9f14ccfeeb160a3fe50c5b14d63ed9'
OLD=ROOT/'tests/graphics/qualify_bt_bg_scroll_mem.py'
OLD_SHA='577d202b3aadc3bb2563b0562a5a94eed9a8349496a3626aeb06720476c83041'
OLD_EDGE=ROOT/'build/bg_scroll_mem_v23_v1/source-edge'
OLD_RECEIPT=ROOT/'build/bg_scroll_mem_v23_v1/proof-r2/receipt.json'
OLD_RECEIPT_SHA='0d19c3b65777402f600b4ef598e6a6cf57615b4acea80f01f48897f2cfd5af73'
SHIM=ROOT/'tests/graphics/native_lcell_run.py'
SHIM_SHA='16000e801a9ba952ee5da2406c559dbc87045370c21e991a7738adeeb448c28a'
VENDOR=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA='c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'
MODEL_SHA='481b1c8fc9326e98502b4cdafa921dbe9f17b061b498b80b4d602d52ec511b29'
SIM=Path('D:/q17/modelsim_ase/win32aloem')
SCHEMA='bt-v25-bg-write-hold-lcell-qualification-v1'
STATUS='PASS_ACTUAL_BG_AND_SHIPPED_LCELL'

FULL_DECL="""
  integer hold_pin_checks=0,hold_coincident=0,hold_offedge_resets=0;
  always @(posedge CLK) if(CPU_CLK===1'b1) hold_coincident=hold_coincident+1;
  always @(negedge RST_N)
    if(CLK===1'b0 && CPU_CLK===1'b0) hold_offedge_resets=hold_offedge_resets+1;
"""
FULL_CHECK="""
      if(new_i.RAM_WRITE_DATA !== old_i.WRITE_DATA ||
         off_i.RAM_WRITE_DATA !== off_i.WRITE_DATA)
        $fatal(1,"actual LCELL RAM data branch changed");
      hold_pin_checks=hold_pin_checks+2;
"""
FULL_MARKER="""
    $display("BG_HOLD_COMPLETE_PASS pin_checks=%0d coincident=%0d offedge_resets=%0d",
             hold_pin_checks,hold_coincident,hold_offedge_resets);
"""
CELL_BENCH=r"""
module bt_bg_hold_lcell_tb;
  logic [15:0] raw=0;
  wire [15:0] direct_data,cell_data,stage_data;
  assign direct_data=raw;
  bit [15:0] captured=0,old_mem=0,new_mem=0;
  logic SYS=0,MEM=0;
  integer truth_checks=0,known=0,xz=0,literals=0,phases=0,coincident=0;
  bt_bg_hold_branch raw_branch(raw,cell_data);
  bt_bg_hold_branch registered_branch(captured,stage_data);
  always @(posedge SYS) captured<=raw;
  always @(posedge MEM) begin old_mem<=captured;new_mem<=stage_data;end
  function automatic logic four(input integer value);
    case(value&3)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
  endfunction
  task automatic truth;
    if(cell_data !== direct_data || stage_data !== captured)
      $fatal(1,"shipped LCELL four-state branch mismatch");
    truth_checks=truth_checks+1;
  endtask
  task automatic memory_edge;
    bit[15:0] expected;
    begin
      expected=captured;MEM=1;#1;truth;
      if(old_mem !== new_mem || old_mem !== expected)
        $fatal(1,"LCELL added a memory capture edge");
      MEM=0;#1;phases=phases+1;
    end
  endtask
  integer i,b,k;
  bit[15:0] previous;
  initial begin
    #1;truth;
    if(captured!==0 || old_mem!==0 || new_mem!==0)
      $fatal(1,"unclocked startup changed");
    for(i=0;i<65536;i=i+1) begin raw=i;#1;truth;known=known+1;end
    for(i=0;i<65536;i=i+1) begin
      for(b=0;b<16;b=b+1) raw[b]=four(i>>(b%8));
      #1;truth;xz=xz+1;
    end
    for(b=0;b<16;b=b+1) for(k=0;k<4;k=k+1) begin
      raw=16'ha55a;raw[b]=four(k);#1;truth;literals=literals+1;
    end
    for(i=0;i<4096;i=i+1) begin
      for(b=0;b<16;b=b+1) raw[b]=four((i*13+b)>>(b%8));
      #1;truth;
      case(i&3)
        0:begin
          previous=captured;SYS=1;MEM=1;#1;truth;
          if(old_mem!==new_mem || old_mem!==previous)
            $fatal(1,"coincident SYS/MEM sample changed");
          SYS=0;MEM=0;#1;coincident=coincident+1;phases=phases+1;
        end
        1:begin SYS=1;#1;SYS=0;#1;memory_edge;end
        2:memory_edge;
        3:begin memory_edge;SYS=1;#1;SYS=0;#1;memory_edge;end
      endcase
    end
    $display("BG_HOLD_LCELL_PASS truth=%0d known=%0d xz=%0d literals=%0d phases=%0d coincident=%0d",
             truth_checks,known,xz,literals,phases,coincident);
    $finish;
  end
endmodule
"""

def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
    if not value:raise AssertionError(message)
def normal(value):return json.loads(json.dumps(value))
def record(path):
    path=Path(path).resolve()
    return dict(path=str(path),sha256=sha(path.read_bytes()),bytes=path.stat().st_size)
def load(path,name,digest):
    require(sha(Path(path).read_bytes())==digest,'frozen helper changed: '+str(path))
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m);return m
def canonical(data):return data.decode().replace('\r\n','\n')

def generated_inputs(edge):
    edge=Path(edge).resolve();require(sha((edge/'manifest.json').read_bytes())==EDGE_SHA,'hold source manifest changed')
    p=load(PREPARER,'bg_hold_source',PREPARER_SHA);before,after,manifest=p.verify_edge(edge)
    q=load(OLD,'bg_hold_frozen_full_regression',OLD_SHA)
    require(sha(OLD_RECEIPT.read_bytes())==OLD_RECEIPT_SHA,'qualified original BG receipt changed')
    inherited=q.verify_composition_receipt(OLD_RECEIPT)
    previous,unused,detail=q.generated_inputs(OLD_EDGE)
    require(previous['bg_vram.sv']==before,'actual v24 BG must be the qualified source parent')
    reference=re.sub(rb'\bBG_VRAM\b',b'BG_VRAM_REFERENCE',before)
    require(reference.replace(b'BG_VRAM_REFERENCE',b'BG_VRAM')==before,'old complete BG namespace inverse failed')
    bench=previous['bt_bg_scroll_full_tb.sv'].decode();edits=[]
    def edit(old,new):
        nonlocal bench
        require(bench.count(old)==1,'retained full BG fixture anchor changed')
        bench=bench.replace(old,new,1);edits.append(dict(old=old,new=new))
    edit('  BG_VRAM_REFERENCE old_i(CLK,CPU_CLK,RST_N,EFFECTIVE_A,',
         '  BG_VRAM_REFERENCE #(.MEM_SCROLL_ADDER(1)) old_i(CLK,CPU_CLK,RST_N,A,')
    edit('WE_N,OE_N,TRANSFER,old_rdy,SC,SE_N,old_sq,old_grid,old_nz,old_high);',
         'WE_N,OE_N,TRANSFER,old_rdy,SC,SE_N,old_sq,old_grid,old_nz,old_high,A,OFFSET,ADDRESS_TRANSFER);')
    edit('  integer stage_checks=0,extra_edges=0,raw_cases=0,offedge_resets=0;',
         '  integer stage_checks=0,extra_edges=0,raw_cases=0,offedge_resets=0;'+FULL_DECL)
    edit('      coerced=new_sq;','      coerced=new_sq;'+FULL_CHECK)
    edit('    $finish;',FULL_MARKER+'    $finish;')
    inverse=bench
    for op in reversed(edits):
        require(inverse.count(op['new'])==1,'full original fixture inverse failed')
        inverse=inverse.replace(op['new'],op['old'],1)
    require(inverse.encode()==previous['bt_bg_scroll_full_tb.sv'],'original assertions and stimulus changed')
    shim=load(SHIM,'bg_hold_frozen_primitive_model',SHIM_SHA)
    vendor=VENDOR.read_bytes();require(sha(vendor)==VENDOR_SHA,'installed Intel primary model changed')
    model=shim.shipped_model(vendor);require(sha(model)==MODEL_SHA,'exact shipped LCELL model changed')
    scalar=re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule',vendor,re.S)[0]
    require(re.search(rb'assign\s+out\s*=\s*in\s*;',scalar) is not None,
            'source induction requires actual shipped identity expression')
    branch=('module bt_bg_hold_branch(input [15:0] WRITE_DATA,output [15:0] observed);\n'
            +canonical(p.INSERT)+'assign observed=RAM_WRITE_DATA;\nendmodule\n')
    inputs=dict(previous);inputs['bg_vram.sv']=after;inputs['reference-bg_vram.sv']=reference
    inputs['bt_bg_scroll_full_tb.sv']=bench.encode()
    inputs['intel_lcell_sim.v']=model
    inputs['bt_bg_hold_lcell_tb.sv']=(chr(96)+'timescale 1 ns / 1 ps\n'+branch+CELL_BENCH).encode()
    return inputs,manifest,dict(inherited_BG_proof=inherited,full_fixture_edits=edits,
      original_fixture_inverse_sha256=sha(previous['bt_bg_scroll_full_tb.sv']),
      old_complete_BG_namespace_only=True,old_and_new_MEM_scroll_activation=True,
      exact_source_branch_compiled=True,exact_shipped_LCELL_scalar_sha256=sha(scalar),
      source_induction='The exact shipped scalar is assign out=in. Bits14:0 use the identical WRITE_DATA wires; bit15 uses that identity. For all 4^16 raw words and every clock ordering, both RAM data buses and sampling edges agree.',
      universal_four_state_word_cases=4**16,reset_and_all_old_packet_state_byte_identical=True,
      original_assertions_and_stimulus_preserved=True,collision_masks=0,case_equality_exclusions=0)

def commands(output,inputs):
    compiled=output/'compiled-inputs'
    return [([str(SIM/'vlib.exe'),'work'],'vlib.log'),
      ([str(SIM/'vlog.exe'),'-sv','-timescale','1 ps / 1 ps','-work','work']+[str(compiled/name) for name in inputs],'compile.log')]+[
      ([str(SIM/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib','work',top,
        '-do','run -all; quit -code 0'],kind+'.log') for kind,top in
      [('full','bt_bg_scroll_full_tb'),('raw','bt_bg_scroll_raw_tb'),
       ('pixel','bt_pixel_parallel_tb'),('cell','bt_bg_hold_lcell_tb')]]

def parse_logs(output):
    q=load(OLD,'bg_hold_original_coverage_parser',OLD_SHA);result={}
    for kind in ('full','raw','pixel','cell'):
        text=(output/(kind+'.log')).read_text(errors='replace')
        require(not re.search(r'(?m)\*\*\s+(?:Error|Fatal)|\$fatal|Error loading design|^FAIL',text),'actual BG regression failed')
        if kind!='cell':result[kind]=q.parse_counts(kind,text)
        if kind=='full':
            values=re.findall(r'BG_HOLD_COMPLETE_PASS pin_checks=(\d+) coincident=(\d+) offedge_resets=(\d+)',text)
            require(len(values)==1,'actual full RAM branch marker missing');n=tuple(map(int,values[0]))
            require(n[0]>600000 and n[1]>4096 and n[2]>=64,'full BG coincident/reset coverage missing')
            result['actual_RAM_branch']=n
        if kind=='cell':
            values=re.findall(r'BG_HOLD_LCELL_PASS truth=(\d+) known=(\d+) xz=(\d+) literals=(\d+) phases=(\d+) coincident=(\d+)',text)
            require(len(values)==1,'actual shipped LCELL marker missing');n=tuple(map(int,values[0]))
            require(n[1:]==(65536,65536,64,5120,1024) and n[0]>139000,'shipped four-state/same-edge coverage changed')
            result['cell']=n
    return normal(result)

def validate(output,receipt,inputs,detail):
    require(receipt['schema']==SCHEMA and receipt['status']==STATUS,'actual successful BG hold proof required')
    require(receipt['no_masks_or_exclusions'] is True and receipt['mapped_or_timing_qualified'] is False,
            'BG functional proof scope changed')
    expected={name:record(output/'compiled-inputs'/name) for name in inputs}
    require(receipt['compiled_inputs']==expected,'compiled source inventory changed')
    for name,data in inputs.items():
        require((output/'compiled-inputs'/name).read_bytes()==data,'complete actual compiler input changed: '+name)
    require(receipt['source_and_fixture_projection']==normal(detail),'source/fixture provenance changed')
    wanted=commands(output,inputs);require(len(receipt['commands'])==len(wanted),'actual command omitted')
    for row,(argv,log) in zip(receipt['commands'],wanted):
        require(row['command']==argv and row['exit_code']==0 and row['log']==record(output/log),'actual argv/exit/log changed')
        require(not re.search(r'\*\*\s+(?:Error|Fatal)|Error loading design',(output/log).read_text(errors='replace')),
                'actual compiler or simulation failed')
    require(receipt['coverage']==parse_logs(output),'actual source-derived coverage changed')
    for path,digest in receipt['retained_files'].items():
        require(sha(Path(path).read_bytes())==digest,'required retained evidence changed: '+path)
    return True

def negative_controls(output,receipt,inputs,detail):
    tests=[
      ('failed_status',lambda r:r.update(status='FAIL')),
      ('case_mask',lambda r:r.update(no_masks_or_exclusions=False)),
      ('timing_claim',lambda r:r.update(mapped_or_timing_qualified=True)),
      ('extra_latency',lambda r:r['source_and_fixture_projection'].update(exact_source_branch_compiled=False)),
      ('missing_source',lambda r:r['compiled_inputs'].pop('bg_vram.sv')),
      ('changed_source',lambda r:r['compiled_inputs']['bg_vram.sv'].update(sha256='0'*64)),
      ('missing_command',lambda r:r['commands'].pop()),
      ('assertions_disabled',lambda r:r['commands'][2]['command'].append('-DSYNTHESIS')),
      ('wrong_runtime',lambda r:r['commands'][2]['command'].__setitem__(0,'unknown.exe')),
      ('nonzero_exit',lambda r:r['commands'][0].update(exit_code=1)),
      ('changed_log',lambda r:r['commands'][-1]['log'].update(sha256='0'*64)),
      ('changed_coverage',lambda r:r['coverage'].clear())]
    rejected=[]
    for name,mutate in tests:
        wrong=copy.deepcopy(receipt);mutate(wrong)
        try:validate(output,wrong,inputs,detail)
        except (AssertionError,KeyError):rejected.append(name)
        else:raise AssertionError('altered proof accepted: '+name)
    return rejected

def verify_composition_receipt(path):
    path=Path(path).resolve();rec=json.loads(path.read_bytes());output=path.parent
    inputs,manifest,detail=generated_inputs(rec['edge_directory'])
    require(rec['edge_manifest_sha256']==EDGE_SHA,'wrong hold source edge')
    require(rec['helper_sha256']==sha(Path(__file__).read_bytes()),'executed qualifier changed')
    require((output/'executed-helpers'/Path(__file__).name).read_bytes()==Path(__file__).read_bytes(),'retained executed helper changed')
    validate(output,rec,inputs,detail)
    controls=negative_controls(output,rec,inputs,detail)
    require(len(controls)==12,'all rejection controls required')
    return dict(schema=SCHEMA,status=STATUS,receipt=str(path),receipt_sha256=sha(path.read_bytes()),
      parent_sha256=manifest['parent_sha256'],candidate_sha256=manifest['candidate_sha256'],
      coverage=rec['coverage'],rejected_controls=controls,compiled_inputs=len(inputs),
      bound_evidence_files=rec['retained_files'],mapped_or_timing_qualified=False)

def prepare(edge,output):
    edge=Path(edge).resolve();output=Path(output).resolve();require(not output.exists(),'exclusive new evidence directory required')
    inputs,manifest,detail=generated_inputs(edge);output.mkdir(parents=True)
    compiled=output/'compiled-inputs';compiled.mkdir();helpers=output/'executed-helpers';helpers.mkdir()
    retained={}
    for name,data in inputs.items():
        path=compiled/name;path.write_bytes(data);retained[str(path)]=sha(data)
    for helper in (Path(__file__),PREPARER,OLD,SHIM):
        data=helper.read_bytes();target=helpers/helper.name;target.write_bytes(data)
        retained[str(target)]=sha(data);retained[str(helper.resolve())]=sha(data)
    retained[str(OLD_RECEIPT)]=OLD_RECEIPT_SHA
    inherited=json.loads(OLD_RECEIPT.read_bytes());retained.update(inherited['retained_files'])
    retained[str(edge/'manifest.json')]=EDGE_SHA
    for role,digest in [('oracle',manifest['parent_sha256']),('candidate',manifest['candidate_sha256'])]:
        retained[str(edge/role/'rtl/bg_vram.sv')]=digest
    retained[str(VENDOR)]=VENDOR_SHA
    for name in ('vlib.exe','vlog.exe','vsim.exe'):
        retained[str(SIM/name)]=sha((SIM/name).read_bytes())
    meta=dict(schema='bt-v25-bg-write-hold-lcell-preparation-v1',edge_directory=str(edge),
      edge_manifest_sha256=EDGE_SHA,source_and_fixture_projection=normal(detail),
      compiled_inputs={name:record(compiled/name) for name in inputs},retained_files=retained,
      helper_sha256=sha(Path(__file__).read_bytes()))
    (output/'preparation.json').write_text(json.dumps(meta,indent=2)+'\n')
    return meta

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--edge',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume',action='store_true');parser.add_argument('--verify',type=Path);args=parser.parse_args()
    if args.verify:print(json.dumps(verify_composition_receipt(args.verify)));return
    output=args.output.resolve()
    meta=json.loads((output/'preparation.json').read_bytes()) if args.resume else prepare(args.edge,output)
    inputs,manifest,detail=generated_inputs(meta['edge_directory'])
    require(meta['helper_sha256']==sha(Path(__file__).read_bytes()),'prepared qualifier changed')
    require(meta['compiled_inputs']=={name:record(output/'compiled-inputs'/name) for name in inputs}
            and meta['source_and_fixture_projection']==normal(detail),'prepared compiler inputs changed')
    if args.prepare_only:print(json.dumps(dict(status='PREPARED_ONLY',preparation=record(output/'preparation.json'))));return
    rows=[];failure=None
    for argv,log in commands(output,inputs):
        result=subprocess.run(argv,cwd=output,capture_output=True,text=True,errors='replace')
        target=output/log;target.write_text(result.stdout+'\n'+result.stderr)
        rows.append(dict(command=argv,exit_code=result.returncode,log=record(target)))
        if result.returncode:failure='actual tool exited '+str(result.returncode);break
    coverage={}
    if failure is None:
        try:coverage=parse_logs(output)
        except (AssertionError,OSError) as exc:failure=repr(exc)
    retained=dict(meta['retained_files']);retained[str(output/'preparation.json')]=sha((output/'preparation.json').read_bytes())
    for row in rows:retained[row['log']['path']]=row['log']['sha256']
    rec=dict(schema=SCHEMA,status=STATUS if failure is None else 'FAIL',failure=failure,
      edge_directory=meta['edge_directory'],edge_manifest_sha256=EDGE_SHA,helper_sha256=meta['helper_sha256'],
      compiled_inputs=meta['compiled_inputs'],commands=rows,coverage=coverage,retained_files=retained,
      source_and_fixture_projection=normal(detail),no_masks_or_exclusions=True,mapped_or_timing_qualified=False)
    target=output/'receipt.json';target.write_text(json.dumps(rec,indent=2)+'\n')
    require(failure is None,'actual proof failed; retained '+str(target)+': '+str(failure))
    verified=verify_composition_receipt(target)
    (output/'verification.json').write_text(json.dumps(verified,indent=2)+'\n');print(json.dumps(verified))
if __name__=='__main__':main()
