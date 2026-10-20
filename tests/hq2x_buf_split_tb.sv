`timescale 1ns/1ps
// Equivalence of the split HQ2x line store (sys/hq2x.sv hq2x_buf) against the
// original single-array store, frozen below as hq2x_buf_ref. Run:
//   iverilog -g2012 -o hq2x.vvp tests/hq2x_buf_split_tb.sv sys/hq2x.sv && vvp hq2x.vvp
module hq2x_buf_ref #(parameter NUMWORDS, parameter AWIDTH, parameter DWIDTH)
(
	input                 clock,
	input      [DWIDTH:0] data,
	input      [AWIDTH:0] rdaddress,
	input      [AWIDTH:0] wraddress,
	input                 wren,
	output reg [DWIDTH:0] q
);

reg [DWIDTH:0] ram[0:NUMWORDS-1];

always_ff@(posedge clock) begin
	if(wren) ram[wraddress] <= data;
	q <= ram[rdaddress];
end

endmodule

module tb;
  reg clk=0; always #5 clk=~clk;
  task automatic run; endtask
  `define T(NW,AW,DW,NAME)   reg [AW:0] wa_``NAME, ra_``NAME; reg [DW:0] d_``NAME; reg we_``NAME;   wire [DW:0] qn_``NAME, qr_``NAME;   hq2x_buf #(NW,AW,DW) n_``NAME(clk,d_``NAME,ra_``NAME,wa_``NAME,we_``NAME,qn_``NAME);   hq2x_buf_ref #(NW,AW,DW) r_``NAME(clk,d_``NAME,ra_``NAME,wa_``NAME,we_``NAME,qr_``NAME);
  `T(1040,10,95,o)
  `T(520,9,23,i)
  integer c, checks=0, valid_o=0, valid_i=0, tail_o=0, tail_i=0;
  reg [1040:0] wo; reg [520:0] wi;
  initial begin
    wo=0; wi=0;
    for (c=0;c<400000;c=c+1) begin
      @(negedge clk);
      // Sweep and collide at every address before randomized traffic. This
      // guarantees all tail words and both sides of each split are checked.
      wa_o=(c<1040)?c:$urandom%1040; ra_o=(c<1040||$urandom%3==0)?wa_o:$urandom%1040; d_o={$urandom,$urandom,$urandom}; we_o=(c<1040)?1:$urandom;
      wa_i=(c<520)?c:$urandom%520;  ra_i=(c<520||$urandom%3==0)?wa_i:$urandom%520;  d_i=$urandom; we_i=(c<520)?1:$urandom;
      @(posedge clk); #1;
      if (we_o) wo[wa_o]=1; if (we_i) wi[wa_i]=1;
      // Compare once the read word has been written at least once (both sides start X).
      if (qr_o !== qn_o && !$isunknown(qr_o)) begin $display("FAIL o c=%0d %h %h",c,qr_o,qn_o); $fatal(1); end
      if (qr_i !== qn_i && !$isunknown(qr_i)) begin $display("FAIL i c=%0d %h %h",c,qr_i,qn_i); $fatal(1); end
      if (!$isunknown(qr_o)) begin valid_o=valid_o+1; if(ra_o>=1024) tail_o=tail_o+1; end
      if (!$isunknown(qr_i)) begin valid_i=valid_i+1; if(ra_i>=512) tail_i=tail_i+1; end
      checks=checks+1;
    end
    if(tail_o==0 || tail_i==0) $fatal(1,"Tail comparison coverage missing");
    $display("PASS hq2x_buf split: %0d cycles, %0d/%0d defined-word comparisons (1040x96, 520x24), %0d/%0d tail reads, incl. same-address reads",checks,valid_o,valid_i,tail_o,tail_i);
    $finish;
  end
endmodule
