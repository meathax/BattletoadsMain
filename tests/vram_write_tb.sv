`timescale 1ns/1ps
module vram_write_tb;
    bit fast_clk=1, cpu_clk=0, rst_n=0;
    always #2 fast_clk=~fast_clk;
    always #4 cpu_clk=~cpu_clk;
    bit [17:0] a;
    bit [15:0] d;
    bit [1:0] cas_n=3;
    bit ras_n=1, we_n=1, oe_n=1;
    wire [15:0] bg_q,fg_q;
    bit [15:0] expected [32768];
    int writes=0,reads=0;
    BG_VRAM bg(.CLK(fast_clk),.CPU_CLK(cpu_clk),.RST_N(rst_n),
        .A({a[17:10],a[7:0]}),.CPU_A({a[17:10],a[7:1]}),
        .D(d),.Q(bg_q),.RAS_N(ras_n),
        .CAS_N(cas_n),.WE_N(we_n),.OE_N(oe_n),.TRANSFER(1'b0),
        .SC(1'b0),.SE_N(1'b0),.RDY(),.SQ(),.GRID());
    FG_VRAM fg(.CLK(fast_clk),.CPU_CLK(cpu_clk),.RST_N(rst_n),
        .A(a),.D(d),.Q(fg_q),.RAS_N(ras_n),.CAS_N(cas_n),
        .WE_N(we_n),.OE_N(oe_n),.TRANSFER(1'b0),.CPU_SHIFT(1'b0),
        .SC(1'b0),.SE_N(1'b0),.SD(8'b0),.SQ(),.RDY(),
        .DRAW_WE(1'b0),.DRAW_ADDR(17'b0),.DRAW_DATA(8'b0),
        .MEM_CE(1'b0),.HOLE_A(),.HOLE_SEL(),.HOLE_RD(),.HOLE_WE(),.HOLE_DATA(),
        .HOLE_Q(32'b0),.HOLE_RDY(1'b1),.CPU_SHIFT_Q(64'b0),
        .CPU_SHIFT_A(),.CPU_SHIFT_RD(),.CPU_SHIFT_WA(),.CPU_SHIFT_DATA(),.CPU_SHIFT_WE());
    task automatic write_word(input int word_addr,input bit [15:0] value,
                              input bit [1:0] lanes,input int hold_cycles);
        @(negedge cpu_clk);
        a={word_addr[14:7],2'b00,word_addr[6:0],1'b0};
        d=value;cas_n=~lanes;ras_n=0;oe_n=1;we_n=0;
        @(posedge cpu_clk); #1;
        // Advance every live bus field before the RAM consumes the packet.
        // Holding WE low must not repeat the write at this new address.
        a=a^18'h3fcfe;d=~value;cas_n=lanes;
        repeat(hold_cycles) @(negedge cpu_clk);
        we_n=1;ras_n=1;cas_n=3;
        @(posedge cpu_clk); #1;
        if(lanes[0])expected[word_addr][7:0]=value[7:0];
        if(lanes[1])expected[word_addr][15:8]=value[15:8];
        ++writes;
    endtask
    task automatic read_word(input int word_addr);
        @(negedge cpu_clk);
        a={word_addr[14:7],2'b00,word_addr[6:0],1'b0};
        ras_n=0;oe_n=0;we_n=1;
        repeat(2) @(posedge fast_clk); #1;
        if(bg_q!==expected[word_addr] || fg_q!==expected[word_addr])
            $fatal(1,"VRAM write packet address=%0d expected=%h BG=%h FG=%h",
                word_addr,expected[word_addr],bg_q,fg_q);
        ++reads;
        @(negedge cpu_clk);ras_n=1;oe_n=1;
    endtask
    initial begin
        foreach(expected[i])expected[i]=0;
        repeat(3) @(negedge cpu_clk);rst_n=1;
        for(int i=0;i<32768;++i) begin
            write_word(i,16'(i*73+17),2'b11,1);
            read_word(i);
        end
        for(int lane=0;lane<4;++lane)
            for(int i=0;i<32768;++i) begin
                write_word(i,16'(i*97+lane*831),2'(lane),1+(i&3));
                read_word(i);
            end
        // Check that the changing held-write address has not corrupted any
        // other word, including the final write's opposite address.
        for(int i=0;i<32768;++i)read_word(i);
        $display("PASS VRAM CPU/RAM packet: %0d writes, %0d reads, all rows/byte masks, advancing bus and held strobes",writes,reads);
        $finish;
    end
endmodule
