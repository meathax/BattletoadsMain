`timescale 1ns/1ps
module bt_pause_bridge_tb;
  logic clk_sys=0,reset=1,OSD_STATUS=0,nvram_pause=0;
  logic [31:0] joy0=0,joy1=0,joy2=0;
  wire gated_f,gated_r,vce;
  pause_board board(.*);
  integer cycles=0,requests=0,acks=0,resume_f=0,resume_r=0,halted_cycles=0;
  integer raw_f=0,raw_r=0,pixel_ticks=0,paused_raw_ticks=0,paused_pixels=0;
  integer memory_ticks=0,paused_memory_ticks=0,reset_edges=0,reset_while_halted=0;
  integer high_request_resets=0,user_toggles=0,patterns=0;
  integer last_effective=0;
  bit awaiting_resume_r=0;
  bit old_hold,old_req,old_raw_f,old_raw_r,old_f,old_r;

  task automatic tick;
    #1;
    old_hold=board.cpu_pause_bridge.halted_reg;
    old_req=board.pause_cpu;old_raw_f=board.CE_F;old_raw_r=board.CE_R;
    old_f=gated_f;old_r=gated_r;
    assert(!(old_raw_f&&old_raw_r) && !(old_f&&old_r)) else $fatal(1,"phase overlap");
    assert(!old_f||old_raw_f) else $fatal(1,"new F not in original generator");
    assert(!old_r||old_raw_r) else $fatal(1,"new R not in original generator");
    if(reset)begin
      reset_edges++;
      if(old_hold)reset_while_halted++;
      if(old_req)high_request_resets++;
      last_effective=0;awaiting_resume_r=0;
      assert(!old_f&&!old_r&&!vce) else $fatal(1,"reset changed original enable semantics");
    end else begin
      if(!old_hold)assert(old_f==old_raw_f&&old_r==old_raw_r)
        else $fatal(1,"unpaused generator sequence changed");
      if(old_hold&&old_req)assert(!old_f&&!old_r)
        else $fatal(1,"acknowledged pause leaked a CPU phase");
      if(old_hold&&!old_req)begin
        assert(!old_r) else $fatal(1,"resume admitted R before F");
        assert(old_f==old_raw_f) else $fatal(1,"first available F was lost on release");
      end
      if(old_f)begin
        assert(last_effective!=1) else $fatal(1,"F repeated before closing R");
        last_effective=1;
        if(old_hold)begin resume_f++;awaiting_resume_r=1;end
      end
      if(old_r)begin
        assert(last_effective==1) else $fatal(1,"effective R without original preceding F");
        last_effective=2;
        if(awaiting_resume_r)begin resume_r++;awaiting_resume_r=0;end
      end
      if(old_req)requests++;
      if(old_raw_f)raw_f++;
      if(old_raw_r)raw_r++;
      if(vce)pixel_ticks++;
      if(old_hold)begin
        halted_cycles++;
        if(old_raw_f||old_raw_r)paused_raw_ticks++;
        if(vce)paused_pixels++;
      end
    end
    // The board gate has no memory clock input or output. Independently
    // clocked progress is counted during every halting/held CPU interval.
    memory_ticks+=2;
    if(old_hold&&!reset)paused_memory_ticks+=2;
    clk_sys=1;#0.01;cycles++;
    if(reset)assert(!board.cpu_pause_bridge.halted_reg)
      else $fatal(1,"reset startup changed");
    else if(!old_hold&&board.cpu_pause_bridge.halted_reg)begin
      assert(old_req&&old_raw_r&&old_r) else $fatal(1,"pause missed closing R");
      acks++;
    end else if(old_hold&&!board.cpu_pause_bridge.halted_reg)
      assert(!old_req&&old_raw_f&&old_f) else $fatal(1,"resume state changed before included F");
    clk_sys=0;#0.01;
  endtask

  task automatic clear_requests;
    OSD_STATUS=0;nvram_pause=0;joy0=0;joy1=0;joy2=0;
  endtask

  task automatic reset_at(input integer start_phase,input bit request_high);
    clear_requests();OSD_STATUS=request_high;
    reset=1;tick();reset=0;
    repeat(start_phase)tick();
  endtask

  integer start_phase,pattern,mode,i,j,k;
  logic [31:0] rng=32'h54865abc;
  initial begin
    // Every 12-clock request pattern, every steady raw start slot, and both
    // direct level sources pass through the exact registered board request.
    for(mode=0;mode<2;mode++)for(start_phase=0;start_phase<5;start_phase++)
      for(pattern=0;pattern<4096;pattern++)begin
        reset_at(start_phase,0);
        for(i=0;i<12;i++)begin
          if(mode==0)OSD_STATUS=(pattern>>i)&1;
          else nvram_pause=(pattern>>i)&1;
          tick();
        end
        clear_requests();repeat(8)tick();patterns++;
      end
    // Request asserted during reset, reset at each active/held start phase,
    // and release specifically during every raw phase including idle.
    for(start_phase=0;start_phase<5;start_phase++)for(i=0;i<64;i++)begin
      reset_at(start_phase,1);
      repeat(i%13+5)tick();
      reset=1;tick();reset=0;
      repeat(start_phase+7)tick();
      OSD_STATUS=0;repeat(8)tick();
    end
    // Exercise real rising-edge toggle handling for all three players, with
    // overlapping OSD/NVRAM levels and arbitrary release cycles.
    reset_at(0,0);
    for(i=0;i<4096;i++)begin
      rng=rng^(rng<<13);rng=rng^(rng>>17);rng=rng^(rng<<5);
      k=rng%3;OSD_STATUS=rng[1];nvram_pause=rng[2];
      case(k)0:joy0[9]=1;1:joy1[9]=1;2:joy2[9]=1;endcase
      tick();tick();user_toggles++;
      joy0=0;joy1=0;joy2=0;
      repeat(rng[6:3]+1)tick();
      if(i%31==0)begin reset=1;tick();reset=0;end
    end
    clear_requests();reset=1;tick();reset=0;repeat(10)tick();
    assert(patterns==40960&&acks>1000&&resume_f>1000&&resume_r>1000&&
      halted_cycles>1000&&paused_raw_ticks>1000&&paused_pixels>100&&paused_memory_ticks>1000&&
      reset_while_halted>0&&high_request_resets>0&&user_toggles==4096)
      else $fatal(1,"phase/pause coverage incomplete");
    $display("PASS pause_bridge {\"cycles\":%0d,\"request_patterns\":%0d,\"pause_request_edges\":%0d,\"pause_R_ack\":%0d,\"resume_F\":%0d,\"resume_following_R\":%0d,\"held_cycles\":%0d,\"raw_F\":%0d,\"raw_R\":%0d,\"pixel_ticks\":%0d,\"paused_raw_ticks\":%0d,\"paused_pixel_ticks\":%0d,\"independent_memory_ticks\":%0d,\"paused_memory_ticks\":%0d,\"reset_edges\":%0d,\"reset_while_held\":%0d,\"request_high_resets\":%0d,\"player_pause_toggles\":%0d}",
      cycles,patterns,requests,acks,resume_f,resume_r,halted_cycles,raw_f,raw_r,pixel_ticks,
      paused_raw_ticks,paused_pixels,memory_ticks,paused_memory_ticks,reset_edges,
      reset_while_halted,high_request_resets,user_toggles);
    $finish;
  end
endmodule
