// Equivalence of rtl/bt_audio_ram.sv (sliced) against the previous inferred
// version frozen below as bt_audio_ram_ref. Run with altera_mf.v (see vram_slice_tb).
// Z80 byte reads/writes and word-wide ROM loading share one write owner.
// ROM loading resets the Z80, so loader writes take priority during download.
module bt_audio_ram_ref (
    input clock,
    input [14:0] load_addr,
    input [15:0] load_data,
    input load_we,
    input [15:0] cpu_addr,
    input [7:0] cpu_data,
    input cpu_we,
    output [7:0] cpu_q
);
    // Deep byte banks use M10K; foreground DDR storage frees the required blocks.
    (* ramstyle = "M10K" *) reg [7:0] rom_low [0:16383];
    (* ramstyle = "M10K" *) reg [7:0] rom_high [0:16383];
    (* ramstyle = "M10K" *) reg [7:0] low_byte [0:16383];
    (* ramstyle = "M10K" *) reg [7:0] high_byte [0:16383];
    reg [15:0] rom_word = 0, ram_word = 0;
    reg read_lane = 0;
    reg read_bank = 0;
    integer i, j;
    initial begin
        // Keep each loop below Quartus 17's 5000-iteration limit.
        for (i = 0; i < 8; i = i + 1) begin
            for (j = 0; j < 2048; j = j + 1) begin
                rom_low[i*2048+j] = 0;
                rom_high[i*2048+j] = 0;
                low_byte[i*2048+j] = 0;
                high_byte[i*2048+j] = 0;
            end
        end
    end
    wire [14:0] write_addr = load_we ? load_addr : cpu_addr[15:1];
    wire [15:0] write_data = load_we ? load_data : {2{cpu_data}};
    always @(posedge clock) begin
        if (load_we || (cpu_we && !cpu_addr[0])) begin
            if (write_addr[14]) low_byte[write_addr[13:0]] <= write_data[7:0];
            else rom_low[write_addr[13:0]] <= write_data[7:0];
        end
        if (load_we || (cpu_we && cpu_addr[0])) begin
            if (write_addr[14]) high_byte[write_addr[13:0]] <= write_data[15:8];
            else rom_high[write_addr[13:0]] <= write_data[15:8];
        end
        rom_word <= {rom_high[cpu_addr[14:1]], rom_low[cpu_addr[14:1]]};
        ram_word <= {high_byte[cpu_addr[14:1]], low_byte[cpu_addr[14:1]]};
        read_lane <= cpu_addr[0];
        read_bank <= cpu_addr[15];
    end
    wire [15:0] read_word = read_bank ? ram_word : rom_word;
    assign cpu_q = read_lane ? read_word[15:8] : read_word[7:0];
endmodule

`timescale 1ns/1ps
module audio_slice_tb;
  reg clock=0; always #5 clock=~clock;
  reg [14:0] la=0; reg [15:0] ld=0; reg lwe=0; reg [15:0] ca=0; reg [7:0] cd=0; reg cwe=0;
  wire [7:0] qn, qr;
  bt_audio_ram n(clock,la,ld,lwe,ca,cd,cwe,qn);
  bt_audio_ram_ref r(clock,la,ld,lwe,ca,cd,cwe,qr);
  integer c;
  initial begin
    for (c=0;c<400000;c=c+1) begin
      @(negedge clock);
      la=$urandom; ld=$urandom; lwe=(c<20000) ? ($urandom%2) : 0;
      ca=($urandom%4==0) ? ({la,1'b0} | 16'($urandom%2)) : (16'(($urandom%2)<<15) | 16'($urandom % 256) | (($urandom%6==0)? 16'($urandom) : 16'd0));
      cd=$urandom; cwe=(c>=20000) && ($urandom%3==0);
      @(posedge clock); #1;
      if (qn !== qr) begin $display("FAIL c=%0d %h %h",c,qn,qr); $fatal(1); end
    end
    $display("PASS sliced Z80 audio RAM/ROM: %0d cycles, loader and CPU writes, every cycle equal",c);
    $finish;
  end
endmodule
