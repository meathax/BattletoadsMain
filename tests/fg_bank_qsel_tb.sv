`timescale 1ns/1ps
// QSEL_EN folds the foreground bank gate into the slice read mux: the result
// must equal the ungated read masked by the bank gate registered one clock.
//   iverilog -g2012 -s fg_bank_qsel_tb -o q.vvp tests/fg_bank_qsel_tb.sv rtl/BT_mem.sv D:/q17/quartus/eda/sim_lib/altera_mf.v
module fg_bank_qsel_tb;
    reg CLK=0; always #3 CLK=~CLK;
    reg [13:1] ADDR=0; reg [15:0] DATA=0; reg WREN=0; reg [1:0] BE=0;
    reg [13:3] SADDR=0; reg [63:0] SDATA=0; reg SWREN=0; reg gate=0, gate_q=0;
    wire [15:0] q0, q1; wire [63:0] sq0, sq1;
    VRAM_MEM_64Kx8 #(.ADDR_WIDTH(14), .SQ_REG(1), .SERIAL_WRITE_DECODE(1), .QSEL_EN(0)) ref_ram
        (.CLK(CLK), .ADDR(ADDR), .DATA(DATA), .WREN(WREN), .BE(BE), .Q(q0), .SADDR(SADDR), .SDATA(SDATA), .SWREN(SWREN), .SQ(sq0), .SADDR_W(SADDR), .WREN_LANE(2'b00), .QGATE_D(1'b0));
    VRAM_MEM_64Kx8 #(.ADDR_WIDTH(14), .SQ_REG(1), .SERIAL_WRITE_DECODE(1), .QSEL_EN(1)) dut
        (.CLK(CLK), .ADDR(ADDR), .DATA(DATA), .WREN(WREN), .BE(BE), .Q(q1), .SADDR(SADDR), .SDATA(SDATA), .SWREN(SWREN), .SQ(sq1), .SADDR_W(SADDR), .WREN_LANE(2'b00), .QGATE_D(gate));
    always @(posedge CLK) gate_q <= gate;
    integer cycle, checks=0, ones=0;
    initial begin
        for (cycle=0; cycle<100000; cycle=cycle+1) begin
            @(negedge CLK);
            if (cycle > 4) begin
                if (^q0 !== 1'bx && q1 !== (q0 & {16{gate_q}})) begin
                    $display("FAIL cycle=%0d q0=%h q1=%h gate=%b", cycle, q0, q1, gate_q); $fatal(1);
                end
                if (sq0 !== sq1) begin $display("FAIL serial cycle=%0d", cycle); $fatal(1); end
                if (^q0 !== 1'bx) begin checks=checks+1; ones=ones+gate_q; end
            end
            ADDR = $urandom; SADDR = $urandom;
            if (SADDR == ADDR[13:3]) SADDR = SADDR + 11'd1;
            DATA = $urandom; SDATA = {$urandom,$urandom};
            WREN = ($urandom%2)!=0; BE = 2'b11; SWREN = ($urandom%4)==0; gate = ($urandom%3)!=0;
        end
        $display("PASS fg_bank_qsel_tb checks=%0d gated_on=%0d", checks, ones);
        $finish;
    end
endmodule
