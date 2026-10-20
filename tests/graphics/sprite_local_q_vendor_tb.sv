`timescale 1ns/1ps
module sprite_local_q_vendor_tb;
 reg clk=0,aclr=0;
 reg [6:0] wa=0,ra=0;
 reg [63:0] data=0;
 reg [7:0] we=0;
 wire [63:0] qo,qa,qd,a0,a1,d0,d1;
 wire [15:0] no_,na,nd;
 integer pre_checks=0,post_checks=0,old_data_cases=0,mask_cases=0;
 integer collision_cases=0,offedge_checks=0,unknown_samples=0;
 reg [255:0] masks_seen=0;
 reg [127:0] addresses_seen=0;
 reg [495:0] held;
 reg [63:0] base_word,new_word;
 always #3.125 clk=~clk;
 BT_SPR_POST_NONZERO_MIRROR #(10) original(
  .CLK(clk),.ACLR(aclr),.WADDR(wa),.RADDR(ra),.DATA(data),.WREN(we),.Q(qo),.NZ(no_));
 BT_SPR_POST_NONZERO_MIRROR_LOCAL #(10,1) active(
  .CLK(clk),.ACLR(aclr),.WADDR(wa),.RADDR(ra),.DATA(data),.WREN(we),
  .Q(qa),.NZ(na),.FG0_Q(a0),.FG1_Q(a1));
 BT_SPR_POST_NONZERO_MIRROR_LOCAL #(10) default_off(
  .CLK(clk),.ACLR(aclr),.WADDR(wa),.RADDR(ra),.DATA(data),.WREN(we),
  .Q(qd),.NZ(nd),.FG0_Q(d0),.FG1_Q(d1));
 task automatic compare_all;
  assert ({qa,na} === {qo,no_} && {qd,nd} === {qo,no_})
   else $fatal(1,"original mirror Q/NZ changed active=%h/%h default=%h/%h old=%h/%h",qa,na,qd,nd,qo,no_);
  assert (a0===qo && a1===qo && d0===qo && d1===qo)
   else $fatal(1,"foreground local edge/value/X mismatch old=%h fg0=%h fg1=%h",qo,a0,a1);
 endtask
 always @(posedge clk) begin
  compare_all();pre_checks++;
  #0.2;compare_all();post_checks++;
  if ($isunknown(qo)) unknown_samples++;
 end
 task automatic cycles(input integer n);
  repeat(n) begin @(posedge clk);#0.25;end
 endtask
 initial begin
  #0.1;
  assert ({qo,no_,qa,na,qd,nd,a0,a1,d0,d1} === 496'b0)
   else $fatal(1,"original/copy startup initialization changed");
  cycles(3);
  // Independent known-word checks of the production OLD_DATA collision phase.
  for(integer address=0;address<128;address++) begin
   base_word=64'hA5E317D96BC0428F ^ (64'(address)*64'h0198374BCA6502DF);
   new_word=~base_word;
   @(negedge clk);wa=7'(address);ra=7'(address);we=8'hff;data=base_word;
   cycles(1);@(negedge clk);we=0;cycles(3);
   assert (qo===base_word) else $fatal(1,"known mirror write/read failed address=%0d",address);
   @(negedge clk);we=8'hff;data=new_word;cycles(1);
   assert (qo===base_word) else $fatal(1,"collision changed same-edge old word address=%0d",address);
   @(negedge clk);we=0;cycles(1);
   assert (qo===base_word) else $fatal(1,"OLD_DATA collision phase changed address=%0d",address);
   cycles(1);
   assert (qo===new_word) else $fatal(1,"registered read phase changed address=%0d",address);
   old_data_cases++;
  end
  // Every physical address and byte-enable mask, with alternating collision/read targets.
  for(integer address=0;address<128;address++) begin
   for(integer mask=0;mask<256;mask++) begin
    @(negedge clk);
    wa=7'(address);ra=7'((mask&1)?address:(address^85));we=8'(mask);
    data=64'hCE3970A6B52D481F ^ (64'(address)<<39) ^ (64'(mask)*64'h139C28A7D65E4B01);
    cycles(1);mask_cases++;masks_seen[mask]=1;addresses_seen[address]=1;
    if ((mask&1) && mask!=0) collision_cases++;
   end
  end
  @(negedge clk);we=0;cycles(3);
  for(integer trial=0;trial<16;trial++) begin
   @(negedge clk);held={qo,no_,qa,na,qd,nd,a0,a1,d0,d1};
   #0.25;wa=7'(trial*13);ra=7'(trial*29);data=~data;aclr=~aclr;
   #0.25;
   assert ({qo,no_,qa,na,qd,nd,a0,a1,d0,d1}===held)
    else $fatal(1,"output changed off its original clock edge");
   offedge_checks++;
  end
  // Literal unknown/high-impedance data passes through the real Intel RAM model.
  @(negedge clk);aclr=0;wa=126;ra=126;we=8'hff;data='x;cycles(3);
  assert ($isunknown(qo)) else $fatal(1,"unknown-data case was not observed");
  @(negedge clk);wa=127;ra=127;data='z;cycles(3);
  assert ($isunknown(qo)) else $fatal(1,"high-impedance-data case was not observed");
  @(negedge clk);we=0;cycles(3);
  assert (&masks_seen && &addresses_seen && old_data_cases==128 && mask_cases==32768 &&
          collision_cases==16384 && offedge_checks==16 && unknown_samples>=2)
   else $fatal(1,"vendor proof coverage missing");
  $display("SPRITE_LOCAL_VENDOR_PASS pre=%0d post=%0d old_data=%0d mask_cases=%0d collisions=%0d offedge=%0d unknown=%0d",
           pre_checks,post_checks,old_data_cases,mask_cases,collision_cases,offedge_checks,unknown_samples);
  $finish;
 end
endmodule
