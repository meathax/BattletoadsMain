`timescale 1ns/1ps
module fg_remote_v22_fourstate_tb;
  logic [2:0] HOLE_RMT_EXEC_B, HOLE_POS_END_RAM_B, HOLE_POS_END_DDR_B;
  localparam integer hole_group=1;
  logic start_ras, start_rmt, next_copy_mode, step_ram, step_ddr;
  logic [8:0] next_pos;
  logic [8:0] values;
  bit done=0;
  integer checks=0, negative_detected=0;
  // __ORIGINAL_STOP_AND_NEXT__
  // __ORIGINAL_REMOTE__
  // __CANDIDATE_REMOTE__
  wire bad_remote = ((HOLE_RMT_EXEC_B[hole_group] && !start_ras) || start_rmt) &&
      next_copy_mode && next_pos[8] && !(step_ram && HOLE_POS_END_RAM_B[hole_group]);
  function automatic logic digit(input integer code);
    case(code)
      0: digit=1'b0;
      1: digit=1'b1;
      2: digit=1'bx;
      3: digit=1'bz;
    endcase
  endfunction
  initial begin
    for(integer n=0;n<262144;n=n+1) begin
      for(integer k=0;k<9;k=k+1) values[k]=digit((n>>(2*k))&3);
      HOLE_RMT_EXEC_B={3{values[0]}};
      start_ras=values[1];start_rmt=values[2];next_copy_mode=values[3];
      next_pos={values[4],8'b0};step_ram=values[5];step_ddr=values[6];
      HOLE_POS_END_RAM_B={3{values[7]}};HOLE_POS_END_DDR_B={3{values[8]}};
      #1;
      assert(original_remote === candidate_remote)
        else $fatal(1,"FG remote four-state mismatch code=%0d old=%b new=%b",n,original_remote,candidate_remote);
      if(original_remote !== bad_remote) negative_detected=negative_detected+1;
      checks=checks+1;
    end
    assert(checks==262144 && negative_detected>0)
      else $fatal(1,"FG remote exhaustive coverage or negative control missing");
    done=1;
    $display("PASS FG v22 remote four-state: cases=%0d negative_detected=%0d",checks,negative_detected);
  end
endmodule
