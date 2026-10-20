`timescale 1ns/1ps
module bt_pause_nvram_tb;
  logic clk_sys=0,reset=1,OSD_STATUS=0;
  logic [31:0] joy0=0,joy1=0,joy2=0;
  logic [12:0] BT_NVRAM_ADDR=0;
  logic [7:0] BT_NVRAM_DATA=0;
  logic BT_NVRAM_WE=0,rom_download=0,ioctl_download=0,ioctl_upload=0,ioctl_wr=0;
  logic [15:0] ioctl_index=4,ioctl_dout=0;
  logic [26:0] ioctl_addr=0;
  wire gated_f,gated_r,vce,nvram_pause,nvram_ready,nvram_upload_req;
  wire [7:0] nvram_q;
  wire [15:0] nvram_ioctl_din;
  wire old_f,old_r,old_vce,old_pause,old_ready,old_req;
  wire [7:0] old_q;wire [15:0] old_din;
  nvram_phase_board board(.*);
  nvram_phase_board_old old_board(.gated_f(old_f),.gated_r(old_r),.vce(old_vce),
    .nvram_pause(old_pause),.nvram_ready(old_ready),.nvram_upload_req(old_req),
    .nvram_q(old_q),.nvram_ioctl_din(old_din),.*);
  byte expected[8192];
  integer cycles=0,cpu_writes=0,blocked_writes=0,upload_words=0,restore_words=0;
  integer offers=0,old_early_offers=0,last_write_edge=-100,halt_edge=-100,save_edge=-100;
  integer final_saved=0,legacy_lost=0,restore_ready_races=0,manual_uploads=0;
  integer request_cases=0,reset_pending=0,newgame_collisions=0,duplicate_offers=0;
  integer max_halt_delay=0,max_offer_delay=0,min_write_offer_gap=100;
  bit check_offers=0,pending_monitor=0,compare_unpaused=1;
  bit before_hold,before_pending,before_write,before_old_write;

  task automatic tick;
    #1;
    before_hold=board.cpu_pause_bridge.halted_reg;
    before_pending=board.nvram.save_pending;
    before_write=board.nvram.cpu_write;
    before_old_write=old_board.nvram.cpu_write;
    if(ioctl_upload||ioctl_download||board.nvram.initializing)
      assert(!nvram_ready&&!before_write) else $fatal(1,"physical RAM owner not excluded");
    if(compare_unpaused&&!before_pending&&!board.nvram.initializing&&!ioctl_upload&&!ioctl_download&&
       board.nvram.read_valid&&old_board.nvram.read_valid)
      assert(nvram_q==old_q&&nvram_ready==old_ready&&before_write==before_old_write)
      else $fatal(1,"ordinary unpaused RAM behavior changed");
    if(before_write)begin cpu_writes++;last_write_edge=cycles;end
    if(BT_NVRAM_WE&&board.CE_R&&!before_write)blocked_writes++;
    clk_sys=1;#0.01;
    if(!before_hold&&board.cpu_pause_bridge.halted_reg)begin
      halt_edge=cycles;
      if(check_offers&&pending_monitor&&cycles-save_edge>max_halt_delay)max_halt_delay=cycles-save_edge;
    end
    if(!before_pending&&board.nvram.save_pending)begin
      save_edge=cycles;pending_monitor=1;
    end
    if(nvram_upload_req)begin
      offers++;
      assert(before_hold&&!board.nvram.initializing&&!ioctl_upload&&!ioctl_download)
        else $fatal(1,"upload admitted before halt or during physical owner");
      assert(cycles>last_write_edge) else $fatal(1,"upload precedes final settled write");
      if(cycles-last_write_edge<min_write_offer_gap)min_write_offer_gap=cycles-last_write_edge;
      if(check_offers&&pending_monitor&&cycles-save_edge>max_offer_delay)max_offer_delay=cycles-save_edge;
      if(check_offers)begin
        duplicate_offers++;
        assert(duplicate_offers==1) else $fatal(1,"duplicate save upload request");
      end
    end
    if(old_req&&!before_hold)old_early_offers++;
    cycles++;clk_sys=0;#0.01;
  endtask

  task automatic clear_inputs;
    OSD_STATUS=0;joy0=0;joy1=0;joy2=0;BT_NVRAM_WE=0;
    ioctl_download=0;ioctl_upload=0;ioctl_wr=0;ioctl_index=4;rom_download=0;
    check_offers=0;pending_monitor=0;duplicate_offers=0;compare_unpaused=1;
  endtask

  task automatic new_image;
    clear_inputs();rom_download=1;reset=1;tick();rom_download=0;reset=0;
    repeat(4102)tick();
    assert(!board.nvram.initializing&&!old_board.nvram.initializing) else $fatal(1,"init did not finish");
    repeat(10)tick();
  endtask

  task automatic write_byte(input integer addr,input [7:0] value);
    BT_NVRAM_ADDR=addr;BT_NVRAM_DATA=value;BT_NVRAM_WE=1;
    do begin #0.02; if(!gated_r)tick();end while(!gated_r);
    tick();BT_NVRAM_WE=0;expected[addr]=value;
  endtask

  task automatic wait_resume;
    integer guard;
    guard=0;
    while(board.cpu_pause_bridge.halted_reg||board.pause_cpu||nvram_pause)begin
      tick();guard++;assert(guard<40) else $fatal(1,"resume did not complete");
    end
    repeat(3)tick();
  endtask

  integer phase,i,j,guard,offer_before;
  logic [7:0] final_value;
  initial begin
    new_image();
    // Save a complete image for each possible request start phase, including
    // a request asserted on the F that prepares the final admitted R write.
    for(phase=0;phase<5;phase++)begin
      new_image();
      for(i=0;i<8192;i++)write_byte(i,8'(i*13+7));
      // Land on a raw start slot before requesting a save. The pending CPU
      // strobe is held until the bridge's next admitted R, as actual MC
      // clears DBUS_WE only on the R closure (MC528–534).
      while(board.clock_enables.cpu_slot!=phase)tick();
      BT_NVRAM_ADDR=0;final_value=8'ha6+phase;BT_NVRAM_DATA=final_value;BT_NVRAM_WE=1;
      OSD_STATUS=1;check_offers=1;compare_unpaused=0;duplicate_offers=0;offer_before=offers;
      guard=0;
      while(!board.cpu_pause_bridge.halted_reg)begin
        if(gated_r)begin tick();BT_NVRAM_WE=0;end else tick();
        guard++;assert(guard<8) else $fatal(1,"halt boundary exceeded");
      end
      BT_NVRAM_WE=0;
      expected[0]=final_value;
      assert(board.nvram.ram[0][7:0]==final_value) else $fatal(1,"closing R write was lost");
      final_saved++;
      if(old_board.nvram.ram[0][7:0]!=final_value)legacy_lost++;
      while(offers==offer_before)tick();
      repeat(6)tick();assert(offers==offer_before+1) else $fatal(1,"upload request repeated");
      request_cases++;
      // The first host read starts as soon as the safe request is observed.
      // Check every byte and inject CPU write attempts while the port is held.
      ioctl_upload=1;ioctl_addr=0;BT_NVRAM_WE=1;BT_NVRAM_DATA=8'hff;
      for(i=0;i<4096;i++)begin
        ioctl_addr=i*2;tick();
        assert(nvram_ioctl_din=={expected[i*2+1],expected[i*2]})
          else $fatal(1,"uploaded image changed at word%0d",i);
        upload_words++;
      end
      ioctl_upload=0;OSD_STATUS=0;BT_NVRAM_WE=0;check_offers=0;tick();wait_resume();
      assert(nvram_q==final_value&&nvram_ready) else $fatal(1,"upload return did not settle");
      // Restore without waiting for a halt acknowledgement, as the real HPS
      // may start a download directly. Port exclusion is immediate and the
      // final read/write collision is not reported ready until a SYS read.
      BT_NVRAM_ADDR=8191;BT_NVRAM_WE=1;BT_NVRAM_DATA=8'hc1;
      ioctl_download=1;ioctl_wr=1;
      for(i=0;i<4096;i++)begin
        ioctl_addr=i*2;ioctl_dout={8'(~expected[i*2+1]),8'(~expected[i*2])};tick();
        restore_words++;
      end
      ioctl_download=0;ioctl_wr=0;BT_NVRAM_WE=0;#0.02;
      for(i=0;i<4096;i++)assert(board.nvram.ram[i]=={8'(~expected[i*2+1]),8'(~expected[i*2])})
        else $fatal(1,"restore image changed at word%0d",i);
      assert(!nvram_ready) else $fatal(1,"ready raced the last restore write");
      restore_ready_races++;
      tick();assert(nvram_ready&&nvram_q==8'(~expected[8191]))
        else $fatal(1,"restored byte not published after registered read");
      wait_resume();
    end
    // Reset the CPU while a save is pending. The NVRAM request remains, and
    // the board re-enters its original startup then acknowledges R again.
    new_image();write_byte(0,8'h72);OSD_STATUS=1;tick();reset=1;tick();reset=0;
    reset_pending++;while(!board.cpu_pause_bridge.halted_reg)tick();
    repeat(3)tick();assert(board.nvram.save_pending) else $fatal(1,"CPU reset discarded save");
    // A new ROM download cancels the pending save and initializes all RAM,
    // even when host download/write and CPU-write inputs collide.
    rom_download=1;ioctl_download=1;ioctl_wr=1;ioctl_dout=16'hdead;BT_NVRAM_WE=1;tick();
    rom_download=0;ioctl_download=0;ioctl_wr=0;BT_NVRAM_WE=0;OSD_STATUS=0;
    newgame_collisions++;
    assert(!board.nvram.save_pending&&!board.nvram.save_issued) else $fatal(1,"newgame retained upload request");
    repeat(4102)tick();wait_resume();
    for(i=0;i<4096;i++)assert(board.nvram.ram[i]==0) else $fatal(1,"init collision left stale RAM");
    // External upload can begin without a preceding save. It must borrow the
    // port immediately, emit no save request while active, and prevent writes.
    write_byte(0,8'h91);ioctl_upload=1;ioctl_addr=0;BT_NVRAM_WE=1;OSD_STATUS=1;
    offer_before=offers;
    repeat(9)tick();assert(offers==offer_before&&nvram_ioctl_din[7:0]==8'h91)
      else $fatal(1,"manual upload ownership/update request collision");
    ioctl_upload=0;OSD_STATUS=0;BT_NVRAM_WE=0;tick();manual_uploads++;wait_resume();
    assert(!board.nvram.save_pending&&!board.nvram.save_issued) else $fatal(1,"manual upload completion stuck");
    assert(final_saved==5&&legacy_lost>0&&old_early_offers>0&&upload_words==20480&&restore_words==20480&&
      restore_ready_races==5&&blocked_writes>0&&reset_pending>0&&newgame_collisions>0&&manual_uploads>0)
      else $fatal(1,"NVRAM ownership coverage incomplete");
    assert(max_halt_delay<=3&&max_offer_delay<=4&&min_write_offer_gap>=1)
      else $fatal(1,"safe save boundary timing changed: halt%0d offer%0d gap%0d",max_halt_delay,max_offer_delay,min_write_offer_gap);
    $display("PASS pause_nvram {\"cycles\":%0d,\"cpu_write_edges\":%0d,\"blocked_cpu_write_attempts\":%0d,\"save_request_phases\":%0d,\"final_R_writes_saved\":%0d,\"legacy_integration_lost_writes\":%0d,\"old_early_upload_requests\":%0d,\"upload_words\":%0d,\"upload_bytes\":%0d,\"restore_words\":%0d,\"restore_ready_races\":%0d,\"CPU_reset_pending_save\":%0d,\"newgame_download_collision\":%0d,\"manual_upload_collision\":%0d,\"maximum_save_to_halt_SYS\":%0d,\"maximum_save_to_upload_req_SYS\":%0d,\"minimum_final_write_to_request_SYS\":%0d}",
      cycles,cpu_writes,blocked_writes,request_cases,final_saved,legacy_lost,old_early_offers,
      upload_words,upload_words*2,restore_words,restore_ready_races,reset_pending,newgame_collisions,
      manual_uploads,max_halt_delay,max_offer_delay,min_write_offer_gap);
    $finish;
  end
endmodule
