`timescale 1ns/1ps
module foreground_ddr_fast_tb;
    wire fast_we, fast_done;
    wire [16:0] fast_word;
    wire [63:0] fast_data;
    reg clk=0, rst_n=0, ras_n=1, we_n=1, oe_n=1;
    always #5 clk=!clk;
    integer cycles=0, writes=0, empty_writes=0, copied=0;
    reg [17:0] a=0;
    wire sclk=(cycles%4)<2;
    wire [15:0] q;
    wire ready, copy_we, copy_rd, hole_sel, hole_rd;
    wire [17:0] hole_a;
    wire [3:0] hole_we;
    wire [31:0] hole_data, ddr_q;
    wire [5:0] copy_a, copy_wa;
    wire [63:0] copy_data;
    reg [63:0] copy_q;
    function automatic [7:0] pattern(input integer index);
        pattern=8'ha7 ^ (index*13);
    endfunction
    // The production shared sprite cache (SPR_VRAM read_mirror) returns its
    // wide word two clocks after the address: the M10K address register and
    // its output register. Preserve that latency in this DDR boundary test.
    reg [63:0] copy_q_addressed;
    always @(posedge clk) begin
        for(integer i=0;i<8;i++) copy_q_addressed[i*8+:8]<=pattern(copy_a*8+i);
        copy_q<=copy_q_addressed;
    end
    FG_VRAM #(.FAST_UPPER(1)) fg(.CLK(clk),.CPU_CLK(clk),.RST_N(rst_n),.A(a),.D(16'b0),.Q(q),
        .RAS_N(ras_n),.CAS_N(2'b11),.WE_N(we_n),.OE_N(oe_n),.RDY(ready),
        .SC(1'b0),.SE_N(1'b0),.SD(8'b0),.SQ(),
        .DRAW_WE(1'b0),.DRAW_ADDR(17'b0),.DRAW_DATA(8'b0),
        .DRAW_BANK_WE(16'b0),.DRAW_RAM_BANK_WE(16'b0),
        .TRANSFER(1'b1),.CPU_SHIFT(1'b1),.MEM_CE(sclk),
        .HOLE_A(hole_a),.HOLE_SEL(hole_sel),.HOLE_RD(hole_rd),
        .HOLE_WE(hole_we),.HOLE_DATA(hole_data),.HOLE_Q(ddr_q),.HOLE_RDY(!busy),
        .CPU_SHIFT_Q(copy_q),.CPU_SHIFT_A(copy_a),.CPU_SHIFT_RD(copy_rd),
        .CPU_SHIFT_WA(copy_wa),.CPU_SHIFT_DATA(copy_data),.CPU_SHIFT_WE(copy_we),
        .FAST_WE(fast_we),.FAST_WORD(fast_word),.FAST_DATA(fast_data),.FAST_DONE(fast_done));
    wire [27:0] address=28'h2000000 | {9'b0,hole_a[17:1],2'b0};
    wire busy, mem_busy, mem_rd, mem_we;
    wire [28:0] mem_addr;
    wire [7:0] mem_be, mem_burst;
    wire [63:0] mem_din;
    reg [63:0] mem_dout=0;
    reg mem_ready=0;
    reg init_n=0;
    wire clear_ready, io_busy;
    wire [27:1] clear_addr;
    wire [3:0] clear_we;
    bt_fg_ddr_clear initializer(.clk(clk),.init_n(init_n),.io_busy(io_busy),
        .io_addr(clear_addr),.io_we(clear_we),.ready(clear_ready));
    assign mem_busy=(cycles%13)<5;
    ddram #(.FG_FAST(1)) controller(.clk(clk),.rst(!rst_n),.sclk(sclk),.addr(address[27:1]),
        .din(hole_data),.dout(ddr_q),.rd(hole_rd),.we(hole_we),.cache(2'b0),.busy(busy),
        .io_addr(clear_addr),.io_din(32'b0),.io_dout(),.io_rd(1'b0),.io_we(clear_we),.io_busy(io_busy),
        .fg_we(fast_we && clear_ready),.fg_addr({2'b00,1'b1,6'b0,fast_word,1'b0}),.fg_din(fast_data),.fg_done(fast_done),
        .baddr(27'b0),.bin(64'b0),.bout(),.bwr(1'b0),.brd(1'b0),.ba(),.bte(),.dbg_din(),
        .DDRAM_CLK(),.DDRAM_BUSY(mem_busy),.DDRAM_RD(mem_rd),.DDRAM_WE(mem_we),
        .DDRAM_ADDR(mem_addr),.DDRAM_BE(mem_be),.DDRAM_BURSTCNT(mem_burst),
        .DDRAM_DIN(mem_din),.DDRAM_DOUT(mem_dout),.DDRAM_DOUT_READY(mem_ready));
    reg [63:0] memory[0:131071];
    integer response_address=0, response_left=0, response_delay=0;
    always @(posedge clk) begin
        cycles<=cycles+1;
        mem_ready<=0;
        if((mem_we||mem_rd)&&!mem_busy) begin
            if(mem_addr<29'h6400000 || mem_addr>=29'h6420000)
                $fatal(1,"foreground DDR address out of range %h",mem_addr);
            if(mem_we) begin
                writes=writes+1;
                if(!mem_be) empty_writes=empty_writes+1;
                for(integer lane=0;lane<8;lane++)
                    if(mem_be[lane]) memory[mem_addr-29'h6400000][lane*8+:8]<=mem_din[lane*8+:8];
            end else begin
                if(response_left) $fatal(1,"overlapping read commands");
                response_address=mem_addr-29'h6400000;
                response_left=mem_burst;
                response_delay=3;
            end
        end
        if(response_left) begin
            if(response_delay) response_delay=response_delay-1;
            else begin
                mem_dout<=memory[response_address];
                mem_ready<=1;
                response_address=response_address+1;
                response_left=response_left-1;
                response_delay=1;
            end
        end
        if(copy_we) begin
            for(integer lane=0;lane<8;lane++)
                if(copy_data[lane*8+:8]!==pattern(copy_wa*8+lane))
                    $fatal(1,"round-trip copy byte %0d actual=%h expected=%h",copy_wa*8+lane,
                        copy_data[lane*8+:8],pattern(copy_wa*8+lane));
            copied=copied+8;
        end
    end
    initial begin
        for(integer i=0;i<131071;i++) memory[i]='1;
        memory[131071]='1;
        repeat(8) @(negedge clk);
        init_n=1;
        wait(clear_ready); @(negedge clk);
        if(writes!=196608 || empty_writes)
            $fatal(1,"bad cold initialization write count %0d empty=%0d",writes,empty_writes);
        for(integer i=0;i<131072;i++) begin
            // One raw DDR beat holds two padded foreground DWORDs.
            if(memory[i] !== ((i%256)<64 ? 64'hffffffffffffffff : 64'b0))
                $fatal(1,"cold initialization did not preserve the visible reserved area or clear hidden storage at beat %0d",i);
        end
        writes=0;
        rst_n=1;
        repeat(8) @(negedge clk);
        a=18'h00c00; ras_n=0; oe_n=0; we_n=0;
        // Ready is registered: it falls two memory clocks after RAS and the
        // controller only samples it later, so wait for the fall, then the rise.
        @(negedge clk); wait(!ready); wait(ready); @(negedge clk);
        ras_n=1; oe_n=1; we_n=1;
        repeat(24) @(negedge clk);
        for(integer x=256;x<512;x++) begin : verify_ddr_byte
            integer pair_index, half_offset, byte_offset;
            reg [7:0] actual;
            pair_index=(3*1024+x)/2;
            half_offset=(pair_index%2) ? 0 : 32;
            byte_offset=(x%2) ? 16 : 0;
            actual=memory[pair_index/2][half_offset+byte_offset+:8];
            if(actual!==pattern(x)) $fatal(1,"DDR copy byte %0d actual=%h expected=%h empty_writes=%0d",
                x,actual,pattern(x),empty_writes);
        end
        if(writes!=64 || empty_writes) $fatal(1,"bad fast DDR beat count %0d empty=%0d",writes,empty_writes);
        copied=0;
        ras_n=0; oe_n=0;
        // Ready is registered: it falls two memory clocks after RAS and the
        // controller only samples it later, so wait for the fall, then the rise.
        @(negedge clk); wait(!ready); wait(ready); @(negedge clk);
        ras_n=1; oe_n=1;
        repeat(24) @(negedge clk);
        if(copied!=512) $fatal(1,"missing copy bytes %0d",copied);
        $display("PASS fast foreground path: 196608 cold-clear writes during reset, 64 two-pair beats, 512 round-trip copy bytes, cache reads and command backpressure");
        $finish;
    end
    initial begin #100000000; $fatal(1,"foreground DDR watchdog writes=%0d clear_ready=%0d io_busy=%0d address=%h",writes,clear_ready,io_busy,clear_addr); end
endmodule
