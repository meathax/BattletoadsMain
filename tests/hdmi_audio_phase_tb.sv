`timescale 1ns/1ps
module hdmi_audio_phase_tb;
    reg clk=0;
    always #5 clk=~clk;
    reg reset=1, sample_rate=0;
    reg [31:0] stimulus=32'hace01234;
    wire bclk, lrclk, data;
    audio_out dut(
        .reset(reset), .clk(clk), .sample_rate(sample_rate),
        .flt_rate(32'd1536000), .cx(40'd0), .cx0(8'd0), .cx1(8'd0), .cx2(8'd0),
        .cy0(24'd0), .cy1(24'd0), .cy2(24'd0), .att(5'd0), .boost(2'd0),
        .mix(2'd0), .is_signed(1'b1), .core_l(16'd0), .core_r(16'd0),
        .alsa_l(stimulus[15:0]), .alsa_r(stimulus[31:16]),
        .i2s_bclk(bclk), .i2s_lrclk(lrclk), .i2s_data(data),
        .spdif(), .dac_l(), .dac_r());
    integer tick, guard=80, last_change=-1000, last_rise=-1000, last_ce=-1000;
    integer rises=0, changes=0, switches=0;
    reg old_bclk=1, old_data=0, old_lrclk=1;
    initial begin
        for(tick=0; tick<1000000; tick=tick+1) begin
            @(negedge clk);
            stimulus={stimulus[30:0],stimulus[31]^stimulus[21]^stimulus[1]^stimulus[0]};
            reset=(tick<10) || (tick%9973==0) || (tick%9973==1);
            if(tick%257==0 || tick%257==37 || tick%257==38) begin
                sample_rate=~sample_rate;
                switches=switches+1;
            end
            @(posedge clk); #1;
            if(reset) begin
                guard=80;
                last_change=tick;
                last_rise=tick;
            end else if(guard!=0) guard=guard-1;
            if(dut.i2s_ce) begin
                assert(tick-last_ce>=4) else $fatal(1,"serializer CE spacing %0d",tick-last_ce);
                last_ce=tick;
            end
            if(bclk && !old_bclk) begin
                if(!guard && !reset) begin
                    assert(tick-last_change>=5) else $fatal(1,"I2S setup phase %0d",tick-last_change);
                    rises=rises+1;
                end
                last_rise=tick;
            end
            if(data!=old_data || lrclk!=old_lrclk) begin
                if(!guard && !reset) begin
                    assert(tick-last_rise>=3) else $fatal(1,"I2S hold phase %0d",tick-last_rise);
                    changes=changes+1;
                end
                last_change=tick;
            end
            old_bclk=bclk; old_data=data; old_lrclk=lrclk;
        end
        assert(rises>50000 && changes>10000) else $fatal(1,"insufficient audio transitions");
        $display("PASS HDMI audio phase: clocks=%0d rises=%0d changes=%0d rate_switches=%0d setup>=5 hold>=3 CE>=4",tick,rises,changes,switches);
        $finish;
    end
endmodule
