`timescale 1ns/1ps
// Frozen per-lane reference for the synchronous VRAM_SHIFTREG mirror.
module VRAM_SHIFTREG_SYNC_REFERENCE #(parameter addr_width = 8) (
  input CLK, input [addr_width-1:3] WADDR, input [63:0] DATA, input [7:0] WREN,
  input [addr_width-1:3] RADDR, output [63:0] Q);
  reg [63:0] mem[0:(1 << (addr_width-3))-1];
  reg [63:0] read_word;
  initial for (integer i=0;i<(1 << (addr_width-3));i=i+1) mem[i]=0;
  always @(posedge CLK) begin
    for (integer lane=0;lane<8;lane=lane+1)
      if (WREN[lane]) mem[WADDR][lane*8 +: 8] <= DATA[lane*8 +: 8];
    read_word <= mem[RADDR];
  end
  assign Q = read_word;
endmodule

module shiftreg_sync_tb;
  localparam W=9;
  reg CLK=0; always #3 CLK=~CLK;
  reg [W-1:3] WADDR=0, RADDR=0; reg [63:0] DATA=0; reg [7:0] WREN=0;
  wire [63:0] cand, ref_q;
  VRAM_SHIFTREG #(.addr_width(W),.sync_read(1)) candidate(.CLK(CLK),.ACLR(1'b0),.WADDR(WADDR),.DATA(DATA),.WREN(WREN),.RADDR(RADDR),.Q(cand));
  VRAM_SHIFTREG_SYNC_REFERENCE #(.addr_width(W)) reference(.CLK(CLK),.WADDR(WADDR),.DATA(DATA),.WREN(WREN),.RADDR(RADDR),.Q(ref_q));
  integer cycle, checks=0, collisions=0;
  initial begin
    for (cycle=0; cycle<200000; cycle=cycle+1) begin
      @(negedge CLK);
      WADDR = $urandom; RADDR = ($urandom%4==0) ? WADDR : $urandom;
      DATA = {$urandom,$urandom};
      WREN = ($urandom%3==0) ? 8'h00 : ($urandom%5==0) ? 8'hff : $urandom;
      if (RADDR==WADDR && WREN!=0) collisions=collisions+1;
      @(posedge CLK); #1;
      if (cand !== ref_q) begin
        $display("FAIL cycle %0d cand=%h ref=%h",cycle,cand,ref_q); $fatal(1);
      end
      checks=checks+1;
    end
    $display("PASS synchronous shift-register mirror: %0d complete-output checks, %0d same-address write/read collisions",checks,collisions);
    $finish;
  end
endmodule
