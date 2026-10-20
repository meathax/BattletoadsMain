`timescale 1ns/1ps
module foreground_read_equivalence_tb;
  logic CLK='0;
  logic CPU_CLK='0;
  logic RST_N='0;
  logic [17: 0] A='0;
  logic [15: 0] D='0;
  logic RAS_N=1;
  logic [ 1: 0] CAS_N=3;
  logic WE_N=1;
  logic OE_N=1;
  logic SC='0;
  logic SE_N='0;
  logic [ 7: 0] SD='0;
  logic DRAW_WE='0;
  wire [15:0] DRAW_BANK_WE=(16'b1 << DRAW_ADDR[16:13]) & {16{DRAW_WE}};
  wire [15:0] DRAW_RAM_BANK_WE=DRAW_BANK_WE & {16{!DRAW_ADDR[8]}};
  logic [16: 0] DRAW_ADDR='0;
  logic [ 7: 0] DRAW_DATA='0;
  logic TRANSFER='0;
  logic CPU_SHIFT='0;
  logic MEM_CE='0;
  wire [31:0] candidate_HOLE_Q, reference_HOLE_Q;
  wire candidate_HOLE_RDY, reference_HOLE_RDY;
  logic [63:0] candidate_CPU_SHIFT_Q=0, candidate_CPU_SHIFT_Q1=0, reference_CPU_SHIFT_Q=0;
  wire [15: 0] candidate_Q, reference_Q;
  wire candidate_RDY, reference_RDY;
  wire [7:0] candidate_SQ, reference_SQ;
  wire [17: 0] candidate_HOLE_A, reference_HOLE_A;
  wire candidate_HOLE_SEL, reference_HOLE_SEL;
  wire candidate_HOLE_RD, reference_HOLE_RD;
  wire [3:0]   candidate_HOLE_WE, reference_HOLE_WE;
  wire [31:0]  candidate_HOLE_DATA, reference_HOLE_DATA;
  wire [ 5: 0] candidate_CPU_SHIFT_A, reference_CPU_SHIFT_A;
  wire candidate_CPU_SHIFT_RD, reference_CPU_SHIFT_RD;
  wire [ 5: 0] candidate_CPU_SHIFT_WA, reference_CPU_SHIFT_WA;
  wire [63: 0] candidate_CPU_SHIFT_DATA, reference_CPU_SHIFT_DATA;
  wire candidate_CPU_SHIFT_WE, reference_CPU_SHIFT_WE;
  FG_VRAM candidate(.CLK(CLK),
    .CPU_CLK(CPU_CLK),
    .RST_N(RST_N),
    .A(A),
    .D(D),
    .Q(candidate_Q),
    .RAS_N(RAS_N),
    .CAS_N(CAS_N),
    .WE_N(WE_N),
    .OE_N(OE_N),
    .RDY(candidate_RDY),
    .SC(SC),
    .SE_N(SE_N),
    .SD(SD),
    .SQ(candidate_SQ),
    .DRAW_WE(DRAW_WE),
    .DRAW_BANK_WE(DRAW_BANK_WE), .DRAW_RAM_BANK_WE(DRAW_RAM_BANK_WE),
    .DRAW_ADDR(DRAW_ADDR),
    .DRAW_DATA(DRAW_DATA),
    .TRANSFER(TRANSFER),
    .CPU_SHIFT(CPU_SHIFT),
    .MEM_CE(MEM_CE),
    .HOLE_A(candidate_HOLE_A),
    .HOLE_SEL(candidate_HOLE_SEL),
    .HOLE_RD(candidate_HOLE_RD),
    .HOLE_WE(candidate_HOLE_WE),
    .HOLE_DATA(candidate_HOLE_DATA),
    .HOLE_Q(candidate_HOLE_Q),
    .HOLE_RDY(candidate_HOLE_RDY),
    .CPU_SHIFT_Q(candidate_CPU_SHIFT_Q),
    .CPU_SHIFT_A(candidate_CPU_SHIFT_A),
    .CPU_SHIFT_RD(candidate_CPU_SHIFT_RD),
    .CPU_SHIFT_WA(candidate_CPU_SHIFT_WA),
    .CPU_SHIFT_DATA(candidate_CPU_SHIFT_DATA),
    .CPU_SHIFT_WE(candidate_CPU_SHIFT_WE));
  FG_VRAM_REFERENCE reference(.CLK(CLK),
    .CPU_CLK(CPU_CLK),
    .RST_N(RST_N),
    .A(A),
    .D(D),
    .Q(reference_Q),
    .RAS_N(RAS_N),
    .CAS_N(CAS_N),
    .WE_N(WE_N),
    .OE_N(OE_N),
    .RDY(reference_RDY),
    .SC(SC),
    .SE_N(SE_N),
    .SD(SD),
    .SQ(reference_SQ),
    .DRAW_WE(DRAW_WE),
    .DRAW_ADDR(DRAW_ADDR),
    .DRAW_DATA(DRAW_DATA),
    .TRANSFER(TRANSFER),
    .CPU_SHIFT(CPU_SHIFT),
    .MEM_CE(MEM_CE),
    .HOLE_A(reference_HOLE_A),
    .HOLE_SEL(reference_HOLE_SEL),
    .HOLE_RD(reference_HOLE_RD),
    .HOLE_WE(reference_HOLE_WE),
    .HOLE_DATA(reference_HOLE_DATA),
    .HOLE_Q(reference_HOLE_Q),
    .HOLE_RDY(reference_HOLE_RDY),
    .CPU_SHIFT_Q(reference_CPU_SHIFT_Q),
    .CPU_SHIFT_A(reference_CPU_SHIFT_A),
    .CPU_SHIFT_RD(reference_CPU_SHIFT_RD),
    .CPU_SHIFT_WA(reference_CPU_SHIFT_WA),
    .CPU_SHIFT_DATA(reference_CPU_SHIFT_DATA),
    .CPU_SHIFT_WE(reference_CPU_SHIFT_WE));
  always #3 CLK=~CLK;
  always #6 CPU_CLK=~CPU_CLK;
  integer clocks=0,checks=0,transactions=0,candidate_packets=0,reference_packets=0;
  logic [69:0] candidate_packet_log[1024],reference_packet_log[1024];
  function automatic [7:0] pattern(input integer index);
    return 8'(32'ha7 ^ index*13 ^ (index>>8));
  endfunction
  function automatic [63:0] cache_word(input logic [5:0] index);
    for(integer lane=0;lane<8;lane++) cache_word[lane*8+:8]=pattern(index*8+lane);
  endfunction
  // Independent adapters preserve the actual old/new cache latency contracts.
  always @(posedge CLK) begin
    reference_CPU_SHIFT_Q<=cache_word(reference_CPU_SHIFT_A);
    candidate_CPU_SHIFT_Q1<=cache_word(candidate_CPU_SHIFT_A);
    candidate_CPU_SHIFT_Q<=candidate_CPU_SHIFT_Q1;
    if(RST_N && candidate_CPU_SHIFT_WE) begin
      candidate_packet_log[candidate_packets]={candidate_CPU_SHIFT_WA,candidate_CPU_SHIFT_DATA};candidate_packets++;
    end
    if(RST_N && reference_CPU_SHIFT_WE) begin
      reference_packet_log[reference_packets]={reference_CPU_SHIFT_WA,reference_CPU_SHIFT_DATA};reference_packets++;
    end
  end
  always @(negedge CLK) begin clocks++;MEM_CE=clocks%4==0;end
  foreground_transaction_memory candidate_ddr(.clk(CLK),.reset_n(RST_N),.ce(MEM_CE),
    .a(candidate_HOLE_A),.rd(candidate_HOLE_RD),.we(candidate_HOLE_WE),.data(candidate_HOLE_DATA),.q(candidate_HOLE_Q),.ready(candidate_HOLE_RDY));
  foreground_transaction_memory reference_ddr(.clk(CLK),.reset_n(RST_N),.ce(MEM_CE),
    .a(reference_HOLE_A),.rd(reference_HOLE_RD),.we(reference_HOLE_WE),.data(reference_HOLE_DATA),.q(reference_HOLE_Q),.ready(reference_HOLE_RDY));
  task automatic tick(input integer count);
    repeat(count) begin @(negedge CLK);#0.2;end
  endtask
  task automatic compare_transactions;
    assert(candidate_packets==reference_packets) else $fatal(1,"foreground packet count differs %0d/%0d",candidate_packets,reference_packets);
    for(integer i=0;i<candidate_packets;i++) begin
      assert(candidate_packet_log[i]===reference_packet_log[i])
        else $fatal(1,"foreground packet differs transaction=%0d packet=%0d candidate=%h reference=%h",transactions,i,candidate_packet_log[i],reference_packet_log[i]);checks++;
    end
    assert(candidate_ddr.commands==reference_ddr.commands) else $fatal(1,"foreground DDR command count differs %0d/%0d",candidate_ddr.commands,reference_ddr.commands);
    for(integer i=0;i<candidate_ddr.commands;i++) begin
      assert(candidate_ddr.command_log[i]===reference_ddr.command_log[i])
        else $fatal(1,"foreground DDR request differs transaction=%0d request=%0d candidate=%h reference=%h",transactions,i,candidate_ddr.command_log[i],reference_ddr.command_log[i]);checks++;
    end
    candidate_packets=0;reference_packets=0;candidate_ddr.commands=0;reference_ddr.commands=0;
  endtask
  task automatic transfer(input logic [17:0] address,input bit write_copy,input bit cpu_copy);
    A=address;RAS_N=1;WE_N=1;OE_N=1;SC=0;TRANSFER=1;CPU_SHIFT=cpu_copy;SE_N=0;
    tick(8);OE_N=0;WE_N=!write_copy;RAS_N=0;tick(6);
    assert(!candidate_RDY && !reference_RDY) else $fatal(1,"foreground transfer never asserted busy");
    RAS_N=1;WE_N=1;OE_N=1;
    for(integer elapsed=0;elapsed<16000;elapsed++) begin
      tick(1);
      if(candidate_RDY && reference_RDY && !candidate_CPU_SHIFT_WE && !reference_CPU_SHIFT_WE) break;
      if(elapsed==15999) $fatal(1,"foreground completion timeout address=%h",address);
    end
    tick(8);
    if(cpu_copy && !write_copy)
      assert(candidate_packets==64 && reference_packets==64) else $fatal(1,"foreground read lost a 512-byte copy");
    compare_transactions();transactions++;CPU_SHIFT=0;TRANSFER=0;
  endtask
  initial begin
    tick(8);RST_N=1;tick(12);
    for(integer bank=0;bank<16;bank++) begin
      for(integer pixel=0;pixel<256;pixel++) begin
        DRAW_WE=1;DRAW_ADDR=17'((bank<<13)|pixel);DRAW_DATA=pattern((bank<<14)|pixel);tick(4);
      end
      DRAW_WE=0;tick(8);
      for(integer pixel=0;pixel<256;pixel+=2) begin
        A=18'((bank<<14)|pixel);tick(8);
        assert(candidate_Q===reference_Q && candidate_Q=={pattern((bank<<14)|(pixel+1)),pattern((bank<<14)|pixel)})
          else $fatal(1,"foreground visible draw/read mismatch bank=%0d pixel=%0d candidate=%h reference=%h",bank,pixel,candidate_Q,reference_Q);checks++;
      end
      for(integer mask=0;mask<4;mask++) begin
        A=18'((bank<<14)|mask*2);D=16'(32'h51a7^(bank*271+mask));CAS_N=2'(~mask);
        RAS_N=0;OE_N=1;WE_N=0;tick(8);WE_N=1;RAS_N=1;tick(12);
        assert(candidate_Q===reference_Q) else $fatal(1,"foreground ordinary byte write mismatch bank=%0d mask=%0d",bank,mask);checks++;
      end
      CAS_N=3;
      for(integer offset=0;offset<8;offset++) transfer(18'((bank<<14)|offset),0,1);
      for(integer region=1;region<4;region++) transfer(18'((bank<<14)|(region<<8)|7),0,1);
      transfer(18'((bank<<14)|1020),0,1);
      transfer(18'(bank<<14),1,1);
      transfer(18'(bank<<14),0,1);
      transfer(18'(bank<<14),0,0);
      for(integer pixel=0;pixel<256;pixel++) begin
        SC=1;tick(6);
        assert(candidate_SQ===reference_SQ) else $fatal(1,"foreground serial consumer mismatch bank=%0d pixel=%0d candidate=%h reference=%h",bank,pixel,candidate_SQ,reference_SQ);
        checks++;SC=0;tick(6);
      end
    end
    RST_N=0;tick(8);RST_N=1;tick(12);A=0;tick(8);
    assert(candidate_Q===reference_Q) else $fatal(1,"foreground reset changed retained memory");
    $display("PASS foreground transaction equivalence: transactions=%0d comparisons=%0d banks/lanes, complete copies, boundaries, serial consumers, independent responses and reset",transactions,checks);
    $finish;
  end
endmodule

module foreground_transaction_memory(input clk,reset_n,ce,input [17:0] a,input rd,
  input [3:0] we,input [31:0] data,output logic [31:0] q=0,output ready);
  logic [7:0] bytes[262144];
  logic busy=0,armed=1;
  integer delay_left=0,commands=0;
  logic [17:0] accepted_address=0;
  logic [54:0] command_log[1024];
  assign ready=!busy;
  initial for(integer i=0;i<262144;i++) bytes[i]=8'(32'ha7 ^ i*13 ^ (i>>8));
  always @(posedge clk) begin
    if(!reset_n) begin busy<=0;armed=1;delay_left=0;end
    else begin
      if(!rd && !we) armed=1;
      if(busy) begin
        delay_left--;
        if(delay_left==0) begin
          q<={8'b0,bytes[(accepted_address & 18'h3fffe)+1],8'b0,bytes[accepted_address & 18'h3fffe]};busy<=0;
        end
      end else if(ce && (rd || |we) && (armed || a!=accepted_address)) begin
        command_log[commands]={a,we,rd,rd ? 32'b0 : data};commands++;
        accepted_address=a;armed=0;busy<=1;delay_left=3+(commands%7);
        if(we[0]) bytes[a & 18'h3fffe]=data[7:0];
        if(we[2]) bytes[(a & 18'h3fffe)+1]=data[23:16];
      end
    end
  end
endmodule
