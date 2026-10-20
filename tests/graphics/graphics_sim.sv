module BT_GRAPHICS_SIM (
    input logic CLK, CLK2X, RST_N, CE_F, CE_R, VCE_R,
    input logic [31:0] BUS_ADDR, BUS_DATA, BUS_BIT_ADDR,
    input logic BUS_RAS_N, BUS_WE_N, BUS_QE_N,
    input logic [3:0] BUS_CAS_N,
    input logic [31:0] EQ,
    input logic ERDY,
    input logic [63:0] ESQ,
    input logic ESTE,
    output logic [17:0] ESADDR,
    output logic ESWR, ESRD,
    output logic [63:0] ESDATA,
    output logic [22:0] EADDR,
    output logic [31:0] EDATA,
    output logic [3:0] EWE,
    output logic ERD, EFG,
    output logic [31:0] BUS_Q,
    output logic BUS_READY,
    output logic [7:0] PIXEL,
    output logic [23:0] RGB,
    output logic [111:0] REG_STATE,
    output logic SCAN_READY,
    output logic [15:0] BG0_PAIR,BG1_PAIR,
    input logic [1:0] TEST_MODE,
    input logic [7:0] TEST_SPR,TEST_BG0,TEST_BG1,
    output logic [7:0] TEST_PIXEL
);
    BT dut (
        .CLK(CLK), .CLK2X(CLK2X), .RST_N(RST_N), .EN(1'b1),
        .CE_F(CE_F), .CE_R(CE_R), .VCE_R(VCE_R),
        .SCE_F(1'b0), .SCE_R(1'b0), .SERVICE(1'b1),
        .EQ(EQ),.NVRAM_Q(EQ), .FG_DDR_Q(EQ), .ERDY(ERDY), .ESQ(ESQ), .ESTE(ESTE), .SRDY(ERDY),
        .ESADDR(ESADDR), .ESDATA(ESDATA), .ESWR(ESWR), .ESRD(ESRD),
        .EADDR(EADDR), .EDATA(EDATA), .EWE(EWE), .ERD(ERD), .EFG(EFG),
        .BSMT_ROM_DI(8'h00), .SW1(8'h7c),
        .P1(8'hff), .P2(8'hff), .P3(8'hff),
        .BG_EN(3'b111), .GRID_EN(3'b000)
    );
    assign BUS_Q = dut.LDI;
    assign BUS_READY = dut.LRDY;
    assign PIXEL = dut.PIX_OUT;
    assign RGB = {dut.R,dut.G,dut.B};
    assign REG_STATE = {dut.MISC_CONTROL,dut.SCROLL1,dut.SCROLL0,
        dut.DISP_CONTROL,dut.SPR_CONTROL,dut.SPR_SCALE1,dut.SPR_SCALE0};
    assign SCAN_READY = dut.FG0_RDY && dut.FG1_RDY;
    assign BG0_PAIR = dut.BG0_SQ;
    assign BG1_PAIR = dut.BG1_SQ;
    BT_MIXER_PROBE mixer_probe (
        .CLK(CLK), .RST_N(RST_N), .VCE_DIV(1'b0), .HBL_N(1'b1),
        .DISP_CONTROL({6'b0,TEST_MODE,8'b0}), .BG_EN(3'b111),
        .FG0_SQ(TEST_SPR), .FG1_SQ(TEST_SPR),
        .BG0_SQ({TEST_BG0,TEST_BG0}), .BG1_SQ({TEST_BG1,TEST_BG1}),
        .PIX_OUT(TEST_PIXEL)
    );
endmodule

// This test deliberately substitutes CPU bus stimulus. It verifies the shipping
// graphics modules, not CPU execution or native whole-system frame equivalence.
module TMS34020 (
    input CLK, RST_N, EN, CE_F, CE_R, RES_N, NMI_N, LINT1_N, LINT2_N,
    input [31:0] LDI, LDI_CACHE_LATE,
    input LDI_CACHE_MEM, LDI_CACHE_DDR, LDI_CACHE_DDR_BYTES,
    input [31:0] LDI_CACHE_DDR_DATA, LDI_CACHE_RAM_DATA,
    input LRDY, VCE_R,
    output [31:0] LA, LDO, BIT_ADDR,
    output RAS_N, WE_N, QE_N, RD_EXT, ALTCH_N, HS_N, VS_N, HBL_N, VBL_N,
    output [3:0] CAS_N,
	output WRITE_ANY_ALL,
	output WRITE_ANY_FG
);
 assign WRITE_ANY_ALL = !WE_N && (|~CAS_N);
 assign WRITE_ANY_FG = !WE_N && (|(~CAS_N & 4'b0101));

    assign LA = BT_GRAPHICS_SIM.BUS_ADDR;
    assign RD_EXT = !BT_GRAPHICS_SIM.BUS_QE_N;
    assign LDO = BT_GRAPHICS_SIM.BUS_DATA;
    assign BIT_ADDR = BT_GRAPHICS_SIM.BUS_BIT_ADDR;
    assign RAS_N = BT_GRAPHICS_SIM.BUS_RAS_N;
    assign WE_N = BT_GRAPHICS_SIM.BUS_WE_N;
    assign QE_N = BT_GRAPHICS_SIM.BUS_QE_N;
    assign CAS_N = BT_GRAPHICS_SIM.BUS_CAS_N;
    assign {ALTCH_N, HS_N, VS_N, HBL_N, VBL_N} = 5'b11111;
endmodule
