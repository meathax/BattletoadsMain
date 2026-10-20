"""Actual ModelSim BG, pixel-process, and four-state same-D qualification."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SIM = Path('D:/q17/modelsim_ase/win32aloem')
PREPARER = ROOT/'tests/graphics/prepare_bt_bg_pixel_predicates.py'
PIXEL_HELPER = ROOT/'tests/graphics/qualify_bt_pixel_parallel.py'
PIXEL_HELPER_SHA = '8882e16f57bcf680c47c6d21a8bc9559005e60d54e23fe018b0202bca94bb9c2'
RAM_MODEL = ROOT/'tests/graphics/ram_models.sv'
RAM_SHA = '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def load(path, name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

def canonical(raw):
    return raw.decode().replace('\r\n','\n')

FULL_BENCH = r'''module bt_bg_predicate_full_tb;
  logic CLK=0,CPU_CLK=0,RST_N=1;
  logic [15:0] A=0,D=0;logic[14:0] CPU_A=0;
  logic RAS_N=1,WE_N=1,OE_N=1,TRANSFER=0,SC=1,SE_N=0;
  logic[1:0] CAS_N=3;
  wire[15:0] old_q,new_q;wire[7:0] old_sq,new_sq;
  wire old_rdy,new_rdy,old_grid,new_grid;wire new_nz,new_high;
  integer pre=0,post=0,writes=0,refreshes=0,shifts=0,resets=0;
  BG_VRAM_REFERENCE old_i(CLK,CPU_CLK,RST_N,A,CPU_A,D,old_q,RAS_N,CAS_N,
    WE_N,OE_N,TRANSFER,old_rdy,SC,SE_N,old_sq,old_grid);
  BG_VRAM new_i(CLK,CPU_CLK,RST_N,A,CPU_A,D,new_q,RAS_N,CAS_N,
    WE_N,OE_N,TRANSFER,new_rdy,SC,SE_N,new_sq,new_grid,new_nz,new_high);
  task automatic compare;
    bit[7:0] coerced;
    begin
      coerced=new_sq;
      if({old_q,old_sq,old_rdy,old_grid} !== {new_q,new_sq,new_rdy,new_grid})
        $fatal(1,"BG legacy outputs changed pre=%0d post=%0d",pre,post);
      if(new_nz !== (|coerced) || new_high !== coerced[7])
        $fatal(1,"BG registered predicate mismatch sq=%h nz=%b high=%b",new_sq,new_nz,new_high);
      if({old_i.LINE_CACHE_RA,old_i.VIDEO_WORD,old_i.VIDEO_LANE,old_i.VIDEO_LANE_OH,
          old_i.SREG_ROW,old_i.SREG_COL,old_i.MRT_EXEC,old_i.RMT_EXEC,old_i.COPY_NEXT,
          old_i.COPY_WADDR,old_i.COPY_RUN,old_i.COPY_VALID,old_i.COPY_VALID2,
          old_i.COPY_WADDR2,old_i.RAM_SQ_R,old_i.RAM_SA,old_i.RAM_ADDR_M,
          old_i.WRITE_PENDING,old_i.WRITE_DATA,old_i.WRITE_BE,old_i.WRITE_ADDR,
          old_i.WRITE_TOGGLE,old_i.WRITE_TOGGLE_M,old_i.WRITE_SEEN,old_i.CPU_RST_N}
        !== {new_i.LINE_CACHE_RA,new_i.VIDEO_WORD,new_i.VIDEO_LANE,new_i.VIDEO_LANE_OH,
          new_i.SREG_ROW,new_i.SREG_COL,new_i.MRT_EXEC,new_i.RMT_EXEC,new_i.COPY_NEXT,
          new_i.COPY_WADDR,new_i.COPY_RUN,new_i.COPY_VALID,new_i.COPY_VALID2,
          new_i.COPY_WADDR2,new_i.RAM_SQ_R,new_i.RAM_SA,new_i.RAM_ADDR_M,
          new_i.WRITE_PENDING,new_i.WRITE_DATA,new_i.WRITE_BE,new_i.WRITE_ADDR,
          new_i.WRITE_TOGGLE,new_i.WRITE_TOGGLE_M,new_i.WRITE_SEEN,new_i.CPU_RST_N})
        $fatal(1,"BG old state/physical RAM pin contract changed");
    end
  endtask
  task automatic tick(input bit cpu);
    begin
      compare;pre=pre+1;#2;CLK=1;if(cpu) CPU_CLK=1;
      #1;compare;post=post+1;CLK=0;CPU_CLK=0;#1;
    end
  endtask
  task automatic cpu_tick;
    begin tick(1);tick(0);end
  endtask
  integer row,col,mask,i;
  initial begin
    // Test the unreset startup before any clock; old SQ is four-state unknown.
    #1;compare;RST_N=0;#1;compare;tick(1);tick(0);RST_N=1;
    repeat(4) cpu_tick;
    for(row=0;row<16;row=row+1) begin
      for(col=0;col<256;col=col+1) begin
        CPU_A={row[6:0],col[7:0]};D={8'(col^row),8'(~col)};
        CAS_N=col[1:0];RAS_N=0;OE_N=1;WE_N=1;cpu_tick;
        WE_N=0;cpu_tick;WE_N=1;repeat(5) cpu_tick;writes=writes+1;
      end
      A={row[7:0],8'h00};RAS_N=1;WE_N=1;OE_N=0;TRANSFER=1;
      repeat(2) cpu_tick;RAS_N=0;repeat(50) cpu_tick;refreshes=refreshes+1;
      RAS_N=1;TRANSFER=0;OE_N=1;
      for(col=0;col<256;col=col+1) begin
        SC=1;repeat(3) cpu_tick;SC=0;repeat(5) cpu_tick;shifts=shifts+1;
        CPU_A={row[6:0],col[7:0]};tick(0);
      end
      if(row[1:0]==3) begin
        #1;RST_N=0;#1;compare;resets=resets+1;
        SC=1;tick(0);tick(1);RST_N=1;repeat(4) cpu_tick;
      end
    end
    // Independent CPU edges, memory edges, and raw four-state command inputs.
    for(i=0;i<1024;i=i+1) begin
      A=i*137;CPU_A=i*71;D=i*97;CAS_N=i[1:0];
      RAS_N=i[0]?1'bx:1'bz;OE_N=i[1]?1'bz:1'bx;
      WE_N=i[2]?1'bx:1'bz;TRANSFER=i[3]?1'bz:1'bx;SC=i[4]?1'bx:1'bz;
      #1;CPU_CLK=1;#1;compare;CPU_CLK=0;tick(0);tick(i[0]);
    end
    $display("BG_FULL_PREDICATES_PASS pre=%0d post=%0d writes=%0d refreshes=%0d shifts=%0d resets=%0d",pre,post,writes,refreshes,shifts,resets);
    $finish;
  end
endmodule
'''

RAW_BENCH = r'''module bt_bg_predicate_raw_tb;
  logic CLK=0,RST_N=1;logic [63:0] VIDEO_WORD=0;logic[7:0] VIDEO_LANE_OH=1;
  wire[7:0] old_sq,new_sq;wire new_nz,new_high;
  bt_bg_raw_old old_i(CLK,RST_N,VIDEO_WORD,VIDEO_LANE_OH,old_sq);
  bt_bg_raw_new new_i(CLK,RST_N,VIDEO_WORD,VIDEO_LANE_OH,new_sq,new_nz,new_high);
  integer checks=0,bytes=0,masks=0,resets=0,stale_mutant_hits=0;
  bit stale_nz=0;bit[7:0] coerced;
  function automatic logic four(input integer v);
    case(v) 0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
  endfunction
  task automatic tick;
    begin
      stale_nz=|coerced;#1;CLK=1;#1;coerced=old_sq;checks=checks+1;
      if(old_sq !== new_sq || new_nz !== (|coerced) || new_high !== coerced[7])
        $fatal(1,"RAW BG predicate mismatch check=%0d old=%h new=%h nz=%b high=%b",checks,old_sq,new_sq,new_nz,new_high);
      if(stale_nz != new_nz) stale_mutant_hits=stale_mutant_hits+1;
      CLK=0;#1;
    end
  endtask
  integer v,j,lane,mask,p;
  logic[7:0] value;
  initial begin
    #1;coerced=old_sq;
    if(new_nz !== (|coerced) || new_high !== coerced[7]) $fatal(1,"RAW startup bit identity");
    RST_N=0;#1;tick;RST_N=1;
    for(v=0;v<65536;v=v+1) begin
      for(j=0;j<8;j=j+1) value[j]=four((v>>(j*2))&3);
      VIDEO_WORD={8{value}};
      for(lane=0;lane<8;lane=lane+1) begin
        VIDEO_LANE_OH=8'b1<<lane;tick;bytes=bytes+1;
      end
    end
    // The widened word/mask abstraction is a superset of the real bit state.
    for(mask=0;mask<65536;mask=mask+1) begin
      for(j=0;j<8;j=j+1) VIDEO_LANE_OH[j]=four((mask>>(j*2))&3);
      VIDEO_WORD=mask[0]?64'h8100000020000001:64'hzzxx00xxzz000000;
      tick;masks=masks+1;
    end
    for(p=0;p<256;p=p+1) begin
      #1;RST_N=0;#1;
      if(old_sq !== 0 || new_sq !== 0 || new_nz !== 0 || new_high !== 0) $fatal(1,"RAW asynchronous reset");
      VIDEO_WORD={8{8'(p)}};tick;RST_N=1;tick;resets=resets+1;
    end
    if(stale_mutant_hits==0) $fatal(1,"old-SQ extra-edge mutant not detected");
    $display("BG_RAW_PREDICATES_PASS checks=%0d bytes=%0d masks=%0d resets=%0d stale_mutant_hits=%0d",checks,bytes,masks,resets,stale_mutant_hits);
    $finish;
  end
endmodule
'''

def pixel_scope(text):
    begin=text.index('\tfunction automatic bit [7:0] BT_SELECT_PIXEL;')
    declaration=re.search(r'(?m)^[ \t]*bit\s+\[\s*7\s*:\s*0\s*\]\s+PIX_OUT;',text[begin:])
    if declaration is None:
        raise AssertionError('missing original PIX_OUT declaration')
    at=begin+declaration.start()
    always_at=text.index('\talways @(posedge CLK or negedge RST_N) begin',at)
    # These nested cases contain no begin/end except bank branches; parse keywords.
    tokens=list(re.finditer(r'\bbegin\b|\bend\b',text[always_at:]))
    depth=0
    for token in tokens:
        depth+=1 if token.group()=='begin' else -1
        if depth==0:
            return text[begin:always_at+token.end()]+'\n'
    raise AssertionError('unclosed pixel process')

def generated_inputs(edge):
    p=load(PREPARER,'bg_predicate_preparer')
    files,manifest=p.verify_edge(edge)
    if sha(PIXEL_HELPER.read_bytes())!=PIXEL_HELPER_SHA or sha(RAM_MODEL.read_bytes())!=RAM_SHA:
        raise AssertionError('immutable fixture/model changed')
    pixel=load(PIXEL_HELPER,'old_pixel_fixture')
    old_bg,new_bg,_=files['rtl/bg_vram.sv'];old_bt,new_bt,_=files['rtl/BT.sv']
    old=canonical(old_bg);new=canonical(new_bg)
    rhs=re.search(r'\t\t\tSQ <= (\(.*?);',old,re.S).group(1)
    wire=re.search(r'\twire \[7:0\] SERIAL_BYTE_D = (.*?);',new,re.S).group(1)
    if rhs!=wire:
        raise AssertionError('registered predicates must use exact original SQ D')
    hdr='(input logic CLK,RST_N,input logic[63:0] VIDEO_WORD,input logic[7:0] VIDEO_LANE_OH,output logic[7:0] SQ'
    raw_old='module bt_bg_raw_old'+hdr+');\n'+f"always @(posedge CLK or negedge RST_N) if(!RST_N) SQ <= '0; else SQ <= {rhs};\nendmodule\n"
    raw_new='module bt_bg_raw_new'+hdr+',output bit SQ_NZ,SQ_HIGH);\n'
    raw_new+='wire[7:0] SERIAL_BYTE_D = '+wire+';\n'
    nz_wire=re.search(r'\twire SERIAL_NZ_D = (.*?);',new,re.S).group(1)
    raw_new+='wire SERIAL_NZ_D = '+nz_wire+';\n'
    # Copy the actual SQ and two predicate capture/reset statements, exactly.
    reset=re.search(r"\t\t\tSQ <= '0;\n\t\t\tSQ_NZ <= 1'b0;\n\t\t\tSQ_HIGH <= 1'b0;",new).group()
    capture=re.search(r'\t\t\tSQ <= SERIAL_BYTE_D;\n\t\t\tSQ_NZ <= SERIAL_NZ_D;\n\t\t\tSQ_HIGH <= SERIAL_BYTE_D\[7\];',new).group()
    raw_new+='always @(posedge CLK or negedge RST_N) begin if(!RST_N) begin\n'+reset+'\nend else begin\n'+capture+'\nend end\nendmodule\n'
    # The driver below supplies the exact bit-coerced predicate of each raw bank.
    # Full BG and raw same-D tests independently prove the physical registered source.
    driver='''bit [1:0] BG0_SQ_NZ,BG0_SQ_HIGH,BG1_SQ_NZ,BG1_SQ_HIGH;
always_comb begin
  bit[7:0] b00,b01,b10,b11;
  b00=BG0_SQ[7:0];b01=BG0_SQ[15:8];b10=BG1_SQ[7:0];b11=BG1_SQ[15:8];
  BG0_SQ_NZ={|b01,|b00};BG0_SQ_HIGH={b01[7],b00[7]};
  BG1_SQ_NZ={|b11,|b10};BG1_SQ_HIGH={b11[7],b10[7]};
end
'''
    pix_old='module bt_pixel_old'+pixel.HEADER.decode()+pixel_scope(canonical(old_bt))+'assign RESULT=PIX_OUT;\nendmodule\n'
    pix_new='module bt_pixel_new'+pixel.HEADER.decode()+driver+pixel_scope(canonical(new_bt))+'assign RESULT=PIX_OUT;\nendmodule\n'
    return {
        'bg_vram.sv':new_bg,'reference-bg_vram.sv':old_bg.replace(b'module BG_VRAM (',b'module BG_VRAM_REFERENCE (',1),
        'ram_models.sv':RAM_MODEL.read_bytes(),
        'bt_bg_predicate_full_tb.sv':FULL_BENCH.encode(),
        'bt_bg_predicate_raw_tb.sv':(raw_old+raw_new+RAW_BENCH).encode(),
        'bt_bg_predicate_pixel_tb.sv':(pix_old+pix_new+pixel.BENCH).encode(),
    },manifest

def run_command(argv,cwd,log):
    start=time.time()
    with log.open('w',encoding='utf8') as f:
        result=subprocess.run([str(x) for x in argv],cwd=cwd,stdout=f,stderr=subprocess.STDOUT)
    record=dict(argv=[str(x) for x in argv],cwd=str(cwd),exit_code=result.returncode,
                log=str(log),log_sha256=sha(log.read_bytes()),elapsed_seconds=round(time.time()-start,3))
    if result.returncode!=0 or re.search(r'\*\*\s+(?:Error|Fatal)|\$fatal|Error loading design',log.read_text(errors='replace')):
        raise RuntimeError(json.dumps(record))
    return record

def parse_counts(text,kind):
    patterns={
        'full':r'BG_FULL_PREDICATES_PASS pre=(\d+) post=(\d+) writes=(\d+) refreshes=(\d+) shifts=(\d+) resets=(\d+)',
        'raw':r'BG_RAW_PREDICATES_PASS checks=(\d+) bytes=(\d+) masks=(\d+) resets=(\d+) stale_mutant_hits=(\d+)',
        'pixel':r'PIXEL_PARALLEL_PASS checks=(\d+) categories=(\d+) values=(\d+) unknowns=(\d+) resets=(\d+)',
    }
    matches=re.findall(patterns[kind],text)
    if len(matches)!=1:
        raise AssertionError(f'exact single {kind} coverage marker required')
    values=tuple(int(x) for x in matches[0])
    if kind=='full' and (values[0]!=values[1] or values[0]<100000 or values[2:]!=(4096,16,4096,4)):
        raise AssertionError('full BG coverage changed')
    if kind=='raw' and (values[:4]!=(590337,524288,65536,256) or values[4]==0):
        raise AssertionError('raw four-state coverage changed')
    if kind=='pixel' and values!=(234241,4608,98304,131072,128):
        raise AssertionError('all original pixel assertions/stimulus required')
    return values

def verify_composition_receipt(path):
    path=Path(path).resolve();receipt=json.loads(path.read_text())
    if receipt['status']!='PASS_ACTUAL_BG_PIXEL_AND_FOUR_STATE' or receipt['schema']!='bt-v22-bg-pixel-predicate-qualification-v1':
        raise AssertionError('wrong proof receipt')
    for name,record in receipt['retained_files'].items():
        if sha(Path(name).read_bytes())!=record:
            raise AssertionError(f'changed proof artifact {name}')
    regenerated,manifest=generated_inputs(receipt['edge_directory'])
    for name,data in regenerated.items():
        compiled=Path(receipt['compiled_inputs'][name]['path'])
        if compiled.read_bytes()!=data or sha(data)!=receipt['compiled_inputs'][name]['sha256']:
            raise AssertionError('exact compiled input reproduction failed')
    coverage={}
    tops={'full':'bt_bg_predicate_full_tb','raw':'bt_bg_predicate_raw_tb','pixel':'bt_pixel_parallel_tb'}
    compiled_dir=Path(next(iter(receipt['compiled_inputs'].values()))['path']).parent
    expected_commands=[[str(SIM/'vlib.exe'),'work'],
                       [str(SIM/'vlog.exe'),'-sv','-work','work']+
                       [str(compiled_dir/name) for name in regenerated]]
    if len(receipt['commands'])!=2:
        raise AssertionError('actual library and compiler commands required')
    for record,expected in zip(receipt['commands'],expected_commands):
        if record['exit_code']!=0 or record['argv']!=expected or Path(record['cwd'])!=path.parent:
            raise AssertionError('actual compilation command/exit changed')
        if re.search(r'\*\*\s+(?:Error|Fatal)|Error loading design',Path(record['log']).read_text()):
            raise AssertionError('actual compilation failed')
    for kind,record in receipt['runs'].items():
        if record['exit_code']!=0 or record['argv']!=[str(SIM/'vsim.exe'),'-c','-lib','work',tops[kind],'-do','run -all; quit -f']:
            raise AssertionError('wrong actual simulator command/exit')
        text=Path(record['log']).read_text()
        if re.search(r'\*\*\s+(?:Error|Fatal)|\$fatal|Error loading design',text):
            raise AssertionError('simulator failure')
        coverage[kind]=parse_counts(text,kind)
    if set(coverage)!=set(tops) or receipt['coverage']!={k:list(v) for k,v in coverage.items()}:
        raise AssertionError('coverage receipt changed')
    return dict(status='PASS_ACTUAL_BG_PIXEL_AND_FOUR_STATE',coverage=coverage,
                source_files={rel:m['candidate_sha256'] for rel,m in manifest['files'].items()},
                no_new_clock_edge=True,old_fixture_assertions_and_stimulus_retained=True,
                physical_ram_body_unchanged=True,mapped_or_timing_qualified=False)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--edge',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--prepare-only',action='store_true')
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    compiled=out/'compiled-inputs';compiled.mkdir();helpers=out/'executed-helpers';helpers.mkdir()
    inputs,manifest=generated_inputs(args.edge)
    for name,data in inputs.items(): (compiled/name).write_bytes(data)
    retained={}
    for helper in (Path(__file__),PREPARER,PIXEL_HELPER):
        target=helpers/helper.name;target.write_bytes(helper.read_bytes());retained[str(target)]=sha(target.read_bytes())
    preparation=dict(schema='bt-v22-bg-pixel-predicate-preparation-v1',edge_directory=str(args.edge.resolve()),
                     edge_manifest_sha256=sha((args.edge/'manifest.json').read_bytes()),
                     compiled_inputs={name:dict(path=str(compiled/name),sha256=sha(data)) for name,data in inputs.items()},
                     executed_helpers=retained,
                     adaptations=['reference module namespace only; raw full BG body unchanged',
                                  'actual pixel function/process extracted; original pixel bench byte-identical',
                                  'pixel harness drives per-bank bit-coerced predicates; full BG separately proves physical captures',
                                  'raw SQ D word/mask types widened to four-state, exact old/new SQ expressions/captures retained'],
                     exclusions=[],timing_qualified=False)
    prep=out/'preparation.json';prep.write_text(json.dumps(preparation,indent=2)+'\n')
    if args.prepare_only:
        print(json.dumps(dict(status='PREPARED_ONLY',preparation=str(prep),sha256=sha(prep.read_bytes()))));return
    commands=[]
    commands.append(run_command([SIM/'vlib.exe','work'],out,out/'vlib.log'))
    commands.append(run_command([SIM/'vlog.exe','-sv','-work','work']+[compiled/name for name in inputs],out,out/'compile.log'))
    runs={};coverage={}
    for kind,top in (('full','bt_bg_predicate_full_tb'),('raw','bt_bg_predicate_raw_tb'),('pixel','bt_pixel_parallel_tb')):
        runs[kind]=run_command([SIM/'vsim.exe','-c','-lib','work',top,'-do','run -all; quit -f'],out,out/f'{kind}.log')
        coverage[kind]=parse_counts((out/f'{kind}.log').read_text(),kind)
    for item in inputs:retained[str(compiled/item)]=sha((compiled/item).read_bytes())
    for record in commands+list(runs.values()):retained[record['log']]=record['log_sha256']
    retained[str(prep)]=sha(prep.read_bytes());retained[str(args.edge.resolve()/'manifest.json')]=sha((args.edge/'manifest.json').read_bytes())
    for record in manifest['files'].values():
        retained[record['parent']]=record['parent_sha256'];retained[record['candidate']]=record['candidate_sha256']
    for helper in (Path(__file__).resolve(),PREPARER,PIXEL_HELPER):retained[str(helper)]=sha(helper.read_bytes())
    for executable in (SIM/'vlib.exe',SIM/'vlog.exe',SIM/'vsim.exe'):
        retained[str(executable)]=sha(executable.read_bytes())
    receipt=dict(schema='bt-v22-bg-pixel-predicate-qualification-v1',status='PASS_ACTUAL_BG_PIXEL_AND_FOUR_STATE',
                 edge_directory=str(args.edge.resolve()),compiled_inputs=preparation['compiled_inputs'],
                 commands=commands,runs=runs,coverage=coverage,retained_files=retained,
                 no_new_clock_edge=True,no_masks_or_exclusions=True,
                 old_bg_ram_storage_and_packet_body_unchanged=True,mapped_or_timing_qualified=False)
    target=out/'receipt.json';target.write_text(json.dumps(receipt,indent=2)+'\n')
    verify_composition_receipt(target)
    print(json.dumps(dict(status=receipt['status'],receipt=str(target),sha256=sha(target.read_bytes()),coverage=coverage)))

if __name__=='__main__':main()
