`timescale 1ns/1ps
module bt_cpu_shift_flags_tb;
  import TMS34020_PKG::*;
  wire line_done;
  bt_cpu_line_gz_tb L(.done(line_done));
  bit[31:0] val;
  bit[4:0] sa;
  bit[3:0] code;
  wire[32:0] oc,nc;
  wire ov,nv;
  bt_shift_function_oracle OF(.*,.carry_result(oc),.shift_overflow(ov));
  bt_shift_function_candidate NF(.*,.carry_result(nc),.shift_overflow(nv));
  bit CLK=0,RST_N=0,EN,CE_R,IW_WAIT,MC_WAIT,CACHE_WAIT;
  DecInstr_t DECI;
  bit[31:0] ALU_A_D,ALU_B_D,MC_DIN,RF_RA_Q,RF_RB_Q,PC,ST_RMASK,WSTART,WEND,PATTERN;
  bit[63:0] MD_ACC;
  bit[15:0] IC;
  bit[4:0] ALU_SA_D,STATE;
  bit[5:0] PSIZE;
  bit[10:0] RF_WRITE_SEL;
  bit DIV_V,RF_WA_WE;
  bit[1:0] WINDOW_CONTROL_W;
  wire[31:0] OR,NR,OW,NW;
  wire ON,OZ,OV,OC,NN,NZ,NV,NC,OG,NG;
  wire[3:0] OXY,NXY;
  wire[223:0] OSNAPSHOT,NSNAPSHOT;
  wire ST_t OSTATUS,NSTATUS;
  bt_shift_phase_oracle OP(.*,.ALU_R(OR),.RF_WRITE_D(OW),.ALU_N(ON),.ALU_Z(OZ),.ALU_V(OV),.ALU_C(OC),
    .ALU_XY_CC(OXY),.ALU_LINE_GZ(OG),.PIX_SNAPSHOT(OSNAPSHOT),.ST_CAPTURED(OSTATUS));
  bt_shift_phase_candidate NP(.*,.ALU_R(NR),.RF_WRITE_D(NW),.ALU_N(NN),.ALU_Z(NZ),.ALU_V(NV),.ALU_C(NC),
    .ALU_XY_CC(NXY),.ALU_LINE_GZ(NG),.PIX_SNAPSHOT(NSNAPSHOT),.ST_CAPTURED(NSTATUS));
  bit[31:0] rng=32'h74319ace;
  int function_checks=0,phase_checks=0,resets=0,en_holds=0,ce_holds=0,stalls=0,status_actions=0,overflow_writes=0;
  int status_coverage[8];
  function bit[31:0] next_rng(input bit[31:0] r);
    r=r^(r<<13);r=r^(r>>17);r=r^(r<<5);return r;
  endfunction
  task check_functions;
    assert({nc,nv}==={oc,ov}) else $fatal(1,"Function mismatch val=%h sa=%d code=%h",val,sa,code);
    if(sa<2) assert(!nv) else $fatal(1,"Existing zero/one overflow semantics changed");
    function_checks++;
  endtask
  task check_phase(input int cycle);
    assert({NR,NW,NN,NZ,NV,NC,NXY,NG,NSNAPSHOT,NSTATUS} ===
           {OR,OW,ON,OZ,OV,OC,OXY,OG,OSNAPSHOT,OSTATUS})
      else $fatal(1,"Actual ALU/operand/status/pixel slice mismatch phase=%d",cycle);
  endtask
  initial begin
    for(int c=0;c<16;c++)for(int s=0;s<32;s++)for(int b=0;b<66;b++) begin
      code=4'(c);sa=5'(s);
      if(b==0)val=0;else if(b==1)val='1;
      else if(b<34)val=32'd1<<(b-2);else val=~(32'd1<<(b-34));
      #1;check_functions();
    end
    for(int n=0;n<1048576;n++) begin
      rng=next_rng(rng);val=rng;sa=5'(n>>4);code=4'(n);
      #1;check_functions();
    end
    EN=1;CE_R=1;DECI='0;
    #1;CLK=1;#1;CLK=0;#1;check_phase(-1);
    for(int n=0;n<65536;n++) begin
      RST_N=n%997!=0;EN=n%13!=0;CE_R=n%5==2||n%5==4;
      IW_WAIT=n%11==0;MC_WAIT=n%17==0;CACHE_WAIT=n%19==0;
      rng=next_rng(rng);ALU_A_D=rng;rng=next_rng(rng);ALU_B_D=rng;
      MC_DIN=~rng;RF_RA_Q=ALU_A_D;RF_RB_Q=ALU_B_D;MD_ACC={ALU_A_D,ALU_B_D};
      DECI='0;DECI.ALU.OP=ALUOp_t'(n>>2);DECI.ALU.CD=4'(n>>6);DECI.ALU.BCOMP=1'(n>>10);
      DECI.SHC.SHOP[$bits(DECI.SHC.SHOP)-1:0]=$bits(DECI.SHC.SHOP)'(n>>6);
      case(n%8)
        0:DECI.STW.STU=STU_ALU;1:DECI.STW.STU=STU_ST;2:DECI.STW.STU=STU_MEM;3:DECI.STW.STU=STU_RES;
        4:DECI.STW.STU=STU_FS;5:DECI.STW.STU=STU_EXFS;6:DECI.STW.STU=STU_C;7:DECI.STW.STU=STU_IE;
      endcase
      DECI.STW.AFU=4'(n>>4);DECI.F=1'(n>>8);
      DECI.PF=$bits(DECI.PF)'(n);DECI.PF.LINE=PixLine_t'(n%4);
      DECI.PALU.CNVS[$bits(DECI.PALU.CNVS)-1:0]=$bits(DECI.PALU.CNVS)'(n>>6);
      IC=16'(n);ALU_SA_D=5'(n>>7);STATE=5'(n>>8);
      PSIZE=6'(1<<(n%6));WSTART=ALU_A_D;WEND=ALU_B_D;PATTERN=MC_DIN;WINDOW_CONTROL_W=2'(n>>12);
      RF_WRITE_SEL=11'(n);RF_WA_WE=1'(n>>4);ST_RMASK=rng;DIV_V=1'(n>>9);
      if(!RST_N)resets++;else if(!EN)en_holds++;else if(!CE_R)ce_holds++;
      else if(IW_WAIT||MC_WAIT||CACHE_WAIT)stalls++;
      else begin status_actions++;status_coverage[n%8]++;if(DECI.STW.STU==STU_ALU&&DECI.STW.AFU[0])overflow_writes++;end
      #1;check_phase(n);CLK=1;#1;check_phase(n);CLK=0;#1;check_phase(n);
      phase_checks++;
    end
    assert(function_checks==1082368 && phase_checks==65536);
    assert(resets&&en_holds&&ce_holds&&stalls&&status_actions&&overflow_writes);
    for(int n=0;n<8;n++)assert(status_coverage[n]>0)else $fatal(1,"Status class uncovered %d",n);
    $display("PASS shift functions comparisons=%0d all16codes/all32amounts/all66basispatterns",function_checks);
    $display("PASS actual operand/status phases=%0d reset=%0d en_hold=%0d ce_hold=%0d stalls=%0d actions=%0d overflow_writes=%0d all8statusclasses",phase_checks,resets,en_holds,ce_holds,stalls,status_actions,overflow_writes);
    wait(line_done);$finish;
  end
endmodule
