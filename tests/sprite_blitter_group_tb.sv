`timescale 1ns/1ps
module sprite_blitter_group_tb;
    reg CLK=0;
    always #5 CLK=~CLK;
    reg RST_N=0, CE_R=0;
    reg [31:0] A=0;
    reg RAS_N=1, WE_N=1, OE_N=0, SHIFT=1;
    reg [15:0] CONTROL=16'h01ff, SOURCE_SCALE=0, DEST_SCALE=0;
    reg SHADOW=0, DEST_PAGE=0, DRAW_READY=1;
    reg [15:0] SOURCE_DATA=0;
    wire [8:0] source_a, source_b;
    wire we_a,we_b,page_a,page_b,busy_a,busy_b;
    wire [16:0] addr_a,addr_b;
    wire [7:0] data_a,data_b;
    wire [1:0] page_we_a,page_we_b;
    wire [1:0][15:0] bank_a,bank_b,ram_a,ram_b;
    BT_SPRITE_BLITTER dut(
        .CLK(CLK),.RST_N(RST_N),.CE_R(CE_R),.A(A),.RAS_N(RAS_N),.WE_N(WE_N),.OE_N(OE_N),.SHIFT(SHIFT),
        .CONTROL(CONTROL),.SOURCE_SCALE(SOURCE_SCALE),.DEST_SCALE(DEST_SCALE),.SHADOW(SHADOW),.DEST_PAGE(DEST_PAGE),
        .DRAW_READY(DRAW_READY),.SOURCE_WORD(source_a),.SOURCE_DATA(SOURCE_DATA),.DRAW_WE(we_a),.DRAW_ADDR(addr_a),
        .DRAW_DATA(data_a),.DRAW_PAGE(page_a),.DRAW_PAGE_WE(page_we_a),.DRAW_BANK_WE(bank_a),.DRAW_RAM_BANK_WE(ram_a),.BUSY(busy_a));
    BT_SPRITE_BLITTER_REFERENCE reference_dut(
        .CLK(CLK),.RST_N(RST_N),.CE_R(CE_R),.A(A),.RAS_N(RAS_N),.WE_N(WE_N),.OE_N(OE_N),.SHIFT(SHIFT),
        .CONTROL(CONTROL),.SOURCE_SCALE(SOURCE_SCALE),.DEST_SCALE(DEST_SCALE),.SHADOW(SHADOW),.DEST_PAGE(DEST_PAGE),
        .DRAW_READY(DRAW_READY),.SOURCE_WORD(source_b),.SOURCE_DATA(SOURCE_DATA),.DRAW_WE(we_b),.DRAW_ADDR(addr_b),
        .DRAW_DATA(data_b),.DRAW_PAGE(page_b),.DRAW_PAGE_WE(page_we_b),.DRAW_BANK_WE(bank_b),.DRAW_RAM_BANK_WE(ram_b),.BUSY(busy_b));
    integer cycles=0, checks=0, emissions=0, transparent=0, holes=0, shadowed=0, stalled=0;
    reg [31:0] bank_coverage=0;
    reg [3:0] nibble_coverage=0;
    reg [31:0] rng=32'h734106a9;
    function [31:0] next_rng(input [31:0] state);
        reg [31:0] x;
        begin x=state^(state<<13); x=x^(x>>17); next_rng=x^(x<<5); end
    endfunction
    task step;
        begin
            @(posedge CLK);
            if(RST_N && dut.emit_pixel) begin
                emissions=emissions+1;
                nibble_coverage[dut.nibble]=1;
                if(dut.color==0) transparent=transparent+1;
                if(SHADOW) shadowed=shadowed+1;
            end
            if(RST_N && dut.DRAW_WE && !DRAW_READY) stalled=stalled+1;
            #1;
            if({source_a,we_a,page_a,busy_a,addr_a,data_a,page_we_a,bank_a,ram_a} !==
               {source_b,we_b,page_b,busy_b,addr_b,data_b,page_we_b,bank_b,ram_b})
                $fatal(1,"Sprite group equivalence cycle=%0d",cycles);
            if(RST_N) begin
                bank_coverage=bank_coverage|bank_a;
                if(we_a && addr_a[8]) holes=holes+1;
            end
            checks=checks+1; cycles=cycles+1;
            @(negedge CLK);
        end
    endtask
    task command(input [31:0] addr,input write);
        begin
            A=addr; WE_N=!write; RAS_N=1; step();
            RAS_N=0; step(); RAS_N=1; step();
        end
    endtask
    integer p,b,k,i;
    initial begin
        step(); step(); RST_N=1;
        // Every page/bank and both foreground/hole destinations, with short
        // rows, all source nibble positions, shadow, transparency and stalls.
        for(p=0;p<2;p=p+1) for(b=0;b<16;b=b+1) for(k=0;k<2;k=k+1) begin
            DEST_PAGE=p; CONTROL=16'hf9fa; SOURCE_SCALE=0; DEST_SCALE=0;
            SHADOW=k; DRAW_READY=1; CE_R=1; SOURCE_DATA=16'h1234;
            command(32'ha4000000|((b*16)<<14)|(k<<13),0);
            command(32'ha8000000,0);
            command(32'hac000000,1);
            for(i=0;i<24;i=i+1) begin
                CE_R=(i%2)==0;
                DRAW_READY=(i%7)>=3;
                SOURCE_DATA=(i%9)==0 ? 16'h0000 : 16'h1234;
                step();
            end
        end
        // Adversarial bus transitions and data/control changes require exact
        // equivalence every clock; this does not assume physical RAM settling.
        for(i=0;i<400000;i=i+1) begin
            rng=next_rng(rng);
            RST_N=(i%100000)!=0;
            CE_R=(i%5)==2 || (i%5)==4;
            DRAW_READY=rng[5:3]!=0;
            SOURCE_DATA=(rng[12:9]==0) ? 16'h0000 : rng[31:16];
            SHADOW=rng[13]; DEST_PAGE=rng[14];
            CONTROL={rng[31:25],rng[8:0]};
            case(rng[2:0])
                0: begin SOURCE_SCALE=0; DEST_SCALE=0; end
                1: begin SOURCE_SCALE=16'h0080; DEST_SCALE=16'h0080; end
                2: begin SOURCE_SCALE=16'h0200; DEST_SCALE=16'h0180; end
                default: begin SOURCE_SCALE=rng[15:0]; DEST_SCALE=rng[31:16]; end
            endcase
            RAS_N=(i%16)%2==0; OE_N=0; SHIFT=1; WE_N=1;
            case(i%16)
                1: A=32'ha4000000|(rng&32'h003fffe0);
                3: A=32'ha8000000|(rng&32'h00001ff8);
                5: begin A=32'hac000000; WE_N=0; end
                default: begin A=rng; SHIFT=rng[15]; OE_N=rng[16]; end
            endcase
            step();
        end
        if(bank_coverage!==32'hffffffff || nibble_coverage!==4'hf || emissions==0 || transparent==0 ||
            holes==0 || shadowed==0 || stalled==0)
            $fatal(1,"Coverage failed banks=%h nibbles=%h emissions=%0d transparent=%0d holes=%0d shadowed=%0d stalled=%0d",
                bank_coverage,nibble_coverage,emissions,transparent,holes,shadowed,stalled);
        $display("PASS sprite_blitter_groups cycles=%0d checks=%0d banks=%h nibbles=%h emissions=%0d transparent=%0d holes=%0d shadowed=%0d stalled=%0d",
            cycles,checks,bank_coverage,nibble_coverage,emissions,transparent,holes,shadowed,stalled);
        $finish;
    end
endmodule

// Frozen pre-change production oracle. Its packed bank vector is flattened
// without changing bit ordering because Icarus cannot elaborate the original
// variable first index. The unmodified source is archived in the receipt.
// Battletoads bitmap sprite row producer. The A4 and A8 shift reads latch
// independent cursors; AC writes use those cursors, not the write address.
module BT_SPRITE_BLITTER_REFERENCE (
    input CLK, RST_N, CE_R,
    input [31:0] A,
    input RAS_N, WE_N, OE_N, SHIFT,
    input [15:0] CONTROL, SOURCE_SCALE, DEST_SCALE,
    input SHADOW, DEST_PAGE,
    input DRAW_READY,
    output [8:0] SOURCE_WORD,
    input [15:0] SOURCE_DATA,
    output reg DRAW_WE,
    output reg [16:0] DRAW_ADDR,
    output reg [7:0] DRAW_DATA,
    output reg DRAW_PAGE,
    (* maxfan = 8, preserve *) output reg [1:0] DRAW_PAGE_WE,
    (* maxfan = 8, preserve *) output reg [31:0] DRAW_BANK_WE, DRAW_RAM_BANK_WE,
    output BUSY
);
    reg ras_old;
    reg exec;
    reg [15:0] source_offset, dest_offset;
    reg [7:0] dest_row;
    reg [24:0] source_cursor, source_end;
    reg [23:0] dest_cursor;
    wire [9:0] width = {1'b0,~CONTROL[8:0]} + 10'd2;
    wire signed [16:0] source_step = 17'sh00100 - $signed({1'b0,SOURCE_SCALE});
    wire signed [16:0] dest_step = 17'sh00100 - $signed({1'b0,DEST_SCALE});
    wire [24:0] source_next = source_cursor + {{8{source_step[16]}},source_step};
    wire [23:0] dest_next = dest_cursor + {{7{dest_step[16]}},dest_step};
    wire [1:0] nibble = source_cursor[9:8] ^ {2{CONTROL[10]}};
    wire [3:0] color = (SOURCE_DATA >> {nibble,2'b00}) & 4'hf;
    wire [31:0] address = A & 32'hbfffffff;
    assign SOURCE_WORD = source_cursor[18:10];
    assign BUSY = exec | DRAW_WE;
    // Same-edge copies of the page-qualified draw strobe. Keep the page
    // decode off the short SYS-to-MEM path into foreground VRAM.
    wire load_page = !RAS_N && ras_old && !OE_N && SHIFT && WE_N && address[31:26] == 6'b101001;
    wire page_next = load_page ? DEST_PAGE : DRAW_PAGE;
    wire draw_next = exec && CE_R && (!DRAW_WE || DRAW_READY) ? |color : DRAW_WE && !DRAW_READY;
    wire emit_pixel = exec && CE_R && (!DRAW_WE || DRAW_READY);
    wire [3:0] bank_next = emit_pixel ? dest_row[7:4] : DRAW_ADDR[16:13];
    wire hole_next = emit_pixel ? dest_cursor[16] : DRAW_ADDR[8];
    always @(posedge CLK or negedge RST_N) begin
        if (!RST_N) begin
            DRAW_PAGE_WE <= 0; DRAW_BANK_WE <= 0; DRAW_RAM_BANK_WE <= 0;
        end else begin
            DRAW_PAGE_WE <= {2{draw_next}} & {page_next,!page_next};
            for (integer page=0;page<2;page=page+1)
                for (integer bank=0;bank<16;bank=bank+1) begin
                    DRAW_BANK_WE[page*16+bank] <= draw_next && page_next==page && bank_next==bank;
                    DRAW_RAM_BANK_WE[page*16+bank] <= draw_next && !hole_next && page_next==page && bank_next==bank;
                end
        end
    end
`ifdef MISTER_CPU_PHASE_CHECK
    always @(negedge CLK)
        if (RST_N) assert (DRAW_PAGE_WE == ({2{DRAW_WE}} & {DRAW_PAGE,!DRAW_PAGE}))
            else $fatal(1,"Page draw strobe changed transfer timing");
