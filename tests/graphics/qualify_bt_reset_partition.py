"""Prove the actual reset domains and original SYS/MEM/phase/video consumers.

The original independent chronology bench is retained through a typed additive
adapter. A separate Icarus proof checks actual four-state original/new producers.
No fitted fanout, timing, RBF or new whole-board replay acceptance is implied.
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
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def wrapper(name, producer, scope, candidate, consumers=True):
    extra = '''
 input wire [31:0] joy0,joy1,joy2,
 input wire OSD_STATUS,nvram_pause,SCLKX2,
 input wire [7:0] mem_ddr_burst,mem_ddr_be,
 input wire [28:0] mem_ddr_addr,
 input wire [63:0] mem_ddr_data,
 input wire mem_ddr_we,mem_ddr_rd,DDRAM_BUSY,
 output wire [8:0] phase_o,output wire audio_o,
 output wire [111:0] video_o,''' if consumers else ''
    text = 'module ' + name + '''(
 input wire clk_sys,clk_mem,RESET,
 input wire [1:0] buttons,input wire [63:0] status,
 input wire rom_download,rom_ready,fg_ddr_ready,locked,
''' + extra + '''
 output wire reset_o,reset_mem_o,clear_init_n_o,
 output wire [1:0] ready_sync_o,output wire [4:0] reset_copies_o);
''' + producer.decode() + '''
 assign reset_o=reset; assign reset_mem_o=reset_mem;
 assign clear_init_n_o=fg_ddr_clear_init_n; assign ready_sync_o=fg_ddr_ready_sys;
''' + (' assign reset_copies_o={reset,reset_bt,reset_phase,reset_ddr,reset_video};\n' if candidate else ' assign reset_copies_o={5{reset}};\n')
    if consumers:
        text += scope['phase'].decode() + scope['audio'].decode() + '''
 wire [28:0] rot_addr=29'd0; wire [63:0] rot_data=64'd0;
 wire [7:0] rot_be=8'd0; wire rot_we=1'b0;
 wire mem_ddr_busy; wire [7:0] DDRAM_BURSTCNT,DDRAM_BE;
 wire [28:0] DDRAM_ADDR; wire [63:0] DDRAM_DIN;
 wire DDRAM_WE,DDRAM_RD;
''' + scope['video'].decode() + '''
 assign phase_o={CE_F,CE_R,VCE_R,CE_F_CPU,CE_R_CPU,cpu_pause_halted,user_pause,old_pause,pause_cpu};
 assign audio_o=SCE_DIV;
 assign video_o={mem_ddr_busy,DDRAM_BURSTCNT,DDRAM_ADDR,DDRAM_DIN,DDRAM_BE,DDRAM_WE,DDRAM_RD};
'''
    return text + '\nendmodule\n'


def main_bench(baseline, scopes_old, scopes_new):
    baseline.wrapper = lambda name, producer: wrapper(name, producer, scopes_new if name == 'reset_candidate' else scopes_old, name == 'reset_candidate')
    text = baseline.bench(scopes_old['producer'], scopes_new['producer'])
    declaration = '''
 bit [31:0] joy0=0,joy1=0,joy2=0;
 bit OSD_STATUS=0,nvram_pause=0,SCLKX2=0,mem_ddr_we=0,mem_ddr_rd=0,DDRAM_BUSY=0;
 bit [7:0] mem_ddr_burst=1,mem_ddr_be=8'hff;
 bit [28:0] mem_ddr_addr=0; bit [63:0] mem_ddr_data=0;
 wire [4:0] old_copies,new_copies; wire [8:0] old_phase,new_phase;
 wire old_audio,new_audio; wire [111:0] old_video,new_video;
 longint unsigned copy_pre=0,copy_post=0,consumer_checks=0;
 always @(negedge clk_sys) begin
   joy0 <= {22'b0,rng[1],9'b0}; joy1<=0; joy2<=0;
   OSD_STATUS<=rng[2]; nvram_pause<=rng[3]; SCLKX2<=rng[4];
   DDRAM_BUSY<=rng[5]; mem_ddr_we<=rng[6]; mem_ddr_rd<=!rng[6]&&rng[7];
   mem_ddr_burst<=rng[15:8]; mem_ddr_be<=rng[23:16];
   mem_ddr_addr<=rng[28:0]; mem_ddr_data<={rng,~rng};
 end
 always @(posedge clk_sys or posedge clk_mem) begin
   copy_pre++;
   if(new_copies !== {5{old_reset}} || old_copies !== {5{old_reset}})
     $fatal(1,"pre-NBA clone identity/held value changed");
   #2; copy_post++; consumer_checks++;
   if(new_copies !== {5{old_reset}} || old_copies !== {5{old_reset}})
     $fatal(1,"post-NBA same-edge clone identity changed");
   if({new_phase,new_audio,new_video} !== {old_phase,old_audio,old_video})
     $fatal(1,"actual phase/audio/video consumer changed");
 end
'''
    anchor = " bit [31:0] rng=32'h534e4142;"
    assert text.count(anchor) == 1; text = text.replace(anchor, anchor + declaration)
    for side in ('old', 'new'):
        anchor = '.ready_sync_o(' + side + '_ready));'
        assert text.count(anchor) == 1
        ports = '.ready_sync_o(' + side + '_ready),.reset_copies_o(' + side + '''_copies),
 .joy0(joy0),.joy1(joy1),.joy2(joy2),.OSD_STATUS(OSD_STATUS),.nvram_pause(nvram_pause),.SCLKX2(SCLKX2),
 .mem_ddr_burst(mem_ddr_burst),.mem_ddr_be(mem_ddr_be),.mem_ddr_addr(mem_ddr_addr),.mem_ddr_data(mem_ddr_data),
 .mem_ddr_we(mem_ddr_we),.mem_ddr_rd(mem_ddr_rd),.DDRAM_BUSY(DDRAM_BUSY),
 .phase_o(''' + side + '_phase),.audio_o(' + side + '_audio),.video_o(' + side + '_video));'
        text = text.replace(anchor, ports)
    anchor = '     $fatal(1,"registered reset changed from a raw input before its SYS edge");'
    assert text.count(anchor) == 1
    text = text.replace(anchor, anchor + '''
   if(new_copies !== {5{previous_reset}} || old_copies !== {5{previous_reset}})
     $fatal(1,"clone changed between SYS captures");''')
    anchor = '   $finish;'
    assert text.count(anchor) == 1
    text = text.replace(anchor, '''
   if(copy_pre<132000 || copy_post<132000 || consumer_checks<132000)
     $fatal(1,"missing every-clock clone/actual-consumer coverage");
   $display("PASS RESET_PARTITION copy_pre=%0d copy_post=%0d consumer_checks=%0d copies=5 roles=7",copy_pre,copy_post,consumer_checks);
''' + anchor)
    return text.replace('reset_maxfan_tb', 'reset_partition_tb')


def fourstate_bench(old, new):
    text = '`timescale 1ps/1ps\n' + wrapper('reset_old_x',old['producer'],old,False,False) + wrapper('reset_new_x',new['producer'],new,True,False)
    return text + '''
module reset_partition_fourstate_tb;
 reg clk_sys=0,clk_mem=1; always #6250 clk_sys=~clk_sys; always #3125 clk_mem=~clk_mem;
 reg RESET=0,rom_download=0,rom_ready=1,fg_ddr_ready=1,locked=1;
 reg [1:0] buttons=0; reg [63:0] status=0;
 wire o,n,om,nm,oc,nc; wire [1:0] orq,nrq; wire [4:0] oq,nq;
 reset_old_x old_x(.clk_sys(clk_sys),.clk_mem(clk_mem),.RESET(RESET),.buttons(buttons),.status(status),.rom_download(rom_download),.rom_ready(rom_ready),.fg_ddr_ready(fg_ddr_ready),.locked(locked),.reset_o(o),.reset_mem_o(om),.clear_init_n_o(oc),.ready_sync_o(orq),.reset_copies_o(oq));
 reset_new_x new_x(.clk_sys(clk_sys),.clk_mem(clk_mem),.RESET(RESET),.buttons(buttons),.status(status),.rom_download(rom_download),.rom_ready(rom_ready),.fg_ddr_ready(fg_ddr_ready),.locked(locked),.reset_o(n),.reset_mem_o(nm),.clear_init_n_o(nc),.ready_sync_o(nrq),.reset_copies_o(nq));
 reg mr=1,mm=1,mc=0; reg [1:0] ms=0;
 integer sys_checks=0,mem_checks=0,unknown_checks=0,offedge_checks=0;
 integer field,kind,masked,j; reg [6:0] tuple; reg held_reset;
 always @(posedge clk_sys) begin
   ms <= {ms[0],fg_ddr_ready};
   mr <= RESET|buttons[1]|status[0]|rom_download|~rom_ready|~ms[1]|~locked;
   #1; sys_checks++;
   if({o,n,oq,nq,orq,nrq} !== {mr,mr,{5{mr}},{5{mr}},ms,ms}) $fatal(1,"4-state same-edge/old-D/CDC mismatch");
   if($isunknown(mr)) unknown_checks++;
 end
 always @(posedge clk_mem) begin
   mm <= mr; mc <= locked && rom_ready && !rom_download;
   #1; mem_checks++;
   if({om,nm,oc,nc} !== {mm,mm,mc,mc}) $fatal(1,"4-state original MEM old-value capture mismatch");
 end
 initial begin
   #1;
   if({o,n,oq,nq,om,nm,oc,nc,orq,nrq} !== {1'b1,1'b1,5'b11111,5'b11111,1'b1,1'b1,1'b0,1'b0,2'b00,2'b00}) $fatal(1,"4-state init changed");
   repeat(4) @(posedge clk_sys);
   for(masked=0;masked<2;masked++) for(kind=0;kind<2;kind++) for(field=0;field<7;field++) begin
     @(negedge clk_sys); held_reset=n; tuple=7'b1110000;
     if(masked) begin j=(field+1)%7; tuple[j]=(j>=4)?1'b0:1'b1; end
     tuple[field]=kind?1'bz:1'bx;
     #1000; {fg_ddr_ready,locked,rom_ready,rom_download,status[0],buttons[1],RESET}=tuple;
     #1; offedge_checks++;
     if(nq !== {5{held_reset}} || oq !== {5{held_reset}}) $fatal(1,"4-state off-edge hold changed");
     repeat(5) @(posedge clk_sys);
   end
   @(negedge clk_sys); {fg_ddr_ready,locked,rom_ready,rom_download,status[0],buttons[1],RESET}=7'b1110000;
   repeat(5) @(posedge clk_sys); #2;
   if(unknown_checks<14 || sys_checks<140 || mem_checks<280 || offedge_checks!=28) $fatal(1,"4-state X/Z coverage missing");
   $display("PASS RESET_PARTITION_FOURSTATE sys_checks=%0d mem_checks=%0d unknown_checks=%0d offedge_checks=%0d xz_cases=28",sys_checks,mem_checks,unknown_checks,offedge_checks);
   $finish;
 end
endmodule
'''


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge',type=Path,required=True); parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args(); edge=args.edge.resolve(); output=args.output.resolve()
    edge.relative_to(ROOT/'build'); output.relative_to(ROOT/'build'); assert not output.exists(); output.mkdir(parents=True)
    hp=ROOT/'tests/graphics/prepare_bt_reset_partition.py'; h=load(hp,'reset_partition_edge')
    manifest_path=edge/'manifest.json'; manifest=json.loads(manifest_path.read_text())
    assert manifest['helper_sha256']==sha(hp.read_bytes())
    op=edge/('oracle/'+h.TOP); np=edge/('candidate/'+h.TOP); old=op.read_bytes(); new=np.read_bytes()
    assert sha(old)==h.PARENT_SHA and sha(new)==manifest['candidate_sha256']
    assert h.source_equivalence(old,new)==manifest['source_equivalence']
    controls=[]
    def reject(name,data):
        try: h.reverse(data)
        except (AssertionError,ValueError): controls.append({'name':name,'rejected':True}); return
        raise AssertionError('Negative control accepted: '+name)
    cap=h.capture(old)
    reject('sampling_old_reset_extra_SYS_edge',new.replace(cap.replace(b' reset <=',b' reset_bt <='),b'\talways @(posedge clk_sys) reset_bt <= reset;\r\n'))
    reject('clone_prior_cause',new.replace(b'reset_bt <= RESET |',b'reset_bt <= !RESET |',1))
    reject('wrong_MEM_edge',new.replace(b'always @(posedge clk_mem) begin',b'always @(negedge clk_mem) begin',1))
    reject('MEM_extra_SYS_sample',new.replace(b'reset_mem <= reset_ddr;',b'reset_mem <= reset_mem;',1))
    reject('clone_init_zero',new.replace(b"reg reset_bt = 1'b1",b"reg reset_bt = 1'b0",1))
    reject('clone_wrong_clock',new.replace(b'clk_sys) reset_video <=',b'clk_mem) reset_video <=',1))
    reject('missing_dont_merge',new.replace(b'preserve, dont_merge',b'preserve',1))
    reject('async_audio_reset_body_changed',new.replace(b'SCE_DIV <= 0;',b'SCE_DIV <= 1;',1))
    reject('unrelated_top_edit',new+b'// unrelated\n')
    for before,after,role in h.BINDINGS:
        reject('wrong_consumer_'+role,new.replace(after,before,1))
    old_scope,new_scope=h.scopes(old),h.scopes(new)
    bp=ROOT/'tests/graphics/qualify_bt_reset_maxfan.py'; baseline=load(bp,'immutable_reset_chronology_bench')
    tb=output/'reset_partition_tb.sv'; tb.write_bytes(main_bench(baseline,old_scope,new_scope).encode())
    xtb=output/'reset_partition_fourstate_tb.sv'; xtb.write_bytes(fourstate_bench(old_scope,new_scope).encode())
    actual=[]
    for name in ('bt_clock_enables.sv','bt_pause_bridge.sv','bt_video_ddr.sv'):
        original=h.BASE/'rtl'/name; target=output/'compiled'/name; target.parent.mkdir(exist_ok=True)
        target.write_bytes(original.read_bytes()); actual.append(target)
        assert sha(target.read_bytes())==manifest['all144_sources']['rtl/'+name]
    commands={}; codes={}
    def run(label,argv):
        commands[label]=argv; r=subprocess.run(argv,capture_output=True,text=True)
        (output/(label+'.log')).write_text(r.stdout+r.stderr); codes[label]=r.returncode
        assert r.returncode==0,(label,r.returncode,str(output/(label+'.log')))
        return r.stdout
    version=run('version',['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','verilator','--version'])
    prefix=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec']
    rel=output.relative_to(ROOT).as_posix()
    run('compile',prefix+['verilator','--binary','--timing','--top-module','reset_partition_tb','-Wno-fatal','-j','2','--Mdir',rel+'/obj',tb.relative_to(ROOT).as_posix()]+[p.relative_to(ROOT).as_posix() for p in actual])
    log=run('run',prefix+['./'+rel+'/obj/Vreset_partition_tb'])
    original=re.search(r'PASS RESET_MAXFAN sys_edges=(\d+) mem_edges=(\d+) assertions=(\d+) releases=(\d+) held=(\d+) coincident=(\d+) off_edge_holds=(\d+) tuples=128 random_tuples=65536 init_checks=2',log)
    addition=re.search(r'PASS RESET_PARTITION copy_pre=(\d+) copy_post=(\d+) consumer_checks=(\d+) copies=5 roles=7',log)
    assert original and addition
    counts=dict(zip(['sys_edges','mem_edges','assertions','releases','held','coincident','off_edge_holds'],map(int,original.groups())))
    counts.update(dict(zip(['copy_pre','copy_post','consumer_checks'],map(int,addition.groups()))))
    run('fourstate_compile',prefix+['iverilog','-g2012','-s','reset_partition_fourstate_tb','-o',rel+'/fourstate.vvp',xtb.relative_to(ROOT).as_posix()])
    xlog=run('fourstate_run',prefix+['vvp',rel+'/fourstate.vvp'])
    xmarker=re.search(r'PASS RESET_PARTITION_FOURSTATE sys_checks=(\d+) mem_checks=(\d+) unknown_checks=(\d+) offedge_checks=(\d+) xz_cases=28',xlog); assert xmarker
    xcounts=dict(zip(['sys_checks','mem_checks','unknown_checks','offedge_checks'],map(int,xmarker.groups())))
    artifacts=[manifest_path,op,np,Path(manifest['full_snapshot']),hp,Path(__file__),bp,tb,xtb,*actual]+[output/(label+'.log') for label in commands]
    receipt={'schema':'bt-reset-partition-qualification-v18','status':'PASS','parent_sha256':h.PARENT_SHA,
             'candidate_sha256':sha(new),'source_equivalence':manifest['source_equivalence'],
             'actual_original_chronology_bench_assertions_retained':True,
             'actual_compiled_consumer_scopes':['clock_enables','user_pause','cpu_pause_bridge','async_audio_SCE_DIV','video_ddr'],
             'all7_consumer_roles_source_bound':True,'all5_reset_Qs_case_equal_pre_post_and_off_edge':True,
             'coverage':{**counts,'directed_tuples':128,'random_tuples':65536,'consumer_bits':122},
             'fourstate_coverage':{**xcounts,'xz_cases':28,'independent_fourstate_nba_model':True},
             'negative_controls':controls,'commands':commands,'return_codes':codes,'verilator_version':version.strip(),
             'clock_periods_ps':{'SYS':12500,'MEM':6250},
             'artifacts':[{'path':str(p),'sha256':sha(p.read_bytes())} for p in artifacts],
             'timing_accepted':False,'mapped_copies_proven':False,
             'limitations':['Explicit domain FF retention and actual routed fanout require exact-source native synthesis/fitting.',
                            'No new full-board replay/hardware claim; all other top behavior is source-identical after exact clone/alias inverse, with same-D four-state induction plus focused compiled actual consumers.']}
    rp=output/'receipt.json'; rp.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':'PASS','receipt':str(rp),'receipt_sha256':sha(rp.read_bytes()),
                      'candidate_sha256':sha(new),'coverage':receipt['coverage'],
                      'fourstate_coverage':receipt['fourstate_coverage'],'negative_controls':len(controls)},indent=2))


if __name__=='__main__':
    main()
