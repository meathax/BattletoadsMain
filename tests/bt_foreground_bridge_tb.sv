`timescale 1ns/1ps
// The production BT bridge is exercised with the existing graphics CPU-bus
// stimulus stub. CPU instruction execution remains covered by native replay.
module BT_GRAPHICS_SIM;
    bit CLK=0, CLK2X=0, RST_N=0;
    always #6.25 CLK=~CLK;
    always #3.125 CLK2X=~CLK2X;
    bit [31:0] BUS_ADDR=0, BUS_DATA=0, BUS_BIT_ADDR=0;
    bit BUS_RAS_N=1, BUS_WE_N=1, BUS_QE_N=1;
    bit [3:0] BUS_CAS_N=4'hf;
    wire ERAM, EROM, ENVRAM, ESPR, EFG, ERD;
    wire [22:0] EADDR;
    bit [31:0] raw_ddr_q=32'h70503010;
    bit pending=0;
    integer remaining=0, requests=0, consumers=0, ready_checks=0;
    bit [17:0] request_addr;
    wire hole_rd=dut.FG0_HOLE_RD || dut.FG1_HOLE_RD;
    wire hole_sel=dut.FG0_HOLE_SEL || dut.FG1_HOLE_SEL;
    wire srdy=!(pending || hole_rd);
    // Same priority as the production top: only the NVRAM arm replaces DDR.
    wire [31:0] selected_eq=ERAM ? raw_ddr_q : EROM ? raw_ddr_q :
                               ENVRAM ? 32'h00c3005a : ESPR ? raw_ddr_q : raw_ddr_q;
    BT dut(.CLK(CLK),.CLK2X(CLK2X),.RST_N(RST_N),.EN(1'b1),
        .CE_F(1'b0),.CE_R(1'b1),.VCE_R(1'b0),.SCE_F(1'b0),.SCE_R(1'b0),
        .SERVICE(1'b1),.EQ(selected_eq),.NVRAM_Q(selected_eq),.FG_DDR_Q(raw_ddr_q),.ERDY(srdy),
        .ESQ(64'b0),.ESTE(1'b0),.SRDY(srdy),
        .ERAM(ERAM),.EROM(EROM),.ENVRAM(ENVRAM),.ESPR(ESPR),.EFG(EFG),
        .EADDR(EADDR),.ERD(ERD),.BSMT_ROM_DI(8'b0),.SW1(8'h7c),
        .P1(8'hff),.P2(8'hff),.P3(8'hff),.BG_EN(3'b111),.GRID_EN(3'b0));
    function automatic [7:0] pattern(input bit [17:0] address);
        return (address[7:0] * 8'd37) ^ address[17:10] ^ 8'hb6;
    endfunction
    always @(posedge CLK2X) if (RST_N) begin
        if (hole_rd && !pending) begin
            request_addr <= dut.FG0_HOLE_RD ? dut.FG0_HOLE_A : dut.FG1_HOLE_A;
            pending <= 1;
            remaining <= 3 + (requests % 7);
            requests <= requests + 1;
        end else if (pending) begin
            if (remaining == 0) begin
                raw_ddr_q <= {8'h99,pattern(request_addr | 18'd1),
                              8'h55,pattern(request_addr & ~18'd1)};
                pending <= 0;
            end else remaining <= remaining - 1;
        end
    end
    bit [31:0] previous_eq;
    always @(posedge CLK2X) begin
        previous_eq <= selected_eq;
        if (RST_N) begin
            if (dut.FG0_VRAM.UNALIGNED_EXEC && dut.FG0_VRAM.COPY_DDR &&
                dut.FG0_VRAM.COPY_STATE == 3'd3) begin
                assert(dut.FG0_VRAM.COPY_DDR_WORD == previous_eq)
                    else $fatal(1,"FG0 selected return changed at gather capture");
                assert((dut.FG0_VRAM.COPY_ODD ? dut.FG0_VRAM.COPY_DDR_WORD[23:16] :
                        dut.FG0_VRAM.COPY_DDR_WORD[7:0]) == pattern(dut.FG0_VRAM.COPY_ADDR))
                    else $fatal(1,"FG0 raw DDR gathered wrong byte");
                consumers <= consumers+1;
            end
            if (dut.FG1_VRAM.UNALIGNED_EXEC && dut.FG1_VRAM.COPY_DDR &&
                dut.FG1_VRAM.COPY_STATE == 3'd3) begin
                assert(dut.FG1_VRAM.COPY_DDR_WORD == previous_eq)
                    else $fatal(1,"FG1 selected return changed at gather capture");
                assert((dut.FG1_VRAM.COPY_ODD ? dut.FG1_VRAM.COPY_DDR_WORD[23:16] :
                        dut.FG1_VRAM.COPY_DDR_WORD[7:0]) == pattern(dut.FG1_VRAM.COPY_ADDR))
                    else $fatal(1,"FG1 raw DDR gathered wrong byte");
                consumers <= consumers+1;
            end
        end
    end
    // Compare the bridge against the exact previous priority mux after its
    // address publication. All transfer busy and DDR backpressure transitions
    // are checked, including the ready edge that completes each transaction.
    bit [32:0] previous_decode;
    always @(posedge CLK) previous_decode <= {BUS_ADDR,dut.DISP_CONTROL[15]};
    always @(negedge CLK2X) if (RST_N && previous_decode == {BUS_ADDR,dut.DISP_CONTROL[15]}) begin
        assert(dut.LRDY == (dut.SPR_BUSY || dut.CPU_SHIFT_BUSY ? 1'b0 : dut.MISC_SEL ? 1'b1 :
            BUS_ADDR[3:0] == 4'b0100 ? dut.FG0_RDY & dut.FG1_RDY : BUS_ADDR[31:24] == 8'h40 ? 1'b1 :
            EFG && BUS_ADDR[3] ? srdy : dut.SPR_SEL ? dut.SPR_RDY & srdy : dut.FG0_SEL ? dut.FG0_RDY :
            dut.FG1_SEL ? dut.FG1_RDY : dut.BG0_SEL ? 1'b1 : dut.BG1_SEL ? 1'b1 : srdy))
            else $fatal(1,"BT selected-busy ready differs from original priority mux");
        ready_checks <= ready_checks+1;
    end
    task automatic gather(input bit [31:0] address);
        @(negedge CLK);
        BUS_ADDR=address;
        BUS_BIT_ADDR=32'h0000c000;
        BUS_RAS_N=1; BUS_WE_N=1; BUS_QE_N=1;
        repeat(4) @(negedge CLK);
        BUS_RAS_N=0; BUS_QE_N=0;
        wait(!dut.LRDY);
        wait(dut.LRDY);
        @(negedge CLK);
        BUS_RAS_N=1; BUS_QE_N=1;
        repeat(12) @(negedge CLK);
    endtask
    initial begin
        repeat(8) @(negedge CLK);
        RST_N=1;
        repeat(8) @(negedge CLK);
        // Idle NVRAM selection deliberately makes EQ differ from raw DDR.
        BUS_ADDR=32'h6000000a;
        repeat(4) @(negedge CLK);
        assert(ENVRAM && selected_eq != raw_ddr_q)
            else $fatal(1,"test did not exercise the separate NVRAM return arm");
        gather(32'ha0000005);
        // Flip the real display-page register through the CPU bus; the
        // display-transfer window then gathers the other physical page.
        BUS_ADDR=32'h2000018a; BUS_DATA=32'h00008000;
        BUS_WE_N=0; BUS_CAS_N=4'hd;
        repeat(3) @(negedge CLK);
        BUS_WE_N=1; BUS_CAS_N=4'hf;
        assert(dut.DISP_CONTROL[15]) else $fatal(1,"display-page register write failed");
        gather(32'ha0000005);
        assert(consumers==512 && requests==512)
            else $fatal(1,"missing DDR gather consumers=%0d requests=%0d",consumers,requests);
        assert(ready_checks>1024) else $fatal(1,"insufficient live ready checks");
        $display("PASS production BT FG bridge: %0d DDR byte consumers on both pages, %0d varied-backpressure requests, %0d old/new ready checks, distinct NVRAM return",consumers,requests,ready_checks);
        $finish;
    end
    initial begin #2000000; $fatal(1,"BT FG bridge watchdog consumers=%0d requests=%0d ready=%b addr=%h",consumers,requests,dut.LRDY,BUS_ADDR); end
endmodule
