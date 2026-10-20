`timescale 1ns/1ps
// Simulation substitute for the vendor FIFO only. The production arbiter and
// screen_rotate_two address generator are exercised without substitution.
module dcfifo #(parameter lpm_width=62,lpm_numwords=512,lpm_widthu=9,
    lpm_showahead="ON",overflow_checking="ON",underflow_checking="ON",
    use_eab="ON",rdsync_delaypipe=4,wrsync_delaypipe=4)(
    input aclr,wrclk,rdclk,input [lpm_width-1:0] data,input wrreq,rdreq,
    output [lpm_width-1:0] q,output rdempty,wrfull);
    reg [lpm_width-1:0] ram[0:lpm_numwords-1];
    integer wp=0,rp=0;
    assign rdempty=wp==rp;
    assign wrfull=wp-rp==lpm_numwords;
    assign q=ram[rp%lpm_numwords];
    always @(posedge wrclk or posedge aclr)
        if(aclr) wp<=0;
        else if(wrreq) begin ram[wp%lpm_numwords]<=data;wp<=wp+1;end
    always @(posedge rdclk or posedge aclr)
        if(aclr) rp<=0;
        else if(rdreq) rp<=rp+1;
endmodule

module rotation_ddr_tb;
    reg clk=0,memclk=0,reset=1;
    always #6.25 clk=~clk;
    always #3.125 memclk=~memclk;
    reg ce=0,de=0,vs=0,ccw=0,no_rotate=0,flip=0;
    reg [7:0] r=0,g=0,b=0;
    wire fb_en,rot_we;
    wire [11:0] fw,fh;
    wire [13:0] stride;
    wire [28:0] rot_addr;
    wire [63:0] rot_data;
    wire [7:0] rot_be;
    screen_rotate_two rotate(.CLK_VIDEO(clk),.CE_PIXEL(ce),.VGA_R(r),
        .VGA_G(g),.VGA_B(b),.VGA_HS(1'b0),.VGA_VS(vs),.VGA_DE(de),
        .rotate_ccw(ccw),.no_rotate(no_rotate),.flip(flip),.two_screen(1'b0),
        .FB_EN(fb_en),.FB_WIDTH(fw),.FB_HEIGHT(fh),.FB_STRIDE(stride),
        .FB_VBL(vs),.FB_LL(1'b0),.DDRAM_BUSY(1'b0),
        .DDRAM_ADDR(rot_addr),.DDRAM_DIN(rot_data),.DDRAM_BE(rot_be),.DDRAM_WE(rot_we));
    reg mem_we=0,mem_rd=0,busy=0;
    reg [28:0] mem_addr=29'h6000000;
    wire mem_busy,we,rd;
    wire [7:0] burst,be;
    wire [28:0] addr;
    wire [63:0] data;
    bt_video_ddr arb(.reset(reset),.video_clk(clk),.mem_clk(memclk),
        .rot_we(rot_we),.rot_addr(rot_addr),.rot_data(rot_data),.rot_be(rot_be),
        .mem_burst(8'd128),.mem_addr(mem_addr),.mem_data(64'h1122334455667788),
        .mem_be(8'hff),.mem_we(mem_we),.mem_rd(mem_rd),.ddr_busy(busy),
        .mem_busy(mem_busy),.ddr_burst(burst),.ddr_addr(addr),.ddr_data(data),
        .ddr_be(be),.ddr_we(we),.ddr_rd(rd));
    integer ticknum=0,queued=0,accepted=0,commands=0;
    reg [61:0] expected[0:10000];
    reg verify_pixels=0;
    integer mode=0,pixels=0,dx,dy,x,y,offset;
    reg seen[0:39];
    reg [31:0] pixel;
    always @(posedge clk) if(rot_we && !reset) begin
        expected[queued]={rot_addr,rot_be[4],rot_data[31:0]};queued=queued+1;
    end
    // Memory requests are deliberately held across external DDR backpressure.
    always @(negedge memclk) begin
        ticknum=ticknum+1;
        busy=(ticknum%17)<8;
        if(mem_we || mem_rd) begin
            if(!mem_busy) begin mem_we=0;mem_rd=0;commands=commands+1;end
        end else if(ticknum%13==0) begin
            mem_addr=mem_addr+1;
            mem_we=ticknum[0];mem_rd=!ticknum[0];
        end
    end
    // A presented command must stay unchanged while the controller is busy.
    reg held=0; reg [8+29+64+8+2-1:0] held_cmd;
    always @(posedge memclk) if(!reset) begin
        if(held && {burst,addr,data,be,we,rd}!==held_cmd)
            $fatal(1,"DDR command changed under backpressure: was %h now %h busy=%0d mem_we=%0d mem_rd=%0d hold=%0d",held_cmd,{burst,addr,data,be,we,rd},busy,mem_we,mem_rd,arb.video_hold);
        held<=busy && (we||rd); held_cmd<={burst,addr,data,be,we,rd};
    end
    // Scoreboard: every command accepted upstream (memory client or video
    // FIFO) must reach the DDR port in the same order with identical fields.
    reg        sb_video[0:20000];
    reg [28:0] sb_addr[0:20000];
    reg        sb_we[0:20000];
    integer sb_head=0, sb_tail=0;
    always @(posedge memclk) if(!reset) begin
        if((mem_we || mem_rd) && !mem_busy) begin
            sb_video[sb_tail]=0; sb_addr[sb_tail]=mem_addr; sb_we[sb_tail]=mem_we; sb_tail=sb_tail+1;
        end
        if(arb.use_video) begin
            sb_video[sb_tail]=1; sb_tail=sb_tail+1;
        end
    end
    always @(posedge memclk) if(!reset && !busy) begin
        if((we||rd) && sb_head==sb_tail)
            $fatal(1,"DDR command with nothing accepted upstream");
        if((we||rd) && !sb_video[sb_head]) begin
            if(burst!==128 || addr!==sb_addr[sb_head] || we!==sb_we[sb_head] || rd!==!sb_we[sb_head] ||
               be!==8'hff || data!==64'h1122334455667788)
                $fatal(1,"Existing DDR command corrupted/stolen");
            sb_head=sb_head+1;
        end else if(we) begin
            if(!sb_video[sb_head]) $fatal(1,"DDR order changed");
            sb_head=sb_head+1;
            if({addr,be[4],data[31:0]} !== expected[accepted])
                $fatal(1,"Rotation DDR lost/reordered transaction %0d",accepted);
            if(data[63:32]!==data[31:0] || rd || burst!==1) $fatal(1,"Video command format");
            accepted=accepted+1;
            if(verify_pixels) begin
                pixel=be[4] ? data[63:32] : data[31:0];
                x=pixel[7:0]-1;y=pixel[15:8]-1;
                dx=mode==1 ? y : mode==2 ? 7-x : 4-y;
                dy=mode==1 ? 7-x : mode==2 ? 4-y : x;
                offset=(addr & 29'hfffff)*8+(be[4]?4:0);
                if(offset!==dy*stride+dx*4) $fatal(1,"Rotation mode %0d (%0d,%0d) at %0d expected %0d",mode,x,y,offset,dy*stride+dx*4);
                if(seen[y*8+x]) $fatal(1,"Duplicate pixel");
                seen[y*8+x]=1;pixels=pixels+1;
            end
        end
    end
    task sample(input bit ivs,input bit ide,input integer ix,iy);
        begin
            @(negedge clk);ce=1;vs=ivs;de=ide;r=ix+1;g=iy+1;b=8'h5a;
            @(negedge clk);ce=0;
            repeat(6) @(negedge clk);
        end
    endtask
    task frame;
        begin
            sample(1,0,0,0);sample(0,0,0,0);
            for(integer yy=0;yy<5;yy=yy+1) begin
                for(integer xx=0;xx<8;xx=xx+1) sample(0,1,xx,yy);
                sample(0,0,0,0);sample(0,0,0,0);
            end
            repeat(4) sample(0,0,0,0);
            repeat(50) @(negedge clk);
        end
    endtask
    initial begin
        repeat(4) @(negedge clk);reset=0;
        for(mode=0;mode<3;mode=mode+1) begin
            ccw=mode==1;no_rotate=mode==2;flip=mode==2;
            repeat(7) frame();
            if(fw !== (mode==2?12'd8:12'd5) || fh !== (mode==2?12'd5:12'd8)) $fatal(1,"Framebuffer dimensions");
            for(integer s=0;s<40;s=s+1) seen[s]=0;
            pixels=0;verify_pixels=1;frame();verify_pixels=0;
            if(pixels!=40) $fatal(1,"Missing pixels: %0d",pixels);
        end
        no_rotate=1;flip=0;repeat(5) frame();
        if(fb_en) $fatal(1,"Rotation disabled still enables framebuffer");
        if(accepted!=queued || commands<100) $fatal(1,"DDR queue not drained or memory client untested");
        if(sb_head!=sb_tail) $fatal(1,"Accepted DDR commands not delivered");
        $display("PASS CW, CCW and 180 pixel coordinates/dimensions; disabled framebuffer; %0d queued writes and %0d memory commands under stalls",accepted,commands);
        $finish;
    end
endmodule
