`timescale 1ns/1ps
import TMS34020_PKG::*;
module cpu_operand_stage_tb;
  bit CLK=0; always #5 CLK=~CLK;
  bit RST_N=0;
  bit [31:0] RAW, PIX_VALUE;
  bit [5:0] FIELD0, FIELD1;
  bit FIELD_SELECT, PIX_SELECT;
  bit [1:0] EXTEND_OP;
  wire [31:0] Q;
  bit [31:0] golden;
  TMS34020_OPERAND_STAGE dut(.*);
  always @(posedge CLK or negedge RST_N)
    if(!RST_N) golden<=0;
    else golden<=PIX_SELECT ? PIX_VALUE :
      (FIELD_SELECT ? Ext(RAW,FIELD1,EXTEND_OP) : Ext(RAW,FIELD0,EXTEND_OP));
  int unsigned seed=32'h10C0FFEE;
  function automatic int unsigned random_bits();
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
  endfunction
  initial begin
    repeat(3) @(posedge CLK);
    for(int cycle=0;cycle<85536;cycle++) begin
      @(negedge CLK);
      RST_N=cycle<65536 || ((cycle-65536)%5000)>=3;
      if(cycle<65536) begin
        FIELD0=cycle[5:0]; FIELD1=cycle[11:6]; FIELD_SELECT=cycle[12];
        EXTEND_OP=cycle[14:13]; PIX_SELECT=cycle[15];
      end else begin
        FIELD0=6'(random_bits()); FIELD1=6'(random_bits());
        FIELD_SELECT=1'(random_bits()); EXTEND_OP=2'(random_bits()); PIX_SELECT=1'(random_bits());
      end
      RAW=random_bits(); PIX_VALUE=random_bits();
      @(posedge CLK); #1;
      assert (Q===golden) else $fatal(1,"Operand retiming changed cycle %0d: %h != %h",cycle,Q,golden);
    end
    $display("PASS operand retiming: 65536 field/operation/select tuples and 20000 random/reset cycles");
    $finish;
  end
endmodule
