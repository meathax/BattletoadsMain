`timescale 1ns/1ps
// Read-window model with independent memory contents and explicit pin delays.
// The model checks command spacing and byte masks; post-fit STA checks routes.
module sdram_window_model #(
    parameter real CLOCK_FLIGHT=3.55,
    parameter real RETURN_FLIGHT=2.0,
    parameter real INPUT_PATH=2.445,
    parameter real DATA_HOLD=1.8
)(input clock, input [12:0] address, input [1:0] bank,
  input nras,ncas,nwe, input dqml,dqmh, inout [15:0] dq);
    wire chip_clk;
    assign #(CLOCK_FLIGHT) chip_clk=clock;
    reg [15:0] memory[0:131071];
    reg [12:0] row[4];
    integer activated[4];
    integer cycle=0, remaining=0, pending_index=0;
    integer reads=0, writes=0, refreshes=0;
    reg drive=0;
    reg commands_started=0;
    reg [15:0] value=0;
    wire delayed_drive;
    wire [15:0] delayed_value;
    assign #(RETURN_FLIGHT+INPUT_PATH) delayed_drive=drive;
    assign #(RETURN_FLIGHT+INPUT_PATH) delayed_value=value;
    assign dq=delayed_drive ? delayed_value : 16'hzzzz;
    function automatic integer index(input [1:0] b,input [12:0] r,input [8:0] c);
        return {b,r[5:0],c};
    endfunction
    initial begin
        for(integer i=0;i<131072;i=i+1) memory[i]=16'h5a96 ^ i[15:0] ^ (i>>16);
        for(integer b=0;b<4;b=b+1) begin row[b]=0; activated[b]=-100; end
    end
    always @(posedge chip_clk) begin
        cycle=cycle+1;
        // A burst of one stops at the next rising edge plus tOHn (the
        // specified no-load minimum, earlier than the 3 ns loaded hold).
        if(drive) drive<=#(DATA_HOLD) 0;
        if(remaining!=0) begin
            remaining=remaining-1;
            if(remaining==0) begin
                value<=#6.0 memory[pending_index];
                drive<=#6.0 1;
            end
        end
        // Before the first system edge, FPGA power-up values need not be a
        // valid command. The normal initialization sequence follows NOP.
        if({nras,ncas,nwe}==3'b111) commands_started=1;
        if(commands_started) case({nras,ncas,nwe})
            3'b011: begin row[bank]=address; activated[bank]=cycle; end
            3'b101: begin
                assert(cycle-activated[bank]>=2) else $fatal(1,"SDRAM tRCD read");
                pending_index=index(bank,row[bank],address[8:0]);
                // CL2 begins driving after T1 and is valid by T2. tAC is
                // measured from T1; delaying data until T2 is one beat late.
                remaining=1;
                reads=reads+1;
            end
            3'b100: begin
                integer target;
                assert(cycle-activated[bank]>=2) else $fatal(1,"SDRAM tRCD write");
                target=index(bank,row[bank],address[8:0]);
                if(!dqml) memory[target][7:0]=dq[7:0];
                if(!dqmh) memory[target][15:8]=dq[15:8];
                writes=writes+1;
            end
            3'b001: refreshes=refreshes+1;
            3'b000: assert(address[6:4]==3'd2 && address[2:0]==3'd0)
                        else $fatal(1,"SDRAM mode must be CL2, burst one");
            default: ;
        endcase
    end
endmodule

module sdram_phase_tb;
    reg clk=0, sample_clk=0;
    always #6.25 clk=~clk;
    initial begin #15.0; forever begin sample_clk=1; #6.25; sample_clk=0; #6.25; end end
    // System rising edges are at 6.25+12.5*n; receive edges are +8.75 ns.
    reg [24:0] address=0;
    reg rd=0,wr=0,word_mode=1;
    reg [15:0] din=0;
    wire [15:0] dout[3];
    wire [2:0] busy;
    wire [15:0] dq_slow,dq_fast,dq_old;
    wire [12:0] a[3];
    wire [1:0] ba[3];
    wire [2:0] ram_clk,nras,ncas,nwe,dqml,dqmh;
    sdram slow(.init(1'b0),.clk(clk),.sample_clk(sample_clk),.addr(address),
        .rd(rd),.wr(wr),.word(word_mode),.din(din),.dout(dout[0]),.busy(busy[0]),
        .SDRAM_CLK(ram_clk[0]),.SDRAM_DQ(dq_slow),.SDRAM_A(a[0]),.SDRAM_BA(ba[0]),
        .SDRAM_nRAS(nras[0]),.SDRAM_nCAS(ncas[0]),.SDRAM_nWE(nwe[0]),
        .SDRAM_DQML(dqml[0]),.SDRAM_DQMH(dqmh[0]),.SDRAM_nCS(),.SDRAM_CKE());
    sdram fast(.init(1'b0),.clk(clk),.sample_clk(sample_clk),.addr(address),
        .rd(rd),.wr(wr),.word(word_mode),.din(din),.dout(dout[1]),.busy(busy[1]),
        .SDRAM_CLK(ram_clk[1]),.SDRAM_DQ(dq_fast),.SDRAM_A(a[1]),.SDRAM_BA(ba[1]),
        .SDRAM_nRAS(nras[1]),.SDRAM_nCAS(ncas[1]),.SDRAM_nWE(nwe[1]),
        .SDRAM_DQML(dqml[1]),.SDRAM_DQMH(dqmh[1]),.SDRAM_nCS(),.SDRAM_CKE());
    legacy_sdram reference(.init(1'b0),.clk(clk),.addr(address),.rd(rd),.wr(wr),
        .word(word_mode),.din(din),.dout(dout[2]),.busy(busy[2]),
        .SDRAM_CLK(ram_clk[2]),.SDRAM_DQ(dq_old),.SDRAM_A(a[2]),.SDRAM_BA(ba[2]),
        .SDRAM_nRAS(nras[2]),.SDRAM_nCAS(ncas[2]),.SDRAM_nWE(nwe[2]),
        .SDRAM_DQML(dqml[2]),.SDRAM_DQMH(dqmh[2]),.SDRAM_nCS(),.SDRAM_CKE());
    sdram_window_model slow_ram(.clock(ram_clk[0]),.address(a[0]),.bank(ba[0]),
        .nras(nras[0]),.ncas(ncas[0]),.nwe(nwe[0]),.dqml(dqml[0]),.dqmh(dqmh[0]),.dq(dq_slow));
    sdram_window_model #(.CLOCK_FLIGHT(2.2),.RETURN_FLIGHT(0.0),.INPUT_PATH(1.1)) fast_ram(
        .clock(ram_clk[1]),.address(a[1]),.bank(ba[1]),.nras(nras[1]),.ncas(ncas[1]),
        .nwe(nwe[1]),.dqml(dqml[1]),.dqmh(dqmh[1]),.dq(dq_fast));
    sdram_window_model old_ram(.clock(ram_clk[2]),.address(a[2]),.bank(ba[2]),
        .nras(nras[2]),.ncas(ncas[2]),.nwe(nwe[2]),.dqml(dqml[2]),.dqmh(dqmh[2]),.dq(dq_old));
    // A frozen late-phase candidate must fail the active-drive check even
    // when Verilator's two-state treatment of undriven DQ retains its value.
    wire [15:0] dq_late;
    wire [12:0] a_late;
    wire [1:0] ba_late;
    wire clock_late,ras_late,cas_late,we_late,dqml_late,dqmh_late;
    late_sdram late(.init(1'b0),.clk(clk),.sample_clk(sample_clk),.addr(address),
        .rd(rd),.wr(wr),.word(word_mode),.din(din),.dout(),.busy(),
        .SDRAM_CLK(clock_late),.SDRAM_DQ(dq_late),.SDRAM_A(a_late),.SDRAM_BA(ba_late),
        .SDRAM_nRAS(ras_late),.SDRAM_nCAS(cas_late),.SDRAM_nWE(we_late),
        .SDRAM_DQML(dqml_late),.SDRAM_DQMH(dqmh_late),.SDRAM_nCS(),.SDRAM_CKE());
    sdram_window_model late_ram(.clock(clock_late),.address(a_late),.bank(ba_late),
        .nras(ras_late),.ncas(cas_late),.nwe(we_late),.dqml(dqml_late),.dqmh(dqmh_late),.dq(dq_late));
    integer late_window_failures=0, receive_windows=0, bridge_checks=0;
    realtime last_receive_edge=-1000.0;
    always @(posedge sample_clk) begin
        if(slow.state==slow.STATE_READY-1 && slow.busy && slow.ram_req && !slow.we) begin
            assert(slow_ram.delayed_drive && fast_ram.delayed_drive)
                else $fatal(1,"SDRAM capture outside the single-word active-drive window");
            last_receive_edge=$realtime;
            receive_windows++;
        end
        if(late.state==late.STATE_READY && late.busy && late.ram_req && !late.we && !late_ram.delayed_drive)
            late_window_failures++;
    end
    always @(posedge clk) begin
        if(slow.state==slow.STATE_READY && slow.busy && slow.ram_req && !slow.we) begin
            assert($realtime-last_receive_edge>=16.249)
                else $fatal(1,"SDRAM bridge has less than its qualified 16.25 ns relationship");
            bridge_checks++;
        end
    end
    reg [15:0] golden[0:131071];
    integer checks=0, old_failures=0;
    function automatic integer index(input [24:0] loc);
        return {loc[24:23],loc[6:1],loc[22:14]};
    endfunction
    task automatic transfer(input bit write_en,input bit words,input [24:0] loc,input [15:0] val);
        integer ticks;
        reg [15:0] expected;
        @(negedge clk); address=loc; din=val; word_mode=words; wr=write_en; rd=!write_en;
        @(posedge clk); #0.1;
        assert(busy==3'b111) else $fatal(1,"request not accepted");
        @(negedge clk); rd=0; wr=0;
        ticks=0;
        while(busy[0]) begin
            @(posedge clk); #0.1; ticks=ticks+1;
            assert(busy[0]==busy[1] && busy[0]==busy[2]) else $fatal(1,"completion timing changed");
            assert(ticks<=6) else $fatal(1,"SDRAM transaction exceeded six clocks");
        end
        assert(ticks==6) else $fatal(1,"SDRAM completion boundary changed");
        if(write_en) begin
            if(words) golden[index(loc)]=val;
            else if(loc[0]) golden[index(loc)][15:8]=val[7:0];
            else golden[index(loc)][7:0]=val[7:0];
        end else begin
            expected=golden[index(loc)];
            if(!words && loc[0]) expected={expected[7:0],expected[15:8]};
            for(integer candidate=0;candidate<2;candidate=candidate+1) begin
                if(words) assert(dout[candidate]==expected)
                    else $fatal(1,"SDRAM word mismatch model=%0d addr=%h got=%h want=%h",candidate,loc,dout[candidate],expected);
                else assert(dout[candidate][7:0]==expected[7:0])
                    else $fatal(1,"SDRAM byte mismatch model=%0d addr=%h",candidate,loc);
            end
            if(dout[2]!=expected) old_failures=old_failures+1;
            checks=checks+1;
        end
        @(negedge clk);
    endtask
    initial begin
        reg [24:0] loc;
        for(integer i=0;i<131072;i=i+1) golden[i]=16'h5a96 ^ i[15:0] ^ (i>>16);
        repeat(300) @(posedge clk);
        // Shipping sample-ROM reads start after ROM download. A completed
        // write invalidates the legacy single-word cache as on real hardware.
        transfer(1,1,25'd0,16'h5a96);
        for(integer bank=0;bank<4;bank=bank+1) begin
            for(integer n=0;n<64;n=n+1) begin
                loc=(bank<<23)|(((n*37)&511)<<14)|(n<<1);
                transfer(0,1,loc,0);
                transfer(0,0,loc,0);
                transfer(0,0,loc|1,0);
                transfer(1,1,loc,16'h9876^n);
                transfer(0,1,loc,0);
                transfer(1,0,loc,16'h00ab^n);
                transfer(1,0,loc|1,16'h00cd^n);
                transfer(0,1,loc,0);
                transfer(0,0,loc|1,0);
            end
        end
        assert(old_failures==0) else $fatal(1,"Legacy reference data changed under the correct CL2 model");
        assert(late_window_failures==slow_ram.reads && receive_windows==slow_ram.reads && bridge_checks==slow_ram.reads)
            else $fatal(1,"The qualification missed a receive window or bridge transfer");
        assert(slow_ram.reads==fast_ram.reads && slow_ram.reads==old_ram.reads &&
               slow_ram.writes==old_ram.writes) else $fatal(1,"memory commands changed");
        $display("PASS SDRAM receive phase: reads=%0d writes=%0d checks=%0d active_windows=%0d bridge_checks=%0d late_window_failures=%0d legacy_data_mismatches=%0d completion=6 clocks",slow_ram.reads,slow_ram.writes,checks,receive_windows,bridge_checks,late_window_failures,old_failures);
        $finish;
    end
endmodule

// The shipping primitive receives constant high/low values to forward clk
// inverted. Routing and I/O cell delays are audited separately in TimeQuest.
module altddio_out #(
    parameter extend_oe_disable="OFF", intended_device_family="Cyclone V",
    invert_output="OFF", lpm_hint="UNUSED", lpm_type="altddio_out",
    oe_reg="UNREGISTERED", power_up_high="OFF", width=1
)(input [width-1:0] datain_h,datain_l,input outclock,aclr,aset,oe,outclocken,sclr,sset,
  output [width-1:0] dataout);
    assign dataout=outclock ? datain_h : datain_l;
endmodule
