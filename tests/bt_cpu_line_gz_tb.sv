`timescale 1ns/1ps
module bt_cpu_line_gz_tb;
  import TMS34020_PKG::*;
  bit CLK=0,RST_N=0,EN,CE_R,IW_WAIT,MC_WAIT,CACHE_WAIT;
  DecInstr_t DECI;
  ST_t ST;
  bit[31:0] ALU_A,ALU_B,MC_DIN,RF_RA_Q,RF_RB_Q,PC,ST_RMASK,WSTART,WEND,PATTERN;
  bit[63:0] MD_ACC;
  bit[15:0] IC;
  bit[4:0] ALU_SA,STATE;
  bit[5:0] PSIZE;
  bit[10:0] RF_WRITE_SEL;
  bit DIV_V,RF_WA_WE;
  bit[1:0] WINDOW_CONTROL_W;
  wire[31:0] OR,CR,OW,CW;
  wire ON,OZ,OV,OC,CN,CZ,CV,CC,OG,CG;
  wire[3:0] OXY,CXY;
  wire[223:0] OSNAPSHOT,CSNAPSHOT;
  bt_line_gz_oracle O(.*,.ALU_R(OR),.RF_WRITE_D(OW),.ALU_N(ON),.ALU_Z(OZ),.ALU_V(OV),.ALU_C(OC),
                       .ALU_XY_CC(OXY),.ALU_LINE_GZ(OG),.PIX_SNAPSHOT(OSNAPSHOT));
  bt_line_gz_candidate C(.*,.ALU_R(CR),.RF_WRITE_D(CW),.ALU_N(CN),.ALU_Z(CZ),.ALU_V(CV),.ALU_C(CC),
                          .ALU_XY_CC(CXY),.ALU_LINE_GZ(CG),.PIX_SNAPSHOT(CSNAPSHOT));
  longint combin_checks=0,phase_checks=0,zero_sign_checks=0;
  int xy_coverage[8],op_coverage[16];
  int resets=0,en_holds=0,ce_holds=0,stalls=0,line_updates=0,line_holds=0;
  bit[31:0] rng=32'h8675309a;
  function bit[31:0] next_rng(input bit[31:0] r);
    r=r^(r<<13);r=r^(r>>17);r=r^(r<<5);return r;
  endfunction
  function bit[31:0] boundary(input int n);
    case(n)
      0:return 0;1:return 1;2:return 32'hffffffff;3:return 32'h7fffffff;
      4:return 32'h80000000;5:return 32'h0000ffff;6:return 32'hffff0000;
      7:return 32'h00010000;8:return 32'h00000001;9:return 32'h00010001;
      10:return 32'h80008000;11:return 32'h7fff7fff;12:return 32'h55555555;
      13:return 32'haaaaaaaa;14:return 32'h01010101;default:return 32'h80808080;
    endcase
  endfunction
  task check_combin;
    assert({CR,CW,CN,CZ,CV,CC,CXY}==={OR,OW,ON,OZ,OV,OC,OXY})
      else $fatal(1,"ALU outputs changed op=%0d",DECI.ALU.OP);
    assert(CG===OG) else $fatal(1,"Line predicate mismatch op=%0d A=%h B=%h IC7=%0d N=%0d Z=%0d",DECI.ALU.OP,ALU_A,ALU_B,IC[7],ON,OZ);
    if(DECI.ALU.OP==ALUOP_ADD || DECI.ALU.OP==ALUOP_DIV || DECI.ALU.OP==ALUOP_MOV || DECI.ALU.OP>ALUOP_DIV) begin
      if(OZ) begin assert(!ON) else $fatal(1,"Zero result has sign1");zero_sign_checks++;end
    end
    if(DECI.ALU.OP==ALUOP_ADDXY) xy_coverage[{ON,OZ,IC[7]}]++;
    op_coverage[DECI.ALU.OP]++;
    combin_checks++;
  endtask
  initial begin
    // Exhaust the finite sign/zero lemma used for scalar and memory results.
    for(int n=0;n<2;n++) for(int z=0;z<2;z++) for(int i=0;i<2;i++)
      if(!z || !n) assert((!n | (z & !i)) == !n) else $fatal(1,"Sign/zero lemma failed");
    EN=1;CE_R=1;DECI='0;ST='0;
    #1;CLK=1;#1;CLK=0;#1;
    for(int op=0;op<16;op++) for(int cd=0;cd<16;cd++) for(int bc=0;bc<2;bc++)
      for(int carry=0;carry<2;carry++) for(int i7=0;i7<2;i7++)
      for(int sa=0;sa<32;sa++) for(int shop=0;shop<8;shop++) for(int d=0;d<16;d++) begin
        DECI='0;DECI.ALU.OP=ALUOp_t'(op);DECI.ALU.CD=4'(cd);DECI.ALU.BCOMP=1'(bc);
        DECI.SHC.SHOP[$bits(DECI.SHC.SHOP)-1:0]=$bits(DECI.SHC.SHOP)'(shop);
        ST.C=1'(carry);IC=16'(i7<<7);ALU_SA=5'(sa);
        ALU_A=boundary(d);ALU_B=(d<10)?0:boundary(15-d);MC_DIN=boundary(15-d);
        MD_ACC={ALU_A,ALU_B};RF_RA_Q=ALU_A;RF_RB_Q=ALU_B;
        #1;check_combin();
      end
    for(int n=0;n<1048576;n++) begin
      rng=next_rng(rng);ALU_A=rng;rng=next_rng(rng);ALU_B=rng;
      rng=next_rng(rng);MC_DIN=rng;MD_ACC={ALU_A,ALU_B};RF_RA_Q=ALU_B;RF_RB_Q=ALU_A;
      DECI='0;DECI.ALU.OP=ALUOp_t'(n%16);DECI.ALU.CD=4'(n>>4);DECI.ALU.BCOMP=1'(n>>8);
      DECI.SHC.SHOP[$bits(DECI.SHC.SHOP)-1:0]=$bits(DECI.SHC.SHOP)'(n>>9);
      ALU_SA=5'(n>>12);ST.C=1'(n>>17);IC=16'(n>>10);DIV_V=1'(n>>18);
      #1;check_combin();
    end
    for(int n=0;n<32768;n++) begin
      RST_N=n%997!=0;EN=n%13!=0;CE_R=n%5==2 || n%5==4;
      IW_WAIT=n%11==0;MC_WAIT=n%17==0;CACHE_WAIT=n%19==0;
      rng=next_rng(rng);ALU_A=rng;rng=next_rng(rng);ALU_B=rng;
      MC_DIN=~rng;RF_RA_Q=ALU_A;RF_RB_Q=ALU_B;MD_ACC={ALU_A,ALU_B};
      DECI='0;DECI.ALU.OP=ALUOp_t'(n>>2);DECI.ALU.CD=4'(n>>6);DECI.ALU.BCOMP=1'(n>>10);
      DECI.SHC.SHOP[$bits(DECI.SHC.SHOP)-1:0]=$bits(DECI.SHC.SHOP)'(n>>11);
      DECI.PF=$bits(DECI.PF)'(n);DECI.PF.LINE=PixLine_t'(n%4);
      DECI.PALU.CNVS[$bits(DECI.PALU.CNVS)-1:0]=$bits(DECI.PALU.CNVS)'(n>>6);
      ST.C=1'(n>>9);IC=16'(n);ALU_SA=5'(n>>7);STATE=5'(n>>8);
      PSIZE=6'(1<<(n%6));WSTART=ALU_A;WEND=ALU_B;PATTERN=MC_DIN;WINDOW_CONTROL_W=2'(n>>12);
      if(!RST_N)resets++;else if(!EN)en_holds++;else if(!CE_R)ce_holds++;
      else if(IW_WAIT||MC_WAIT||CACHE_WAIT)stalls++;else if(DECI.PF.LINE==PLN_COND)line_updates++;else line_holds++;
      #1;check_combin();CLK=1;#1;CLK=0;#1;
      assert(CSNAPSHOT===OSNAPSHOT) else $fatal(1,"Pixel/line phase mismatch clock=%0d",n);
      phase_checks++;
    end
    for(int n=0;n<8;n++) assert(xy_coverage[n]>0) else $fatal(1,"ADDXY flag/IC7 coverage missing %0d",n);
    for(int n=0;n<16;n++) assert(op_coverage[n]>0) else $fatal(1,"ALU operation coverage missing %0d",n);
    assert(resets && en_holds && ce_holds && stalls && line_updates && line_holds && zero_sign_checks)
      else $fatal(1,"Reset/enable/stall/line/zero coverage incomplete");
    $display("PASS line predicate combin=%0d phase=%0d zero_sign=%0d all16ops/all8ADDXYflagIC7 cases",combin_checks,phase_checks,zero_sign_checks);
    $display("PASS phases reset=%0d en_hold=%0d ce_hold=%0d stalls=%0d line_update=%0d line_hold=%0d",resets,en_holds,ce_holds,stalls,line_updates,line_holds);
    $finish;
  end
endmodule
