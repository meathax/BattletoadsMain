`timescale 1ns/1ps
module ddram_cache_tb;
    bit clk=0;always #5 clk=~clk;
    bit reset=1;integer cycles=0;
    wire sclk=(cycles%10==2 || cycles%10==3 || cycles%10==6 || cycles%10==7);
    bit[27:1] address;bit[31:0] data;bit[3:0] write_be;bit read_req;bit[1:0] bank;
    bit burst_read,burst_write,io_read;bit[3:0] io_write;
    bit[27:1] burst_address,io_address;bit[31:0] io_data;
    wire[63:0] burst_q0,burst_q1;wire[9:3] burst_pos0,burst_pos1;wire burst_tick0,burst_tick1;
    wire[31:0] io_q0,io_q1;wire io_busy0,io_busy1;
    wire[31:0] q0,q1;wire busy0,busy1;
    wire[28:0] a0,a1;wire[63:0] d0,d1;wire[7:0] be0,be1,len0,len1;wire rd0,rd1,wr0,wr1;
    bit backend_busy,ready;bit[63:0] backend_data;
    bit[63:0] memory[512];integer remaining=0,delay_count=0,read_index=0;
    integer writes=0,reads=0,checks=0;
    ddram candidate(.clk(clk),.rst(reset),.sclk(sclk),.addr(address),.dout(q0),.din(data),
        .rd(read_req),.we(write_be),.cache(bank),.busy(busy0),
        .io_addr(io_address),.io_din(io_data),.io_rd(io_read),.io_we(io_write),.io_dout(io_q0),.io_busy(io_busy0),
        .baddr(burst_address),.bin(64'hacbedefd01324567),.bwr(burst_write),.brd(burst_read),
        .bout(burst_q0),.ba(burst_pos0),.bte(burst_tick0),
        .DDRAM_BUSY(backend_busy),.DDRAM_DOUT(backend_data),.DDRAM_DOUT_READY(ready),
        .DDRAM_ADDR(a0),.DDRAM_DIN(d0),.DDRAM_BE(be0),.DDRAM_BURSTCNT(len0),.DDRAM_RD(rd0),.DDRAM_WE(wr0));
    ddram_baseline original(.clk(clk),.rst(reset),.sclk(sclk),.addr(address),.dout(q1),.din(data),
        .rd(read_req),.we(write_be),.cache(bank),.busy(busy1),
        .io_addr(io_address),.io_din(io_data),.io_rd(io_read),.io_we(io_write),.io_dout(io_q1),.io_busy(io_busy1),
        .baddr(burst_address),.bin(64'hacbedefd01324567),.bwr(burst_write),.brd(burst_read),
        .bout(burst_q1),.ba(burst_pos1),.bte(burst_tick1),
        .DDRAM_BUSY(backend_busy),.DDRAM_DOUT(backend_data),.DDRAM_DOUT_READY(ready),
        .DDRAM_ADDR(a1),.DDRAM_DIN(d1),.DDRAM_BE(be1),.DDRAM_BURSTCNT(len1),.DDRAM_RD(rd1),.DDRAM_WE(wr1));
    always @(negedge clk) begin
        if(!reset) begin
            if({busy0,rd0,wr0}!={busy1,rd1,wr1})$fatal(1,"DDR handshake changed cycle=%0d",cycles);
            if({io_busy0,burst_tick0}!={io_busy1,burst_tick1})$fatal(1,"DDR auxiliary handshake changed cycle=%0d",cycles);
            if(burst_tick0 && {burst_q0,burst_pos0}!=={burst_q1,burst_pos1})$fatal(1,"DDR burst return changed cycle=%0d",cycles);
            if(io_read && !io_busy0 && io_q0!==io_q1)$fatal(1,"DDR I/O return changed cycle=%0d",cycles);
            if((rd0 || wr0) && {a0,d0,be0,len0}!={a1,d1,be1,len1})
                $fatal(1,"DDR command payload changed cycle=%0d",cycles);
            if(read_req && !busy0 && q0!==q1)$fatal(1,"valid cache data changed cycle=%0d",cycles);
            if(!backend_busy && wr0) begin
                for(integer lane=0;lane<8;lane++)if(be0[lane])memory[a0[8:0]][lane*8+:8]=d0[lane*8+:8];
                writes++;
            end
            if(!backend_busy && rd0) begin
                if(remaining)$fatal(1,"overlapping DDR read");
                remaining=len0;delay_count=7;read_index=a0[8:0];reads++;
            end
        end
        cycles++;
        backend_busy=cycles%13<5;
        ready=0;
        if(remaining) begin
            if(delay_count)delay_count--;
            else if(cycles%3!=0)begin
                backend_data=memory[read_index%512];read_index++;remaining--;ready=1;
            end
        end
    end
    task automatic tick;
        @(posedge clk);#1;
    endtask
    task automatic wait_idle;
        integer limit=0;
        while(busy0 || remaining || wr0 || rd0)begin
            tick();limit++;if(limit>1200)$fatal(1,"DDR transaction stalled");
        end
    endtask
    task automatic read_word(input bit[27:1] a,input bit[1:0] cache_id);
        bit[31:0] expected;
        wait_idle();address=a;bank=cache_id;read_req=1;
        repeat(2)tick();wait_idle();
        expected=a[2]?memory[(a>>2)&511][31:0]:memory[(a>>2)&511][63:32];
        if(q0!==expected || q1!==expected)$fatal(1,"cache read mismatch address=%h bank=%0d actual=%h/%h expected=%h",a,cache_id,q0,q1,expected);
        checks++;read_req=0;repeat(2)tick();
    endtask
    task automatic write_word(input bit[27:1] a,input bit[1:0] cache_id,input bit[31:0] value,input bit[3:0] mask);
        wait_idle();address=a;bank=cache_id;data=32'hdeadbeef;write_be=mask;
        // Write data arrives after the strobe and is captured on sclk.
        tick();data=value;
        repeat(2)tick();wait_idle();write_be=0;repeat(2)tick();
    endtask
    initial begin
        for(integer i=0;i<512;i++)memory[i]={32'h72560000+i,32'h13a40000+i};
        repeat(8)tick();reset=0;repeat(2)tick();
        for(integer cache_id=0;cache_id<4;cache_id++)begin
            for(integer tag=0;tag<8;tag++)begin
                for(integer word_id=0;word_id<4;word_id++)begin
                    bit[27:1] a;
                    a=27'h10000+tag*8+word_id*2;
                    read_word(a,cache_id[1:0]);
                    for(integer mask=1;mask<16;mask++)begin
                        write_word(a,cache_id[1:0],$urandom,mask[3:0]);
                        read_word(a,cache_id[1:0]);
                    end
                    // Write a different tag, then force a refill of the old one.
                    write_word(a+27'h2000,cache_id[1:0],$urandom,4'hf);
                    read_word(a,cache_id[1:0]);
                end
            end
        end
        if(writes<2048 || checks<2000)$fatal(1,"insufficient DDR cache coverage");
        // Exercise the remaining aggregate-ready flags under the same stalls.
        for(integer round_id=0;round_id<8;round_id++) begin
            wait_idle();burst_address=27'h20000+round_id*512;burst_write=1;
            repeat(2)tick();wait_idle();burst_write=0;repeat(2)tick();
            burst_read=1;repeat(2)tick();wait_idle();burst_read=0;repeat(2)tick();
            io_address=27'h30000+round_id*2;io_data=$urandom;io_write=4'hf;
            repeat(2)tick();while(io_busy0 || wr0)tick();io_write=0;repeat(2)tick();
            io_read=1;repeat(2)tick();while(io_busy0 || remaining || rd0)tick();
            io_read=0;repeat(2)tick();
        end
        $display("PASS DDR cache pipeline: %0d masked/burst/I/O writes, %0d checked reads, %0d DDR read commands; all banks/words/masks, hit/miss, 128-word bursts, I/O, delayed data and stalls; command/busy cycles unchanged",writes,checks,reads);
        $finish;
    end
endmodule
