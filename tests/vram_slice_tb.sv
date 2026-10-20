`timescale 1ns/1ps
// Compare both physical layouts with Altera's real mixed-width RAM model.
// AW16/SQ_REG0 protects the background layout; AW14/SQ_REG1 qualifies FG.
// The frozen sixteen-bank module below also checks all four address groups.
// Mixed-port DONT_CARE output bits are excluded; every defined reference bit
// must match, and subsequent settled reads verify retained memory contents.
// iverilog -g2012 -s vram_slice_tb -o proof.vvp tests/vram_slice_tb.sv rtl/BT_mem.sv rtl/fg_vram.sv D:/q17/quartus/eda/sim_lib/altera_mf.v
module VRAM_MEM_REF #(parameter AW=16, parameter SQ_REG=0) (
    input CLK, input [AW-1:1] ADDR, input [15:0] DATA, input WREN, input [1:0] BE,
    output [15:0] Q, input [AW-1:3] SADDR, input [63:0] SDATA, input SWREN, output [63:0] SQ);
    altsyncram #(.address_reg_b("CLOCK0"), .byte_size(8), .clock_enable_input_a("BYPASS"),
        .clock_enable_input_b("BYPASS"), .clock_enable_output_a("BYPASS"), .clock_enable_output_b("BYPASS"),
        .indata_reg_b("CLOCK0"), .intended_device_family("Cyclone V"), .lpm_type("altsyncram"),
        .numwords_a(1 << (AW-1)), .numwords_b(1 << (AW-3)), .operation_mode("BIDIR_DUAL_PORT"), .outdata_aclr_a("NONE"),
        .outdata_aclr_b("NONE"), .outdata_reg_a("UNREGISTERED"), .outdata_reg_b(SQ_REG ? "CLOCK0" : "UNREGISTERED"),
        .power_up_uninitialized("FALSE"), .read_during_write_mode_mixed_ports("DONT_CARE"),
        .read_during_write_mode_port_a("NEW_DATA_NO_NBE_READ"), .read_during_write_mode_port_b("NEW_DATA_NO_NBE_READ"),
        .widthad_a(AW-1), .widthad_b(AW-3), .width_a(16), .width_b(64), .width_byteena_a(2), .width_byteena_b(1),
        .wrcontrol_wraddress_reg_b("CLOCK0"))
    r (.byteena_a(BE), .clock0(CLK), .wren_a(WREN), .address_b(SADDR), .data_b(SDATA), .wren_b(SWREN),
       .address_a(ADDR), .data_a(DATA), .q_a(Q), .q_b(SQ), .aclr0(1'b0), .aclr1(1'b0), .addressstall_a(1'b0),
       .addressstall_b(1'b0), .byteena_b(1'b1), .clock1(1'b1), .clocken0(1'b1), .clocken1(1'b1),
       .clocken2(1'b1), .clocken3(1'b1), .eccstatus(), .rden_a(1'b1), .rden_b(1'b1));
endmodule

module vram_slice_case #(parameter AW=16, parameter SQ_REG=0, parameter SEED=32'h145a0321)
    (input CLK, output reg done=0);
    reg [AW-1:1] a=0;
    reg [15:0] d=0;
    reg wa=0;
    reg [1:0] be=0;
    reg [AW-1:3] sa=0;
    reg [63:0] sd=0;
    reg wb=0;
    wire [15:0] qc,qr;
    wire [63:0] sqc,sqr;
    VRAM_MEM_64Kx8 #(.ADDR_WIDTH(AW),.SQ_REG(SQ_REG)) cand
        (CLK,a,d,wa,be,qc,sa,sd,wb,sqc);
    VRAM_MEM_REF #(.AW(AW),.SQ_REG(SQ_REG)) ref_ram
        (CLK,a,d,wa,be,qr,sa,sd,wb,sqr);
    integer cycles=0,known_bits=0,undefined_bits=0,a_writes=0,b_writes=0,mixed_reads=0;
    integer seed=SEED, ignored, c;
    function automatic [63:0] pattern(input integer word);
        for(integer byte_lane=0;byte_lane<8;byte_lane++)
            pattern[byte_lane*8+:8]=(word*29+byte_lane*53) ^ (word>>5);
    endfunction
    function automatic [15:0] word_pattern(input integer word);
        word_pattern=pattern(word>>2) >> ((word%4)*16);
    endfunction
    task automatic check_outputs;
        for(integer bit_index=0;bit_index<80;bit_index++) begin
            if(bit_index<16) begin
                if(qr[bit_index]===1'b0 || qr[bit_index]===1'b1) begin
                    known_bits++;
                    if(qc[bit_index] !== qr[bit_index])
                        $fatal(1,"slice AW%0d SQ_REG%0d Q cycle=%0d bit=%0d a=%h be=%b wa=%b wb=%b got=%h expected=%h",
                               AW,SQ_REG,cycles,bit_index,a,be,wa,wb,qc,qr);
                end else undefined_bits++;
            end else begin
                if(sqr[bit_index-16]===1'b0 || sqr[bit_index-16]===1'b1) begin
                    known_bits++;
                    if(sqc[bit_index-16] !== sqr[bit_index-16])
                        $fatal(1,"slice AW%0d SQ_REG%0d SQ cycle=%0d bit=%0d sa=%h wa=%b wb=%b got=%h expected=%h",
                               AW,SQ_REG,cycles,bit_index-16,sa,wa,wb,sqc,sqr);
                end else undefined_bits++;
            end
        end
        cycles++;
        if(wa && |be) a_writes++;
        if(wb) b_writes++;
        if(wa && |be && sa==a[AW-1:3]) mixed_reads++;
    endtask
    task automatic tick;
        @(posedge CLK); #1; check_outputs();
    endtask
    initial begin
        ignored=$urandom(seed);
        // Initialize and subsequently read every byte through both widths.
        for(c=0;c<(1 << (AW-3));c++) begin
            @(negedge CLK); a=(c+3)*4; sa=c; sd=pattern(c); wb=1; wa=0; be=0;
            tick();
        end
        for(c=0;c<(1 << (AW-1));c++) begin
            @(negedge CLK); a=c; sa=c>>2; wb=0; wa=0;
            tick();
            if(qc !== word_pattern(c))
                $fatal(1,"every-byte initialization AW%0d address=%h got=%h",AW,a,qc);
        end
        // A registered serial result must retain the previous address for the
        // first edge and publish the new word on the second edge.
        @(negedge CLK); a=0; sa=0; tick();
        @(negedge CLK); tick();
        if(sqc !== pattern(0)) $fatal(1,"serial initial word AW%0d",AW);
        @(negedge CLK); sa=(1 << (AW-3))-1; tick();
        if(sqc !== pattern(SQ_REG ? 0 : (1 << (AW-3))-1))
            $fatal(1,"serial address-stage latency AW%0d SQ_REG%0d",AW,SQ_REG);
        @(negedge CLK); tick();
        if(sqc !== pattern((1 << (AW-3))-1)) $fatal(1,"serial output-stage latency AW%0d",AW);
        // Exercise every byte-enable combination at every port-A address.
        for(c=0;c<(1 << (AW-1));c++) begin
            @(negedge CLK); a=c; sa=c>>2; d=(c*43)^16'hc381; be=c%4; wa=1; wb=0;
            tick();
            @(negedge CLK); wa=0;
            tick();
        end
        // Repeat accesses to initialized words, including read/write
        // collisions, serial new-data writes, and all address/bank boundaries.
        for(c=0;c<30000;c++) begin
            @(negedge CLK);
            a=($urandom%3) ? ($urandom%128) : $urandom;
            sa=($urandom%2) ? a[AW-1:3] : $urandom;
            d=$urandom; sd={$urandom,$urandom}; be=$urandom;
            wa=($urandom%3==0);
            wb=($urandom%11==0) && !(wa && |be && sa==a[AW-1:3]);
            tick();
        end
        @(negedge CLK); wa=0; wb=0;
        repeat(3) tick();
        if(mixed_reads<100 || a_writes<1000 || b_writes<1000)
            $fatal(1,"insufficient collision/write coverage AW%0d",AW);
        $display("PASS slice AW=%0d SQ_REG=%0d cycles=%0d defined_bits=%0d undefined_bits=%0d A_writes=%0d B_writes=%0d mixed_reads=%0d",
                 AW,SQ_REG,cycles,known_bits,undefined_bits,a_writes,b_writes,mixed_reads);
        done=1;
    end
endmodule

module vram_bank_case(input CLK,output reg done=0);
    reg [15:1] a=0;
    reg [15:0] d=0,banks=0;
    reg [1:0] be=0;
    reg [15:3] swaddr=0,copyaddr=0,videoaddr=0;
    reg srsel=0,swsel=0,scsel=0;
    reg [63:0] dc=0,ds=0;
    wire [15:0] qc,qr;
    wire [63:0] sqc,sqr;
    wire [3:0][12:0] wb4={4{swaddr}};
    wire [15:0][12:0] wb16={16{swaddr}};
    BT_FG_BANKED_VRAM cand(CLK,a,d,banks,be,qc,swaddr,copyaddr,videoaddr,wb4,
        {4{srsel}},{4{swsel}},dc,ds,{4{scsel}},sqc);
    BT_FG_BANKED_VRAM_16_REF ref_ram(CLK,a,d,banks,be,qr,swaddr,copyaddr,videoaddr,wb16,
        {16{srsel}},{16{swsel}},dc,ds,{16{scsel}},sqr);
    integer cycles=0,known_bits=0,undefined_bits=0,c,seed=32'h25690a4b,ignored;
    integer a_writes=0,b_writes=0,mixed_reads=0,boundary_reads=0;
    function automatic [15:0] pattern(input integer word);
        pattern=(word*71)^16'h8e25;
    endfunction
    task automatic tick;
        @(posedge CLK); #1;
        for(integer bit_index=0;bit_index<80;bit_index++) begin
            if(bit_index<16) begin
                if(qr[bit_index]===1'b0 || qr[bit_index]===1'b1) begin
                    known_bits++;
                    if(qc[bit_index] !== qr[bit_index])
                        $fatal(1,"bank Q cycle=%0d bit=%0d a=%h banks=%h be=%b got=%h expected=%h",cycles,bit_index,a,banks,be,qc,qr);
                end else undefined_bits++;
            end else begin
                if(sqr[bit_index-16]===1'b0 || sqr[bit_index-16]===1'b1) begin
                    known_bits++;
                    if(sqc[bit_index-16] !== sqr[bit_index-16])
                        $fatal(1,"bank SQ cycle=%0d bit=%0d sw=%h copy=%h video=%h selects=%b%b got=%h expected=%h",
                               cycles,bit_index-16,swaddr,copyaddr,videoaddr,swsel,srsel,sqc,sqr);
                end else undefined_bits++;
            end
        end
        cycles++;
        if(|banks && |be) a_writes++;
        if(swsel) b_writes++;
        if(|banks && |be && (swsel ? swaddr : srsel ? copyaddr : videoaddr)==a[15:3]) mixed_reads++;
        if(a[11:1]==0 || &a[11:1]) boundary_reads++;
    endtask
    initial begin
        ignored=$urandom(seed);
        for(c=0;c<32768;c++) begin
            @(negedge CLK); a=c; d=pattern(c); be=3; banks=16'b1<<a[15:12];
            videoaddr=c>>2;
            tick();
        end
        for(c=0;c<32768;c++) begin
            @(negedge CLK); a=c; banks=0; videoaddr=c>>2;
            tick();
            if(qc !== pattern(c))
                $fatal(1,"bank every-byte initialization address=%h got=%h",a,qc);
        end
        for(c=0;c<30000;c++) begin
            @(negedge CLK);
            a=($urandom%3) ? ($urandom%128) : $urandom;
            d=$urandom; be=$urandom; banks=($urandom%3==0) ? (16'b1<<a[15:12]) : 0;
            swaddr=$urandom; copyaddr=$urandom;
            videoaddr=($urandom%2) ? a[15:3] : $urandom;
            srsel=$urandom; scsel=$urandom; dc={$urandom,$urandom}; ds={$urandom,$urandom};
            swsel=($urandom%11==0) && !(|banks && |be && swaddr==a[15:3]);
            tick();
        end
        @(negedge CLK); banks=0; swsel=0;
        repeat(3) tick();
        if(a_writes<1000 || b_writes<1000 || mixed_reads<100 || boundary_reads<20)
            $fatal(1,"insufficient consolidated-bank coverage");
        $display("PASS FG16->4 banks cycles=%0d defined_bits=%0d undefined_bits=%0d A_writes=%0d B_writes=%0d mixed_reads=%0d boundaries=%0d",
                 cycles,known_bits,undefined_bits,a_writes,b_writes,mixed_reads,boundary_reads);
        done=1;
    end
endmodule

module vram_slice_tb;
    reg CLK=0; always #5 CLK=~CLK;
    wire bg_done,fg_done,bank_done;
    vram_slice_case #(.AW(16),.SQ_REG(0)) background(CLK,bg_done);
    vram_slice_case #(.AW(14),.SQ_REG(1),.SEED(32'h231954d1)) foreground(CLK,fg_done);
    vram_bank_case bank_mapping(CLK,bank_done);
    initial begin
        wait(bg_done && fg_done && bank_done);
        $display("PASS physical VRAM slicing and foreground bank consolidation");
        $finish;
    end
    initial begin #2000000; $fatal(1,"VRAM proof timeout"); end
endmodule

// Frozen pre-consolidation bank wrapper; unchanged leaf AW12 retains the
// original whole mixed-width primitive. Backup SHA256 is in
// build/resource_audit/before/fg_bank_before.json.
module BT_FG_BANKED_VRAM_16_REF (
    input CLK,
    input [15:1] ADDR,
    input [15:0] DATA, BANK_WREN,
    input [1:0] BE,
    output logic [15:0] Q,
    // Serial port: per-bank copies of the write strobe and copy-mode select
    // keep each bank's address/data mux local instead of one 1024-load net.
    input [15:3] SADDR_W, SADDR_C, SADDR_V,
    input [15:0][12:0] SADDR_WB,
    input [15:0] SRSEL, SWSEL,
    input [63:0] SDATA_C, SDATA_S,
    input [15:0] SCSEL,
    output logic [63:0] SQ
);
    wire [15:3] SADDR = SWSEL[0] ? SADDR_W : SRSEL[0] ? SADDR_C : SADDR_V;
    wire [15:0][15:0] bank_q;
    wire [15:0][63:0] bank_sq;
    reg [15:0] read_bank=16'b1, serial_bank=16'b1, serial_bank2=16'b1;
    always @(posedge CLK) begin
        read_bank <= 16'b1 << ADDR[15:12];
        serial_bank <= 16'b1 << SADDR[15:12];
        serial_bank2 <= serial_bank;
    end
    genvar bank;
    generate for (bank=0;bank<16;bank=bank+1) begin : banks
        VRAM_MEM_64Kx8 #(.ADDR_WIDTH(12), .SQ_REG(1)) ram (
            .CLK(CLK),.ADDR(ADDR[11:1]),.DATA(DATA),.WREN(BANK_WREN[bank]),.BE(BE),.Q(bank_q[bank]),
            .SADDR(SWSEL[bank] ? SADDR_WB[bank][8:0] : SRSEL[bank] ? SADDR_C[11:3] : SADDR_V[11:3]),.SDATA(SCSEL[bank] ? SDATA_C : SDATA_S),
            .SWREN(SWSEL[bank] && SADDR_WB[bank][12:9]==bank),.SQ(bank_sq[bank]));
    end endgenerate
    always_comb begin
        Q=0; SQ=0;
        for (integer bank=0;bank<16;bank=bank+1) begin
            Q |= bank_q[bank] & {16{read_bank[bank]}};
            SQ |= bank_sq[bank] & {64{serial_bank2[bank]}};
        end
    end
endmodule
