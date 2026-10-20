`timescale 1ns/1ps
// Equivalence of the M10K output-register modes added to rtl/BT_mem.sv
// (VRAM_MEM_64Kx8 SQ_REG and VRAM_SHIFTREG q_reg) against frozen references
// that mirror tests/graphics/ram_models.sv: the registered mode must equal the
// unregistered read delayed by exactly one clock, with identical contents.
//   iverilog -g2012 -s ram_output_reg_tb -o r.vvp tests/ram_output_reg_tb.sv rtl/BT_mem.sv D:/q17/quartus/eda/sim_lib/altera_mf.v
module VRAM_BANK_REFERENCE #(parameter ADDR_WIDTH = 12) (
    input CLK, input [ADDR_WIDTH-1:1] ADDR, input [15:0] DATA, input WREN, input [1:0] BE,
    output [15:0] Q, input [ADDR_WIDTH-1:3] SADDR, input [63:0] SDATA, input SWREN,
    output [63:0] SQ);
    logic [7:0] mem [0:(1 << ADDR_WIDTH)-1];
    logic [ADDR_WIDTH-1:1] a; logic [ADDR_WIDTH-1:3] sa;
    initial for (integer i=0; i<(1 << ADDR_WIDTH); i=i+1) mem[i]=0;
    always @(posedge CLK) begin
        a <= ADDR; sa <= SADDR;
        if (WREN) begin
            if (BE[0]) mem[{ADDR,1'b0}] <= DATA[7:0];
            if (BE[1]) mem[{ADDR,1'b1}] <= DATA[15:8];
        end
        if (SWREN) for (integer j=0; j<8; j=j+1) mem[{SADDR,3'b000}+j] <= SDATA[j*8+:8];
    end
    assign Q = {mem[{a,1'b1}],mem[{a,1'b0}]};
    wire [63:0] sq_now;
    for (genvar k=0; k<8; k=k+1) assign sq_now[k*8+:8] = mem[{sa,3'b000}+k];
    reg [63:0] sq_r; always @(posedge CLK) sq_r <= sq_now;
    assign SQ = sq_r;
endmodule

module VRAM_SHIFTREG_REGISTERED_REFERENCE #(parameter addr_width = 10) (
    input CLK, input ACLR, input [addr_width-1:3] WADDR, input [63:0] DATA, input [7:0] WREN,
    input [addr_width-1:3] RADDR, output [63:0] Q);
    reg [63:0] mem[0:(1 << (addr_width-3))-1];
    reg [63:0] read_word, output_word;
    initial for (integer i=0;i<(1 << (addr_width-3));i=i+1) mem[i]=0;
    always @(posedge CLK) begin
        for (integer lane=0;lane<8;lane=lane+1)
            if (WREN[lane]) mem[WADDR][lane*8 +: 8] <= DATA[lane*8 +: 8];
        read_word <= mem[RADDR];
    end
    always @(posedge CLK or posedge ACLR)
        if (ACLR) output_word <= 64'd0; else output_word <= read_word;
    assign Q = output_word;
endmodule

module ram_output_reg_tb;
    reg CLK=0; always #3 CLK=~CLK;
    // Foreground bank: 4 Kbyte leaf with the registered serial output.
    reg [11:1] ADDR=0; reg [15:0] DATA=0; reg WREN=0; reg [1:0] BE=0;
    reg [11:3] SADDR=0; reg [63:0] SDATA=0; reg SWREN=0;
    wire [15:0] qc, qr; wire [63:0] sqc, sqr;
    VRAM_MEM_64Kx8 #(.ADDR_WIDTH(12), .SQ_REG(1)) bank_cand (CLK, ADDR, DATA, WREN, BE, qc, SADDR, SDATA, SWREN, sqc);
    VRAM_BANK_REFERENCE #(12) bank_ref (CLK, ADDR, DATA, WREN, BE, qr, SADDR, SDATA, SWREN, sqr);
    // Shift-register mirror with the registered read.
    reg [9:3] WADDR=0, RADDR=0; reg [63:0] SDATA2=0; reg [7:0] WREN2=0; reg ACLR=1;
    wire [63:0] shc, shr;
    VRAM_SHIFTREG #(.addr_width(10), .sync_read(1), .q_reg(1)) shift_cand (.CLK(CLK), .ACLR(ACLR), .WADDR(WADDR), .DATA(SDATA2), .WREN(WREN2), .RADDR(RADDR), .Q(shc));
    VRAM_SHIFTREG_REGISTERED_REFERENCE #(10) shift_ref (.CLK(CLK), .ACLR(ACLR), .WADDR(WADDR), .DATA(SDATA2), .WREN(WREN2), .RADDR(RADDR), .Q(shr));
    integer cycle, checks=0;
    reg wren_prev=0;
    initial begin
        for (cycle=0; cycle<200000; cycle=cycle+1) begin
            @(negedge CLK);
            // Port A read-during-write (NEW_DATA_NO_NBE_READ) leaves masked
            // bytes undefined in simulation; the CPU never reads its own write.
            wren_prev = WREN;
            // Mixed-port same-word collisions are inadmissible in the bank leaf
            // (DONT_CARE); keep the serial word away from the CPU word.
            ADDR = $urandom; SADDR = $urandom;
            if (SADDR == ADDR[11:3]) SADDR = SADDR + 9'd1;
            DATA = $urandom; SDATA = {$urandom,$urandom};
            WREN = ($urandom%3)!=0; BE = $urandom; SWREN = ($urandom%4)==0;
            WADDR = $urandom; RADDR = ($urandom%4==0) ? WADDR : $urandom;
            SDATA2 = {$urandom,$urandom};
            WREN2 = ($urandom%3==0) ? 8'h00 : ($urandom%5==0) ? 8'hff : $urandom;
            // Hold the output clear for the first cycles and pulse it later,
            // including while reads are in flight.
            ACLR = (cycle < 3) || (cycle % 7001) == 0 || (cycle % 7001) == 1;
            if (cycle > 4) begin
                if (!wren_prev && qc !== qr) $fatal(1,"bank CPU read differs cycle=%0d %h vs %h",cycle,qc,qr);
                if (sqc !== sqr) $fatal(1,"bank serial read differs cycle=%0d %h vs %h",cycle,sqc,sqr);
                if (shc !== shr) $fatal(1,"shift-register read differs cycle=%0d %h vs %h",cycle,shc,shr);
                checks = checks + 3;
            end
        end
        $display("PASS registered M10K output modes: %0d comparisons (bank CPU/serial reads, shift-register read)",checks);
        $finish;
    end
endmodule