`endif


    always @(posedge CLK or negedge RST_N) begin
        if (!RST_N) begin
            ras_old <= 1;
            exec <= 0;
            source_offset <= 0;
            dest_offset <= 0;
            dest_row <= 0;
            DRAW_PAGE <= 0;
            source_cursor <= 0;
            source_end <= 0;
            dest_cursor <= 0;
            DRAW_WE <= 0;
            DRAW_ADDR <= 0;
            DRAW_DATA <= 0;
        end else begin
            ras_old <= RAS_N;
            DRAW_WE <= DRAW_WE && !DRAW_READY;
            if (!RAS_N && ras_old && !OE_N && SHIFT) begin
                if (WE_N && address[31:26] == 6'b101001) begin
                    dest_row <= address[21:14];
                    DRAW_PAGE <= DEST_PAGE;
                    dest_offset <= {7'b0,address[13:5]};
                end
                if (WE_N && address[31:26] == 6'b101010)
                    source_offset <= {5'b0,address[13:3]};
                if (!WE_N && address[31:26] == 6'b101011) begin
                    source_cursor <= {1'b0,source_offset,8'b0};
                    source_end <= {1'b0,source_offset,8'b0} + {7'b0,width,8'b0};
                    dest_cursor <= {dest_offset,8'b0};
                    exec <= 1;
                end
            end
            if (exec && CE_R && (!DRAW_WE || DRAW_READY)) begin
                DRAW_ADDR <= {dest_row,dest_cursor[16:8]};
                DRAW_DATA <= {~CONTROL[15:12],color & {4{!SHADOW}}};
                DRAW_WE <= |color;
                source_cursor <= source_next;
                dest_cursor <= dest_next;
                if (source_next >= source_end) begin
                    exec <= 0;
                    source_offset <= source_offset + {6'b0,width};
                    dest_offset <= dest_next[23:8];
                end
            end
        end
    end
endmodule
