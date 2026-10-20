"""Actual complete BG and four-state scroll-stage equivalence; no timing claim."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SIM=Path('D:/q17/modelsim_ase/win32aloem')
PREPARER=ROOT/'tests/graphics/prepare_bt_bg_scroll_mem.py'
PREPARER_SHA='a76c9c81b9bef8f226dbe7f8ebce78d0d6acd927ff126170c18b9ff1a4a7cb9e'
OLD=ROOT/'tests/graphics/qualify_bt_bg_pixel_predicates.py'
OLD_SHA='fe020fa70b2a7ff2ec586d0990fe1c388b0b3123d3bf6d377928ed8fe7216305'
OLD_EDGE=ROOT/'build/bg_pixel_predicates_v22_v1/source-edge-r2'
OLD_MANIFEST_SHA='f419ccbc4948b1c1291530139c6a19dcca86fbd0e8df72043dda6166eb21e4f1'
RAM=ROOT/'tests/graphics/ram_models.sv'
RAM_SHA='039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc'

def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
    if not value:raise AssertionError(message)
def load(path,name,digest=None):
    if digest is not None:require(sha(Path(path).read_bytes())==digest,'changed pinned proof helper')
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def canonical(data):return data.decode().replace('\r\n','\n')

FULL_DECL=r'''
  logic[15:0] OFFSET=0;logic ADDRESS_TRANSFER=1;
  wire[7:0] ADDRESS_ROW=A[15:8]+OFFSET[15:8];
  wire[7:0] ADDRESS_COL=A[7:0]+OFFSET[7:0];
  wire[15:0] EFFECTIVE_A=ADDRESS_TRANSFER?{ADDRESS_ROW,ADDRESS_COL}:{A[15:8],A[7:1],1'b0};
  wire[15:0] off_q;wire[7:0] off_sq;wire off_rdy,off_grid,off_nz,off_high;
  wire old_nz,old_high;
  integer stage_checks=0,extra_edges=0,raw_cases=0,offedge_resets=0;
  BG_VRAM off_i(CLK,CPU_CLK,RST_N,EFFECTIVE_A,CPU_A,D,off_q,RAS_N,CAS_N,
    WE_N,OE_N,TRANSFER,off_rdy,SC,SE_N,off_sq,off_grid,off_nz,off_high);
  function automatic logic four(input integer value);
    case(value&3)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
  endfunction
'''
FULL_COMPARE=r'''
      stage_checks=stage_checks+1;
      if({old_q,old_sq,old_rdy,old_grid,old_nz,old_high} !==
         {off_q,off_sq,off_rdy,off_grid,off_nz,off_high})
        $fatal(1,"default-off BG behavior changed");
      if({old_nz,old_high} !== {new_nz,new_high})
        $fatal(1,"old BG pixel predicate outputs changed");
      if({old_i.A_M,old_i.CPU_A_M,old_i.RAS_N_M,old_i.OE_N_M,old_i.WE_N_M,
          old_i.TRANSFER_M,old_i.SC_M} !==
         {new_i.A_M,new_i.CPU_A_M,new_i.RAS_N_M,new_i.OE_N_M,new_i.WE_N_M,
          new_i.TRANSFER_M,new_i.SC_M})
        $fatal(1,"first/second memory-edge address or command changed");
      if(old_i.A_M !== off_i.A_M) $fatal(1,"default-off address capture changed");
'''
FULL_EXTRA=r'''
    // This is additive; the original complete BG workload/report preceded it.
    // Address, scroll and mode change between clocks and at independent CPU
    // edges. Reset must not reset the original unreset A_M capture.
    for(i=0;i<8192;i=i+1) begin
      A=(i*137)^16'hc951;OFFSET=(i*313)^16'h9e27;
      ADDRESS_TRANSFER=four(i);TRANSFER=four(i>>2);RAS_N=four(i>>4);
      OE_N=four(i>>6);WE_N=four(i>>8);SC=four(i>>10);
      for(mask=0;mask<16;mask=mask+1) begin
        if(((i+mask)&31)==0) A[mask]=four(i>>5);
        if(((i+mask)&31)==1) OFFSET[mask]=four(i>>7);
      end
      CPU_A=i*37;D=i*91;CAS_N=i[1:0];
      #1;compare;CPU_CLK=1;#1;compare;CPU_CLK=0;
      tick(0);tick(i[0]);extra_edges=extra_edges+2;raw_cases=raw_cases+1;
      if((i&127)==0)begin
        #1;RST_N=0;#1;compare;offedge_resets=offedge_resets+1;
        tick(0);RST_N=1;#1;compare;extra_edges=extra_edges+1;
      end
    end
    $display("BG_SCROLL_COMPLETE_PASS checks=%0d extra_edges=%0d raw_cases=%0d offedge_resets=%0d",stage_checks,extra_edges,raw_cases,offedge_resets);
'''

RAW_BENCH=r'''module bt_bg_scroll_raw_tb;
  logic CLK=0;logic[15:0] SCROLL_BASE=0,SCROLL_OFFSET=0;logic SCROLL_TRANSFER=0;
  wire[15:0] old_address,new_address;
  bt_bg_scroll_old old_i(CLK,SCROLL_BASE,SCROLL_OFFSET,SCROLL_TRANSFER,old_address);
  bt_bg_scroll_new new_i(CLK,SCROLL_BASE,SCROLL_OFFSET,SCROLL_TRANSFER,new_address);
  bit[15:0] stale_address=0;bit[15:0] bit_base=0,bit_offset=0;bit bit_transfer=0;
  bit[15:0] coerced_mutant;integer checks=0,known_pairs=0,raw_words=0,holds=0;
  integer stale_hits=0,early_coercion_hits=0,i,j;
  function automatic logic four(input integer v);
    case(v&3)0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
  endfunction
  task automatic tick;
    begin
      #1;
      if(old_address !== new_address) $fatal(1,"address changed without admitted MEM edge");
      stale_address=old_address;bit_base=SCROLL_BASE;bit_offset=SCROLL_OFFSET;bit_transfer=SCROLL_TRANSFER;
      CLK=1;#1;checks=checks+1;
      if(old_address !== new_address) $fatal(1,"raw scroll address mismatch base=%h offset=%h mode=%b old=%h new=%h",SCROLL_BASE,SCROLL_OFFSET,SCROLL_TRANSFER,old_address,new_address);
      if(stale_address !== old_address) stale_hits=stale_hits+1;
      coerced_mutant=bit_transfer?
        {8'(bit_base[15:8]+bit_offset[15:8]),8'(bit_base[7:0]+bit_offset[7:0])}:
        {bit_base[15:8],bit_base[7:1],1'b0};
      if(coerced_mutant !== old_address) early_coercion_hits=early_coercion_hits+1;
      CLK=0;#1;
    end
  endtask
  initial begin
    #1;if(old_address !== 0 || new_address !== 0)$fatal(1,"unreset startup A_M changed");
    for(i=0;i<65536;i=i+1)begin
      SCROLL_BASE=i;SCROLL_OFFSET={i[7:0],i[15:8]};SCROLL_TRANSFER=i[0];tick;known_pairs=known_pairs+1;
    end
    for(i=0;i<65536;i=i+1)begin
      for(j=0;j<8;j=j+1)begin SCROLL_BASE[j]=four(i>>(2*j));SCROLL_BASE[j+8]=four((i>>(2*j))+1);end
      SCROLL_OFFSET=i*97;
      for(j=0;j<4;j=j+1)begin SCROLL_TRANSFER=four(j);tick;raw_words=raw_words+1;end
    end
    for(i=0;i<65536;i=i+1)begin
      for(j=0;j<8;j=j+1)begin SCROLL_OFFSET[j]=four(i>>(2*j));SCROLL_OFFSET[j+8]=four((i>>(2*j))+2);end
      SCROLL_BASE=i*157;
      for(j=0;j<4;j=j+1)begin SCROLL_TRANSFER=four(j);tick;raw_words=raw_words+1;end
    end
    for(i=0;i<256;i=i+1)begin
      SCROLL_BASE=i*311;SCROLL_OFFSET=i*199;SCROLL_TRANSFER=four(i);
      #1;if(old_address !== new_address)$fatal(1,"offedge raw inputs changed held address");holds=holds+1;
    end
    if(stale_hits==0 || early_coercion_hits==0)$fatal(1,"required latency/XZ mutant was not detected");
    $display("BG_SCROLL_RAW_PASS checks=%0d known_pairs=%0d raw_words=%0d holds=%0d stale_hits=%0d early_coercion_hits=%0d",checks,known_pairs,raw_words,holds,stale_hits,early_coercion_hits);
    $finish;
  end
endmodule
'''

def source_induction(files,manifest):
    before=Path(manifest['files']['rtl/BT.sv']['parent']).read_bytes().decode()
    current=files['rtl/bg_vram.sv'].decode().replace('\r\n','\n')
    require('reg [15:0] base_m = 16\'d0;' in current and 'reg [15:0] offset_m = 16\'d0;' in current
            and 'reg transfer_m = 1\'b0;' in current,'raw four-state operand storage and zero startup required')
    for bg in (0,1):
        require(f'wire [7:0] BG{bg}_ROW = LA[21:14] + SCROLL{bg}[15:8];' in before
                and f'wire [7:0] BG{bg}_COL = LA[11:4] + SCROLL{bg}[7:0];' in before,
                'exact original unsigned byte arithmetic required')
        require(f"wire [15: 0] BG{bg}_A = LA[3:0] == 4'b0100 ? {{BG{bg}_ROW,BG{bg}_COL}} : {{LA[21:14],LA[11:5],1'b0}};" in before,
                'exact original four-state mux/ordinary address required')
    require('wire [7:0] row_d = base_m[15:8] + offset_m[15:8];' in current
            and 'wire [7:0] col_d = base_m[7:0] + offset_m[7:0];' in current
            and "always_comb A_M = transfer_m ? {row_d,col_d} : {base_m[15:8],base_m[7:1],1'b0};" in current,
            'byte width/final original bit conversion changed')
    require('base_m <= SCROLL_BASE;' in current and 'offset_m <= SCROLL_OFFSET;' in current
            and 'transfer_m <= SCROLL_TRANSFER;' in current,'exact current input sampling required')
    return dict(method='source-bound temporal substitution of identical four-state F, at the existing MEM edge',
       arbitrary_four_state_input_bits=33,arbitrary_four_state_tuples=4**33,
       before='A_M[n+1] = bit16(F(raw_inputs[n]))',
       after='raw_regs[n+1] = raw_inputs[n]; A_M = bit16(F(raw_regs))',
       first_edge_post_NBA_equality=True,second_edge_pre_NBA_consumers_unchanged=True,
       initialization_equal_zero=True,no_new_reset_guard=True,all_raw_arithmetic_and_mux_types_unchanged=True)

def generated_inputs(edge):
    p=load(PREPARER,'scroll_mem_source',PREPARER_SHA);files,manifest=p.verify_edge(edge)
    old=load(OLD,'scroll_mem_frozen_full_proof',OLD_SHA)
    require(sha((OLD_EDGE/'manifest.json').read_bytes())==OLD_MANIFEST_SHA,'frozen pixel source edge changed')
    previous,unused=old.generated_inputs(OLD_EDGE)
    bg=files['rtl/bg_vram.sv'];parent=Path(manifest['files']['rtl/bg_vram.sv']['parent']).read_bytes()
    reference=re.sub(rb'\bBG_VRAM\b',b'BG_VRAM_REFERENCE',parent)
    require(reference.replace(b'BG_VRAM_REFERENCE',b'BG_VRAM')==parent,'reference namespace-only full-file inverse failed')
    bench=old.FULL_BENCH;changes=[]
    def edit(before,after):
        nonlocal bench
        require(bench.count(before)==1,'original full fixture adapter anchor changed')
        bench=bench.replace(before,after,1);changes.append(dict(old=before,new=after))
    edit('module bt_bg_predicate_full_tb;','module bt_bg_scroll_full_tb;')
    edit('  integer pre=0,post=0,writes=0,refreshes=0,shifts=0,resets=0;',
         '  integer pre=0,post=0,writes=0,refreshes=0,shifts=0,resets=0;'+FULL_DECL)
    edit('old_i(CLK,CPU_CLK,RST_N,A,CPU_A,D,old_q','old_i(CLK,CPU_CLK,RST_N,EFFECTIVE_A,CPU_A,D,old_q')
    edit('WE_N,OE_N,TRANSFER,old_rdy,SC,SE_N,old_sq,old_grid);',
         'WE_N,OE_N,TRANSFER,old_rdy,SC,SE_N,old_sq,old_grid,old_nz,old_high);')
    edit('  BG_VRAM new_i(', '  BG_VRAM #(.MEM_SCROLL_ADDER(1)) new_i(')
    edit('WE_N,OE_N,TRANSFER,new_rdy,SC,SE_N,new_sq,new_grid,new_nz,new_high);',
         'WE_N,OE_N,TRANSFER,new_rdy,SC,SE_N,new_sq,new_grid,new_nz,new_high,A,OFFSET,ADDRESS_TRANSFER);')
    edit('      coerced=new_sq;', '      coerced=new_sq;'+FULL_COMPARE)
    edit('    $finish;',FULL_EXTRA+'    $finish;')
    inverse=bench
    for op in reversed(changes):
        require(inverse.count(op['new'])==1,'full fixture inverse changed');inverse=inverse.replace(op['new'],op['old'],1)
    require(inverse==old.FULL_BENCH,'all original fixture assertions and stimulus must be retained')
    # The raw old cut is the exact original BT arithmetic + original BG capture.
    old_raw='''module bt_bg_scroll_old(input CLK,input[15:0] SCROLL_BASE,SCROLL_OFFSET,input SCROLL_TRANSFER,output bit[15:0] A_M);
 wire[7:0] row_d=SCROLL_BASE[15:8]+SCROLL_OFFSET[15:8];
 wire[7:0] col_d=SCROLL_BASE[7:0]+SCROLL_OFFSET[7:0];
 wire[15:0] A=SCROLL_TRANSFER?{row_d,col_d}:{SCROLL_BASE[15:8],SCROLL_BASE[7:1],1'b0};
 always @(posedge CLK) A_M <= A;
endmodule
'''
    stage=p.ADDRESS_STAGE
    require(canonical(bg).count(stage)==1,'raw test must compile the complete actual activated A_M block')
    raw_new='module bt_bg_scroll_new(input CLK,input[15:0] SCROLL_BASE,SCROLL_OFFSET,input SCROLL_TRANSFER,output[15:0] address);\nparameter MEM_SCROLL_ADDER=1;wire[15:0] A=0;\n'+stage+'\nassign address=A_M;\nendmodule\n'
    require(sha(RAM.read_bytes())==RAM_SHA,'qualified RAM adapter changed')
    inputs={'bg_vram.sv':bg,'reference-bg_vram.sv':reference,'ram_models.sv':RAM.read_bytes(),
      'bt_bg_scroll_full_tb.sv':bench.encode(),'bt_bg_scroll_raw_tb.sv':(old_raw+raw_new+RAW_BENCH).encode(),
      'bt_bg_scroll_pixel_tb.sv':previous['bt_bg_predicate_pixel_tb.sv']}
    # Scroll relocation must leave every byte of both actual pixel functions,
    # bank holding and SYS capture unchanged; the sole BT edits are instance ABI.
    pixel_scope=files['rtl/BT.sv'].decode().split('\tfunction automatic bit [7:0] BT_SELECT_PIXEL',1)[1]
    parent_scope=before_bt=Path(manifest['files']['rtl/BT.sv']['parent']).read_bytes().decode().split('\tfunction automatic bit [7:0] BT_SELECT_PIXEL',1)[1]
    require(pixel_scope==parent_scope,'pixel/bank/reset/SYS consumer body changed')
    return inputs,manifest,dict(fixture_changes=changes,original_fixture_inverse_sha256=sha(old.FULL_BENCH.encode()),
                               source_induction=source_induction(files,manifest),pixel_body_byte_identical=True)

def run_command(argv,cwd,log):
    argv=[str(item) for item in argv];started=time.monotonic()
    with log.open('w') as stream:
        result=subprocess.run(argv,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,creationflags=0x08000000)
    data=log.read_bytes();text=data.decode(errors='replace')
    require(result.returncode==0 and not re.search(r'\*\*\s+(?:Error|Fatal)|\$fatal|Error loading design',text),
            'actual simulator/compiler failed: '+str(log))
    return dict(argv=argv,cwd=str(cwd),exit_code=result.returncode,log=str(log),log_sha256=sha(data),
                elapsed_seconds=round(time.monotonic()-started,3))

def parse_counts(kind,text):
    if kind=='full':
        old=re.findall(r'BG_FULL_PREDICATES_PASS pre=(\d+) post=(\d+) writes=(\d+) refreshes=(\d+) shifts=(\d+) resets=(\d+)',text)
        require(old==[('130738','130738','4096','16','4096','4')],'original complete BG workload changed')
        values=re.findall(r'BG_SCROLL_COMPLETE_PASS checks=(\d+) extra_edges=(\d+) raw_cases=(\d+) offedge_resets=(\d+)',text)
        require(len(values)==1,'complete BG scroll trace marker required')
        nums=tuple(map(int,values[0]));require(nums[0]>260000 and nums[1:]==(16448,8192,64),'complete BG phase/XZ coverage changed')
        return dict(original=tuple(map(int,old[0])),scroll=nums)
    if kind=='raw':
        values=re.findall(r'BG_SCROLL_RAW_PASS checks=(\d+) known_pairs=(\d+) raw_words=(\d+) holds=(\d+) stale_hits=(\d+) early_coercion_hits=(\d+)',text)
        require(len(values)==1,'actual raw stage marker required');nums=tuple(map(int,values[0]))
        require(nums[:4]==(589824,65536,524288,256) and min(nums[4:])>0,'actual raw X/Z/latency coverage changed')
        return nums
    old=load(OLD,'scroll_mem_pixel_parser',OLD_SHA);return old.parse_counts(text,'pixel')

def verify_composition_receipt(path):
    path=Path(path).resolve();rec=json.loads(path.read_bytes())
    require(rec['schema']=='bt-v23-bg-scroll-MEM-qualification-v1'
            and rec['status']=='PASS_ACTUAL_BG_SCROLL_AND_PIXEL','wrong qualification schema/status')
    for artifact,digest in rec['retained_files'].items():require(sha(Path(artifact).read_bytes())==digest,'changed actual proof artifact')
    inputs,manifest,detail=generated_inputs(rec['edge_directory'])
    require(json.loads(json.dumps(detail))==rec['source_and_fixture_projection'],'changed actual source/fixture induction')
    require(set(inputs)==set(rec['compiled_inputs']),'complete compiled input inventory required')
    for name,data in inputs.items():
        record=rec['compiled_inputs'][name];require(sha(data)==record['sha256'] and Path(record['path']).read_bytes()==data,
                                                   'actual compiler input regeneration failed: '+name)
    work=path.parent;command=rec['commands']
    require(len(command)==2 and command[0]['argv']==[str(SIM/'vlib.exe'),'work']
       and command[1]['argv']==[str(SIM/'vlog.exe'),'-sv','-work','work']+[str(work/'compiled-inputs'/name) for name in inputs],
       'actual complete compiler command changed')
    coverage={};tops={'full':'bt_bg_scroll_full_tb','raw':'bt_bg_scroll_raw_tb','pixel':'bt_pixel_parallel_tb'}
    require(set(rec['runs'])==set(tops),'all complete BG/raw/pixel simulations required')
    for kind,top in tops.items():
        record=rec['runs'][kind];require(record['argv']==[str(SIM/'vsim.exe'),'-c','-lib','work',top,'-do','run -all; quit -f'],
                                       'wrong actual simulator top/options')
        text=Path(record['log']).read_text();coverage[kind]=parse_counts(kind,text)
    for record in command+list(rec['runs'].values()):
        require(record['exit_code']==0 and Path(record['cwd']).resolve()==work
                and sha(Path(record['log']).read_bytes())==record['log_sha256'],'actual command/exit/log changed')
        require(not re.search(r'\*\*\s+(?:Error|Fatal)|\$fatal|Error loading design',Path(record['log']).read_text()),'actual proof failure')
    require(json.loads(json.dumps(coverage))==rec['coverage'],'actual reparsed coverage changed')
    require(rec['no_masks_or_exclusions'] and rec['old_RAM_storage_and_packet_body_unchanged']
            and rec['consumer_clock_edges_and_latency_unchanged'] and not rec['mapped_or_timing_qualified'],'proof scope broadened')
    return dict(status=rec['status'],receipt=str(path),receipt_sha256=sha(path.read_bytes()),coverage=coverage,
      source_induction=detail['source_induction'],source_files={name:r['candidate_sha256'] for name,r in manifest['files'].items()},
      case_equality_exclusions=0,collision_masks=0,physical_ram_body_unchanged=True,consumer_edges_unchanged=True,
      default_off_ABI_preserved=True,mapped_or_timing_qualified=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--edge',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--prepare-only',action='store_true');args=parser.parse_args()
    out=args.output.resolve();require(not out.exists(),'exclusive new qualification output required')
    inputs,manifest,detail=generated_inputs(args.edge);out.mkdir(parents=True);compiled=out/'compiled-inputs';compiled.mkdir()
    helpers=out/'executed-helpers';helpers.mkdir();retained={}
    for name,data in inputs.items():target=compiled/name;target.write_bytes(data);retained[str(target)]=sha(data)
    for helper in (Path(__file__),PREPARER,OLD):
        target=helpers/helper.name;target.write_bytes(helper.read_bytes());retained[str(target)]=sha(target.read_bytes())
        retained[str(helper.resolve())]=sha(helper.read_bytes())
    prep=dict(schema='bt-v23-bg-scroll-MEM-preparation-v1',edge_directory=str(args.edge.resolve()),
      source_and_fixture_projection=detail,compiled_inputs={name:dict(path=str(compiled/name),sha256=sha(data)) for name,data in inputs.items()},
      executed_helpers={p:d for p,d in retained.items() if 'executed-helpers' in p},no_masks_or_exclusions=True)
    prep_path=out/'preparation.json';prep_path.write_text(json.dumps(prep,indent=2)+'\n');retained[str(prep_path)]=sha(prep_path.read_bytes())
    if args.prepare_only:print(json.dumps(dict(status='PREPARED_ONLY',preparation=str(prep_path),sha256=sha(prep_path.read_bytes()))));return
    commands=[run_command([SIM/'vlib.exe','work'],out,out/'vlib.log'),
              run_command([SIM/'vlog.exe','-sv','-work','work']+[compiled/name for name in inputs],out,out/'compile.log')]
    runs={};coverage={}
    for kind,top in (('full','bt_bg_scroll_full_tb'),('raw','bt_bg_scroll_raw_tb'),('pixel','bt_pixel_parallel_tb')):
        runs[kind]=run_command([SIM/'vsim.exe','-c','-lib','work',top,'-do','run -all; quit -f'],out,out/f'{kind}.log')
        coverage[kind]=parse_counts(kind,(out/f'{kind}.log').read_text())
    for record in commands+list(runs.values()):retained[record['log']]=record['log_sha256']
    retained[str(args.edge.resolve()/'manifest.json')]=sha((args.edge/'manifest.json').read_bytes())
    for item in manifest['files'].values():retained[item['parent']]=item['parent_sha256'];retained[item['candidate']]=item['candidate_sha256']
    for executable in ('vlib.exe','vlog.exe','vsim.exe'):path=SIM/executable;retained[str(path)]=sha(path.read_bytes())
    rec=dict(schema='bt-v23-bg-scroll-MEM-qualification-v1',status='PASS_ACTUAL_BG_SCROLL_AND_PIXEL',edge_directory=str(args.edge.resolve()),
      compiled_inputs=prep['compiled_inputs'],commands=commands,runs=runs,coverage=coverage,retained_files=retained,
      source_and_fixture_projection=detail,no_masks_or_exclusions=True,old_RAM_storage_and_packet_body_unchanged=True,
      consumer_clock_edges_and_latency_unchanged=True,mapped_or_timing_qualified=False)
    path=out/'receipt.json';path.write_text(json.dumps(rec,indent=2)+'\n');verified=verify_composition_receipt(path)
    (out/'verification.json').write_text(json.dumps(verified,indent=2)+'\n');print(json.dumps(verified))
if __name__=='__main__':main()
