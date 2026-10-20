// TMS34020_IO raster contract: sync never disappears once the game has started the raster,
// DPYCTL.ENV never changes the raster geometry, and a total lowered below the live counter wraps promptly.
`timescale 1ps/1ps
module raster_sync_tb;
	import TMS34020_PKG::*;
	localparam int FRAME_PIX = 640 * 257;

	bit CLK = 0;
	always #6250 CLK = ~CLK; // 80 MHz

	bit RST_N = 0;
	bit [2:0] ce_div = 0;
	bit [3:0] pix_div = 0;
	wire CE_R = ce_div == 0;
	wire VCE_R = pix_div == 7;
	always @(posedge CLK) begin
		ce_div <= ce_div == 4 ? 0 : ce_div + 1;
		pix_div <= pix_div + 1;
	end

	bit [12:0] A = 0;
	bit [31:0] DI = 0;
	bit WE = 0;
	wire [31:0] DO, DO_NEXT, SCRREF_ADDR;
	IOReg_t REGS;
	wire INT1_REQ, INT2_REQ, HI_REQ, DI_REQ, WV_REQ, SCRREF_RUN, HS_N, VS_N, HBL_N, VBL_N;

	TMS34020_IO io(.CLK(CLK), .RST_N(RST_N), .EN(1'b1), .CE_F(1'b0), .CE_R(CE_R),
		.RES_N(1'b1), .NMI_N(1'b1), .LINT1_N(1'b1), .LINT2_N(1'b1),
		.A(A), .DI(DI), .DO(DO), .DO_NEXT(DO_NEXT), .WE(WE), .RD(1'b0), .BE(4'hf),
		.REGS(REGS), .INT1_REQ(INT1_REQ), .INT2_REQ(INT2_REQ), .HI_REQ(HI_REQ),
		.DI_REQ(DI_REQ), .WV_REQ(WV_REQ), .SCRREF_ADDR(SCRREF_ADDR), .SCRREF_RUN(SCRREF_RUN),
		.VCE_R(VCE_R), .HS_N(HS_N), .VS_N(VS_N), .HBL_N(HBL_N), .VBL_N(VBL_N),
		.SCRREF_CE_R(CE_R));

	longint pix = 0;
	longint last_vs = -1;
	longint period = 0;
	int vs_edges = 0;
	int hs_edges = 0;
	int de_clocks = 0; // clocks where the picture is not blanked
	bit vs_old = 1, hs_old = 1;
	always @(posedge CLK) begin
		if (VCE_R) pix <= pix + 1;
		vs_old <= VS_N;
		hs_old <= HS_N;
		if (vs_old && !VS_N) begin
			vs_edges <= vs_edges + 1;
			if (last_vs >= 0) period <= pix - last_vs;
			last_vs <= pix;
		end
		if (hs_old && !HS_N) hs_edges <= hs_edges + 1;
		if (HBL_N && VBL_N) de_clocks <= de_clocks + 1;
	end

	task automatic wr(input [12:0] addr, input [31:0] data);
		@(posedge CLK); while (!CE_R) @(posedge CLK);
		A <= addr; DI <= data; WE <= 1;
		@(posedge CLK); while (!CE_R) @(posedge CLK);
		WE <= 0;
	endtask

	task automatic run_pix(input longint n);
		longint target = pix + n;
		while (pix < target) @(posedge CLK);
	endtask

	task automatic expect_frames(input string what, input int frames);
		int base = vs_edges;
		longint limit = pix + longint'(frames + 2) * FRAME_PIX;
		while (vs_edges < base + frames + 1 && pix < limit) @(posedge CLK);
		if (vs_edges < base + frames + 1) $fatal(1, "FAIL %s: sync stopped (vs edges %0d of %0d)", what, vs_edges - base, frames + 1);
		if (period != FRAME_PIX) $fatal(1, "FAIL %s: frame period %0d pixels, expected %0d", what, period, FRAME_PIX);
		$display("ok  %s: %0d frames at %0d pixels", what, frames, period);
	endtask

	initial begin
		int before_edges, before_de;
		repeat (20) @(posedge CLK);
		RST_N = 1;
		run_pix(5000);
		if (vs_edges != 0 || hs_edges != 0 || !VS_N || !HS_N) $fatal(1, "FAIL unprogrammed raster emits sync");
		$display("ok  no sync before the raster is programmed");

		wr(13'h0000, {16'h0020, 16'h0006});
		wr(13'h0020, {16'h0060, 16'h0018});
		wr(13'h0040, {16'h0260, 16'h00f8});
		wr(13'h0060, {16'h027f, 16'h0100});
		run_pix(3000);
		if (vs_edges != 0) $fatal(1, "FAIL raster started before DPYCTL.ENV");
		wr(13'h0080, {16'h0000, 16'hd00f});
		expect_frames("ENV on", 3);
		before_de = de_clocks; run_pix(FRAME_PIX);
		if (de_clocks == before_de) $fatal(1, "FAIL no active picture with ENV on");

		wr(13'h0080, {16'h0000, 16'h500f});
		run_pix(2000);
		before_de = de_clocks;
		expect_frames("ENV off keeps sync", 3);
		if (de_clocks == before_de) $fatal(1, "FAIL display geometry changed while ENV is off");
		$display("ok  display geometry unchanged while ENV is off (colour is blanked in BT)");

		wr(13'h0080, {16'h0000, 16'hd00f});
		run_pix(2000);
		expect_frames("ENV back on", 3);
		before_de = de_clocks; run_pix(FRAME_PIX);
		if (de_clocks == before_de) $fatal(1, "FAIL picture did not return after ENV on");

		// Lower VTOTAL below the live VCOUNT: the next frame boundary must come within two lines.
		while (REGS.VCOUNT < 16'd200) @(posedge CLK);
		before_edges = vs_edges;
		wr(13'h0060, {16'h027f, 16'h0080});
		run_pix(2 * 640 + 64);
		if (vs_edges == before_edges) $fatal(1, "FAIL VTOTAL below live count: no frame wrap (VCOUNT=%0d)", REGS.VCOUNT);
		$display("ok  lowered VTOTAL wraps within two lines");
		wr(13'h0060, {16'h027f, 16'h0100});
		run_pix(2 * FRAME_PIX);
		expect_frames("restored VTOTAL", 2);

		// Lower HTOTAL below the live HCOUNT likewise.
		while (REGS.HCOUNT < 16'd500) @(posedge CLK);
		before_edges = hs_edges;
		wr(13'h0060, {16'h0100, 16'h0100});
		run_pix(300);
		if (hs_edges == before_edges) $fatal(1, "FAIL HTOTAL below live count: no line wrap (HCOUNT=%0d)", REGS.HCOUNT);
		$display("ok  lowered HTOTAL wraps");
		$display("PASS raster sync contract");
		$finish;
	end

	initial begin #2000000000000; $fatal(1, "FAIL timeout"); end
endmodule
