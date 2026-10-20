`timescale 1ns/1ps
// The frozen oracle has no writes into its vendor FIFO (rot_we is tied low).
// Its reachable FIFO state is empty. This substitute has only that state;
// no claim about active rotation or the vendor's CDC implementation is made.
module dcfifo #(parameter lpm_width=62,lpm_numwords=512,lpm_widthu=9,
    lpm_showahead="ON",overflow_checking="ON",underflow_checking="ON",
    use_eab="ON",rdsync_delaypipe=4,wrsync_delaypipe=4)(
    input aclr,wrclk,rdclk,input [lpm_width-1:0] data,input wrreq,rdreq,
    output [lpm_width-1:0] q,output rdempty,wrfull);
    assign q = '0;
    assign rdempty = 1'b1;
    assign wrfull = 1'b0;
    always @(posedge wrclk) if (wrreq) $fatal(1,"Oracle FIFO must stay empty");
endmodule

module bt_video_ddr_memory_equiv_tb;
    localparam CW=111;
    reg mem_clk=0, video_clk=0, reset=1;
    always #3.125 mem_clk=~mem_clk;
    always #6.25 video_clk=~video_clk;
    reg mem_we=0,mem_rd=0,ddr_busy=0;
    reg [7:0] mem_burst=0,mem_be=0;
    reg [28:0] mem_addr=0;
    reg [63:0] mem_data=0;
    wire busy_new,busy_old;
    wire [7:0] burst_new,burst_old,be_new,be_old;
    wire [28:0] addr_new,addr_old;
    wire [63:0] data_new,data_old;
    wire we_new,we_old,rd_new,rd_old;
    wire [CW-1:0] command_new={we_new,rd_new,burst_new,addr_new,data_new,be_new};
    wire [CW-1:0] command_old={we_old,rd_old,burst_old,addr_old,data_old,be_old};
    bt_video_ddr dut(.reset(reset),.video_clk(video_clk),.mem_clk(mem_clk),
        .rot_we(1'b0),.rot_addr(29'b0),.rot_data(64'b0),.rot_be(8'b0),
        .mem_burst(mem_burst),.mem_addr(mem_addr),.mem_data(mem_data),.mem_be(mem_be),
        .mem_we(mem_we),.mem_rd(mem_rd),.ddr_busy(ddr_busy),.mem_busy(busy_new),
        .ddr_burst(burst_new),.ddr_addr(addr_new),.ddr_data(data_new),.ddr_be(be_new),
        .ddr_we(we_new),.ddr_rd(rd_new));
    bt_video_ddr_rotation_oracle oracle(.reset(reset),.video_clk(video_clk),.mem_clk(mem_clk),
        .rot_we(1'b0),.rot_addr(29'b0),.rot_data(64'b0),.rot_be(8'b0),
        .mem_burst(mem_burst),.mem_addr(mem_addr),.mem_data(mem_data),.mem_be(mem_be),
        .mem_we(mem_we),.mem_rd(mem_rd),.ddr_busy(ddr_busy),.mem_busy(busy_old),
        .ddr_burst(burst_old),.ddr_addr(addr_old),.ddr_data(data_old),.ddr_be(be_old),
        .ddr_we(we_old),.ddr_rd(rd_old));
    // The bridge holds at most two commands. A small ring also bounds the
    // proof's own storage independently of the length of the traffic run.
    reg [CW-1:0] expected[0:7];
    integer cycles=0,queued=0,delivered=0,held_cycles=0,full_cycles=0;
    integer reads=0,writes=0,continuous=0,mask_seen[0:255],burst_seen[0:255];
    bit scoreboard=0,accepted_last=0;
    reg [63:0] rng=64'h82946b34f215c7a1;
    function automatic [63:0] random_word(input [63:0] value);
        reg [63:0] x;
        begin x=value^(value<<13);x=x^(x>>7);random_word=x^(x<<17);end
    endfunction
    task automatic compare_outputs;
        begin
            if ({busy_new,command_new} !== {busy_old,command_old})
                $fatal(1,"Equivalence cycle %0d reset=%b busy=%b request=%b%b new=%h old=%h",
                    cycles,reset,ddr_busy,mem_we,mem_rd,{busy_new,command_new},{busy_old,command_old});
        end
    endtask
    task automatic tick(input bit rst,input bit stalled,input [1:0] req,input [63:0] word);
        reg [CW-1:0] before_command;
        bit held;
        begin
            @(negedge mem_clk);
            reset=rst;ddr_busy=stalled;{mem_we,mem_rd}=req;
            mem_burst=word[15:8];mem_addr=word[28:0];
            mem_data={word[31:0],word[63:32]}^64'h98a2d3f04be56c71;
            mem_be=word[7:0]^word[27:20];
            @(posedge mem_clk);
            compare_outputs();
            accepted_last=(mem_we||mem_rd)&&!busy_new;
            before_command=command_new;
            held=ddr_busy&&(we_new||rd_new)&&!dut.fifo_reset;
            if(scoreboard) begin
                if(reset||dut.fifo_reset) $fatal(1,"Scoreboard run reset while active");
                if(accepted_last) begin
                    if(queued-delivered>=8) $fatal(1,"Scoreboard ring overflow");
                    expected[queued%8]={mem_we,mem_rd,mem_burst,mem_addr,mem_data,mem_be};
                    queued=queued+1;
                    if(mem_we) writes=writes+1;else reads=reads+1;
                    mask_seen[mem_be]=1;burst_seen[mem_burst]=1;
                end
                if((we_new||rd_new)&&!ddr_busy) begin
                    if(delivered>=queued||command_new!==expected[delivered%8])
                        $fatal(1,"Lost/corrupt/reordered DDR command %0d cycle %0d",delivered,cycles);
                    delivered=delivered+1;
                end
                if(held) held_cycles=held_cycles+1;
                if(busy_new) full_cycles=full_cycles+1;
            end
            #1;
            compare_outputs();
            if(scoreboard && held && command_new!==before_command)
                $fatal(1,"Command changed while DDR busy at cycle %0d",cycles);
            cycles=cycles+1;
        end
    endtask
    task automatic clean_reset;
        begin
            tick(1,0,0,0);tick(1,0,0,0);tick(0,0,0,0);tick(0,0,0,0);
        end
    endtask
    task automatic traffic(input integer count,input integer mode);
        bit pending;
        reg [1:0] req;
        reg [63:0] word;
        bit stall;
        begin
            pending=0;req=0;word=0;
            for(integer i=0;i<count;i=i+1) begin
                rng=random_word(rng);
                if(!pending && (mode!=2 || rng[3:0]!=0)) begin
                    pending=1;word=rng;req=rng[8]?2'b10:2'b01;
                end
                stall=mode==0?1'b0:mode==1?(i%160<128):((i%977<300)||rng[1:0]==0);
                tick(0,stall,pending?req:2'b00,word);
                if(pending && accepted_last) pending=0;
            end
            while(pending) begin
                tick(0,0,req,word);
                if(accepted_last) pending=0;
            end
            repeat(4) tick(0,0,0,0);
            if(queued!=delivered) $fatal(1,"Undrained skid/output queue after traffic");
        end
    endtask
    integer pattern,step,nibble,masks,bursts;
    initial begin
        for(integer i=0;i<256;i=i+1) begin mask_seen[i]=0;burst_seen[i]=0;end
        clean_reset();
        // Exhaust all 16^4 four-cycle control sequences: reset, waitrequest,
        // idle, write, read and simultaneous read/write. Payloads vary too.
        // This intentionally includes invalid producer sequences; equivalence
        // must still cover the original raw payload buses and reset edges.
        $display("INFO memory bridge: exhaustive control equivalence begins");
        for(pattern=0;pattern<65536;pattern=pattern+1) begin
            clean_reset();
            for(step=0;step<4;step=step+1) begin
                nibble=(pattern>>(step*4))&15;
                rng=random_word(rng);
                tick(nibble[3],nibble[2],nibble[1:0],rng);
            end
        end
        $display("INFO memory bridge: 65536 exhaustive sequences passed; protocol scoreboard begins");
        clean_reset();scoreboard=1;
        traffic(4096,0);continuous=delivered;
        if(continuous!=4096) $fatal(1,"Ready DDR did not sustain one command per cycle");
        traffic(4096,1);traffic(32768,2);
        // Sweep every write mask and burst value explicitly while DDR is ready.
        for(integer i=0;i<256;i=i+1) begin
            tick(0,0,2'b10,{32'hffff1234,16'h5a00,i[7:0],i[7:0]^8'hb0});
        end
        repeat(4) tick(0,0,0,0);
        if(queued!=delivered||full_cycles==0||held_cycles<128||reads==0||writes==0)
            $fatal(1,"Missing traffic coverage or undelivered command");
        masks=0;bursts=0;
        for(integer i=0;i<256;i=i+1) begin masks=masks+mask_seen[i];bursts=bursts+burst_seen[i];end
        if(masks!=256||bursts!=256) $fatal(1,"Mask/burst coverage incomplete: %0d/%0d",masks,bursts);
        $display("PASS memory-only cycle equivalence: %0d cycles, 65536 exhaustive sequences; %0d ordered commands (%0d reads/%0d writes), 4096 full-rate commands, %0d held/%0d full-skid cycles, all 256 masks and bursts",cycles,delivered,reads,writes,held_cycles,full_cycles);
        $finish;
    end
endmodule
