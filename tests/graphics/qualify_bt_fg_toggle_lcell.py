"""Fresh exact-parent FG full-pin replay and shipped LCELL four-state proof."""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
COMPILED = ROOT/'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2-compiled-inputs'
VENDOR = Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA = 'c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'
PRIMITIVE_SHA = '4012bc0467a7c3844315fd56d3c0d12d62fab6ef1050d55f06f617b47784eb0e'
BENCH_SHA = 'af689824790f60bcce1b309cae68071e91fb693281da99a9c672e9e8978bc9aa'
BOUND = {
    'rtl/BT_mem.sv':'903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'rtl/ddram.sv':'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'rtl/bt_fg_ddr_clear.sv':'bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1',
    'tests/graphics/ram_models.sv':'039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
    'tests/foreground_ddr_tb.sv':'fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c',
}
WRITE_STATES = ('CPU_RST_N','WE_N_OLD','WRITE_TOGGLE','WRITE_ADDR','WRITE_DATA',
                'WRITE_BE','WRITE_BANK_SEL','WRITE_TOGGLE_M','WRITE_SEEN',
                'WRITE_PENDING','PENDING_NEXT')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load(path):
    spec=importlib.util.spec_from_file_location('toggle_transform',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def fourstate_bench():
    return '''`timescale 1ns/1ps
module toggle_lcell_fourstate_tb;
  logic SYS=0, MEM=1, RST_N=0;
  logic VALUE=0, SOURCE=0, OLD_CAPTURE=0, NEW_CAPTURE=0;
  wire FIRST,SECOND;
  (* keep *) lcell cell0(.in(SOURCE),.out(FIRST));
  (* keep *) lcell cell1(.in(FIRST),.out(SECOND));
  always #6.25 SYS=~SYS;
  always #3.125 MEM=~MEM;
  always @(posedge SYS) SOURCE <= VALUE;
  always @(posedge MEM) begin
    if (!RST_N) begin OLD_CAPTURE<=0; NEW_CAPTURE<=0; end
    else begin OLD_CAPTURE<=SOURCE; NEW_CAPTURE<=SECOND; end
  end
  integer edges=0, states[0:3], resets=0, coincident=0;
  always @(posedge MEM) begin
    if (SYS) coincident++;
    #0.001;
    assert(FIRST === SOURCE && SECOND === SOURCE) else $fatal(1,"actual LCELL four-state identity");
    assert(OLD_CAPTURE === NEW_CAPTURE) else $fatal(1,"LCELL altered MEM capture/reset/NBA priority");
    edges++;
  end
  initial begin
    for(integer j=0;j<4;j++) states[j]=0;
    for(integer i=0;i<4096;i++) begin
      @(negedge SYS);
      case (i%4)
        0: VALUE=1'b0;
        1: VALUE=1'b1;
        2: VALUE=1'bx;
        3: VALUE=1'bz;
      endcase
      states[i%4]++;
      RST_N=(i%17 != 0);
      if (!RST_N) resets++;
      #0.002;
      assert(FIRST === SOURCE && SECOND === SOURCE) else $fatal(1,"LCELL off-edge identity");
    end
    repeat(4) @(negedge MEM);
    assert(edges>8192 && resets>200 && coincident>4096) else $fatal(1,"missing four-state/coincident coverage");
    for(integer j=0;j<4;j++) assert(states[j]==1024) else $fatal(1,"missing input state");
    $display("PASS shipped LCELL four-state identity: mem_edges=%0d each_01XZ=1024 resets=%0d coincident_SYS_MEM=%0d",edges,resets,coincident);
    $finish;
  end
endmodule
'''

def pin_bench(original):
    assert original.count('  initial begin\n') == 1
    extra = '  integer toggle_pre_edges=0,toggle_post_edges=0;\n'
    joined_c=','.join('candidate.'+n for n in WRITE_STATES)
    joined_r=','.join('reference.'+n for n in WRITE_STATES)
    extra += '  always @(posedge CLK or negedge CLK or posedge CPU_CLK or negedge CPU_CLK) begin\n'
    extra += f'    assert({{{joined_c}}} === {{{joined_r}}}) else $fatal(1,"pre-edge write packet or toggle state changed");\n'
    extra += '    toggle_pre_edges++;\n    #0.001;\n'
    extra += f'    assert({{{joined_c}}} === {{{joined_r}}}) else $fatal(1,"post-edge write packet or toggle state changed");\n'
    extra += '    assert(candidate.WRITE_TOGGLE_DELAY0 === candidate.WRITE_TOGGLE && candidate.WRITE_TOGGLE_DELAY1 === candidate.WRITE_TOGGLE) else $fatal(1,"shipped LCELL chain input identity");\n'
    extra += '    toggle_post_edges++;\n  end\n'
    data=original.replace('  initial begin\n',extra+'  initial begin\n',1)
    marker='    $display("PASS foreground transaction equivalence'
    assert data.count(marker)==1
    display='    assert(toggle_pre_edges>100000 && toggle_post_edges>100000) else $fatal(1,"missing toggle pin edge coverage");\n'
    display+='    $display("PASS toggle complete packet/sync state: pre=%0d post=%0d write_states=11 original_states=31 RAM_pin_fields=13 case_exclusions=0",toggle_pre_edges,toggle_post_edges);\n'
    return data.replace(marker,display+marker,1)

def run_logged(command,cwd,env,path):
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    with path.open('w') as log:
        result=subprocess.run(command,cwd=cwd,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
    return {'command':command,'exit_code':result.returncode,'log':str(path),'log_sha256':sha(path.read_bytes())}

def linux_path(path):
    path=Path(path).resolve().as_posix()
    assert len(path)>3 and path[1:3]==':/'
    return '/mnt/'+path[0].lower()+'/'+path[3:]

def wsl(command,cwd):
    return ['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(Path(cwd).resolve()),'--exec',*command]

def source_controls(transform,old,new,primitive,bench):
    controls=[]
    def rejected(name,operation):
        try:
            operation()
        except (AssertionError,ValueError):
            controls.append({'name':name,'rejected':True})
            return
        raise AssertionError('Negative control accepted: '+name)
    def same_inverse(data):
        assert transform.reverse(data)==old
    rejected('modified immutable whole FG parent',lambda:transform.transform(old+b'\n'))
    rejected('first kept net protection removed',lambda:same_inverse(new.replace(b'(* keep *) wire',b'wire',1)))
    rejected('first LCELL input changed',lambda:same_inverse(new.replace(b'.in(WRITE_TOGGLE)',b'.in(WRITE_TOGGLE_M)',1)))
    rejected('first MEM fan-in reverted',lambda:same_inverse(new.replace(transform.NEW_CAPTURE,transform.OLD_CAPTURE,1)))
    rejected('raw toggle next consumer changed',lambda:same_inverse(new.replace(b'PENDING_NEXT = WRITE_TOGGLE !=',b'PENDING_NEXT = WRITE_TOGGLE_DELAY1 !=',1)))
    rejected('toggle reset changed',lambda:same_inverse(new.replace(b'WRITE_TOGGLE_M <= 0;',b'WRITE_TOGGLE_M <= 1;',1)))
    def primitive_identity(data):
        assert sha(data)==PRIMITIVE_SHA
    rejected('shipped primitive behavior changed',lambda:primitive_identity(primitive.replace(b'out = in',b'out = ~in',1)))
    def bench_identity(data):
        assert sha(data)==BENCH_SHA
    rejected('retained original assertion changed',lambda:bench_identity(bench.replace(b'assert(',b'assert(1 || ',1)))
    return controls

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--edge',type=Path,required=True)
    p.add_argument('--source-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    assert not a.output.exists(), 'Output must be fresh'
    transform_path=ROOT/'tests/graphics/prepare_bt_fg_toggle_lcell.py'
    transform=load(transform_path)
    old,new,edge=transform.verify_edge(a.edge)
    assert (a.source_root/'rtl/fg_vram.sv').read_bytes()==old
    a.output.mkdir(parents=True)
    oracle_modules=re.findall(rb'(?m)^module\s+(\w+)',old)
    oracle=old
    for name in sorted(oracle_modules,key=len,reverse=True):
        oracle=re.sub(rb'\b'+re.escape(name)+rb'\b',name+b'_REFERENCE',oracle)
    sources={'fg_vram.sv':new,'reference-fg_vram.sv':oracle}
    consumed={}
    for name,wanted in BOUND.items():
        path=a.source_root/name if name.startswith('rtl/') else ROOT/name
        raw=path.read_bytes()
        assert sha(raw)==wanted, (name,sha(raw),wanted)
        sources[Path(name).name]=raw
        consumed[str(path.resolve())]=sha(raw)
    vendor=VENDOR.read_bytes()
    assert sha(vendor)==VENDOR_SHA
    primitive=re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule',vendor,re.S)[0]
    assert sha(primitive)==PRIMITIVE_SHA
    sources['intel_lcell.v']=b'`timescale 1ps/1ps\n'+primitive+b'\n'
    retained=(COMPILED/'item4_foreground_equivalence_tb.sv').read_bytes()
    assert sha(retained)==BENCH_SHA
    sources['item4_foreground_equivalence_tb.sv']=pin_bench(retained.decode().replace('\r\n','\n')).encode()
    sources['toggle_lcell_fourstate_tb.sv']=fourstate_bench().encode()
    inputs=a.output/'compiled-inputs'
    inputs.mkdir()
    for name,data in sources.items():
        (inputs/name).write_bytes(data)
    controls=source_controls(transform,old,new,primitive,retained)
    prep={'schema':'bt-fg-toggle-lcell-proof-preparation-v1',
          'source_edge_path':str(a.edge.resolve()/'manifest.json'),'source_edge_sha256':sha((a.edge/'manifest.json').read_bytes()),
          'parent_sha256':sha(old),'candidate_sha256':sha(new),'source_root':str(a.source_root.resolve()),
          'transform_helper_sha256':sha(transform_path.read_bytes()),'proof_helper_sha256':sha(Path(__file__).read_bytes()),
          'retained_bench_path':str(COMPILED/'item4_foreground_equivalence_tb.sv'),'retained_bench_sha256':BENCH_SHA,
          'oracle_module_names':[n.decode() for n in oracle_modules],
          'vendor_file':str(VENDOR),'vendor_file_sha256':VENDOR_SHA,'lcell_actual_module_sha256':PRIMITIVE_SHA,
          'current_shared_inputs':consumed,'compiled_inputs':{n:sha(d) for n,d in sources.items()},
          'original_retained_bench_line_endings_normalized_to_lf':True,
          'all_original_normalized_bench_bytes_preserved_except_added_monitors':True,'collision_masks_added':0,
          'case_equality_exclusions':0,'write_state_names':WRITE_STATES,'actual_intel_physical_ram_rerun':False,
          'source_negative_controls':controls,'runtime':'Ubuntu WSL: actual ELF compiler/simulator routed explicitly'}
    (a.output/'preparation.json').write_text(json.dumps(prep,indent=2)+'\n')
    env=dict(os.environ)
    stages=[]
    # The original installed Intel LCELL module is compiled, never a behavioral replacement.
    ftarget=a.output/'fourstate'
    ftarget.mkdir()
    for label,command in (('iverilog-version',['iverilog','-V']),('verilator-version',['verilator','--version'])):
        record=run_logged(wsl(command,ROOT),ROOT,env,a.output/(label+'.log'));stages.append(record)
        assert record['exit_code']==0, ('Retained runtime probe failure',record)
    c=wsl(['iverilog','-g2012','-s','toggle_lcell_fourstate_tb','-o',linux_path(ftarget/'proof.vvp'),
           linux_path(inputs/'intel_lcell.v'),linux_path(inputs/'toggle_lcell_fourstate_tb.sv')],ROOT)
    record=run_logged(c,ROOT,env,ftarget/'build.log');stages.append(record)
    assert record['exit_code']==0, ('Retained compiler failure',record)
    record=run_logged(wsl(['vvp',linux_path(ftarget/'proof.vvp')],ROOT),ROOT,env,ftarget/'run.log');stages.append(record)
    assert record['exit_code']==0 and 'PASS shipped LCELL four-state identity:' in (ftarget/'run.log').read_text(), ('Retained four-state failure',record)
    workspace=a.output/'wsl-native-workspace'
    workspace.mkdir()
    for key,data in sources.items():
        (workspace/key).write_bytes(data)
    env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
             VERILATOR_WORKSPACE=str(workspace),VERILATOR_RAM_WORKSPACE=str(workspace))
    tests=[('fg','item4_foreground_equivalence_tb',['fg_vram.sv','reference-fg_vram.sv','intel_lcell.v','ram_models.sv','item4_foreground_equivalence_tb.sv']),
           ('fg-ddr','foreground_ddr_tb',['fg_vram.sv','intel_lcell.v','ddram.sv','bt_fg_ddr_clear.sv','ram_models.sv','foreground_ddr_tb.sv'])]
    for label,top,files in tests:
        target=workspace/label
        target.mkdir()
        command=wsl(['verilator','--binary','--assert','--timing','-j','4','--threads','1',
                     '--x-initial','unique','--x-assign','unique','--top-module',top,
                     '--Mdir',linux_path(target/'obj'),'-Wno-fatal','-CFLAGS','-DVL_TIME_CONTEXT -std=c++17',
                     *[linux_path(workspace/f) for f in files]],ROOT)
        build=run_logged(command,ROOT,env,target/'build.log')
        saved=a.output/label
        saved.mkdir()
        shutil.copyfile(target/'build.log',saved/'build.log')
        build.update(log=str(saved/'build.log'),log_sha256=sha((saved/'build.log').read_bytes()))
        stages.append(build)
        assert build['exit_code']==0, ('Retained full-module compiler failure',build)
        run=run_logged(wsl([linux_path(target/'obj'/('V'+top))],ROOT),ROOT,env,target/'run.log')
        shutil.copyfile(target/'run.log',saved/'run.log')
        run.update(log=str(saved/'run.log'),log_sha256=sha((saved/'run.log').read_bytes()))
        stages.append(run)
        text=(saved/'run.log').read_text()
        assert run['exit_code']==0 and 'PASS' in text and not re.search(r'\b(fatal|failed|error)\b',text,re.I), ('Retained full-module functional failure',run)
        print(label+': '+text[-1900:])
    for path,wanted in consumed.items():
        assert sha(Path(path).read_bytes())==wanted
    assert load(transform_path).verify_edge(a.edge)[1]==new
    assert sha(VENDOR.read_bytes())==VENDOR_SHA
    for key,wanted in prep['compiled_inputs'].items():
        assert sha((inputs/key).read_bytes())==wanted and sha((workspace/key).read_bytes())==wanted
    fg=(a.output/'fg/run.log').read_text()
    match=re.search(r'pre=(\d+) post=(\d+) write_states=11',fg)
    assert match and int(match[1])>100000 and int(match[2])>100000
    assert 'restart_collisions=8 abort_collisions=8 reset_collects=2' in fg
    receipt={'schema':'bt-fg-toggle-lcell-full-pin-fourstate-v1','status':'PASS',
             'preparation':str(a.output/'preparation.json'),'preparation_sha256':sha((a.output/'preparation.json').read_bytes()),
             'candidate_sha256':sha(new),'parent_sha256':sha(old),'stages':stages,
             'original_assertions_preserved':True,'case_equality_exclusions':0,'collision_masks_added':0,
             'coverage':{'write_state_pre_edges':int(match[1]),'write_state_post_edges':int(match[2]),
                         'write_state_fields':11,'original_state_fields':31,'bank_pin_fields':13,'banks':4},
             'actual_shipped_primitive_fourstate_compiled':True,'current_source_stability':True,
             'source_negative_controls':controls,
             'compiler_workspace':str(workspace),'actual_intel_physical_ram_rerun':False,
             'mapped_or_timing_claim':False,'rbf_or_hardware_claim':False,
             'scope':'Fresh actual FG full state/RAM-pin and shipping DDR workload comparison against exact v18 FG parent; actual shipped Intel scalar LCELL four-state identity/capture proof. Unchanged physical RAM modes and narrow collision/X contracts require explicit existing vendor applicability composition; no mapped timing acceptance.'}
    (a.output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':str(a.output/'receipt.json'),'sha256':sha((a.output/'receipt.json').read_bytes()),'status':'PASS'}))

if __name__=='__main__':
    main()
