"""Check blit rectangle rejection and all three production XY blit decoders.

The oracle uses the original signed destination, independently of the RTL's
reconstruction from the wrapped exclusive far corner. This is a non-video
component test; it produces no raster screenshots.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import uuid

p=argparse.ArgumentParser()
p.add_argument('--decoder-source',type=Path)
p.add_argument('--expect-reject',action='store_true')
a=p.parse_args()
root=Path(__file__).resolve().parents[1]
pkg=root/'rtl/TMS34020/TMS34020_pkg.sv'
decoder=(a.decoder_source or root/'rtl/TMS34020/TMS34020_ID.sv').resolve()
work=Path('R:/Verilator/BT')/('blit-window-'+uuid.uuid4().hex)
work.mkdir(parents=True)
cases=[(0,0,64,32,0,0,63,31),(64,8,8,8,0,0,63,31),
       (72,8,8,8,0,0,63,31),(8,32,8,8,0,0,63,31),
       (-8,8,8,8,0,0,63,31),(8,-8,8,8,0,0,63,31),
       (-4,8,8,8,0,0,63,31),(60,8,8,8,0,0,63,31),
       (8,-4,8,8,0,0,63,31),(8,28,8,8,0,0,63,31),
       (63,31,1,1,0,0,63,31),(8,8,0,8,0,0,63,31)]
rng=random.Random(0xb70ad5)
for _ in range(8192):
    x,y=[rng.randint(-32768,32767) for _ in range(2)]
    w,h=[rng.randint(0,32767) for _ in range(2)]
    lx,ly=[rng.randint(-32768,32766) for _ in range(2)]
    hx,hy=rng.randint(lx,32767),rng.randint(ly,32767)
    cases.append((x,y,w,h,lx,ly,hx,hy))
def xy(x,y):return ((y&65535)<<16)|(x&65535)
rows=[]
for x,y,w,h,lx,ly,hx,hy in cases:
    flags=(int(y>hy)<<3)|(int(h==0 or y+h<=ly)<<2)|(int(x>hx)<<1)|int(w==0 or x+w<=lx)
    clip_w=max(0,min(x+w,hx+1)-max(x,lx))
    clip_h=max(0,min(y+h,hy+1)-max(y,ly))
    rows.append(f'{xy(x+w,y+h):08x} {xy(w,h):08x} {xy(lx,ly):08x} {xy(hx,hy):08x} {flags:x} {clip_w:x} {clip_h:x}\n')
(work/'vectors.hex').write_text(''.join(rows))
tb=r'''import TMS34020_PKG::*;
module tb;
    bit [15:0] ic;
    ICMatches_t ic_matches;
    bit enabled;
    bit [3:0] got, expected;
    ICRFAddress_t rf_addr,rf_addr_pos;
    DecInstr_t dec;
    bit [31:0] far_xy,size_xy,min_xy,max_xy;
    XY_t clipped,expected_extent;
    bit [15:0] expected_w,expected_h;
    integer f,n,checks=0;
    TMS34020_ID dut(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b0),.CE_R(1'b0),
        .IC(ic),.IC_MATCHES(ic_matches),.IC_RS_STATIC(4'b0),.IC_RF_ADDR(rf_addr),.IC_RF_ADDR_POS(rf_addr_pos),.OPSEL('0),
        .STATE(5'd4),.STATE_OH(32'h10),.MD_COND(1'b0),.MD_NEG(1'b0),.DIV_V(1'b0),.J_COND(1'b0),
        .DS_COND(1'b0),.MM_COND(1'b0),.FE0(1'b0),.FE1(1'b0),.RP_COND(1'b0),.LINE_GZ(1'b0),
        .LINE_COND(1'b0),.PIX_XEND(1'b0),.PIX_YEND(1'b0),.PIX_WINEN(enabled),.PIX_WINCC(got),
        .PIX_BL(1'b0),.PIX_WE(1'b0),.DECI(dec),.DECI_AT_PRE(),.OPSEL_COMB(),.MD_DIVIDEND_NEG(1'b0));
    initial begin
        f=$fopen("VECTORS","r");
        if (!f) $fatal(1,"vectors missing");
        while (!$feof(f)) begin
            n=$fscanf(f,"%h %h %h %h %h\n",far_xy,size_xy,min_xy,max_xy,expected);
            if(n==5) begin
                got=XYCompareBltWin(far_xy,size_xy,min_xy,max_xy);
                if(got!==expected) $fatal(1,"FAIL bounds far=%h size=%h got=%h expected=%h",far_xy,size_xy,got,expected);
                n=$fscanf(f,"%h %h",expected_w,expected_h);
                if(n!=2) $fatal(1,"FAIL clipped extents missing");
                clipped=WinAdjust(far_xy,size_xy,min_xy,max_xy,1'b1);
                expected_extent={expected_h,expected_w};
                if(clipped!==expected_extent) $fatal(1,"FAIL extent far=%h size=%h got=%h expected=%h",far_xy,size_xy,clipped,expected_extent);
                clipped=WinAdjust(far_xy,size_xy,min_xy,max_xy,1'b0);
                if(clipped!==size_xy) $fatal(1,"FAIL unwindowed extent far=%h size=%h got=%h",far_xy,size_xy,clipped);
                for(integer k=0;k<3;k++) begin
                    case(k) 0:ic=16'h0f20; 1:ic=16'h0fa0; 2:ic=16'h0fe0; endcase
                    ic_matches=DecodeICMatches(ic);
                    rf_addr=DecodeICRFAddress(ic,5'd4,1'b0);
                    rf_addr_pos=DecodeICRFAddress(ic,5'd4,1'b1);
                    enabled=1; #1;
                    if(dec.R!==1'b1 || dec.RS!==4'd14)
                        $fatal(1,"FAIL state-4 B14 predecode opcode=%h R=%b RS=%h",ic,dec.R,dec.RS);
                    if(dec.LST!==(expected!=0)) $fatal(1,"FAIL decoder opcode=%h flags=%h last=%b",ic,got,dec.LST);
                    enabled=0; #1;
                    if(dec.LST!==0) $fatal(1,"FAIL disabled window opcode=%h",ic);
                end
                checks++;
            end
        end
        $display("PASS blit window: %0d rectangles, state-4 B14 predecode, three XY decoders, enabled/disabled",checks);
        $finish;
    end
endmodule
'''.replace('VECTORS',(work/'vectors.hex').as_posix())
(work/'tb.sv').write_text(tb)
cmd=['D:/vibes/fpga/bin/verilator.exe','--binary','--timing','--assert','--threads','1',
     '--x-initial','unique','--x-assign','unique','-j','4','-Wno-fatal','--top-module','tb',
     '--Mdir',str(work/'obj'),'-MAKEFLAGS',
     'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
     '-CFLAGS','-DVL_TIME_CONTEXT -std=c++17','-LDFLAGS','-static-libstdc++ -static-libgcc',
     str(pkg),str(decoder),str(work/'tb.sv')]
env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',VERILATOR_WORKSPACE=str(work),VERILATOR_RAM_WORKSPACE=str(work))
flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
with (work/'build.log').open('w') as log:
    build=subprocess.run(cmd,cwd=work,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=flags)
if build.returncode:
    print((work/'build.log').read_text(errors='replace')[-4000:]);sys.exit(build.returncode)
run=subprocess.run([str(work/'obj/Vtb.exe')],cwd=work,env=env,capture_output=True,text=True,creationflags=flags)
text=run.stdout+run.stderr
(work/'run.log').write_text(text)
passed=(run.returncode!=0 and 'FAIL decoder' in text) if a.expect_reject else (run.returncode==0 and 'PASS blit window:' in text and 'FAIL' not in text)
retained=root/'build/credit_overlap_20261019'/work.name
retained.mkdir(parents=True,exist_ok=True)
for name in ['vectors.hex','tb.sv','build.log','run.log']:(retained/name).write_bytes((work/name).read_bytes())
(retained/'receipt.json').write_text(json.dumps({'scope':'Non-video rectangle/decoder component test; no raster screenshots',
    'vectors':len(cases),'expect_reject':a.expect_reject,'build_command':cmd,'exit':run.returncode,'passed':passed,
    'sources':{str(q):hashlib.sha256(q.read_bytes()).hexdigest() for q in [pkg,decoder,work/'tb.sv']},'workspace':str(work)},indent=2))
print(text.strip());print('receipt='+str(retained/'receipt.json'))
sys.exit(0 if passed else 1)
