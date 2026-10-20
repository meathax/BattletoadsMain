`timescale 1ns/1ps
module bt_palette_early_tb;
  logic CLK=0,RST_N=0,EN=1,CE_R=0;
  logic [31:0] LA=0,LDO=0,NVRAM_Q=0;
  logic [3:0] CAS_N=15;
  logic WE_N=1,QE_N=1,RAS_N=1;
  logic [23:0] IO_PAL_Q=0;
  logic [7:0] P1=8'h11,P2=8'h22,P3=8'h33,SW1=8'h44,Z80_RESP_DATA=8'h55;
  logic [7:0] LDI_SELECT=1;
  logic Z80_CTRL_RDY=1,SERVICE=0,Z80_RESP_RDY=1,LDI_EXTERNAL_VALID=0,ENVRAM=0;
  wire [31:0] old_late,old_early,new_late,new_early;
  palette_old ref_pal(.LDI_CACHE_LATE(old_late),.LDI_CACHE_LATE_E(old_early),.*);
  palette_new dut_pal(.LDI_CACHE_LATE(new_late),.LDI_CACHE_LATE_E(new_early),.*);
  integer cycles=0,predictions=0,changes=0,noen_changes=0,resets=0,writes=0,reads=0;
  integer byte_count[4];
  integer guards=0,late_masks=0;
  logic [7:0] saved_pred;
  logic [31:0] saved_late_e;
  logic [31:0] rng=32'h7267be11;

  function automatic [31:0] next_random();
    rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
    return rng;
  endfunction

  task automatic tick(input bit expect_late_prediction=1);
    #1;
    assert(old_late===new_late) else $fatal(1,"F return changed before edge");
    saved_pred=dut_pal.PAL_READ_DATA_E;
    saved_late_e=new_early;
    if(RST_N&&CE_R&&ref_pal.MISC_SEL&&!QE_N&&!ref_pal.PAL_ACCESSED&&
       {LA[11:5],5'b0}==12'h320) begin
      predictions++;
      byte_count[ref_pal.PAL_RBYTE]++;
      if(saved_pred!=ref_pal.PAL_READ_DATA) begin
        changes++;
        if(!EN) noen_changes++;
      end
    end
    if(!RST_N) resets++;
    if(RST_N&&CE_R&&ref_pal.MISC_SEL&&!WE_N) writes++;
    if(RST_N&&CE_R&&ref_pal.MISC_SEL&&!QE_N) reads++;
    CLK=1; #0.01;
    cycles++;
    assert(dut_pal.PAL_READ_DATA===ref_pal.PAL_READ_DATA &&
      dut_pal.PAL_WDATA===ref_pal.PAL_WDATA && dut_pal.PAL_RADDR===ref_pal.PAL_RADDR &&
      dut_pal.PAL_RBYTE===ref_pal.PAL_RBYTE && dut_pal.PAL_WADDR===ref_pal.PAL_WADDR &&
      dut_pal.PAL_MASK===ref_pal.PAL_MASK && dut_pal.PAL_ACCESSED===ref_pal.PAL_ACCESSED &&
      dut_pal.PAL_RAM_A===ref_pal.PAL_RAM_A && dut_pal.PAL_RAM_WE===ref_pal.PAL_RAM_WE &&
      dut_pal.SPR_SCALE0===ref_pal.SPR_SCALE0 && dut_pal.SPR_SCALE1===ref_pal.SPR_SCALE1 &&
      dut_pal.SPR_CONTROL===ref_pal.SPR_CONTROL && dut_pal.DISP_CONTROL===ref_pal.DISP_CONTROL &&
      dut_pal.SCROLL0===ref_pal.SCROLL0 && dut_pal.SCROLL1===ref_pal.SCROLL1 &&
      dut_pal.MISC_CONTROL===ref_pal.MISC_CONTROL && dut_pal.Z80_CTRL_DATA===ref_pal.Z80_CTRL_DATA &&
      dut_pal.Z80_CTRL_DATA_WRITE===ref_pal.Z80_CTRL_DATA_WRITE &&
      dut_pal.Z80_RESP_DATA_READ===ref_pal.Z80_RESP_DATA_READ)
      else $fatal(1,"unchanged side effect differs");
    assert(saved_pred===ref_pal.PAL_READ_DATA) else
      $fatal(1,"predicted palette byte differs from unchanged R result");
    assert(old_late===new_late) else $fatal(1,"F return changed after edge");
    if(expect_late_prediction)
      assert(saved_late_e===old_late) else
        $fatal(1,"early late-owner word differs from unchanged next F word");
    CLK=0; #0.01;
  endtask

  task automatic idle;
    LA=0;CE_R=1;RAS_N=1;WE_N=1;QE_N=1;
    tick();
  endtask

  task automatic pal_write(input [11:0] offset,input [7:0] value);
    idle();
    LA=32'h20000000|offset;LDO={24'b0,value};CAS_N=14;WE_N=0;QE_N=1;RAS_N=0;
    // Writes intentionally alter the F mux's current register value. There is
    // no pending read for this edge; the byte predictor is still checked.
    tick(0);
    idle();
  endtask

  integer i,j,k,b,g,mask;
  initial begin
    for(i=0;i<4;i++)byte_count[i]=0;
    tick();RST_N=1;idle();
    // Reproduce 00 -> 12 at the exact original R update, then green/blue.
    pal_write(12'h360,8'h23);
    IO_PAL_Q=24'h123456;
    for(i=0;i<3;i++)begin
      idle();LA=32'h20000320;RAS_N=0;QE_N=0;CE_R=1;tick();
    end
    // Exercise every predicate combination, all reachable byte positions,
    // the original rollover, and every independent data-byte value.
    for(b=0;b<4;b++)for(g=0;g<64;g++)for(i=0;i<256;i++)begin
      RST_N=0;tick();RST_N=1;idle();
      // Establish PAL_WDATA with the unchanged production write block.
      pal_write(12'h300,8'h25);
      pal_write(12'h320,i[7:0]);pal_write(12'h320,(i^8'h5a));pal_write(12'h320,(i^8'ha5));
      pal_write(12'h360,8'h23);
      IO_PAL_Q={i[7:0],8'(i^8'h3c),8'(i^8'hc3)};
      for(j=0;j<b;j++)begin
        idle();LA=32'h20000320;RAS_N=0;QE_N=0;CE_R=1;tick();
      end
      if(b==3)begin
        // Legitimate transaction count3 rolls back to0; verify the wrap.
        assert(ref_pal.PAL_RBYTE==0) else $fatal(1,"palette rollover changed");
      end
      if(g[0])begin LA=32'h20000320;RAS_N=0;QE_N=0;CE_R=1;tick();end
      LA=g[1]?32'h20000320:32'h00000320;
      if(g[2])LA=LA^32'h00000020;
      CE_R=g[3];QE_N=g[4];RAS_N=0;WE_N=1;EN=g[5];
      tick();guards++;
    end
    // Every late owner mask, enable and valid bit preserves the existing
    // priority/mask equations. Inputs are held across the prediction edge.
    RST_N=1;CE_R=0;LA=32'h20000320;WE_N=1;QE_N=1;
    for(mask=0;mask<256;mask++)for(g=0;g<4;g++)for(i=0;i<64;i++)begin
      LDI_SELECT=mask;ENVRAM=g[0];LDI_EXTERNAL_VALID=g[1];NVRAM_Q=next_random();
      tick();late_masks++;
    end
    // Varied real read/write activity, reset during activity, EN holds and
    // simultaneous write/read use the compiled original palette block.
    LDI_SELECT=1;ENVRAM=0;
    for(i=0;i<32768;i++)begin
      k=next_random();RST_N=(i%257)!=0;EN=k[0];CE_R=k[1];WE_N=k[2];QE_N=k[3];
      RAS_N=k[4];CAS_N=k[8:5];IO_PAL_Q=next_random();LDO=next_random();
      LA=32'h20000000 | ((k[12:9]%5)*32'h20+32'h300);
      tick(WE_N || !CE_R || !RST_N);
    end
    assert(predictions>1000&&changes>1000&&noen_changes>0&&resets>0&&writes>0&&reads>0)
      else $fatal(1,"coverage missing");
    assert(byte_count[0]>0&&byte_count[1]>0&&byte_count[2]>0)
      else $fatal(1,"RGB byte coverage missing");
    $display("PASS palette_early {\"cycles\":%0d,\"predictions\":%0d,\"changes\":%0d,\"EN0_changes\":%0d,\"resets\":%0d,\"write_edges\":%0d,\"read_edges\":%0d,\"guard_cases\":%0d,\"late_owner_masks\":%0d,\"red\":%0d,\"green\":%0d,\"blue\":%0d}",
      cycles,predictions,changes,noen_changes,resets,writes,reads,guards,late_masks,
      byte_count[0],byte_count[1],byte_count[2]);
    $finish;
  end
endmodule
