`timescale 1ns/1ps
module sprite_packet_tb;
    logic clk=0, reset_n=0, write_en=0;
    logic [5:0] write_addr=0, read_addr=0;
    logic [63:0] write_data=0;
    wire [63:0] read_data;
    wire busy;
    logic [63:0] expected [64];
    always #3.125 clk=~clk;
    SPR_VRAM dut(.CLK(clk),.RST_N(reset_n),.A(18'b0),.D(32'b0),
        .RAS_N(1'b1),.CAS_N(4'hf),.WE_N(1'b1),.OE_N(1'b1),
        .SC(1'b0),.SE_N(1'b1),.BLIT_A(9'b0),
        .CPU_SHIFT_WE(write_en),.CPU_SHIFT_WA(write_addr),
        .CPU_SHIFT_DATA(write_data),.CPU_SHIFT_BUSY(busy),
        .CPU_SHIFT_RD(1'b1),.CPU_SHIFT_A(read_addr),.CPU_SHIFT_Q(read_data),
        .ESQ(64'b0),.ESTE(1'b0));
    initial begin
        repeat(3) @(negedge clk);
        reset_n=1;
        // Consecutive packets exercise both address wrap and all byte lanes.
        for (int pass=0; pass<8; pass++) begin
            for (int i=0; i<64; i++) begin
                @(negedge clk);
                write_en=1;
                write_addr=6'((i*17+pass)%64);
                write_data={32'((pass+1)*32'h93a541d7+i),32'(32'hd812f074^(i*32'h219e307b))};
                expected[write_addr]=write_data;
                #0.1;
                assert(busy) else $fatal(1,"incoming packet did not hold completion");
            end
            @(negedge clk);
            write_en=0;
            #0.1;
            assert(busy) else $fatal(1,"completion released before final commit");
            @(negedge clk);
            assert(!busy) else $fatal(1,"packet did not drain");
            for (int i=0; i<64; i++) begin
                read_addr=6'(i);
                repeat(2) @(negedge clk);
                assert(read_data===expected[i])
                    else $fatal(1,"packet address/data mismatch pass=%0d word=%0d",pass,i);
            end
        end
        $display("SPRITE_PACKET_PASS packets=512 readbacks=512 completion_checks=528");
        $finish;
    end
endmodule
