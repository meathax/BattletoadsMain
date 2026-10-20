// Simulation adapters for the registered address, unregistered output modes
// selected by BT_mem.sv. Same-address mixed-port collisions are not admissible.
module VRAM_MEM_64Kx8 #(
    parameter ADDR_WIDTH = 16,
    parameter SQ_REG = 0,
    parameter QA_REG = 0,
    parameter SERIAL_WRITE_DECODE = 0,
    parameter LANE_WREN_PRE = 0,
    parameter QSEL_EN = 0,
    parameter SERIAL_SEGMENT_PRE = 0
) (
    input CLK,
    input [ADDR_WIDTH-1:1] ADDR,
    input [15:0] DATA,
    input WREN,
    input [1:0] BE,
    output [15:0] Q,
    input [ADDR_WIDTH-1:3] SADDR,
    input [63:0] SDATA,
    input SWREN,
    output [63:0] SQ,
    input [ADDR_WIDTH-1:3] SADDR_W,
    input [1:0] WREN_LANE,
    input QGATE_D,
    input [3:0] SWREN_SEGMENT
);
    reg qg = 1'b0;
    wire swren_exact = SERIAL_SEGMENT_PRE ? (|SWREN_SEGMENT) : SWREN;
    always @(posedge CLK) if (SERIAL_SEGMENT_PRE)
      for (integer seg=0; seg<4; seg++)
        assert(SWREN_SEGMENT[seg] == (SWREN && SADDR_W[ADDR_WIDTH-1:ADDR_WIDTH-2] == seg))
          else $fatal(1,"same-edge physical serial enable differs seg=%0d",seg);
    always @(posedge CLK) qg <= QGATE_D;
    // Explicit physical depth segments preserve this canonical memory view.
    // The optional write-only segment address must match the selected write.
    always @(posedge CLK) if (SERIAL_WRITE_DECODE && SWREN)
        assert (SADDR_W === SADDR) else $fatal(1,"Serial write address diverged");
    // Byte-addressed behavior is shared by the whole and 5/2/1-bit sliced
    // physical stores. ADDR_WIDTH 14 models each consolidated foreground bank;
    // SQ_REG still delays the serial result one clock after its address stage.
    logic [7:0] mem [0:(1 << ADDR_WIDTH)-1];
    logic [ADDR_WIDTH-1:1] a;
    logic [ADDR_WIDTH-1:3] sa;
    initial begin
        for (integer i=0; i<(1 << ADDR_WIDTH); i=i+1) mem[i]=0;
    end
    always @(posedge CLK) begin
        a <= ADDR;
        sa <= SADDR;
        if (LANE_WREN_PRE) begin
            if (WREN_LANE[0]) mem[{ADDR,1'b0}] <= DATA[7:0];
            if (WREN_LANE[1]) mem[{ADDR,1'b1}] <= DATA[15:8];
        end else if (WREN) begin
            if (BE[0]) mem[{ADDR,1'b0}] <= DATA[7:0];
            if (BE[1]) mem[{ADDR,1'b1}] <= DATA[15:8];
        end
        if (swren_exact) begin
            for (integer j=0; j<8; j=j+1)
                mem[{SADDR,3'b000}+j] <= SDATA[j*8+:8];
        end
    end
    wire [15:0] q_now = {mem[{a,1'b1}],mem[{a,1'b0}]} & {16{!QSEL_EN || qg}};
    // The physical output register follows the existing address register.
    // This model replaces the physical helper, so register exactly once here.
    generate if (QA_REG) begin : registered_cpu_output
        reg [15:0] q_r;
        always @(posedge CLK) q_r <= q_now;
        assign Q = q_r;
    end else begin : unregistered_cpu_output
        assign Q = q_now;
    end endgenerate
    wire [63:0] sq_now;
    for (genvar k=0; k<8; k=k+1) begin
        assign sq_now[k*8+:8] = mem[{sa,3'b000}+k];
    end
    // SQ_REG: the M10K output register, one clock after the address register.
    generate if (SQ_REG) begin : registered_serial_output
        reg [63:0] sq_r;
        always @(posedge CLK) sq_r <= sq_now;
        assign SQ = sq_r;
    end else begin : unregistered_serial_output
        assign SQ = sq_now;
    end endgenerate
endmodule

module VRAM_SHIFTREG #(parameter addr_width=8, parameter sync_read=0, parameter q_reg=0) (
    input CLK,
    input ACLR,
    input [addr_width-1:3] WADDR,
    input [63:0] DATA,
    input [7:0] WREN,
    input [addr_width-1:3] RADDR,
    output [63:0] Q
);
    logic [63:0] mem [0:(1 << (addr_width-3))-1];
    initial begin
        for (integer i=0; i<(1 << (addr_width-3)); i=i+1) mem[i]=0;
    end
    always @(posedge CLK) begin
        for (integer j=0; j<8; j=j+1)
            if (WREN[j]) mem[WADDR][j*8+:8] <= DATA[j*8+:8];
    end
    generate if(sync_read && q_reg) begin : clocked_read_registered_output
        reg [63:0] read_word, output_word;
        always @(posedge CLK) read_word <= mem[RADDR];
        always @(posedge CLK or posedge ACLR)
            if (ACLR) output_word <= 64'd0;
            else output_word <= read_word;
        assign Q=output_word;
    end else if(sync_read) begin : clocked_read
        reg [63:0] read_word;
        always @(posedge CLK) read_word <= mem[RADDR];
        assign Q=read_word;
    end else begin : asynchronous_read
        assign Q = mem[RADDR];
    end endgenerate
endmodule

module dpram #(parameter aw=8, dw=18) (
    input clock,
    input [aw-1:0] address_a, address_b,
    input [dw-1:0] data_a, data_b,
    input wren_a, wren_b,
    output [dw-1:0] q_a, q_b
);
    logic [dw-1:0] mem [0:(1<<aw)-1];
    logic [aw-1:0] aa, ab;
    initial begin
        for (integer i=0; i<(1<<aw); i=i+1) mem[i]=0;
    end
    always @(posedge clock) begin
        aa <= address_a;
        ab <= address_b;
        if (wren_a) mem[address_a] <= data_a;
        if (wren_b) mem[address_b] <= data_b;
    end
    assign q_a=mem[aa];
    assign q_b=mem[ab];
endmodule
