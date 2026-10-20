`timescale 1ns/1ps
module sprite_read_equivalence_tb;
    bit clk=0,reset_n=0;
    bit [17:0] a;
    bit [31:0] d;
    bit ras_n=1,we_n=1,oe_n=1,sc=0,se_n=1;
    bit [3:0] cas_n=15;
    bit [8:0] blit_a;
    bit cpu_we,cpu_rd;
    bit [5:0] cpu_wa,cpu_a;
    bit [63:0] cpu_data;
    wire [63:0] esq_old,esq_new;
    wire este_old,este_new;
    wire [15:0] blit_q_old,blit_q_new,sq_old,sq_new;
    wire [63:0] cpu_q_old,cpu_q_new,esdata_old,esdata_new;
    wire cpu_busy_old,cpu_busy_new,spr_busy_old,spr_busy_new;
    wire esrd_old,esrd_new,eswr_old,eswr_new;
    wire [17:0] esaddr_old,esaddr_new;
    always #3.125 clk=~clk;
    SPR_VRAM reference_core(.CLK(clk),.RST_N(reset_n),.A(a),.D(d),
        .RAS_N(ras_n),.CAS_N(cas_n),.WE_N(we_n),.OE_N(oe_n),.SC(sc),.SE_N(se_n),.SQ(sq_old),
        .BLIT_A(blit_a),.BLIT_Q(blit_q_old),.RDY(spr_busy_old),
        .CPU_SHIFT_WE(cpu_we),.CPU_SHIFT_WA(cpu_wa),.CPU_SHIFT_DATA(cpu_data),
        .CPU_SHIFT_BUSY(cpu_busy_old),.CPU_SHIFT_RD(cpu_rd),.CPU_SHIFT_A(cpu_a),.CPU_SHIFT_Q(cpu_q_old),
        .ESQ(esq_old),.ESTE(este_old),.ESDATA(esdata_old),.ESADDR(esaddr_old),.ESRD(esrd_old),.ESWR(eswr_old));
    SPR_VRAM_SYNC candidate_core(.CLK(clk),.RST_N(reset_n),.A(a),.D(d),
        .RAS_N(ras_n),.CAS_N(cas_n),.WE_N(we_n),.OE_N(oe_n),.SC(sc),.SE_N(se_n),.SQ(sq_new),
        .BLIT_A(blit_a),.BLIT_Q(blit_q_new),.RDY(spr_busy_new),
        .CPU_SHIFT_WE(cpu_we),.CPU_SHIFT_WA(cpu_wa),.CPU_SHIFT_DATA(cpu_data),
        .CPU_SHIFT_BUSY(cpu_busy_new),.CPU_SHIFT_RD(cpu_rd),.CPU_SHIFT_A(cpu_a),.CPU_SHIFT_Q(cpu_q_new),
        .ESQ(esq_new),.ESTE(este_new),.ESDATA(esdata_new),.ESADDR(esaddr_new),.ESRD(esrd_new),.ESWR(eswr_new));
    logic [63:0] expected[64];
    integer comparisons=0,transfers=0;
    sprite_transaction_memory golden_ddr(.clk(clk),.reset_n(reset_n),.rd(esrd_old),.wr(eswr_old),
        .a(esaddr_old),.data(esdata_old),.q(esq_old),.te(este_old));
    sprite_transaction_memory candidate_ddr(.clk(clk),.reset_n(reset_n),.rd(esrd_new),.wr(eswr_new),
        .a(esaddr_new),.data(esdata_new),.q(esq_new),.te(este_new));
    task automatic tick(input integer count);
        repeat(count) begin @(negedge clk);#0.2;end
    endtask
    task automatic consumer_read(input integer address);
        cpu_rd=0;blit_a=9'(address);
        // The real blitter consumes pre-edge data on the next CE_R, four
        // memory clocks after changing its cursor. Invalid intermediate data
        // is not part of that contract.
        repeat(3) @(negedge clk);
        @(posedge clk);
        assert(blit_q_new===blit_q_old) else $fatal(1,"sprite CE_R consumer mismatch address=%0d candidate=%h reference=%h",address,blit_q_new,blit_q_old);
        comparisons++;@(negedge clk);#0.2;
    endtask
    task automatic cache_read(input integer address);
        cpu_rd=1;cpu_a=6'(address);tick(3);
        assert(cpu_q_new===cpu_q_old) else $fatal(1,"sprite foreground cache consumer mismatch word=%0d candidate=%h reference=%h",address,cpu_q_new,cpu_q_old);
        comparisons++;
    endtask
    task automatic transfer(input bit write_transfer,input integer row);
        cpu_rd=0;cpu_we=0;sc=0;ras_n=1;oe_n=1;we_n=1;tick(6);
        a=18'(row<<9);oe_n=0;we_n=!write_transfer;se_n=0;ras_n=0;tick(6);
        assert(!spr_busy_old && !spr_busy_new) else $fatal(1,"sprite transfer never asserted busy");
        ras_n=1;oe_n=1;we_n=1;
        for(integer elapsed=0;elapsed<4096;elapsed++) begin
            tick(1);
            if(spr_busy_old && spr_busy_new) break;
            if(elapsed==4095) $fatal(1,"sprite completion timeout");
        end
        tick(4);
        assert(golden_ddr.beats==128 && candidate_ddr.beats==128) else $fatal(1,"sprite transfer beat count differs %0d/%0d",golden_ddr.beats,candidate_ddr.beats);
        for(integer i=0;i<128;i++) begin
            assert(golden_ddr.beat_log[i]===candidate_ddr.beat_log[i]) else $fatal(1,"sprite serial transaction differs beat=%0d candidate=%h reference=%h",i,candidate_ddr.beat_log[i],golden_ddr.beat_log[i]);comparisons++;
        end
        golden_ddr.beats=0;candidate_ddr.beats=0;transfers++;
    endtask
    initial begin
        tick(8);reset_n=1;tick(8);
        for(integer pass=0;pass<8;pass++) begin
            for(integer i=0;i<64;i++) begin
                cpu_we=1;cpu_wa=6'((i*17+pass)%64);
                cpu_data={32'(32'h93a541d7*(pass+1)+i),32'(32'hd812f074^(i*32'h219e307b))};expected[cpu_wa]=cpu_data;
                #0.1;assert(cpu_busy_old && cpu_busy_new) else $fatal(1,"sprite packet completion released before capture");tick(1);
            end
            cpu_we=0;#0.1;assert(cpu_busy_old && cpu_busy_new) else $fatal(1,"sprite final packet completion released before commit");tick(2);
            assert(!cpu_busy_old && !cpu_busy_new) else $fatal(1,"sprite packet did not drain");
            for(integer i=0;i<64;i++) begin
                cache_read(i);assert(cpu_q_new===expected[i]) else $fatal(1,"sprite independent packet scoreboard differs word=%0d",i);
            end
            for(integer i=0;i<512;i++) consumer_read((i*17+pass)%512);
            transfer(1,pass*61);transfer(0,pass*61+1);
            for(integer i=0;i<512;i++) consumer_read(i);
            for(integer i=0;i<64;i++) cache_read(i);
            cpu_rd=0;
            for(integer i=0;i<512;i++) begin
                sc=1;tick(3);
                assert(sq_new===sq_old) else $fatal(1,"sprite serial pixel consumer differs pixel=%0d candidate=%h reference=%h",i,sq_new,sq_old);
                comparisons++;sc=0;tick(3);
            end
        end
        reset_n=0;tick(8);reset_n=1;tick(6);
        for(integer i=0;i<64;i++) cache_read(i);
        $display("PASS sprite transaction equivalence: transfers=%0d comparisons=%0d packets, CE_R blitter/cache consumers, independent serial read/write responses, pixels and reset",transfers,comparisons);
        $finish;
    end
endmodule

module sprite_transaction_memory(input clk,reset_n,rd,wr,input [17:0] a,
    input [63:0] data,output logic [63:0] q=0,output logic te=0);
    integer beat_index=0,beats=0,phase=0;
    logic active=0;
    logic [82:0] beat_log[128];
    function automatic [63:0] incoming(input integer address,input integer index);
        return {32'(32'h271983a5 ^ address ^ (index*32'h1965)),32'(32'h92f10a67 ^ (address<<2) ^ (index*32'h3971))};
    endfunction
    always @(negedge clk) begin
        te=0;
        if(!reset_n || (!rd && !wr)) begin active=0;beat_index=0;phase=0;end
        else begin
            if(!active) begin active=1;phase=0;beat_index=0;end
            phase++;
            if(phase>=3+(beat_index%5)) begin q=incoming(a,beat_index);te=1;phase=0;end
        end
    end
    always @(posedge clk) if(reset_n && (rd || wr) && te) begin
        beat_log[beats]={a,wr,wr ? data : q};beats++;beat_index++;
        if(beats>128) $fatal(1,"sprite controller accepted an extra beat");
    end
endmodule
