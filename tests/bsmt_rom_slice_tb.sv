`timescale 1ns/1ps
// Compile the production file with only synopsys translate_off blocks removed,
// selecting its hardware branch, together with Intel's altera_mf.v model.
module bsmt_rom_slice_tb;
    reg CLK=0; always #6.25 CLK=~CLK;
    reg [11:0] ADDR=0;
    wire [15:0] sliced_q, original_q, alternate_q;
    reg [15:0] canonical [0:4095];
    TMS320C1X_ROM #(.rom_file("rtl/bsmt2000.mif")) sliced (CLK, ADDR, sliced_q);
    // A different filename selects the retained unsliced production branch.
    TMS320C1X_ROM #(.rom_file("rtl/./bsmt2000.mif"))
        alternate (CLK, ADDR, alternate_q);
    altsyncram #(
        .address_aclr_a("NONE"), .clock_enable_input_a("BYPASS"),
        .clock_enable_output_a("BYPASS"), .init_file("rtl/bsmt2000.mif"),
        .intended_device_family("Cyclone V"), .lpm_hint("ENABLE_RUNTIME_MOD=NO"),
        .lpm_type("altsyncram"), .numwords_a(4096), .operation_mode("ROM"),
        .outdata_aclr_a("NONE"), .outdata_reg_a("UNREGISTERED"),
        .widthad_a(12), .width_a(16), .width_byteena_a(1)
    ) original (
        .address_a(ADDR), .clock0(CLK), .q_a(original_q), .aclr0(1'b0), .aclr1(1'b0),
        .address_b(1'b1), .addressstall_a(1'b0), .addressstall_b(1'b0),
        .byteena_a(1'b1), .byteena_b(1'b1), .clock1(1'b1),
        .clocken0(1'b1), .clocken1(1'b1), .clocken2(1'b1), .clocken3(1'b1),
        .data_a(16'hffff), .data_b(1'b1), .eccstatus(), .q_b(),
        .rden_a(1'b1), .rden_b(1'b1), .wren_a(1'b0), .wren_b(1'b0)
    );
    integer cycle, checks=0, held_checks=0;
    reg [15:0] held;
    initial begin
        $readmemh("tests/graphics/evidence/bsmt_rom_slices/canonical.hex",canonical);
        for(cycle=0;cycle<20000;cycle=cycle+1) begin
            @(negedge CLK);
            held=original_q;
            ADDR=cycle<4096 ? cycle : $urandom;
            #1;
            if(cycle>0) begin
                if(sliced_q!==held || alternate_q!==held || original_q!==held)
                    $fatal(1,"ROM latency changed before clock at cycle %0d",cycle);
                held_checks=held_checks+1;
            end
            @(posedge CLK); #1;
            if(sliced_q!==original_q || alternate_q!==original_q ||
               sliced_q!==canonical[ADDR])
                $fatal(1,"ROM mismatch address=%h candidate=%h original=%h golden=%h",
                    ADDR,sliced_q,original_q,canonical[ADDR]);
            checks=checks+1;
        end
        $display("PASS BSMT ROM slicing: all 4096 words, %0d clocked reads, %0d held-output checks; fallback path equal",checks,held_checks);
        $finish;
    end
endmodule
