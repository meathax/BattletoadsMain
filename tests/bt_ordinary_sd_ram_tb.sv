`timescale 1ns/1ps
// Four-state old-data read/collision oracle for both final 24-bit geometries.
module bt_ordinary_ram_ref #(parameter NUMWORDS=520, AWIDTH=9, DWIDTH=23)
(
  input clock,
  input [DWIDTH:0] data,
  input [AWIDTH:0] rdaddress, wraddress,
  input wren,
  output reg [DWIDTH:0] q
);
  reg [DWIDTH:0] ram[0:NUMWORDS-1];
  always @(posedge clock) begin
    if(wren) ram[wraddress] <= data;
    q <= ram[rdaddress];
  end
endmodule

module bt_ordinary_sd_ram_tb;
  reg clk=0;
  always #5 clk=~clk;
  reg [9:0] wa_i=0, ra_i=0;
  reg [10:0] wa_o=0, ra_o=0;
  reg [23:0] d_i=0, d_o=0;
  reg we_i=0, we_o=0;
  wire [23:0] q_i, qr_i, q_o, qr_o;
  bt_sd_ram #(520,9,23) input_store(clk,d_i,ra_i,wa_i,we_i,q_i);
  bt_sd_ram #(1040,10,23) output_store(clk,d_o,ra_o,wa_o,we_o,q_o);
  bt_ordinary_ram_ref #(520,9,23) input_ref(clk,d_i,ra_i,wa_i,we_i,qr_i);
  bt_ordinary_ram_ref #(1040,10,23) output_ref(clk,d_o,ra_o,wa_o,we_o,qr_o);
`ifdef BT_SD_NATIVE_PRIMITIVE
  wire [23:0] qpi,qpo;
  bt_sd_primitive_ram #(520,9,23) input_primitive(clk,d_i,ra_i,wa_i,we_i,qpi);
  bt_sd_primitive_ram #(1040,10,23) output_primitive(clk,d_o,ra_o,wa_o,we_o,qpo);
`endif
  integer c, valid_i=0, valid_o=0, tail_i=0, tail_o=0;
  integer collision_i=0, collision_o=0;
  initial begin
    for(c=0;c<400000;c=c+1) begin
      @(negedge clk);
      wa_i=(c<1040)?c%520:$urandom%520;
      wa_o=(c<2080)?c%1040:$urandom%1040;
      // Directed tail/collision sweeps initialize every location; randomized
      // traffic then exercises pending writes, forwarding and all color bits.
      ra_i=(c<1040 || $urandom%3==0)?wa_i:$urandom%520;
      ra_o=(c<2080 || $urandom%3==0)?wa_o:$urandom%1040;
      d_i=$urandom; d_o=$urandom;
      we_i=(c<1040)?1:$urandom;
      we_o=(c<2080)?1:$urandom;
      @(posedge clk); #1;
      if(!$isunknown(qr_i)) begin
        if(qr_i !== q_i) $fatal(1,"input-store collision mismatch cycle=%0d read=%0d write=%0d",c,ra_i,wa_i);
`ifdef BT_SD_NATIVE_PRIMITIVE
        if(qr_i !== qpi) $fatal(1,"Intel input-store collision mismatch cycle=%0d read=%0d write=%0d ref=%h primitive=%h",c,ra_i,wa_i,qr_i,qpi);
`endif
        valid_i=valid_i+1;
        if(ra_i>=512) tail_i=tail_i+1;
        if(we_i && ra_i==wa_i) collision_i=collision_i+1;
      end
      if(!$isunknown(qr_o)) begin
        if(qr_o !== q_o) $fatal(1,"output-store collision mismatch cycle=%0d read=%0d write=%0d",c,ra_o,wa_o);
`ifdef BT_SD_NATIVE_PRIMITIVE
        if(qr_o !== qpo) $fatal(1,"Intel output-store collision mismatch cycle=%0d read=%0d write=%0d ref=%h primitive=%h",c,ra_o,wa_o,qr_o,qpo);
`endif
        valid_o=valid_o+1;
        if(ra_o>=1024) tail_o=tail_o+1;
        if(we_o && ra_o==wa_o) collision_o=collision_o+1;
      end
    end
    if(tail_i<1000 || tail_o<1000 || collision_i<1000 || collision_o<1000)
      $fatal(1,"coverage incomplete");
    $display("PASS ordinary 24-bit RAM: %0d cycles, %0d/%0d defined comparisons, %0d/%0d tail reads, %0d/%0d old-data same-address collisions",c,valid_i,valid_o,tail_i,tail_o,collision_i,collision_o);
    $finish;
  end
endmodule
