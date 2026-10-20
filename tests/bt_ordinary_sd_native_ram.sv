// Independent Intel altsyncram oracle for the inferred M10K+MLAB split.
// Main words use mixed-port OLD_DATA. Tail writes commit one cycle later;
// pending writes are forwarded, so undefined MLAB collisions never propagate.
module bt_sd_primitive_ram #(parameter NUMWORDS, AWIDTH, DWIDTH)
(
  input clock,
  input [DWIDTH:0] data,
  input [AWIDTH:0] rdaddress, wraddress,
  input wren,
  output [DWIDTH:0] q
);
  localparam MAIN=1<<($clog2(NUMWORDS+1)-1);
  localparam TAIL=NUMWORDS-MAIN;
  localparam MBITS=$clog2(MAIN);
  localparam TBITS=$clog2(TAIL);
  wire [DWIDTH:0] qm,qt;
  reg sel;
  reg pending=0;
  reg [TBITS-1:0] pending_addr;
  reg [DWIDTH:0] pending_data;
  reg forward;
  reg [DWIDTH:0] forward_data;
  wire [AWIDTH:0] tail_read=rdaddress-MAIN;
  wire [AWIDTH:0] tail_write=wraddress-MAIN;
  always @(posedge clock) begin
    sel <= rdaddress>=MAIN;
    forward <= pending && pending_addr==tail_read;
    forward_data <= pending_data;
    pending <= wren && wraddress>=MAIN;
    pending_addr <= tail_write[TBITS-1:0];
    pending_data <= data;
  end
  altsyncram #(
    .intended_device_family("Cyclone V"),.operation_mode("DUAL_PORT"),
    .ram_block_type("M10K"),.numwords_a(MAIN),.numwords_b(MAIN),
    .width_a(DWIDTH+1),.width_b(DWIDTH+1),.widthad_a(MBITS),.widthad_b(MBITS),
    .width_byteena_a(1),.width_byteena_b(1),
    .address_reg_b("CLOCK0"),.outdata_reg_b("UNREGISTERED"),
    .clock_enable_input_a("BYPASS"),.clock_enable_input_b("BYPASS"),
    .clock_enable_output_b("BYPASS"),.read_during_write_mode_mixed_ports("OLD_DATA")
  ) main_store (
    .clock0(clock),.clock1(clock),.clocken0(1'b1),.clocken1(1'b1),
    .clocken2(1'b1),.clocken3(1'b1),.aclr0(1'b0),.aclr1(1'b0),
    .address_a(wraddress[MBITS-1:0]),.address_b(rdaddress[MBITS-1:0]),
    .data_a(data),.data_b({(DWIDTH+1){1'b0}}),
    .wren_a(wren && wraddress<MAIN),.wren_b(1'b0),
    .byteena_a(1'b1),.byteena_b(1'b1),.rden_a(1'b1),.rden_b(1'b1),.q_b(qm)
  );
  altsyncram #(
    .intended_device_family("Cyclone V"),.operation_mode("DUAL_PORT"),
    .ram_block_type("MLAB"),.numwords_a(TAIL),.numwords_b(TAIL),
    .width_a(DWIDTH+1),.width_b(DWIDTH+1),.widthad_a(TBITS),.widthad_b(TBITS),
    .width_byteena_a(1),.width_byteena_b(1),
    .address_reg_b("CLOCK0"),.outdata_reg_b("UNREGISTERED"),
    .clock_enable_input_a("BYPASS"),.clock_enable_input_b("BYPASS"),
    .clock_enable_output_b("BYPASS"),.read_during_write_mode_mixed_ports("DONT_CARE")
  ) tail_store (
    .clock0(clock),.clock1(clock),.clocken0(1'b1),.clocken1(1'b1),
    .clocken2(1'b1),.clocken3(1'b1),.aclr0(1'b0),.aclr1(1'b0),
    .address_a(pending_addr),.address_b(tail_read[TBITS-1:0]),
    .data_a(pending_data),.data_b({(DWIDTH+1){1'b0}}),
    .wren_a(pending),.wren_b(1'b0),
    .byteena_a(1'b1),.byteena_b(1'b1),.rden_a(1'b1),.rden_b(1'b1),.q_b(qt)
  );
  assign q=sel?(forward?forward_data:qt):qm;
endmodule
