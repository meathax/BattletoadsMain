"""Current FG selectors/segments and BG capture pins with Intel's exact RAM model.

Retains immutable b537 RTL and the existing full-width/sixteen-bank oracle.
Uses at most two native ModelSim jobs. Fresh receipts preserve physical modes,
contract-defined canonical data, exact before/candidate collision X masks and latency.
No Quartus, RBF, global gate edits, or historical receipt relabeling.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
ORACLE = 'b53726397822b9dbebb02d36411294056fd08649'
VENDOR = Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA = 'c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'
IVERILOG = Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin/iverilog.exe')
VVP = Path('D:/vibes/fpga/toolchains/msys64/ucrt64/bin/vvp.exe')
MODELSIM = Path('D:/q17/modelsim_ase/win32aloem')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def once(text, old, new):
    if text.count(old) != 1:
        raise ValueError('fixture guard failed: '+repr(old[:120]))
    return text.replace(old, new, 1)


def module(text, name):
    start = re.search(r'^module\s+'+re.escape(name)+r'\b', text, re.M)
    if start is None:
        raise ValueError('module absent: '+name)
    end = re.search(r'^endmodule\b', text[start.start():], re.M)
    if end is None:
        raise ValueError('endmodule absent: '+name)
    return text[start.start():start.start()+end.end()]+'\n'


def renamed(text, names, suffix):
    for name in sorted(names, key=len, reverse=True):
        text=re.sub(r'\b'+re.escape(name)+r'\b',name+suffix,text)
    return text


def canonical_contract_masks(text, label, address, a_write, b_write, qa_reg, sq_reg, a_group):
    # The canonical full-width AUTO model can publish defined zero for data
    # which its declared RDW mode leaves unspecified. Never exclude a bit
    # from the exact immutable-before physical data/X comparison.
    declarations = '''    wire [15:0] canonical_q_mask_now =
      (16'hff00 & {16{(%s) && !be[1]}}) |
      (16'h00ff & {16{(%s) && !be[0]}}) |
      {16{(%s) && (%s)==%s}};
    wire [63:0] canonical_sq_mask_now =
      ((%s) && !(%s) && (%s)==%s) ? (64'hffff << (16*a[2:1])) : 64'b0;
    reg [15:0] canonical_q_mask_1=0,canonical_q_mask_2=0;
    reg [63:0] canonical_sq_mask_1=0,canonical_sq_mask_2=0;
    always @(posedge CLK) begin
      canonical_q_mask_1<=canonical_q_mask_now;
      canonical_q_mask_2<=canonical_q_mask_1;
      canonical_sq_mask_1<=canonical_sq_mask_now;
      canonical_sq_mask_2<=canonical_sq_mask_1;
    end
    wire [15:0] canonical_q_mask=%s;
    wire [63:0] canonical_sq_mask=%s;
    integer canonical_q_excluded_bits=0,canonical_sq_excluded_bits=0;
''' % (a_write,a_write,b_write,address,a_group,a_write,b_write,address,a_group,
       'canonical_q_mask_2' if qa_reg else 'canonical_q_mask_now',sq_reg)
    prefix='    integer cycles=0,known_bits=0,undefined_bits=0'
    text=once(text,prefix,declarations+prefix)
    text=once(text,"                if(qr[bit_index]===1'b0 || qr[bit_index]===1'b1) begin",
        "                if(canonical_q_mask[bit_index]) canonical_q_excluded_bits++;\n"
        "                else if(qr[bit_index]===1'b0 || qr[bit_index]===1'b1) begin")
    text=once(text,"                if(sqr[bit_index-16]===1'b0 || sqr[bit_index-16]===1'b1) begin",
        "                if(canonical_sq_mask[bit_index-16]) canonical_sq_excluded_bits++;\n"
        "                else if(sqr[bit_index-16]===1'b0 || sqr[bit_index-16]===1'b1) begin")
    text=once(text,'        done=1;',
        '        $display("PASS canonical RDW contract '+label+': excluded_Q_bits=%0d excluded_SQ_bits=%0d; actual-before physical data/X comparisons have no exclusions",canonical_q_excluded_bits,canonical_sq_excluded_bits);\n'
        '        done=1;')
    return text


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--fg-source',type=Path,default=ROOT/'rtl/fg_vram.sv')
    parser.add_argument('--memory-source',type=Path,default=ROOT/'rtl/BT_mem.sv')
    parser.add_argument('--bg-source',type=Path,default=ROOT/'rtl/bg_vram.sv')
    parser.add_argument('--simulator',choices=['modelsim','iverilog'],default='modelsim')
    args=parser.parse_args()
    identifier='vram-current-'+uuid.uuid4().hex
    workspace=ROOT/'build/resource_audit'/identifier
    evidence=ROOT/'tests/graphics/evidence/vram-physical'/identifier
    workspace.mkdir(parents=True);evidence.mkdir(parents=True)
    sources={};actual_paths={};fixtures={}
    files={}
    for role,path in [('rtl/fg_vram.sv',args.fg_source),('rtl/BT_mem.sv',args.memory_source),('rtl/bg_vram.sv',args.bg_source)]:
        path=path.resolve();data=path.read_bytes();sources[role]=sha(data);actual_paths[role]=str(path)
        target=workspace/'canonical'/role;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        files[role]=data.decode('utf-8').replace('\r\n','\n')
    if sha(VENDOR.read_bytes())!=VENDOR_SHA:
        raise ValueError('Intel model fingerprint differs from the retained contract')
    oracle_files={}
    for name in ['rtl/fg_vram.sv','rtl/BT_mem.sv','rtl/bg_vram.sv','tests/vram_slice_tb.sv']:
        data=subprocess.check_output(['git','show',ORACLE+':'+name],cwd=ROOT)
        target=workspace/'oracle'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
        fixtures[str(target.relative_to(ROOT)).replace('\\','/')]=sha(data)
        oracle_files[name]=data.decode('utf-8').replace('\r\n','\n')
    current_test=(ROOT/'tests/vram_slice_tb.sv').read_bytes()
    if current_test.replace(b'\r\n',b'\n')!=oracle_files['tests/vram_slice_tb.sv'].encode('utf-8'):
        raise ValueError('retained canonical sixteen-bank fixture differs from immutable b537')
    sources['tests/vram_slice_tb.sv']=sha(current_test)
    adapter=ROOT/'tests/graphics/ram_models.sv'
    adapter_data=adapter.read_bytes()
    sources['tests/graphics/ram_models.sv']=sha(adapter_data)
    target=workspace/'canonical/tests/graphics/ram_models.sv'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(adapter_data)
    fixtures[str(target.relative_to(ROOT)).replace('\\','/')]=sha(adapter_data)
    runner=Path(__file__).resolve();sources['tests/graphics/qualify_current_vram_vendor.py']=sha(runner.read_bytes())
    proof_helper=ROOT/'tests/graphics/qualify_bg_port_address.py'
    sources['tests/graphics/qualify_bg_port_address.py']=sha(proof_helper.read_bytes())
    spec=importlib.util.spec_from_file_location('current_bg_vendor_fixture',proof_helper)
    imported=importlib.util.module_from_spec(spec);spec.loader.exec_module(imported)

    memory='\n'.join(module(files['rtl/BT_mem.sv'],n) for n in ['VRAM_MEM_64Kx8','VRAM_MEM_SLICE'])
    baseline_memory='\n'.join(module(oracle_files['rtl/BT_mem.sv'],n) for n in ['VRAM_MEM_64Kx8','VRAM_MEM_SLICE'])
    baseline_memory=renamed(baseline_memory,['VRAM_MEM_64Kx8','VRAM_MEM_SLICE'],'_BASELINE')
    fg=module(files['rtl/fg_vram.sv'],'BT_FG_BANKED_VRAM')
    baseline_fg=renamed(module(oracle_files['rtl/fg_vram.sv'],'BT_FG_BANKED_VRAM'),
        ['BT_FG_BANKED_VRAM','VRAM_MEM_64Kx8'],'_BASELINE')
    segment_pre='SERIAL_SEGMENT_PRE' in memory
    bank=module(oracle_files['tests/vram_slice_tb.sv'],'vram_bank_case')
    bank=once(bank,'module vram_bank_case(', 'module current_vram_bank_case(')
    bank=once(bank,'    wire [15:0] qc,qr;',
        '    wire [15:0] qc,qbase,qlegacy;\n    reg [15:0] qr=0;\n    always @(posedge CLK) qr<=qlegacy;')
    bank=once(bank,'    wire [63:0] sqc,sqr;',
        '    wire [63:0] sqc,sqr,sqbase,sqdc,sqdbase;\n'
        '    reg prefetch=0,copy_we=0,copy_we_r=0;\n'
        '    always @(posedge CLK) copy_we_r<=copy_we;\n'
        '    wire [15:3] copyaddr_next=copyaddr+13\'d1;\n'
        '    wire [15:3] copyaddr_selected=prefetch ? copyaddr_next : copyaddr;\n'
        '    wire [3:0] bank_write,serial_write;\n'
        '    wire [3:0][1:0] lane_write;\n'
        '    wire [3:0][3:0] serial_segments;\n'
        '    for(genvar b=0;b<4;b++) begin\n'
        '      assign bank_write[b]=|banks[b*4+:4];\n'
        '      assign lane_write[b]={2{bank_write[b]}} & be;\n'
        '      assign serial_write[b]=swsel && swaddr[15:14]==b;\n'
        '      for(genvar s=0;s<4;s++) assign serial_segments[b][s]=serial_write[b] && swaddr[13:12]==s;\n'
        '    end\n'
        '    integer bank_reads[4],segment_reads[4],segment_writes[4][4],mask_hits[4];\n'
        '    integer prefetch_reads=0,copy_reads=0,video_reads=0,suppressed_reads=0,exact_x_checks=0;')
    old_candidate=('    BT_FG_BANKED_VRAM cand(CLK,a,d,banks,be,qc,swaddr,copyaddr,videoaddr,wb4,\n'
        '        {4{srsel}},{4{swsel}},dc,ds,{4{scsel}},sqc);')
    ports=('        .CLK(CLK),.ADDR(a),.ADDR_B({4{a}}),.DATA_B({4{d}}),.DATA(d),.BANK_WREN(banks),.BE(be),.Q(Q_OUTPUT),\n'
        '        .SADDR_W(swaddr),.SADDR_C(copyaddr),.SADDR_V(videoaddr),.SADDR_WB(wb4),\n'
        '        .SRSEL({4{srsel}}),.SWSEL({4{swsel}}),.SWREN_B(serial_write),.SDATA_C(dc),.SDATA_S(ds),\n'
        '        .SCSEL({4{scsel}}),.SCSEL4({16{scsel}}),.SQ(SQ_OUTPUT),.SQ_D(SQD_OUTPUT),.COPY_WE_NEXT(copy_we),\n'
        '        .SADDR_CN(copyaddr_next),.SADDR_VB({4{videoaddr[13:3]}}),.SADDR_CB({4{copyaddr[13:3]}}),\n'
        '        .SADDR_CNB({4{copyaddr_next[13:3]}}),.COPY_PREFETCH_B({4{prefetch}}),\n'
        '        .BANK_WREN_PRE(bank_write),.BANK_LANE_WREN_PRE(lane_write)')
    cp=ports.replace('SQD_OUTPUT','sqdc').replace('SQ_OUTPUT','sqc').replace('Q_OUTPUT','qc')
    bp=ports.replace('SQD_OUTPUT','sqdbase').replace('SQ_OUTPUT','sqbase').replace('Q_OUTPUT','qbase')
    if '.SQ(sqc)' not in cp or '.SQ(sqbase)' not in bp or '_OUTPUT' in cp+bp:
        raise ValueError('foreground named-output fixture binding differs')
    extra_param=',.SERIAL_SEGMENT_PRE(1)' if segment_pre else ''
    extra_port=',.SWREN_SEG_B(serial_segments)' if segment_pre else ''
    bank=once(bank,old_candidate,
        '    BT_FG_BANKED_VRAM #(.QA_REG(1),.COPY_PREFETCH_LOCAL(1),.BANK_WRITE_PREDECODED(1)'+extra_param+') cand(\n'+cp+extra_port+');\n'
        '    BT_FG_BANKED_VRAM_BASELINE #(.QA_REG(1),.COPY_PREFETCH_LOCAL(1),.BANK_WRITE_PREDECODED(1)) actual_before(\n'+bp+');')
    bank=once(bank,'ref_ram(CLK,a,d,banks,be,qr,swaddr,copyaddr,videoaddr,wb16,',
        'ref_ram(CLK,a,d,banks,be,qlegacy,swaddr,copyaddr_selected,videoaddr,wb16,')
    bank=once(bank,'        @(posedge CLK); #1;',
        '        @(posedge CLK); #1;\n'
        '        if({qc,sqc,sqdc} !== {qbase,sqbase,sqdbase})\n'
        '          $fatal(1,"current FG physical-model data/X mask differs from immutable before cycle=%0d",cycles);\n'
        '        if(cycles>=2 && sqdc !== (sqc & {64{!copy_we_r}}))\n'
        '          $fatal(1,"current FG copy suppression capture edge differs cycle=%0d",cycles);\n'
        '        exact_x_checks++;bank_reads[a[15:14]]++;segment_reads[a[13:12]]++;mask_hits[be]++;\n'
        '        if(swsel) segment_writes[swaddr[15:14]][swaddr[13:12]]++;\n'
        '        if(!swsel && srsel) begin copy_reads++;if(prefetch) prefetch_reads++;end\n'
        '        if(!swsel && !srsel) video_reads++;\n'
        '        if(copy_we_r) suppressed_reads++;')
    bank=once(bank,'        ignored=$urandom(seed);',
        '        for(integer b=0;b<4;b++) begin bank_reads[b]=0;segment_reads[b]=0;mask_hits[b]=0;\n'
        '          for(integer s=0;s<4;s++) segment_writes[b][s]=0;end\n'
        '        ignored=$urandom(seed);')
    bank=once(bank,'            if(qc !== pattern(c))','            if(c>0 && qc !== pattern(c-1))')
    bank=once(bank,'            srsel=$urandom; scsel=$urandom; dc={$urandom,$urandom}; ds={$urandom,$urandom};',
        '            srsel=$urandom; scsel=$urandom; prefetch=$urandom;copy_we=$urandom;dc={$urandom,$urandom};ds={$urandom,$urandom};')
    bank=once(bank,'            done=1;', '            done=1;') if '            done=1;' in bank else bank
    bank=once(bank,'        done=1;',
        '        for(integer b=0;b<4;b++) begin\n'
        '          if(bank_reads[b]<8000 || segment_reads[b]<8000 || mask_hits[b]<5000)\n'
        '            $fatal(1,"current FG bank/segment/mask coverage missing %0d",b);\n'
        '          for(integer s=0;s<4;s++) if(segment_writes[b][s]<50)\n'
        '            $fatal(1,"current FG serial bank/segment coverage missing %0d/%0d",b,s);\n'
        '        end\n'
        '        if(prefetch_reads<5000 || copy_reads<5000 || video_reads<5000 || suppressed_reads<10000 || exact_x_checks<95000)\n'
        '          $fatal(1,"current FG selector/copy suppression coverage missing");\n'
        '        $display("PASS current FG QSEL_EN1: exact_data_x_masks=%0d prefetch=%0d copy=%0d video=%0d suppression=%0d; all4banks/4segments/two lanes/four masks and original read/output edges",exact_x_checks,prefetch_reads,copy_reads,video_reads,suppressed_reads);\n'
        '        done=1;')
    bank=once(bank,'        if({qc,sqc,sqdc} !== {qbase,sqbase,sqdbase})',
        '        if({cand.bank_q,cand.bank_sq} !== {actual_before.bank_q,actual_before.bank_sq})\n'
        '          $fatal(1,"current FG every-bank physical data/X mask differs from immutable before cycle=%0d",cycles);\n'
        '        if({qc,sqc,sqdc} !== {qbase,sqbase,sqdbase})')
    bank=canonical_contract_masks(bank,'FG4banks',
        '(swsel ? swaddr : srsel ? copyaddr_selected : videoaddr)',
        'banks[a[15:12]]','swsel',True,'canonical_sq_mask_2','a[15:3]')
    primitive=module(oracle_files['tests/vram_slice_tb.sv'],'vram_slice_case')
    primitive=once(primitive,'    wire [15:0] qc,qr;',
        '    wire [15:0] qc,qr,qbase;')
    primitive=once(primitive,'    wire [63:0] sqc,sqr;',
        '    wire [63:0] sqc,sqr,sqbase;')
    primitive=once(primitive,'        (CLK,a,d,wa,be,qc,sa,sd,wb,sqc);',
        '        (.CLK(CLK),.ADDR(a),.DATA(d),.WREN(wa),.BE(be),.Q(qc),.SADDR(sa),.SDATA(sd),.SWREN(wb),.SQ(sqc),.SADDR_W(sa),.WREN_LANE({2{wa}} & be),.QGATE_D(1\'b1)'+
        (',.SWREN_SEGMENT({4{wb}} & (4\'b0001 << sa[AW-1:AW-2]))' if segment_pre else '')+');')
    primitive=once(primitive,'#(.ADDR_WIDTH(AW),.SQ_REG(SQ_REG)) cand',
        '#(.ADDR_WIDTH(AW),.SQ_REG(SQ_REG),.SERIAL_WRITE_DECODE(AW==14),.LANE_WREN_PRE(AW==14),.QSEL_EN(AW==14)'+
        (',.SERIAL_SEGMENT_PRE(AW==14)' if segment_pre else '')+') cand')
    primitive=once(primitive,'    VRAM_MEM_REF #(',
        '    VRAM_MEM_64Kx8_BASELINE #(.ADDR_WIDTH(AW),.SQ_REG(SQ_REG),.SERIAL_WRITE_DECODE(AW==14),.LANE_WREN_PRE(AW==14),.QSEL_EN(AW==14)) actual_before\n'
        '        (.CLK(CLK),.ADDR(a),.DATA(d),.WREN(wa),.BE(be),.Q(qbase),.SADDR(sa),.SDATA(sd),.SWREN(wb),.SQ(sqbase),.SADDR_W(sa),.WREN_LANE({2{wa}} & be),.QGATE_D(1\'b1));\n'
        '    VRAM_MEM_REF #(')
    primitive=once(primitive,'    task automatic check_outputs;',
        '    task automatic check_outputs;\n'
        '        if({qc,sqc} !== {qbase,sqbase})\n'
        '          $fatal(1,"current primitive AW%0d physical data/X mask differs from immutable before cycle=%0d",AW,cycles);')
    primitive=canonical_contract_masks(primitive,'primitive','sa','wa','wb',False,
        'SQ_REG ? canonical_sq_mask_2 : canonical_sq_mask_now','a[AW-1:3]')
    top='''module current_vram_vendor_tb;
  reg CLK=0;always #5 CLK=~CLK;
  wire bg_done,fg_done,bank_done;
  vram_slice_case #(.AW(16),.SQ_REG(0)) background(CLK,bg_done);
  vram_slice_case #(.AW(14),.SQ_REG(1),.SEED(32'h231954d1)) foreground(CLK,fg_done);
  current_vram_bank_case bank_mapping(CLK,bank_done);
  initial begin wait(bg_done && fg_done && bank_done);$display("PASS current Intel VRAM selectors/geometry/collision suite");$finish;end
  initial begin #2000000;$fatal(1,"current VRAM proof timeout");end
endmodule
'''
    vram_tb='`timescale 1ns/1ps\n'+module(oracle_files['tests/vram_slice_tb.sv'],'VRAM_MEM_REF')+primitive+bank+top+module(oracle_files['tests/vram_slice_tb.sv'],'BT_FG_BANKED_VRAM_16_REF')
    bg_tb=imported.BENCH
    for old,new in [('147456','16384'),('131072','8192'),('15\'(n>>2)','15\'((n>>2)*37)'),
        ('comparisons>290000','comparisons>32000'),('consuming_writes>20000','consuming_writes>2000'),
        ('resets>60','resets>28'),('refreshes>2000','refreshes>200'),
        ('segment_writes[s][l]>400','segment_writes[s][l]>25'),('masks[m]>2000','masks[m]>250')]:
        if old not in bg_tb:raise ValueError('BG workload guard failed '+old)
        bg_tb=bg_tb.replace(old,new)
    bg_ref=renamed(oracle_files['rtl/bg_vram.sv'],['BG_VRAM'],'_REFERENCE')
    bg_ref=renamed(bg_ref,['VRAM_MEM_64Kx8'],'_BASELINE')
    generated={'memory.sv':memory,'memory_baseline.sv':baseline_memory,'fg_banked.sv':fg,
        'fg_banked_baseline.sv':baseline_fg,'current_vram_vendor_tb.sv':vram_tb,
        'bg_candidate.sv':files['rtl/bg_vram.sv'],'bg_reference.sv':bg_ref,'bt_bg_port_address_tb.sv':bg_tb}
    for name,text in generated.items():
        path=workspace/name;path.write_text(text);fixtures[str(path.relative_to(ROOT)).replace('\\','/')]=sha(path.read_bytes())

    def job(label,top,names,phases):
        target=workspace/label;target.mkdir()
        commands=[]
        with (target/'compile.log').open('w') as log:
            if args.simulator=='modelsim':
                command=[str(MODELSIM/'vlib.exe'),'work'];commands.append(command)
                result=subprocess.run(command,cwd=target,stdout=log,stderr=subprocess.STDOUT,timeout=300)
                if result.returncode==0:
                    command=[str(MODELSIM/'vlog.exe'),'-sv','-work','work']+[str(workspace/n) for n in names]+[str(VENDOR)]
                    commands.append(command)
                    result=subprocess.run(command,cwd=target,stdout=log,stderr=subprocess.STDOUT,timeout=600)
            else:
                command=[str(IVERILOG),'-g2012','-s',top,'-o',str(target/'proof.vvp')]+[str(workspace/n) for n in names]+[str(VENDOR)]
                commands.append(command)
                result=subprocess.run(command,cwd=target,stdout=log,stderr=subprocess.STDOUT,timeout=300)
        row={'test':label,'simulator':args.simulator,'compile_exit_code':result.returncode,'compile_commands':commands,
            'compile_log_sha256':sha((target/'compile.log').read_bytes()),'runs':[]}
        if result.returncode:
            print(label+': compile_exit_code='+str(result.returncode)+' '+(target/'compile.log').read_text(errors='replace')[-3500:],flush=True);return row
        for phase in phases:
            logpath=target/('run'+('' if phase is None else '_'+str(phase))+'.log')
            if args.simulator=='modelsim':
                run_command=[str(MODELSIM/'vsim.exe'),'-c','work.'+top]+([] if phase is None else ['+phase='+str(phase)])
                run_command+=['-do','onerror {quit -code 1}; run -all; quit -code 0']
            else:
                run_command=[str(VVP),str(target/'proof.vvp')]+([] if phase is None else ['+phase='+str(phase)])
            with logpath.open('w') as log:
                result=subprocess.run(run_command,cwd=target,stdout=log,stderr=subprocess.STDOUT,timeout=7200)
            text=logpath.read_text(errors='replace')
            normalized=[l[2:] if l.startswith('# ') else l for l in text.splitlines()]
            markers=[l for l in normalized if l.startswith('PASS ')]
            required=(['PASS current FG QSEL_EN1:','PASS current Intel VRAM selectors/geometry/collision suite','PASS slice AW=14 SQ_REG=1','PASS slice AW=16 SQ_REG=0']
                if label=='ram' else ['PASS BG same-edge address:'])
            passed=result.returncode==0 and all(any(m in l for l in markers) for m in required) and not re.search(r'\bFATAL\b|\bFAIL\b|\bERROR\b',text,re.I)
            row['runs'].append({'phase':phase,'exit_code':result.returncode,'passed':passed,'markers':markers,'command':run_command,'log_sha256':sha(logpath.read_bytes())})
            print(label+': '+json.dumps(row['runs'][-1]),flush=True)
            if not passed: print(text[-2200:],flush=True);break
        return row

    with ThreadPoolExecutor(max_workers=2) as executor:
        ram=executor.submit(job,'ram','current_vram_vendor_tb',
            ['current_vram_vendor_tb.sv','memory.sv','memory_baseline.sv','fg_banked.sv','fg_banked_baseline.sv'],[None])
        bg=executor.submit(job,'bg','bt_bg_port_address_tb',
            ['bt_bg_port_address_tb.sv','memory.sv','memory_baseline.sv','bg_candidate.sv','bg_reference.sv'],[0,5])
        results=[ram.result(),bg.result()]
    stable=(all(sha(Path(actual_paths[name]).read_bytes())==sources[name] for name in actual_paths)
        and sha(adapter.read_bytes())==sources['tests/graphics/ram_models.sv'])
    passed=stable and all(r['compile_exit_code']==0 and len(r['runs'])==(1 if r['test']=='ram' else 2) and all(s['passed'] for s in r['runs']) for r in results)
    receipt={'schema':'bt-current-vram-intel-model-v1','oracle_ref':ORACLE,'sources':sources,
        'actual_source_paths':actual_paths,'fixtures':fixtures,'external_sources':{str(VENDOR):VENDOR_SHA},
        'workspace':str(workspace),'results':results,'source_stability_passed':stable,'exit_code':0 if passed else 1,
        'functional_adapter_provenance':{'sha256':sources['tests/graphics/ram_models.sv'],
            'used_in_vendor_simulation':False,'qualification':'separate immutable-b537 FG same-edge pin/assertion/controller proof; this suite uses exact Intel models'},
        'canonical_comparison_contract':{
            'before_candidate_physical_comparison':'Every Q/SQ bit including X/Z at every capture edge, and every FG bank, without exclusions; immutable-b537 physical modules have the identical geometry/modes/output-register configuration.',
            'mixed_port_mode':'DONT_CARE', 'same_port_mode':'NEW_DATA_NO_NBE_READ',
            'canonical_q_exclusions':'Only selected CPU word bytes whose A write enable is high and BE byte is low, or all16 selected CPU word bits on a same-word serial B write. Q postmux register delays exactly one edge in FG; primitive QA_REG0 uses current edge.',
            'canonical_sq_exclusions':'Only the16 bits of A word a[2:1] within serial64bit read when A write enable is high, B write enable is low, and A/selected B word groups match. SQ_REG1 delays exactly one edge; SQ_REG0 uses current edge. Other48 serial bits remain compared.',
            'intel_source_reference':'Exact altera_mf.v SHA c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213; original mode parameters47658/47659/47669, masked same-port behavior50465-50468, exact A-write/B-read word predicate50513-50545. Defined generic AUTO-model zero under these unspecified modes is not a physical-data promise.',
            'fixture_predicates':'canonical_q_mask_now/canonical_sq_mask_now and two capture-history registers are source-bound in current_vram_vendor_tb.sv; exclusions do not modify output data, X masks, physical controls or the immutable physical oracle.'},
        'hardware_equivalence_passed':passed,'intel_model_equivalence_passed':passed,'mapped_atoms_verified':False,
        'scope':'current actual FG four-bank QSEL_EN1/segment selectors with QA postmux/SQ output edges, all masks/lanes/segments/read-source/prefetch/copy suppression, defined original canonical16bank outputs plus exact current-before data/X-mask comparison, actual BG RTL complete RAM capture-pin/state equality at two coincident phases, exact Intel altera_mf.v; no new Quartus mapped atoms/routed timing or MiSTer hardware qualification'}
    text=json.dumps(receipt,indent=2)+'\n';(workspace/'receipt.json').write_text(text);(evidence/'receipt.json').write_text(text)
    for label in ('ram','bg'):
        for path in (workspace/label).glob('*.log'):
            target=evidence/label/path.name;target.parent.mkdir(exist_ok=True);target.write_bytes(path.read_bytes())
    print('receipt='+str(evidence/'receipt.json'),flush=True)
    return 0 if passed else 1


if __name__=='__main__':
    sys.exit(main())
