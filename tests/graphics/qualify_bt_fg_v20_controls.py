"""Fresh immutable-v20 FG control replay; original assertions remain intact.

The source edge, complete canonical-RAM trace and actual-function 4-state proof
are separate typed scopes. This helper makes no Intel RAM, timing or RBF claim.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
BASE=ROOT/'build/timing_closure_20261011/fg_sprite_controls_v20_private'
TB=ROOT/'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2-compiled-inputs/item4_foreground_equivalence_tb.sv'
TB_SHA='af689824790f60bcce1b309cae68071e91fb693281da99a9c672e9e8978bc9aa'
PREPARER=ROOT/'tests/graphics/prepare_bt_fg_v20_controls.py'
PREPARER_SHA='ff98bb48363dd2b354cb3e39dd3e534abff91c9664b874b4dbd6c57c755282fb'
ORDER=ROOT/'tests/graphics/qualify_bt_fg_setup_q17_four_state_r3.py'
ORDER_SHA='3a29728f6f5ad978d25731a528fc8fa90ef0df24665adb0b8fdd8ab7bd1eb32f'
VENDOR=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA='c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'
PRIMITIVE_SHA='4012bc0467a7c3844315fd56d3c0d12d62fab6ef1050d55f06f617b47784eb0e'
BOUND={
 'rtl/BT_mem.sv':'903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
 'rtl/ddram.sv':'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
 'rtl/bt_fg_ddr_clear.sv':'bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1',
 'tests/graphics/ram_models.sv':'039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
 'tests/foreground_ddr_tb.sv':'fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c'}
FUNCTIONS=('FG_TRANSFER_COMMAND','FG_RMT_COMMAND','FG_POSITION_END_NEXT')
ORDER_NAMES=('MEM_ROW','SREG_POS','COPY_ADDR','RDY_NEXT_COPY_WE','HOLE_NEXT_ADDR',
             'COPY_ADDR_STEP_VALUE','COPY_ADDR_START_VALUE','CPU_CACHE_READY','CPU_PAIR_POS','SQ_D')
SHA=lambda raw:hashlib.sha256(raw).hexdigest()


def load(path,expected,name):
    checked(path,expected)
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def checked(path,expected):
    raw=Path(path).read_bytes()
    assert SHA(raw)==expected,('Frozen input changed',str(path),SHA(raw),expected)
    return raw


def record(path):
    raw=Path(path).read_bytes()
    return {'path':str(path),'sha256':SHA(raw),'bytes':len(raw)}


def canonical(raw):
    return raw.replace(b'\r\n',b'\n')


def extract_functions(candidate):
    text=canonical(candidate).decode('latin1');found=[]
    for name in FUNCTIONS:
        pattern=r'(?m)^\s*function automatic bit '+name+r';.*?^\s*endfunction'
        matches=re.findall(pattern,text,re.S)
        assert len(matches)==1,(name,len(matches))
        found.append(matches[0])
    bad=found[-1].replace('FG_POSITION_END_NEXT','BAD_EARLY_COERCE')
    assert bad.count('input logic [8:0] pos;')==1
    bad=bad.replace('input logic [8:0] pos;','input bit [8:0] pos;',1)
    return '\n'.join(found+[bad]),{name:SHA(body.encode('latin1')) for name,body in zip(FUNCTIONS,found)}


def source_proof(preparer,parent,candidate,edits):
    assert preparer.forward(parent,edits)==candidate
    assert preparer.reverse(candidate,edits)==parent
    regenerated,again=preparer.transform(parent)
    assert regenerated==candidate and again==edits
    coverage=preparer.verify_predicates()
    old=canonical(parent).decode('latin1');new=canonical(candidate).decode('latin1')
    owners=re.findall(r'(?m)^\s*COPY_DDR\s*<=\s*([^;]+);',old)
    assert owners==['0','|A_M[9:8]','|next_addr[9:8]'],owners
    assert new.count("COPY_DDR_CHUNK <= '0;")==1
    assert new.count('COPY_DDR_CHUNK <= {4{|A_M[9:8]}};')==1
    assert new.count('COPY_DDR_CHUNK <= {4{|next_addr[9:8]}};')==1
    # Same original raw bit captures; do not infer their conversion from logic.
    raw_assignments={}
    for field in ('RAS_N','OE_N','WE_N','TRANSFER','SE_N'):
        matches=re.findall(r'\b'+field+r'_M\s*<=\s*'+field+r'\s*;',old)
        assert len(matches)==1,(field,matches)
        raw_assignments[field]=matches[0]
    position_assignments=re.findall(r'\bHOLE_NEXT_POS\s*=(?!=)\s*([^;]+);',old)
    assert position_assignments==['SREG_POS',"9'd0","9'd0","9'd0","SREG_POS + 9'h8","SREG_POS + 9'd2"],position_assignments
    # Explicit first-stage and every existing consumer stays at its old edge.
    assert old.count('always @(posedge CLK or negedge RST_N)')==new.count('always @(posedge CLK or negedge RST_N)')
    assert old.count('always @(posedge CLK)')==new.count('always @(posedge CLK)')
    controls=[
      ("COPY_DDR_CHUNK <= '0;","COPY_DDR_CHUNK <= '1;"),
      ('COPY_DDR_CHUNK <= {4{|next_addr[9:8]}};','COPY_DDR_CHUNK <= {4{COPY_DDR}};'),
      ('COPY_DDR_CHUNK[copy_word_bank] ?','COPY_DDR_CHUNK[0] ?'),
      ('input bit ras_n, oe_n, transfer;','input logic ras_n, oe_n, transfer;'),
      ('HOLE_RAS_N_M <= {3{RAS_N}};','HOLE_RAS_N_M <= {3{RAS_N_M}};'),
      ('input logic [8:0] pos;','input bit [8:0] pos;'),
      ("9'h1fc : 9'h1f6","9'h1fe : 9'h1f8"),
      ('else if (step_ram) FG_POSITION_END_NEXT','else if (step_ddr) FG_POSITION_END_NEXT')]
    rejected=[]
    for before,after in controls:
        assert new.count(before)==1,before
        mutant=new.replace(before,after,1).replace('\n','\r\n').encode('latin1')
        try:
            inverse=preparer.reverse(mutant,edits)
            valid=inverse==parent and preparer.forward(parent,edits)==mutant
        except AssertionError:
            valid=False
        assert not valid,('Source negative control accepted',before)
        rejected.append(before)
    return {'binary_coverage':coverage,'original_owner_assignments':owners,
            'original_raw_bit_assignments':raw_assignments,'original_position_assignments':position_assignments,
            'inverse_raw_equal':True,'negative_controls_rejected':rejected,
            'compiled_four_state_proof_required':True,'timing_claim':False}


def extra_assertions():
    return '''
  integer fg_v20_control_checks=0;
  always @(negedge CLK) begin
    #0.1;
    if(RST_N) begin
      fg_v20_control_checks++;
      assert(candidate.COPY_DDR_CHUNK === {4{reference.COPY_DDR}})
        else $fatal(1,"FG local owner capture differs");
      assert(candidate.HOLE_RAS_N_M === {3{reference.RAS_N_M}} &&
             candidate.HOLE_TRANSFER_REQUEST_M === {3{!reference.RAS_N_M && !reference.OE_N_M && reference.TRANSFER_M}} &&
             candidate.HOLE_RMT_REQUEST_M === {3{!reference.RAS_N_M && !reference.OE_N_M && !reference.WE_N_M && reference.TRANSFER_M && !reference.SE_N_M}})
        else $fatal(1,"FG raw-command local capture differs");
      assert(candidate.HOLE_POS_END_RAM_B === reference.HOLE_POS_END_RAM_B &&
             candidate.HOLE_POS_END_DDR_B === reference.HOLE_POS_END_DDR_B)
        else $fatal(1,"FG original next-position capture differs");
    end
  end
'''


def prepare(edge,output,profile):
    manifest_path=edge/'manifest.json';manifest=json.loads(manifest_path.read_text())
    assert manifest['schema']=='bt-v20-fg-local-control-source-edge-v1'
    preparer=load(PREPARER,PREPARER_SHA,'fg_v20_controls_preparer')
    parent=checked(Path(manifest['oracle']['path']),preparer.PARENT_SHA)
    checked(Path(manifest['parent']['path']),preparer.PARENT_SHA)
    candidate=checked(Path(manifest['candidate']['path']),manifest['candidate']['sha256'])
    assert manifest['helper']['sha256']==PREPARER_SHA
    proof=source_proof(preparer,parent,candidate,manifest['edits'])
    output.mkdir(parents=True);inputs=output/'inputs';inputs.mkdir()
    frozen=output/'executed-helpers';frozen.mkdir()
    helpers=[Path(__file__).resolve(),PREPARER,ORDER,ROOT/'tests/graphics/bt_fg_v20_control_functions_tb.sv']
    for helper in helpers:(frozen/helper.name).write_bytes(helper.read_bytes())
    sources={}
    for name,expected in BOUND.items():
        path=(ROOT if name.startswith('tests/') else BASE)/name
        raw=checked(path,expected);sources[name]=record(path)
        (inputs/Path(name).name).write_bytes(raw)
    (inputs/'fg_vram.sv').write_bytes(candidate)
    reference=parent.decode('latin1');modules=re.findall(r'^module\s+(\w+)',reference,re.M)
    for module in sorted(modules,key=len,reverse=True):reference=re.sub(r'\b'+re.escape(module)+r'\b',module+'_REFERENCE',reference)
    reference=reference.encode('latin1');(inputs/'reference-fg_vram.sv').write_bytes(reference)
    vendor=checked(VENDOR,VENDOR_SHA)
    primitive=re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule',vendor,re.S)[0]
    assert SHA(primitive)==PRIMITIVE_SHA
    (inputs/'intel_lcell.v').write_bytes(b'`timescale 1ps/1ps\n'+primitive+b'\n')
    original_tb=checked(TB,TB_SHA);tb=canonical(original_tb).decode('latin1')
    additions=extra_assertions();assert '  initial begin\n' in tb
    tb=tb.replace('  initial begin\n',additions+'  initial begin\n',1)
    marker='    $display("PASS serial chunk complete pins/state:'
    assert tb.count(marker)==1
    report='    $display("PASS FG v20 controls: checks=%0d",fg_v20_control_checks);\n'
    if profile=='four-state':
        report+='    assert(fg_local_controls_fourstate_tb.done) else $fatal(1,"FG function proof did not finish");\n'
    tb=tb.replace(marker,report+marker,1)
    assert tb.replace(additions,'',1).replace(report,'',1)==canonical(original_tb).decode('latin1')
    (inputs/'item4_foreground_equivalence_tb.sv').write_bytes(tb.encode('latin1'))
    function_template=(ROOT/'tests/graphics/bt_fg_v20_control_functions_tb.sv').read_bytes()
    functions,function_hashes=extract_functions(candidate)
    template=canonical(function_template).decode('latin1');assert template.count('// __ACTUAL_FUNCTIONS__')==1
    function_tb=template.replace('// __ACTUAL_FUNCTIONS__',functions,1)
    (inputs/'fg_local_controls_fourstate_tb.sv').write_bytes(function_tb.encode('latin1'))
    adapters={}
    if profile=='four-state':
        order=load(ORDER,ORDER_SHA,'fg_v20_declaration_order')
        for name in ('fg_vram.sv','reference-fg_vram.sv'):
            raw=(inputs/name).read_bytes();original=canonical(raw)
            adapted,details=order.declaration_order(original,ORDER_NAMES)
            adapters[name]={'raw_sha256':SHA(raw),'canonical_sha256':SHA(original),'newline_edge':'CRLF to LF',**details}
            (inputs/name).write_bytes(adapted)
        raw=(inputs/'item4_foreground_equivalence_tb.sv').read_bytes()
        adapted,details=order.declaration_order(raw,('DRAW_ADDR',))
        adapters['item4_foreground_equivalence_tb.sv']=details
        (inputs/'item4_foreground_equivalence_tb.sv').write_bytes(adapted)
    meta={'schema':'bt-v20-fg-local-controls-inputs-v1','profile':profile,
          'edge':record(manifest_path),'parent':manifest['parent'],'oracle':manifest['oracle'],'candidate':manifest['candidate'],
          'source_proof':proof,'parent_sources':sources,'original_tb':record(TB),
          'assertion_additions':additions,'report_addition':report,'original_fixture_canonical_inverse':True,
          'oracle_namespace_modules':modules,'function_body_sha256':function_hashes,
          'function_template':record(ROOT/'tests/graphics/bt_fg_v20_control_functions_tb.sv'),
          'declaration_order_adapters':adapters,'vendor_lcell_source':record(VENDOR),'vendor_lcell_module_sha256':PRIMITIVE_SHA,
          'executed_helpers':{str(p):SHA(p.read_bytes()) for p in frozen.iterdir()},
          'compiled_inputs':{str(p):SHA(p.read_bytes()) for p in inputs.iterdir()},
          'case_equality_exclusions':0,'collision_masks_added':0,'intel_ram_claim':False,'timing_or_hardware_claim':False}
    (output/'preparation.json').write_text(json.dumps(meta,indent=2)+'\n')
    (output/'source-proof.json').write_text(json.dumps({'schema':'bt-v20-fg-local-controls-source-proof-v1','status':'PASS',
       'preparation':record(output/'preparation.json'),**proof},indent=2)+'\n')
    return meta


def wsl(path):
    value=path.resolve().as_posix();assert value[1]==':'
    return '/mnt/'+value[0].lower()+value[2:]


def run(command,cwd,log):
    with log.open('w') as target:
        result=subprocess.run(command,cwd=cwd,stdout=target,stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    return {'command':command,'exit_code':result.returncode,'log':record(log)}


def failure_text(text):
    return bool(re.search(r'(?im)(?:\*\*\s+(?:Fatal|Error)|\bfatal\b|\bassertion failed\b|\bFAIL(?:ED)?\b)',text))


def simulate(output,meta):
    inputs=output/'inputs';records=[];profile=meta['profile']
    if profile=='native':
        jobs=[('fg','item4_foreground_equivalence_tb',['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','intel_lcell.v','item4_foreground_equivalence_tb.sv']),
              ('fg-ddr','foreground_ddr_tb',['fg_vram.sv','ddram.sv','bt_fg_ddr_clear.sv','ram_models.sv','intel_lcell.v','foreground_ddr_tb.sv'])]
        for label,top,files in jobs:
            target=output/label;target.mkdir()
            command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec','verilator',
                '--binary','--assert','--timing','-j','4','--threads','1','--x-initial','unique','--x-assign','unique',
                '--top-module',top,'--Mdir',wsl(target/'obj'),'-Wno-fatal',*files]
            records.append(run(command,inputs,target/'build.log'))
            if records[-1]['exit_code']:break
            records.append(run(['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec',wsl(target/'obj'/('V'+top))],inputs,target/'run.log'))
            if records[-1]['exit_code']:break
    else:
        tool=Path('D:/q17/modelsim_ase/win32aloem');work=output/'work'
        records.append(run([str(tool/'vlib.exe'),str(work)],output,output/'vlib.log'))
        if not records[-1]['exit_code']:
            files=['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','intel_lcell.v','item4_foreground_equivalence_tb.sv','fg_local_controls_fourstate_tb.sv']
            records.append(run([str(tool/'vlog.exe'),'-sv','-work',str(work),*[str(inputs/f) for f in files]],output,output/'build.log'))
        if not records[-1]['exit_code']:
            records.append(run([str(tool/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib',str(work),
                                'item4_foreground_equivalence_tb','fg_local_controls_fourstate_tb','-do','run -all; quit -code 0'],output,output/'run.log'))
    passed=bool(records) and all(r['exit_code']==0 for r in records);coverage={}
    run_log=output/('fg/run.log' if profile=='native' else 'run.log')
    if passed and run_log.exists():
        text=run_log.read_text(errors='replace')
        state=re.search(r'PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)',text)
        pred=re.search(r'PASS FG v20 controls: checks=(\d+)',text)
        passed=bool(state and pred) and not failure_text(text)
        if passed:
            coverage={'states':31,'ram_banks':4,'ram_pin_fields':13,'state_edges':int(state[1]),
                      'bank_edge_checks':int(state[2]),'same_edge_control_checks':int(pred[1]),
                      'comparison':'case equality before/after every RAM edge'}
            assert int(state[1])>100000 and int(pred[1])>100000
            assert 'restart_collisions=8 abort_collisions=8 reset_collects=2' in text
            assert 'PASS item4 RMT/control corners:' in text
            if profile=='native':
                ddr=(output/'fg-ddr/run.log').read_text(errors='replace')
                passed='PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure' in ddr and not failure_text(ddr)
                coverage.update(cold_clear_writes=196608,masked_writes=128,copy_bytes=512)
            else:
                m=re.search(r'PASS FG actual control functions: raw_xz=(\d+) position_xz=(\d+) control_xz=(\d+) coercion_negative=(\d+)',text)
                passed=bool(m) and tuple(map(int,m.groups()))==(1024,4194304,65536,1)
                if passed:coverage.update(raw_xz_cases=int(m[1]),position_xz_cases=int(m[2]),unknown_control_cases=int(m[3]),compiled_coercion_negative_rejected=int(m[4]))
    return passed,records,coverage


def verify_frozen(meta):
    for key in ('edge','parent','oracle','candidate','original_tb','function_template','vendor_lcell_source'):
        checked(Path(meta[key]['path']),meta[key]['sha256'])
    for rec in meta['parent_sources'].values():checked(Path(rec['path']),rec['sha256'])
    for key in ('compiled_inputs','executed_helpers'):
        for path,expected in meta[key].items():checked(Path(path),expected)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--profile',choices=('native','four-state'),required=True)
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--resume',action='store_true')
    args=parser.parse_args();output=args.output.resolve();output.relative_to(ROOT/'build')
    assert not (args.prepare_only and args.resume)
    if args.resume:
        assert not (output/'receipt.json').exists(),'Retain old evidence; use a fresh output for another run'
        meta=json.loads((output/'preparation.json').read_text());assert meta['profile']==args.profile
        assert meta['edge']['path']==str(args.edge.resolve()/'manifest.json')
    else:
        assert not output.exists(),'Retain old evidence; use a fresh output for another run'
        meta=prepare(args.edge.resolve(),output,args.profile)
    verify_frozen(meta)
    if args.prepare_only:
        print(json.dumps({'status':'PREPARED_NOT_SIMULATED','preparation':record(output/'preparation.json'),
                          'source_proof':record(output/'source-proof.json')},separators=(',',':')));return
    passed,records,coverage=simulate(output,meta);verify_frozen(meta)
    receipt={'schema':'bt-v20-fg-local-controls-current-parent-replay-v1','status':'PASS' if passed else 'FAIL',
             'profile':args.profile,'preparation':record(output/'preparation.json'),'source_proof':record(output/'source-proof.json'),
             'records':records,'coverage':coverage,'original_assertions_and_workload_preserved':True,
             'case_equality_exclusions':0,'collision_masks_added':0,'intel_ram_claim':False,'timing_or_hardware_claim':False}
    path=output/'receipt.json';path.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':record(path),'status':receipt['status'],'coverage':coverage},separators=(',',':')))
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
