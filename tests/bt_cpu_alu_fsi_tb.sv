`timescale 1ns/1ps
// Oracle modules and control/field slices are extracted by the runner from
// immutable commit 0ecfb2f and the actual candidate CPU, with recorded hashes.
module bt_cpu_alu_fsi_decode_checks(output bit done);
  import TMS34020_PKG::*;
  `include "alu_fsi_helpers.svh"
  bit [15:0] ic;
  bit [4:0] state;
  bit [19:0] flags;
  DecInstr_t live_deci,flagless_deci,field_deci;
  bit [5:0] selector,pixel_size,pixel_words;
  ST_t status;
  bit [5:0] candidate_fs0,candidate_fs1,candidate_fs,oracle_fs0,oracle_fs1,oracle_fs;
  bit candidate_fe,oracle_fe;
  wire [31:0] state_oh=32'b1 << state;
  wire ICMatches_t opcode_matches=DecodeICMatches(ic);
  wire [3:0] source_reg=DecodeICRS(ic);
  TMS34020_ID_ORACLE LIVE(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_R(1'b1),.CE_F(1'b0),
    .IC(ic),.IC_MATCHES(opcode_matches),.IC_RS_STATIC(source_reg),.IC_RF_ADDR('0),.IC_RF_ADDR_POS('0),.OPSEL('0),.OPSEL_COMB(),
    .STATE(state),.STATE_OH(state_oh),
    .MD_COND(flags[0]),.MD_NEG(flags[1]),.DIV_V(flags[2]),.J_COND(flags[3]),.DS_COND(flags[4]),.MM_COND(flags[5]),
    .FE0(flags[6]),.FE1(flags[7]),.RP_COND(flags[8]),.LINE_GZ(flags[9]),.LINE_COND(flags[10]),
    .PIX_XEND(flags[11]),.PIX_YEND(flags[12]),.PIX_WINEN(flags[13]),.PIX_WINCC(flags[17:14]),.PIX_BL(flags[18]),.PIX_WE(flags[19]),
    .DECI(live_deci),.DECI_AT_PRE());
  TMS34020_ID_ORACLE FLAGLESS(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_R(1'b1),.CE_F(1'b0),
    .IC(ic),.IC_MATCHES(opcode_matches),.IC_RS_STATIC(source_reg),.IC_RF_ADDR('0),.IC_RF_ADDR_POS('0),.OPSEL('0),.OPSEL_COMB(),
    .STATE(state),.STATE_OH(state_oh),
    .MD_COND(1'b0),.MD_NEG(1'b0),.DIV_V(1'b0),.J_COND(1'b0),.DS_COND(1'b0),.MM_COND(1'b0),
    .FE0(1'b0),.FE1(1'b0),.RP_COND(1'b0),.LINE_GZ(1'b0),.LINE_COND(1'b0),
    .PIX_XEND(1'b0),.PIX_YEND(1'b0),.PIX_WINEN(1'b0),.PIX_WINCC(4'b0),.PIX_BL(1'b0),.PIX_WE(1'b0),
    .DECI(flagless_deci),.DECI_AT_PRE());
  bt_alu_fsi_candidate_field C(.DECI(field_deci),.ST(status),.PSIZE(pixel_size),.PIXBLT_PPW(pixel_words),.OPSEL_ALU_FSI_OH(selector),
    .FS0(candidate_fs0),.FS1(candidate_fs1),.FS(candidate_fs),.FE(candidate_fe));
  bt_alu_fsi_oracle_field O(.DECI(field_deci),.ST(status),.PSIZE(pixel_size),.PIXBLT_PPW(pixel_words),.OPSEL_ALU_FSI_OH(selector),
    .FS0(oracle_fs0),.FS1(oracle_fs1),.FS(oracle_fs),.FE(oracle_fe));
  longint decode_checks=0,field_checks=0;
  initial begin
    for (int op=0;op<65536;op++) for (int s=0;s<32;s++) for (int p=0;p<24;p++) begin
      ic=16'(op); state=5'(s);
      case (p)
        0:flags=0; 1:flags='1; 2:flags=20'haaaaa; 3:flags=20'h55555;
        default:flags=20'b1 << (p-4);
      endcase
      #1;
      assert (live_deci.FT.FSI == flagless_deci.FT.FSI)
        else $fatal(1,"FSI depends on live flags ic=%h state=%0d flags=%h live=%0d flagless=%0d",ic,state,flags,live_deci.FT.FSI,flagless_deci.FT.FSI);
      assert (DecodeAluFSI(flagless_deci.FT.FSI) == (6'b1 << live_deci.FT.FSI))
        else $fatal(1,"FSI selector mapping differs from committed decoder");
      decode_checks++;
    end
    // Every legal FSI, both status field sizes, six-bit pixel size and word
    // count. FE bits and field selection vary independently of the selector.
    for (int f=0;f<6;f++) for(int a=0;a<32;a++) for(int b=0;b<32;b++)
      for(int ps=0;ps<64;ps++) for(int pw=0;pw<64;pw++) begin
        field_deci='0;
        field_deci.FT.FSI=FSImm_t'(f);
        field_deci.FT.FE=1'(ps);
        field_deci.F=1'(pw);
        status='0; status.FS0=5'(a); status.FS1=5'(b);
        status.FE0=1'(a); status.FE1=1'(b);
        pixel_size=6'(ps); pixel_words=6'(pw);
        selector=DecodeAluFSI(3'(f));
        #1;
        assert ({candidate_fs0,candidate_fs1,candidate_fs,candidate_fe} === {oracle_fs0,oracle_fs1,oracle_fs,oracle_fe})
          else $fatal(1,"Live field-size path differs FSI=%0d fs0=%0d fs1=%0d ps=%0d pw=%0d",f,a,b,ps,pw);
        field_checks++;
      end
    $display("PASS FSI decode=%0d opcode/state/flag-profile comparisons; live field tuples=%0d",decode_checks,field_checks);
    done=1;
  end
endmodule

module bt_cpu_alu_fsi_phase_checks(output bit done);
  import TMS34020_PKG::*;
  bit clk=0,rst_n=1,en,ce_r,mc_wait,cache_wait,int_req,j_cond,ds_cond;
  DecInstr_t deci;
  bit [31:0] cache_q,rf_rb_q,mc_din;
  bit [39:0] cache_rf_pre;
  bit [15:0] ci,oi;
  ICMatches_t cm,om;
  bit [3:0] cr,orr;
  ICRFAddress_t ca0,ca1,oa0,oa1;
  OpSel_t cs,os;
  bit [31:0] ciw,oiw,cpc,opc,coh,ooh;
  bit [4:0] cst,ost;
  bit cre,ore;
  bit [1:0] cwm,owm;
  bit [5:0] cfsi,ofsi;
  bt_alu_fsi_candidate_instruction C(.CLK(clk),.RST_N(rst_n),.EN(en),.CE_R(ce_r),.MC_WAIT(mc_wait),.CACHE_WAIT(cache_wait),
    .INT_REQ(int_req),.J_COND(j_cond),.DS_COND(ds_cond),.DECI(deci),.CACHE_Q(cache_q),.RF_RB_Q(rf_rb_q),.MC_DIN(mc_din),.CACHE_RF_PRE(cache_rf_pre),
    .IC(ci),.IC_MATCHES(cm),.IC_RS_STATIC(cr),.IC_RF_ADDR(ca0),.IC_RF_ADDR_POS(ca1),.OPSEL(cs),.IW(ciw),.PC(cpc),.STATE_OH(coh),.STATE(cst),.RST_EXEC(cre),.WORD_MASK(cwm),.OPSEL_ALU_FSI_OH(cfsi));
  bt_alu_fsi_oracle_instruction O(.CLK(clk),.RST_N(rst_n),.EN(en),.CE_R(ce_r),.MC_WAIT(mc_wait),.CACHE_WAIT(cache_wait),
    .INT_REQ(int_req),.J_COND(j_cond),.DS_COND(ds_cond),.DECI(deci),.CACHE_Q(cache_q),.RF_RB_Q(rf_rb_q),.MC_DIN(mc_din),.CACHE_RF_PRE(cache_rf_pre),
    .IC(oi),.IC_MATCHES(om),.IC_RS_STATIC(orr),.IC_RF_ADDR(oa0),.IC_RF_ADDR_POS(oa1),.OPSEL(os),.IW(oiw),.PC(opc),.STATE_OH(ooh),.STATE(ost),.RST_EXEC(ore),.WORD_MASK(owm),.OPSEL_ALU_FSI_OH(ofsi));
  int count_reset=0,count_irq=0,count_fetch0=0,count_fetch1=0,count_stall=0,count_ce_hold=0,count_en_hold=0;
  int count_state=0,count_iw0=0,count_iw1=0,count_iw2=0;
  bit [5:0] previous_fsi;
  task check;
    assert ({ci,cm,cr,ca0,ca1,cs,ciw,cpc,coh,cst,cre,cwm} === {oi,om,orr,oa0,oa1,os,oiw,opc,ooh,ost,ore,owm})
      else $fatal(1,"Original instruction phase state differs");
    assert (cfsi === ofsi) else $fatal(1,"Registered FSI phase differs ic=%h state=%0d candidate=%b oracle=%b",ci,cst,cfsi,ofsi);
  endtask
  initial begin
    en=1; rst_n=0; #1; clk=1; #1; clk=0; #1; check();
    for (int n=0;n<131072;n++) begin
      previous_fsi=cfsi;
      rst_n=n%997 != 0;
      en=n%13 != 0; ce_r=n%4 == 0;
      mc_wait=n%17 == 0; cache_wait=n%19 == 0; int_req=n%29 == 0;
      j_cond=1'(n>>3); ds_cond=1'(n>>4);
      cache_q={16'(n^16'hffff),16'(n)};
      rf_rb_q=32'(n<<4); mc_din=32'((n^32'ha5a5)<<4);
      cache_rf_pre={10'(n),10'(n>>1),10'(n>>2),10'(n>>3)};
      deci='0; deci.NST=5'(n>>2); deci.LST=n%3 != 0;
      deci.IWL=2'((n>>5)%4); deci.PCW=1;
      deci.JC=JC_JUMP; deci.PCS=PCS_REG;
      if (!rst_n) count_reset++;
      else if(!en) count_en_hold++;
      else if(!ce_r) count_ce_hold++;
      else if(mc_wait || cache_wait) count_stall++;
      else if(int_req && deci.LST) count_irq++;
      else if(!deci.IWL) begin
        count_state++;
        if(deci.LST) begin if(!opc[4]) count_fetch0++; else count_fetch1++; end
      end else if(!opc[4] && !owm[0]) count_iw0++;
      else if(!opc[4] && owm[0]) count_iw1++;
      else count_iw2++;
      #1; clk=1; #1; clk=0; #1; check();
      if(rst_n && (!en || !ce_r || mc_wait || cache_wait))
        assert(cfsi === previous_fsi) else $fatal(1,"FSI changed during instruction stall/hold");
    end
    assert(count_reset && count_irq && count_fetch0 && count_fetch1 && count_stall && count_ce_hold && count_en_hold && count_state && count_iw0 && count_iw1 && count_iw2)
      else $fatal(1,"Instruction phase coverage incomplete");
    $display("PASS instruction phase cycles=131072 reset=%0d irq=%0d fetch_low=%0d fetch_high=%0d stalls=%0d ce_hold=%0d en_hold=%0d state=%0d iw_branches=%0d/%0d/%0d",count_reset,count_irq,count_fetch0,count_fetch1,count_stall,count_ce_hold,count_en_hold,count_state,count_iw0,count_iw1,count_iw2);
    done=1;
  end
endmodule

module bt_cpu_alu_fsi_tb;
  wire decode_done,phase_done;
  bt_cpu_alu_fsi_decode_checks D(decode_done);
  bt_cpu_alu_fsi_phase_checks P(phase_done);
  initial begin wait(decode_done && phase_done); $finish; end
endmodule
