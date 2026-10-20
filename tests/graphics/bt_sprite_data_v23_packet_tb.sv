`timescale 1ns/1ps
// Full original/candidate sprite consumers, with the exact foreground packet
// source edge. The foreground D expression is source-bound by the preparer.
module sprite_data_v23_packet_tb;
 reg clk=0;always #3.125 clk=~clk;
 reg rst_n=0,owner=0,cpu_we=0;reg[5:0]cpu_wa=0;
 reg[1:0][63:0]raw_d='0;
 bit[1:0][63:0]foreground_q;
 always @(posedge clk) foreground_q<=raw_d;
 wire[63:0]old_data=owner ? foreground_q[0] : foreground_q[1];
 wire[31:0]qo,qa;wire[15:0]so,sa,bo,ba;wire[63:0]co,ca,eo,ea,f00,f01,f10,f11;
 wire[1:0][3:0][63:0]bko,bka;
 wire ro,ra,cbo,cba,erdo,erda,ewro,ewra,cro,cra,clo,cla,ilo,ila,ipo,ipa;
 wire[17:0]ao,aa;wire[3:0]no,na;
 SPR_VRAM_P #(.LOCAL_FG_Q(1),.REGISTERED_FG_BANK_Q(1)) original(
  .CLK(clk),.RST_N(rst_n),.A(18'b0),.D(32'b0),.Q(qo),.RAS_N(1'b1),.CAS_N(4'hf),.WE_N(1'b1),.OE_N(1'b1),
  .RDY(ro),.SC(1'b0),.SE_N(1'b1),.SQ(so),.BLIT_A({3'b0,cpu_wa}),.BLIT_Q(bo),
  .CPU_SHIFT_WE(cpu_we),.CPU_SHIFT_WA(cpu_wa),.CPU_SHIFT_DATA(old_data),.CPU_SHIFT_BUSY(cbo),
  .CPU_SHIFT_RD(1'b1),.CPU_SHIFT_A(cpu_wa),.CPU_SHIFT_Q(co),
  .ESADDR(ao),.ESDATA(eo),.ESWR(ewro),.ESRD(erdo),.ESQ(64'b0),.ESTE(1'b0),
  .COMPLETE_RDY(cro),.COMPLETE_RDY_L(clo),.PACKET_IDLE_L(ilo),.PACKET_IDLE(ipo),.BLIT_NONZERO(no),
  .FG0_SHIFT_Q(f00),.FG1_SHIFT_Q(f01),.FG_BANK_SHIFT_Q(bko));
 SPR_VRAM_C #(.LOCAL_FG_Q(1),.REGISTERED_FG_BANK_Q(1),.FG_BANK_ADDR_PERMUTE(1),.LOCAL_FG_PACKET_D(1)) active(
  .CLK(clk),.RST_N(rst_n),.A(18'b0),.D(32'b0),.Q(qa),.RAS_N(1'b1),.CAS_N(4'hf),.WE_N(1'b1),.OE_N(1'b1),
  .RDY(ra),.SC(1'b0),.SE_N(1'b1),.SQ(sa),.BLIT_A({3'b0,cpu_wa}),.BLIT_Q(ba),
  .CPU_SHIFT_WE(cpu_we),.CPU_SHIFT_WA(cpu_wa),.CPU_SHIFT_DATA(old_data),.CPU_SHIFT_BUSY(cba),
  .CPU_SHIFT_RD(1'b1),.CPU_SHIFT_A(cpu_wa),.CPU_SHIFT_Q(ca),
  .ESADDR(aa),.ESDATA(ea),.ESWR(ewra),.ESRD(erda),.ESQ(64'b0),.ESTE(1'b0),
  .COMPLETE_RDY(cra),.COMPLETE_RDY_L(cla),.PACKET_IDLE_L(ila),.PACKET_IDLE(ipa),.BLIT_NONZERO(na),
  .FG0_SHIFT_Q(f10),.FG1_SHIFT_Q(f11),.FG_BANK_SHIFT_Q(bka),.FG_PACKET_D(raw_d),.FG_PACKET_SELECT(owner));
 integer checks=0,reset_edges=0,loads=0,owner0=0,owner1=0,xz_payloads=0;
 task automatic compare;
  assert(active.local_foreground_packet.fg_packet_data_q===foreground_q)
   else $fatal(1,"same-edge local foreground snapshots changed");
  assert(active.CPU_PACKET_SOURCE_DATA===old_data)
   else $fatal(1,"live foreground owner priority changed");
  assert({active.CPU_PACKET_WE,active.CPU_PACKET_WA,active.CPU_PACKET_DATA}===
         {original.CPU_PACKET_WE,original.CPU_PACKET_WA,original.CPU_PACKET_DATA})
   else $fatal(1,"actual sprite packet capture/reset/hold changed");
  assert({qa,sa,ba,ca,ea,aa,ra,cba,ewra,erda,cra,cla,ila,ipa,na,f10,f11,bka}===
         {qo,so,bo,co,eo,ao,ro,cbo,ewro,erdo,cro,clo,ilo,ipo,no,f00,f01,bko})
   else $fatal(1,"complete activated sprite outputs changed");
  checks++;
 endtask
 always @(posedge clk)begin
  compare();if(!rst_n)reset_edges++;else if(cpu_we)begin loads++;if(owner)owner1++;else owner0++;end
  #0.2;compare();
 end
 initial begin
  repeat(4)@(negedge clk);rst_n=1;
  for(integer trial=0;trial<4096;trial++)begin
   @(negedge clk);
   cpu_we=(trial%3)!=0;owner=trial[0];cpu_wa=trial[5:0];rst_n=(trial%113)!=0;
   raw_d[0]=64'hb395a70c61ef284d ^ (64'(trial)*64'h9e127bc460d5a38f);
   raw_d[1]=~raw_d[0];
   case(trial%32)
    1:begin raw_d[0][15:0]='x;xz_payloads++;end
    2:begin raw_d[1][31:16]='z;xz_payloads++;end
    3:begin raw_d[0]='z;xz_payloads++;end
    4:begin raw_d[1]='x;xz_payloads++;end
   endcase
   // Assert/deassert reset between edges as well as directly on a raw phase.
   if(trial%127==0)begin #0.75;rst_n=0;#0.5;rst_n=1;end
  end
  @(negedge clk);cpu_we=0;rst_n=1;
  repeat(5)@(negedge clk);
  assert(checks>=8192 && reset_edges>=30 && loads>2000 && owner0>1000 && owner1>1000 && xz_payloads==512)
   else $fatal(1,"actual packet source-edge coverage missing");
  $display("SPRITE_V23_LOCAL_PACKET_PASS checks=%0d resets=%0d loads=%0d owner0=%0d owner1=%0d xz=%0d",checks,reset_edges,loads,owner0,owner1,xz_payloads);
  $finish;
 end
endmodule
