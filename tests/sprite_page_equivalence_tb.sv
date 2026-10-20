`timescale 1ns/1ps
module sprite_page_equivalence_tb;
  bit CLK=0; always #5 CLK=~CLK;
  bit RST_N=0, CE_R=0, RAS_N=1, WE_N=1, OE_N=1, SHIFT=0;
  bit [31:0] A;
  bit [15:0] CONTROL, SOURCE_SCALE, DEST_SCALE, SOURCE_DATA;
  wire [3:0] SOURCE_NONZERO = {|SOURCE_DATA[15:12], |SOURCE_DATA[11:8],
                              |SOURCE_DATA[7:4], |SOURCE_DATA[3:0]};
  bit SHADOW, DEST_PAGE, DRAW_READY;
  wire [8:0] SOURCE_WORD, reference_source_word;
  wire DRAW_WE, DRAW_PAGE, BUSY, reference_we, reference_page, reference_busy;
  wire [1:0] DRAW_PAGE_WE;
  wire [1:0][15:0] DRAW_BANK_WE, DRAW_RAM_BANK_WE;
  wire [16:0] DRAW_ADDR, reference_addr;
  wire [7:0] DRAW_DATA, reference_data;
  BT_SPRITE_BLITTER #(.NONZERO_PREDECODE(1)) dut(.*);
  BT_SPRITE_BLITTER_REFERENCE golden(.SOURCE_WORD(reference_source_word),
    .DRAW_WE(reference_we),.DRAW_ADDR(reference_addr),.DRAW_DATA(reference_data),
    .DRAW_PAGE(reference_page),.BUSY(reference_busy),.*);
  int unsigned seed=32'hD4A7BEEF;
  function automatic int unsigned random_bits();
    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;
    return seed;
  endfunction
  initial begin
    for(int cycle=0;cycle<100000;cycle++) begin
      @(negedge CLK);
      RST_N=(cycle%20000)>=3;
      CE_R=(cycle%3)==0;
      RAS_N=cycle[0]; OE_N=0; SHIFT=1;
      A=random_bits();
      case ((cycle/2)%3)
        0: begin A[31:26]=6'b101001; WE_N=1; end
        1: begin A[31:26]=6'b101010; WE_N=1; end
        2: begin A[31:26]=6'b101011; WE_N=0; end
      endcase
      CONTROL=16'(random_bits()); SOURCE_SCALE=16'(random_bits());
      DEST_SCALE=16'(random_bits()); SOURCE_DATA=16'(random_bits());
      SHADOW=1'(random_bits()); DEST_PAGE=1'(random_bits()); DRAW_READY=1'(random_bits());
      @(posedge CLK); #1;
      assert ({SOURCE_WORD,DRAW_WE,DRAW_ADDR,DRAW_DATA,DRAW_PAGE,BUSY}===
              {reference_source_word,reference_we,reference_addr,reference_data,reference_page,reference_busy})
        else $fatal(1,"Sprite behavior changed at cycle %0d",cycle);
      assert (DRAW_PAGE_WE===({2{reference_we}} & {reference_page,!reference_page}))
        else $fatal(1,"Sprite page strobe changed at cycle %0d",cycle);
      for(int page=0;page<2;page++) begin
        assert(DRAW_BANK_WE[page]===((16'b1 << reference_addr[16:13]) & {16{reference_we && reference_page==page}}))
          else $fatal(1,"Sprite bank predecode changed cycle %0d",cycle);
        assert(DRAW_RAM_BANK_WE[page]===(DRAW_BANK_WE[page] & {16{!reference_addr[8]}}))
          else $fatal(1,"Sprite RAM bank predecode changed cycle %0d",cycle);
      end
    end
    $display("PASS sprite page predecode: 100000 all-output comparisons, resets, cursor updates, stalls, simultaneous page changes");
    $finish;
  end
endmodule
