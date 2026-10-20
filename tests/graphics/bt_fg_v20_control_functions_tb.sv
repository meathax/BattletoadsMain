`timescale 1ns/1ps
// The qualifier replaces this single marker with the actual candidate functions.
module fg_local_controls_fourstate_tb;
  // __ACTUAL_FUNCTIONS__
  logic CLK=0;
  logic RAS_N,OE_N,WE_N,TRANSFER,SE_N;
  bit OLD_RAS,OLD_OE,OLD_WE,OLD_TRANSFER,OLD_SE;
  bit NEW_TRANSFER,NEW_RMT;
  bit done=0;
  integer raw_cases=0,position_cases=0,unknown_control_cases=0;
  logic [8:0] position;
  logic ram_step,ddr_step,restart;
  bit end_mode;
  integer value,bit_index,controls,mode,remainder;

  always @(posedge CLK) begin
    // These bit-valued raw flag assignments are bound to the parent source.
    OLD_RAS<=RAS_N; OLD_OE<=OE_N; OLD_WE<=WE_N;
    OLD_TRANSFER<=TRANSFER; OLD_SE<=SE_N;
    NEW_TRANSFER<=FG_TRANSFER_COMMAND(RAS_N,OE_N,TRANSFER);
    NEW_RMT<=FG_RMT_COMMAND(RAS_N,OE_N,WE_N,TRANSFER,SE_N);
  end

  function automatic logic digit(input integer v);
    case(v & 3)
      0:digit=1'b0;
      1:digit=1'b1;
      2:digit=1'bx;
      3:digit=1'bz;
    endcase
  endfunction

  function automatic bit original_end;
    input logic [8:0] pos;
    input logic step_ram,step_ddr,start;
    input bit ddr_end;
    logic [8:0] next_position;
    begin
      // Original HOLE_NEXT_POS assignments, in their original priority order.
      next_position=pos;
      if(start) next_position=9'd0;
      if(step_ram) next_position=pos+9'h8;
      if(step_ddr) next_position=pos+9'd2;
      // Only this original bit-valued capture converts an unknown equality.
      original_end=next_position==(ddr_end ? 9'h1fe : 9'h1f8);
    end
  endfunction

  initial begin
    // Every 4-state continuous position, every binary priority combination.
    for(value=0;value<262144;value=value+1) begin
      remainder=value;
      for(bit_index=0;bit_index<9;bit_index=bit_index+1) begin
        position[bit_index]=digit(remainder);
        remainder=remainder>>2;
      end
      for(controls=0;controls<8;controls=controls+1) begin
        ram_step=controls[0];ddr_step=controls[1];restart=controls[2];
        for(mode=0;mode<2;mode=mode+1) begin
          end_mode=mode[0];
          assert(FG_POSITION_END_NEXT(position,ram_step,ddr_step,restart,end_mode)
                 ===original_end(position,ram_step,ddr_step,restart,end_mode))
            else $fatal(1,"FG next-position four-state equality differs: pos=%h controls=%b end=%b",position,controls,end_mode);
          position_cases=position_cases+1;
        end
      end
    end
    // Illegal/unknown control combinations preserve procedural-if semantics.
    for(value=0;value<512;value=value+1) begin
      position=value[8:0];
      for(controls=0;controls<64;controls=controls+1) begin
        ram_step=digit(controls);ddr_step=digit(controls>>2);restart=digit(controls>>4);
        for(mode=0;mode<2;mode=mode+1) begin
          end_mode=mode[0];
          assert(FG_POSITION_END_NEXT(position,ram_step,ddr_step,restart,end_mode)
                 ===original_end(position,ram_step,ddr_step,restart,end_mode))
            else $fatal(1,"FG next-position unknown-control priority differs");
          unknown_control_cases=unknown_control_cases+1;
        end
      end
    end
    // This intentionally bad early bit coercion must be distinguished.
    position=9'h1fc;position[0]=1'bx;
    assert(original_end(position,1'b0,1'b1,1'b0,1'b1)==1'b0 &&
           FG_POSITION_END_NEXT(position,1'b0,1'b1,1'b0,1'b1)==1'b0 &&
           BAD_EARLY_COERCE(position,1'b0,1'b1,1'b0,1'b1)==1'b1)
      else $fatal(1,"FG continuous-position coercion negative control was not detected");
    for(value=0;value<1024;value=value+1) begin
      RAS_N=digit(value);OE_N=digit(value>>2);WE_N=digit(value>>4);
      TRANSFER=digit(value>>6);SE_N=digit(value>>8);
      #1;CLK=1;#0.1;
      assert(NEW_TRANSFER===(!OLD_RAS && !OLD_OE && OLD_TRANSFER) &&
             NEW_RMT===(!OLD_RAS && !OLD_OE && !OLD_WE && OLD_TRANSFER && !OLD_SE))
        else $fatal(1,"FG raw-command bit capture differs for X/Z input");
      raw_cases=raw_cases+1;
      #0.9;CLK=0;
    end
    assert(raw_cases==1024 && position_cases==4194304 && unknown_control_cases==65536)
      else $fatal(1,"FG four-state function coverage incomplete");
    $display("PASS FG actual control functions: raw_xz=%0d position_xz=%0d control_xz=%0d coercion_negative=1",raw_cases,position_cases,unknown_control_cases);
    done=1;
  end
endmodule
