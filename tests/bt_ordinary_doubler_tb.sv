`timescale 1ns/1ps
module bt_ordinary_doubler_tb;
  reg clk=0;
  always #5 clk=~clk;
  reg ce=0, hs=0, vs=0, hb=1, vb=1;
  reg [23:0] rgb=0;
  reg sd=0, freeze=0, gamma_en=0, gamma_wr=0;
  reg [9:0] gamma_addr=0;
  reg [7:0] gamma_value=0;
  wire [21:0] gamma_ref, gamma_new;
  assign gamma_ref[20:0]={clk,gamma_en,gamma_wr,gamma_addr,gamma_value};
  assign gamma_new[20:0]={clk,gamma_en,gamma_wr,gamma_addr,gamma_value};
  wire ce_ref, ce_new, fs_ref, fs_new;
  wire [23:0] rgb_ref, rgb_new;
  wire hs_ref, vs_ref, de_ref, hs_new, vs_new, de_new;
  video_mixer #(.LINE_LENGTH(520),.HALF_DEPTH(0),.GAMMA(1)) reference
    (clk,ce_ref,ce,sd,1'b0,gamma_ref,rgb[23:16],rgb[15:8],rgb[7:0],
     hs,vs,hb,vb,freeze,fs_ref,rgb_ref[23:16],rgb_ref[15:8],rgb_ref[7:0],
     vs_ref,hs_ref,de_ref);
  bt_video_mixer #(.LINE_LENGTH(520),.HALF_DEPTH(0),.GAMMA(1)) candidate
    (clk,ce_new,ce,sd,1'b0,gamma_new,rgb[23:16],rgb[15:8],rgb[7:0],
     hs,vs,hb,vb,freeze,fs_new,rgb_new[23:16],rgb_new[15:8],rgb_new[7:0],
     vs_new,hs_new,de_new);
  integer mode, frame, y, x, tick, cycles=0, pixels=0;
  integer left_edge=0, right_edge=512;
  integer period=8;
  integer fail_count=0;
  initial begin
    // Populate every gamma LUT entry through the actual programming bus.
    for(integer a=0;a<768;a=a+1) begin
      @(negedge clk); gamma_wr=1; gamma_addr=a;
      gamma_value=(a[7:0] * (1+a/256)) ^ (8'h31+a/256);
    end
    @(negedge clk); gamma_wr=0;
    for(mode=0;mode<12;mode=mode+1) begin
      // Native, ordinary doubled, forced doubled and every CRT scanline
      // selection all use the same mixer sd input. Also exercise gamma,
      // freeze/unfreeze and non-divisible master/pixel ratios.
      sd=(mode!=0 && mode!=6);
      gamma_en=(mode>=5);
      freeze=(mode==8);
      period=(mode>=10)?10:8;
      left_edge=(mode==9)?4:0;
      right_edge=(mode==9)?516:512;
      for(frame=0;frame<3;frame=frame+1)
        for(y=0;y<257;y=y+1)
          for(x=0;x<640;x=x+1)
            for(tick=0;tick<period;tick=tick+1) begin
              @(negedge clk);
              ce=(tick==0);
              hs=(x>=560 && x<608);
              vs=(y>=240 && y<243);
              hb=(x<left_edge || x>=right_edge);
              vb=(y>=224);
              rgb={8'((x*73+y*19+mode*47)&255),
                   8'((x*13+y*101+frame*61)&255),
                   8'((x*211+y*3+mode*29)&255)};
              @(posedge clk); #1;
              if(frame>=1) begin
                cycles=cycles+1;
                if({ce_ref,fs_ref,hs_ref,vs_ref,de_ref} !==
                   {ce_new,fs_new,hs_new,vs_new,de_new})
                  $fatal(1,"raster mismatch mode=%0d frame=%0d y=%0d x=%0d tick=%0d",mode,frame,y,x,tick);
                if(sd && {reference.sd.hb_out,reference.sd.vb_out} !==
                         {candidate.sd.hb_out,candidate.sd.vb_out})
                  $fatal(1,"blanking mismatch mode=%0d y=%0d x=%0d tick=%0d",mode,y,x,tick);
                if(ce_ref && de_ref) begin
                  pixels=pixels+1;
                  if(rgb_ref !== rgb_new) begin
                    fail_count=fail_count+1;
                    if(fail_count<10)
                      $display("pixel mismatch mode=%0d frame=%0d y=%0d x=%0d tick=%0d ref=%06x new=%06x readx=%0d bank=%0d cyc=%0d",mode,frame,y,x,tick,rgb_ref,rgb_new,
                         reference.sd.Hq2x.read_x,reference.sd.sd_line[1],reference.sd.Hq2x.cyc);
                    if(fail_count>=10) $fatal(1,"ten pixel mismatches");
                  end
                end
              end
            end
      $display("mode %0d checked",mode);
    end
    if(fail_count || pixels<1000000) $fatal(1,"coverage or pixel failures");
    $display("PASS ordinary doubler: %0d exact-clock comparisons, %0d active pixels, 12 mode/CE/gamma/freeze cases",cycles,pixels);
    $finish;
  end
endmodule
