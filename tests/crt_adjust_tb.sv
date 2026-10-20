// Battletoads CRT Adjust bench: 80 MHz clock, 10 MHz pixels, 640x257 raster,
// HS 0..31, active 96..607 x 24..247 (MAME-measured TMS34020 program).
// Checks Off passthrough, On sizes 0/-1/-2 (512 px per line, centred, read
// period 8/7/6), H-Position and V-Shift; writes PPM frames per case.
`timescale 1ns/1ps
module crt_adjust_tb;
	reg clk = 0;
	always #6.25 clk = ~clk;
	reg [2:0] slot = 0;
	reg ce = 0;
	reg [9:0] hc = 0;
	reg [8:0] vc = 0;
	always @(posedge clk) begin
		slot <= slot + 3'd1;
		ce <= slot == 3'd7;
		if (ce) begin
			if (hc == 639) begin hc <= 0; vc <= (vc == 256) ? 9'd0 : vc + 9'd1; end
			else hc <= hc + 10'd1;
		end
	end
	wire hs = hc < 32, hb = !(hc >= 96 && hc < 608);
	wire vs = vc < 3,  vb = !(vc >= 24 && vc < 248);
	wire [9:0] ax = hc - 10'd96;
	wire [8:0] ay = vc - 9'd24;
	// Distinct pattern: border, grid and a gradient keep every column unique.
	wire [7:0] r = hb || vb ? 8'd0 : (ax == 0 || ax == 511 || ay == 0 || ay == 223) ? 8'hff : ax[8:1];
	wire [7:0] g = hb || vb ? 8'd0 : (ax[5:0] == 0 || ay[4:0] == 0) ? 8'hc0 : ay[7:0];
	wire [7:0] b = hb || vb ? 8'd0 : {ax[0], 7'h40};

	reg available = 1, enable = 0;
	reg [1:0] hsize = 0;
	reg signed [6:0] hpos = 0;
	reg signed [4:0] vpos = 0;
	wire oce; wire [7:0] orr, og, ob; wire ohs, ovs, ohb, ovb;
	bt_crt_adjust dut(.clk(clk), .available(available), .enable(enable),
		.hsize_sel(hsize), .hposition(hpos), .vposition(vpos),
		.ce_in(ce), .r_in(r), .g_in(g), .b_in(b),
		.hs_in(hs), .vs_in(vs), .hb_in(hb), .vb_in(vb),
		.ce_out(oce), .r_out(orr), .g_out(og), .b_out(ob),
		.hs_out(ohs), .vs_out(ovs), .hb_out(ohb), .vb_out(ovb));

	// Output measurement in 80 MHz clocks relative to the output HS rise.
	integer clk_in_line = 0, first_de = -1, last_de = -1, de_count = 0, period = 0, last_ce = 0;
	integer vs_line = 0, line = 0, first_de_line = -1, ohs_old = 0, ovs_old = 0, errors = 0;
	integer mismatches = 0, captured = 0;
	reg capture = 0;
	reg [23:0] frame [0:239][0:767];
	integer fx = 0, fy = 0;
	always @(posedge clk) begin
		clk_in_line <= clk_in_line + 1;
		ohs_old <= ohs; ovs_old <= ovs;
		if (ohs && !ohs_old) begin
			clk_in_line <= 0; line <= line + 1; fx <= 0;
			if (capture && fx > 0) fy <= fy + 1;
		end
		if (ovs && !ovs_old) begin line <= 0; first_de_line <= -1; fy <= 0; end
		if (oce) begin
			if (last_ce > 0) period <= clk_in_line - last_ce;
			last_ce <= clk_in_line;
			if (!ohb && !ovb) begin
				if (first_de_line < 0) first_de_line <= line;
				if (capture && fy < 240 && fx < 768) frame[fy][fx] <= {orr, og, ob};
				fx <= fx + 1;
			end
		end
	end

	task automatic measure_line(output integer first, output integer last, output integer count, output integer per);
		integer t; reg in_line;
		begin
			first = -1; last = -1; count = 0; per = 0; t = 0;
			@(posedge ohs);
			repeat (2) @(posedge clk);
			in_line = 1;
			while (in_line) begin
				@(posedge clk); t = t + 1;
				if (ohs && !ohs_old && t > 300) in_line = 0;
				if (oce && !ohb) begin
					if (first < 0) first = t; else if (per == 0) per = t - first;
					last = t; count = count + 1;
				end
			end
		end
	endtask

	task automatic write_ppm(input string name);
		integer f, x, y;
		begin
			f = $fopen(name, "w");
			$fwrite(f, "P3\n768 240\n255\n");
			for (y = 0; y < 240; y++) for (x = 0; x < 768; x++)
				$fwrite(f, "%0d %0d %0d\n", frame[y][x][23:16], frame[y][x][15:8], frame[y][x][7:0]);
			$fclose(f);
		end
	endtask

	task automatic run_case(input string name, input bit en, input [1:0] hs_sel, input integer hp, input integer vp,
	                        input integer exp_period, input integer exp_centre, input integer tol);
		integer first, last, count, per, centre, f, x, y, l0;
		begin
			enable = en; hsize = hs_sel; hpos = 7'(hp); vpos = 5'(vp);
			repeat (3) @(posedge vb);           // settings latch + settle
			@(posedge ovs); capture = 1;
			repeat (100) @(posedge ohs);
			measure_line(first, last, count, per);
			l0 = first_de_line;
			@(posedge ovs); capture = 0;
			write_ppm({"build/crt_adjust_tb/", name, ".ppm"});
			centre = (first + last + per) / 2;
			$display("%s: pixels=%0d period=%0d first=%0d last=%0d centre=%0d first_active_line=%0d",
				name, count, per, first, last, centre, l0);
			if (count != 512) begin $display("FAIL %s pixel count %0d", name, count); errors++; end
			if (per != exp_period) begin $display("FAIL %s period %0d", name, per); errors++; end
			if (centre < exp_centre - tol || centre > exp_centre + tol) begin
				$display("FAIL %s centre %0d expected %0d+-%0d", name, centre, exp_centre, tol); errors++; end
			if (last + per > 5120) begin $display("FAIL %s window overruns line", name); errors++; end
		end
	endtask

	integer off_first_line, on_first_line;
	initial begin
		$system("mkdir -p build/crt_adjust_tb");
		repeat (5) @(posedge vb);
		// Native centre: (96+256)*8 = 2816 clocks after HS rise (+ pipeline).
		run_case("off",          0, 0,   0,  0, 8, 2816, 24);
		off_first_line = first_de_line;
		run_case("on_size0",     1, 0,   0,  0, 8, 2816, 24);
		on_first_line = first_de_line;
		run_case("on_size_m1",   1, 1,   0,  0, 7, 2816, 24);
		run_case("on_size_m2",   1, 2,   0,  0, 6, 2816, 24);
		run_case("on_hpos_p15",  1, 0,  15,  0, 8, 2816+15*8, 24);
		run_case("on_hpos_m16",  1, 0, -16,  0, 8, 2816-16*8, 24);
		run_case("on_m2_hpos_p15", 1, 2, 15, 0, 6, 2816+15*6, 24);
		run_case("on_vshift_p8", 1, 0,   0,  8, 8, 2816, 24);
		if (first_de_line == on_first_line) begin $display("FAIL V-Shift had no effect"); errors++; end
		run_case("on_vshift_m8", 1, 0,   0, -8, 8, 2816, 24);
		available = 0;
		run_case("unavailable",  1, 2,   0,  0, 8, 2816, 24);
		$display("first active output line: off=%0d on=%0d", off_first_line, on_first_line);
		if (errors == 0) $display("PASS bt_crt_adjust all cases");
		else $display("FAIL bt_crt_adjust errors=%0d", errors);
		$finish;
	end
	initial begin #3000ms; $display("FAIL timeout"); $finish; end
endmodule
