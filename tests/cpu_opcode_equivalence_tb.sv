`timescale 1ns/1ps
import TMS34020_PKG::*;
module cpu_opcode_equivalence_tb;
  bit  CLK;
  bit  RST_N;
  bit  EN;
  bit  CE_F;
  bit  CE_R;
  bit [15: 0] IC;
  bit [ 4: 0] STATE;
  bit [31: 0] STATE_OH;
  bit  MD_COND;
  bit  MD_NEG;
  bit  DIV_V;
  bit  J_COND;
  bit  DS_COND;
  bit  MM_COND;
  bit  FE0;
  bit  FE1;
  bit  RP_COND;
  bit  LINE_GZ;
  bit  LINE_COND;
  bit  PIX_XEND;
  bit  PIX_YEND;
  bit  PIX_WINEN;
  bit [ 3: 0] PIX_WINCC;
  bit  PIX_BL;
  bit  PIX_WE;
  DecInstr_t candidate, reference;
  ICMatches_t flags;
  assign flags = DecodeICMatches(IC);
  TMS34020_ID dut(.CLK(CLK),.RST_N(RST_N),.EN(EN),.CE_F(CE_F),.CE_R(CE_R),.IC(IC),.STATE(STATE),.STATE_OH(STATE_OH),.MD_COND(MD_COND),.MD_NEG(MD_NEG),.DIV_V(DIV_V),.J_COND(J_COND),.DS_COND(DS_COND),.MM_COND(MM_COND),.FE0(FE0),.FE1(FE1),.RP_COND(RP_COND),.LINE_GZ(LINE_GZ),.LINE_COND(LINE_COND),.PIX_XEND(PIX_XEND),.PIX_YEND(PIX_YEND),.PIX_WINEN(PIX_WINEN),.PIX_WINCC(PIX_WINCC),.PIX_BL(PIX_BL),.PIX_WE(PIX_WE),.IC_MATCHES(flags),.IC_RS_STATIC(DecodeICRS(IC)),.IC_RF_ADDR(DecodeICRFAddress(IC,STATE,0)),.IC_RF_ADDR_POS(DecodeICRFAddress(IC,STATE,1)),.DECI(candidate));
  TMS34020_ID_REFERENCE golden(.CLK(CLK),.RST_N(RST_N),.EN(EN),.CE_F(CE_F),.CE_R(CE_R),.IC(IC),.STATE(STATE),.STATE_OH(STATE_OH),.MD_COND(MD_COND),.MD_NEG(MD_NEG),.DIV_V(DIV_V),.J_COND(J_COND),.DS_COND(DS_COND),.MM_COND(MM_COND),.FE0(FE0),.FE1(FE1),.RP_COND(RP_COND),.LINE_GZ(LINE_GZ),.LINE_COND(LINE_COND),.PIX_XEND(PIX_XEND),.PIX_YEND(PIX_YEND),.PIX_WINEN(PIX_WINEN),.PIX_WINCC(PIX_WINCC),.PIX_BL(PIX_BL),.PIX_WE(PIX_WE),.DECI(reference));
  int unsigned seed=32'h51CEB00C;
  int unsigned checks=0;
  function automatic int unsigned random_bits();
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
  endfunction
  initial begin
    for(int op=0;op<65536;op++) begin
      IC=16'(op);
      for(int state_index=0;state_index<32;state_index++) begin
        STATE=5'(state_index); STATE_OH=32'b1 << state_index;
        for(int profile=0;profile<3;profile++) begin
          CLK = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          RST_N = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          EN = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          CE_F = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          CE_R = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          MD_COND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          MD_NEG = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          DIV_V = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          J_COND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          DS_COND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          MM_COND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          FE0 = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          FE1 = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          RP_COND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          LINE_GZ = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          LINE_COND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          PIX_XEND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          PIX_YEND = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          PIX_WINEN = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          PIX_BL = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          PIX_WE = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());
          PIX_WINCC = profile==0 ? 4'h0 : profile==1 ? 4'hf : 4'(random_bits());
          #1;
          assert(candidate === reference)
            else $fatal(1,"Opcode decode mismatch IC=%h state=%0d profile=%0d candidate=%h reference=%h",IC,STATE,profile,candidate,reference);
          checks++;
        end
      end
    end
    $display("PASS opcode predecode: all 65536 opcodes, 32 states, 3 condition profiles, %0d complete-control comparisons",checks);
    $finish;
  end
endmodule
