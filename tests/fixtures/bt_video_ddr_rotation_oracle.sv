// Frozen pre-removal bridge; memory equivalence only, rot_we=0.
// Original SHA256 (normalized LF): 48ec55039b242b00fd6d5f998a635d6e58b45661e3c41293c2d651ea094ca535
// Queue the video tap across the system/memory clock domains. The existing
// DDR controller retains command ownership until its held request is accepted.
module bt_video_ddr_rotation_oracle(
    input reset, video_clk, mem_clk,
    input rot_we,
    input [28:0] rot_addr,
    input [63:0] rot_data,
    input [7:0] rot_be,
    input [7:0] mem_burst,
    input [28:0] mem_addr,
    input [63:0] mem_data,
    input [7:0] mem_be,
    input mem_we, mem_rd,
    input ddr_busy,
    output mem_busy,
    output [7:0] ddr_burst,
    output [28:0] ddr_addr,
    output [63:0] ddr_data,
    output [7:0] ddr_be,
    output ddr_we, ddr_rd
);
    wire [61:0] q;
    wire empty, full;
    reg fifo_reset=1'b1;
    always @(posedge mem_clk) fifo_reset<=reset;
    // Same-cycle copy for the head/pop arbitration: fifo_reset itself clears
    // the whole dcfifo (fan-out ~130) and cannot sit next to this logic.
    (* preserve, dont_merge *) reg fifo_reset_pop=1'b1;
    always @(posedge mem_clk) fifo_reset_pop<=reset;
    // Arbitration: a video write takes an idle slot and is then held until the
    // register slice accepts it. Nothing here depends on the HPS wait-request.
    wire slice_busy;
    reg video_hold = 1'b0;
    // The FIFO's combinational empty flag only feeds a one-entry head register;
    // every arbitration decision starts from head_valid (a flop).
    reg head_valid = 1'b0;
    reg [61:0] head_q = '0;
    wire video_cmd = video_hold || (!fifo_reset_pop && head_valid && !mem_we && !mem_rd);
    wire use_video = video_cmd && !slice_busy;
    wire head_open = !head_valid || use_video;
    wire pop_fifo = !fifo_reset_pop && !empty && head_open;
    always @(posedge mem_clk) begin
        if (head_open) head_q <= q;
        if (fifo_reset_pop) head_valid <= 1'b0;
        else if (head_open) head_valid <= !empty;
    end
    always @(posedge mem_clk) video_hold <= !fifo_reset_pop && video_cmd && slice_busy;
    dcfifo #(.lpm_width(62), .lpm_numwords(512), .lpm_widthu(9),
             .lpm_showahead("ON"), .overflow_checking("ON"),
             .underflow_checking("ON"), .use_eab("ON"),
             .rdsync_delaypipe(4), .wrsync_delaypipe(4)) fifo (
        .aclr(fifo_reset), .wrclk(video_clk), .rdclk(mem_clk),
        .data({rot_addr,rot_be[4],rot_data[31:0]}),
        .wrreq(rot_we && !reset && !fifo_reset && !full), .rdreq(pop_fifo),
        .q(q), .rdempty(empty), .wrfull(full)
    );
    assign mem_busy = slice_busy || video_cmd;
    // Avalon register slice toward the HPS port: registered command outputs,
    // registered wait-request upstream, full throughput via a skid register.
    // A presented command is held unchanged while ddr_busy is high.
    localparam CW = 1+1+8+29+64+8;
    reg  [CW-1:0] d_cmd = '0, s_cmd = '0;
    reg d_valid = 1'b0, s_valid = 1'b0;
    assign slice_busy = s_valid;
    wire accept = (video_cmd || mem_we || mem_rd) && !s_valid;
    wire [CW-1:0] video_payload = {1'b1,1'b0,8'd1,head_q[61:33],{2{head_q[31:0]}},head_q[32] ? 8'hf0 : 8'h0f};
    wire [CW-1:0] mem_payload = {mem_we,mem_rd,mem_burst,mem_addr,mem_data,mem_be};
    wire open_slot = !d_valid || !ddr_busy;
    // The HPS wait-request is late and open_slot enables all of d_cmd: four
    // same-cycle d_valid copies give four independent enable LUTs. An open
    // slot loads the offered command unconditionally (d_valid says whether it
    // is real), so the enable no longer includes the arbitration terms.
    (* preserve, dont_merge *) reg [3:0] d_valid_k = 4'b0;
    wire [3:0] open_k = ~d_valid_k | {4{~ddr_busy}};
    (* keep = "true" *) wire take_skid = !fifo_reset && open_slot && s_valid;
    (* keep = "true" *) wire take_video = !fifo_reset && open_slot && !s_valid && video_cmd;
    (* keep = "true" *) wire take_mem = !fifo_reset && open_slot && !s_valid && !video_cmd && (mem_we || mem_rd);
    wire skid_video = !fifo_reset && !open_slot && !s_valid && video_cmd;
    wire skid_mem = !fifo_reset && !open_slot && !s_valid && !video_cmd && (mem_we || mem_rd);
    // Disjoint captures move arbitration in front of the payload gates.
    // Skid priority, accepted edges and held output bytes are unchanged.
    // The HPS wait-request arrives late (hard-block output delay), so it only
    // gates the flop enable; the next command is selected independently of it.
    wire have_next = !fifo_reset && (s_valid || video_cmd || mem_we || mem_rd);
    wire [CW-1:0] next_cmd = s_valid ? s_cmd : video_cmd ? video_payload : mem_payload;
    always @(posedge mem_clk) begin
        for (integer i = 0; i < CW; i = i + 1)
            if (open_k[i/28])
                d_cmd[i] <= next_cmd[i];
        // The skid word is loaded whenever it is free and a command is offered,
        // independent of the HPS wait-request; it only matters while s_valid.
        if (!s_valid && have_next)
            s_cmd <= video_cmd ? video_payload : mem_payload;
    end
    always @(posedge mem_clk) begin
        if (fifo_reset) begin
            d_valid <= 1'b0;
            d_valid_k <= 4'b0;
            s_valid <= 1'b0;
        end else if (!d_valid || !ddr_busy) begin
            if (s_valid) begin
                d_valid <= 1'b1; d_valid_k <= 4'hf; s_valid <= 1'b0;
            end else if (accept) begin
                d_valid <= 1'b1; d_valid_k <= 4'hf;
            end else begin
                d_valid <= 1'b0; d_valid_k <= 4'b0;
            end
        end else if (accept) begin
            s_valid <= 1'b1;
        end
    end
    assign ddr_we    = d_valid && d_cmd[CW-1];
    assign ddr_rd    = d_valid && d_cmd[CW-2];
    assign ddr_burst = d_cmd[CW-3 -: 8];
    assign ddr_addr  = d_cmd[CW-11 -: 29];
    assign ddr_data  = d_cmd[CW-40 -: 64];
    assign ddr_be    = d_cmd[7:0];
`ifndef SYNTHESIS
    always @(posedge video_clk)
        if (rot_we && full && !reset) $fatal(1,"Rotation FIFO overflow");
`endif
endmodule
