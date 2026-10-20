// Shipping graphics, real TMS34020 video timing and the actual MiSTer input
// pixel enable. CPU transactions are supplied by the host for static replay.
module BT_RASTER_SIM (
    input CLK,CLK2X,RST_N,
    input [31:0] BUS_ADDR,BUS_BIT_ADDR,BUS_DATA,
    input BUS_RAS_N,BUS_WE_N,BUS_QE_N,
    input [3:0] BUS_CAS_N,
    input [12:0] IO_A,input [31:0] IO_DI,input IO_WE,
    output [23:0] RGB,output HBL_N,VBL_N,
    output MIX_CE,output PIXEL_CE,
    output [31:0] REF_ADDR,output REF_RUN,
    output [15:0] VCOUNT,HCOUNT,output READY
);
    wire CE_F,CE_R,VCE_R;
    wire CLK_VIDEO=CLK;
    bt_clock_enables enables(.clk(CLK),.reset(!RST_N),.ce_f(CE_F),.ce_r(CE_R),.vce(VCE_R));
    assign PIXEL_CE=VCE_R;
    `include "mixer_enable.svh"
    wire VIDEO_HBL_N,VIDEO_VBL_N,VIDEO_HS_N,VIDEO_VS_N;
    TMS34020_PKG::IOReg_t regs;
    TMS34020_IO video_io(.CLK(CLK),.RST_N(RST_N),.EN(1'b1),.CE_F(CE_F),.CE_R(CE_R),
        .RES_N(1'b1),.NMI_N(1'b1),.LINT1_N(1'b1),.LINT2_N(1'b1),
        .A(IO_A),.DI(IO_DI),.DO(),.WE(IO_WE),.RD(1'b0),.BE(4'b1111),.REGS(regs),
        .INT1_REQ(),.INT2_REQ(),.HI_REQ(),.DI_REQ(),.WV_REQ(),
        .SCRREF_ADDR(REF_ADDR),.SCRREF_RUN(REF_RUN),.VCE_R(VCE_R),
        .HS_N(VIDEO_HS_N),.VS_N(VIDEO_VS_N),.HBL_N(VIDEO_HBL_N),.VBL_N(VIDEO_VBL_N));
    assign VCOUNT=regs.VCOUNT;
    assign HCOUNT=regs.HCOUNT;
    wire [7:0] r,g,b;
    BT dut(.CLK(CLK),.CLK2X(CLK2X),.RST_N(RST_N),.EN(1'b1),
        .CE_F(CE_F),.CE_R(CE_R),.VCE_R(VCE_R),.SCE_F(1'b0),.SCE_R(1'b0),.SERVICE(1'b1),
        .EQ(32'b0),.NVRAM_Q(32'b0),.FG_DDR_Q(32'b0),.ERDY(1'b1),.ESQ(64'b0),.ESTE(1'b0),.SRDY(1'b1),
        .BSMT_ROM_DI(8'b0),.SW1(8'hf0),.P1(8'hff),.P2(8'hff),.P3(8'hff),
        .R(r),.G(g),.B(b),.HS_N(),.VS_N(),.HBL_N(HBL_N),.VBL_N(VBL_N),
        .BG_EN(3'b111),.GRID_EN(3'b000));
    assign RGB={r,g,b};
    assign READY=dut.LRDY;
endmodule

module TMS34020 (
    input CLK,RST_N,EN,CE_F,CE_R,RES_N,NMI_N,LINT1_N,LINT2_N,
    input [31:0] LDI,input LRDY,VCE_R,
    output [31:0] LA,LDO,BIT_ADDR,
    output RAS_N,WE_N,QE_N,RD_EXT,ALTCH_N,HS_N,VS_N,HBL_N,VBL_N,
    output [3:0] CAS_N
);
    assign LA=BT_RASTER_SIM.BUS_ADDR;
    assign RD_EXT=!BT_RASTER_SIM.BUS_QE_N;
    assign LDO=BT_RASTER_SIM.BUS_DATA;
    assign BIT_ADDR=BT_RASTER_SIM.BUS_BIT_ADDR;
    assign RAS_N=BT_RASTER_SIM.BUS_RAS_N;
    assign WE_N=BT_RASTER_SIM.BUS_WE_N;
    assign QE_N=BT_RASTER_SIM.BUS_QE_N;
    assign CAS_N=BT_RASTER_SIM.BUS_CAS_N;
    assign ALTCH_N=1;
    assign HS_N=BT_RASTER_SIM.VIDEO_HS_N;
    assign VS_N=BT_RASTER_SIM.VIDEO_VS_N;
    assign HBL_N=BT_RASTER_SIM.VIDEO_HBL_N;
    assign VBL_N=BT_RASTER_SIM.VIDEO_VBL_N;
endmodule
