// Operand-select predecode equivalence: every opcode x state x flag profile.
// HEAD = committed TMS34020_ID (module renamed TMS34020_ID_HEAD by the runner).
// N0 decodes (IC,STATE) with flags tied off; N1 forwards the N0 result
// through the registered-select path (OPSEL_REG=1). DECI must match HEAD exactly.
`timescale 1ns/1ps
module tms_opsel_equiv_tb;
	import TMS34020_PKG::*;
	bit [15:0] ic;
	bit [4:0]  st;
	bit [19:0] fl;
	wire [31:0] st_oh = 32'b1 << st;
	ICMatches_t icm;
	bit [3:0] rs;
	ICRFAddress_t rf0, rf1;
	always_comb begin
		icm = DecodeICMatches(ic);
		rs = DecodeICRS(ic);
		rf0 = DecodeICRFAddress(ic,st,1'b0);
		rf1 = DecodeICRFAddress(ic,st,1'b1);
	end
	DecInstr_t head, new0, new1;
	OpSel_t sel_flagless, sel_comb1;
	TMS34020_ID_HEAD H(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b1),.CE_R(1'b1),
		.IC(ic),.IC_MATCHES(icm),.IC_RS_STATIC(rs),.IC_RF_ADDR(rf0),.IC_RF_ADDR_POS(rf1),
		.STATE(st),.STATE_OH(st_oh),
		.MD_COND(fl[0]),.MD_NEG(fl[1]),.DIV_V(fl[2]),.J_COND(fl[3]),.DS_COND(fl[4]),.MM_COND(fl[5]),
		.FE0(fl[6]),.FE1(fl[7]),.RP_COND(fl[8]),.LINE_GZ(fl[9]),.LINE_COND(fl[10]),
		.PIX_XEND(fl[11]),.PIX_YEND(fl[12]),.PIX_WINEN(fl[13]),.PIX_WINCC(fl[17:14]),.PIX_BL(fl[18]),.PIX_WE(fl[19]),
		.DECI(head),.DECI_AT_PRE());
	// flagless decoder (what the CPU's next-value decoders are)
	TMS34020_ID #(.OPSEL_REG(1'b0)) N0(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b1),.CE_R(1'b1),
		.IC(ic),.IC_MATCHES(icm),.IC_RS_STATIC(rs),.IC_RF_ADDR('0),.IC_RF_ADDR_POS('0),.OPSEL('0),.OPSEL_COMB(sel_flagless),
		.STATE(st),.STATE_OH(st_oh),
		.MD_COND(1'b0),.MD_NEG(1'b0),.DIV_V(1'b0),.J_COND(1'b0),.DS_COND(1'b0),.MM_COND(1'b0),
		.FE0(1'b0),.FE1(1'b0),.RP_COND(1'b0),.LINE_GZ(1'b0),.LINE_COND(1'b0),
		.PIX_XEND(1'b0),.PIX_YEND(1'b0),.PIX_WINEN(1'b0),.PIX_WINCC(4'b0),.PIX_BL(1'b0),.PIX_WE(1'b0),
		.DECI(new0),.DECI_AT_PRE());
	// production ID with registered select taken from the flagless decode
	TMS34020_ID #(.OPSEL_REG(1'b1)) N1(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b1),.CE_R(1'b1),
		.IC(ic),.IC_MATCHES(icm),.IC_RS_STATIC(rs),.IC_RF_ADDR(rf0),.IC_RF_ADDR_POS(rf1),.OPSEL(sel_flagless),.OPSEL_COMB(sel_comb1),
		.STATE(st),.STATE_OH(st_oh),
		.MD_COND(fl[0]),.MD_NEG(fl[1]),.DIV_V(fl[2]),.J_COND(fl[3]),.DS_COND(fl[4]),.MM_COND(fl[5]),
		.FE0(fl[6]),.FE1(fl[7]),.RP_COND(fl[8]),.LINE_GZ(fl[9]),.LINE_COND(fl[10]),
		.PIX_XEND(fl[11]),.PIX_YEND(fl[12]),.PIX_WINEN(fl[13]),.PIX_WINCC(fl[17:14]),.PIX_BL(fl[18]),.PIX_WE(fl[19]),
		.DECI(new1),.DECI_AT_PRE());
	integer errors = 0, checks = 0, p, i, s;
	bit [19:0] profiles [0:11];
	OpSel_t head_sel;
	always_comb head_sel = {head.AIA,head.AIB,head.SHC,head.F,head.MC.AS,head.MC.DS};
	task show_const(input [15:0] icv);
		begin
			ic = icv; st = 0; fl = 0; #1;
			$display("OPSEL const ic=%h state=0 : %0d'h%h", icv, $bits(OpSel_t), sel_flagless);
		end
	endtask
	initial begin
		profiles[0]=20'h00000; profiles[1]=20'hFFFFF; profiles[2]=20'hAAAAA; profiles[3]=20'h55555;
		profiles[4]=20'h12345; profiles[5]=20'hEDCBA; profiles[6]=20'h0F0F0; profiles[7]=20'hF0F0F;
		profiles[8]=20'h33333; profiles[9]=20'hCCCCC; profiles[10]=20'h80001; profiles[11]=20'h7FFFE;
		show_const(16'h0900);
		show_const(16'h090A);
		for (i=0;i<65536;i++) begin
			for (s=0;s<32;s++) begin
				for (p=0;p<12;p++) begin
					ic = i[15:0]; st = s[4:0]; fl = profiles[p]; #1;
					checks++;
					if (head !== new1 || sel_flagless !== sel_comb1 || sel_flagless !== head_sel) begin
						errors++;
						if (errors < 20) $display("MISMATCH ic=%h st=%0d fl=%h", ic, st, fl);
					end
				end
			end
		end
		$display("opsel equivalence: checks=%0d errors=%0d", checks, errors);
		if (errors) $fatal(1,"opsel equivalence FAILED");
		$finish;
	end
endmodule
