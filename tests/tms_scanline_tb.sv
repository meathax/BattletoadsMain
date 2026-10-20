`timescale 1ns/1ps
module tms_scanline_tb;
    import TMS34020_PKG::*;
    import "DPI-C" function int unsigned mame_display_advance(input int unsigned address,increment);
    bit clk=0;
    always #5 clk=~clk;
    bit reset_n=0,write=0,pixel=0;
    bit [12:0] addr;
    bit [31:0] data;
    bit [3:0] lanes=15;
    IOReg_t regs;
    wire [31:0] refresh;
    wire refresh_run,hbl,vbl;
    TMS34020_IO dut(.CLK(clk),.RST_N(reset_n),.EN(1'b1),.CE_R(1'b1),.CE_F(1'b0),
        .RES_N(1'b1),.NMI_N(1'b1),.LINT1_N(1'b1),.LINT2_N(1'b1),
        .A(addr),.DI(data),.WE(write),.RD(1'b0),.BE(lanes),.REGS(regs),
        .DO(),.INT1_REQ(),.INT2_REQ(),.HI_REQ(),.DI_REQ(),.WV_REQ(),.HS_N(),.VS_N(),
        .SCRREF_ADDR(refresh),.SCRREF_RUN(refresh_run),.VCE_R(pixel),.HBL_N(hbl),.VBL_N(vbl));
    int checks=0,transfers=0,writes=0;
    task automatic put(input bit [12:0] a,input bit [31:0] d,input bit[3:0] be=15);
        @(negedge clk);addr=a;data=d;lanes=be;write=1;
        @(negedge clk);write=0;lanes=15;
    endtask
    task automatic line_pixel;
        int unsigned expected;
        bit next_visible,boundary;
        bit [15:0] vc_next;
        @(negedge clk);
        pixel=1;
        expected=regs.DPYNX;
        boundary=regs.HCOUNT==regs.HSBLNK;
        vc_next=regs.VCOUNT==regs.VTOTAL ? 0 : regs.VCOUNT+1;
        next_visible=vc_next>=regs.VEBLNK && vc_next<regs.VSBLNK;
        if(boundary) begin
            if(regs.VCOUNT==regs.VSBLNK) expected=regs.DPYST & 32'hffffffe0;
            else if(regs.VCOUNT>=regs.VEBLNK && regs.VCOUNT<regs.VSBLNK)
                expected=mame_display_advance(regs.DPYNX,regs.DINC);
        end
        @(negedge clk);
        if(boundary) begin
            if(regs.DPYNX!==expected) $fatal(1,"MAME display advance mismatch actual=%h expected=%h",regs.DPYNX,expected);
            if(refresh_run!==next_visible) $fatal(1,"next-line prefill missing/extra vc=%0d",regs.VCOUNT);
            if(next_visible) begin
                if(refresh!==expected) $fatal(1,"prefill address mismatch actual=%h expected=%h",refresh,expected);
                transfers++;
            end
            checks++;
        end
        if(vbl!==(regs.VCOUNT>=regs.VEBLNK && regs.VCOUNT<regs.VSBLNK))
            $fatal(1,"vertical blank disagrees with VCOUNT=%0d",regs.VCOUNT);
        pixel=0;
    endtask
    initial begin
        for(integer scenario=0;scenario<64;scenario++) begin
            reset_n=0;repeat(3)@(negedge clk);reset_n=1;
            @(negedge clk);pixel=1;@(negedge clk);pixel=0;
            put('h0000,{16'd2,16'd2});
            put('h0020,{16'd8,16'd2});
            put('h0040,{16'd24,16'd8});
            put('h0060,{16'd31,16'd10});
            if(regs.HTOTAL!=31 || regs.HSBLNK!=24 || regs.HEBLNK!=8 ||
               regs.VTOTAL!=10 || regs.VSBLNK!=8 || regs.VEBLNK!=2)
                $fatal(1,"scanline fixture register map is incorrect");
            put('h0200,scenario[5] ? 32'hffffffe0 : 32'ha0000000);
            put('h0240,(scenario[5] ? 32'hffffffe0 : 32'h00004000) | (scenario%32));
            // Real byte enables and independent writable DPYNX fields.
            put('h0220,32'h12345678);
            if(regs.DPYNX!==32'h12345678)$fatal(1,"DPYNX word write ignored");
            for(integer lane=0;lane<4;lane++) begin
                bit [31:0] old_address,mask;
                old_address=regs.DPYNX;mask=32'hff << (lane*8);
                put('h0220,32'h89abcdef,4'b1<<lane);
                if(regs.DPYNX!==((old_address & ~mask) | (32'h89abcdef & mask)))
                    $fatal(1,"DPYNX byte write mismatch lane=%0d",lane);
                writes++;
            end
            put('h0080,{16'h0000,16'hc000});
            repeat(32*11*8)line_pixel();
        end
        if(checks!=5632 || transfers!=3072 || writes!=256)
            $fatal(1,"scanline coverage incomplete steps=%0d prefills=%0d writes=%0d",checks,transfers,writes);
        $display("PASS MAME scanline rules: %0d line steps, %0d next-line prefills, %0d byte writes; 32 fractional increments and address wraps",checks,transfers,writes);
        $finish;
    end
endmodule
