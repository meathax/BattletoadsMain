`timescale 1ns/1ps
module bt_fg_serial_replicas_intel_tb;
  reg CLK=0, RST_N=0;
  reg [5:0] SRW_A=0;
  reg [63:0] SRW_D=0;
  reg [7:0] SRW_E=0;
  reg RMT_EXEC=0, CPU_COPY_MODE=0;
  reg [8:0] SREG_POS=0, SR_RA=0;
  wire [63:0] SR_Q, oracle_q;
  wire [63:0] SERIAL_WRITE_WORD=SR_Q;
  wire [3:0][63:0] SERIAL_WRITE_WORD_B;
  assign SERIAL_WRITE_WORD_B[0]=SERIAL_WRITE_WORD;
  always #5 CLK=~CLK;

  // @@PRODUCTION_RAM_BLOCK@@
  // @@IMMUTABLE_ORACLE_INSTANCE@@

  integer cycles=0, bit_checks=0, reset_events=0;
  integer collision_reads=0, noncollision_reads=0;
  integer mask_counts[0:255], row_counts[0:63];
  wire [5:0] read_row=RMT_EXEC && !CPU_COPY_MODE ? SREG_POS[8:3] : SR_RA[8:3];
  task automatic compare_q;
    assert(SR_Q === oracle_q)
      else $fatal(1,"original serial RAM differs from immutable Intel oracle, data or X");
    for(integer bank=0;bank<4;bank++) begin
      assert(SERIAL_WRITE_WORD_B[bank] === oracle_q)
        else $fatal(1,"serial replica differs from immutable Intel oracle bank=%0d, data or X",bank);
      bit_checks+=64;
    end
  endtask
  always @(posedge CLK) begin
    cycles++;
    if(SRW_E!=0) begin
      if(read_row==SRW_A) collision_reads++;
      else noncollision_reads++;
    end
    #1;
    compare_q();
  end
  always @(negedge RST_N) begin
    reset_events++;
    #0.2;
    compare_q();
  end

  task automatic drive(input integer row, input integer mask, input integer route,
                        input integer different, input integer tag);
    @(negedge CLK);
    SRW_A=6'(row); SRW_E=8'(mask);
    for(integer byte_lane=0;byte_lane<8;byte_lane++)
      SRW_D[byte_lane*8+:8]=8'(tag*29+row*17+mask*7+byte_lane*31);
    {RMT_EXEC,CPU_COPY_MODE}=2'(route);
    SREG_POS={6'(row^different),3'(tag)};
    SR_RA={6'(row^different),3'(~tag)};
    #1;
  endtask

  initial begin
    for(integer mask=0;mask<256;mask++) mask_counts[mask]=0;
    for(integer row=0;row<64;row++) row_counts[row]=0;
    repeat(3) @(negedge CLK);
    RST_N=1;
    // Fill every native row, then exercise every byte-enable mask and every
    // original read-address selection. Same/different-row collisions remain
    // subject to the exact Intel OLD_DATA contract, with no output masks.
    for(integer row=0;row<64;row++) drive(row,255,0,0,row);
    for(integer mask=0;mask<256;mask++) begin
      for(integer row=0;row<64;row++) begin
        for(integer route=0;route<4;route++) begin
          drive(row,mask,route,(route&1)?0:32,mask*256+row*4+route);
          mask_counts[mask]++; row_counts[row]++;
          if((mask%32)==0 && row==31 && route==0) begin
            // ACLR between clock edges, including a selected read and active
            // byte enables; the production replicas and original keep all
            // configuration and write/read edges unchanged.
            #1; RST_N=0; #0.4; RST_N=1;
          end
          if((mask%64)==0 && row==63 && route==3) begin
            RST_N=0;
            @(posedge CLK); #2; RST_N=1;
          end
        end
      end
    end
    drive(0,0,0,0,0);
    repeat(4) @(negedge CLK);
    for(integer mask=0;mask<256;mask++)
      assert(mask_counts[mask]==256) else $fatal(1,"missing mask=%0d",mask);
    for(integer row=0;row<64;row++)
      assert(row_counts[row]==1024) else $fatal(1,"missing row=%0d",row);
    assert(collision_reads>30000 && noncollision_reads>30000 && reset_events>=12)
      else $fatal(1,"missing Intel collision/reset coverage");
    $display("PASS FG serial RAM replicas: cycles=%0d bit_checks=%0d mask_cases=256 rows=64 replicas=3 reset_events=%0d collision_reads=%0d noncollision_reads=%0d; exact Intel OLD_DATA Q and X case equality",cycles,bit_checks,reset_events,collision_reads,noncollision_reads);
    $finish;
  end
  initial begin #1000000; $fatal(1,"serial RAM replica test timeout"); end
endmodule
