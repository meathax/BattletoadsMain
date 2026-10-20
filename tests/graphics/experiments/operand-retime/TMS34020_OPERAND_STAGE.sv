import TMS34020_PKG::*;
// Retiming of the existing operand register: capture the complete input tuple
// before extension. Q still represents the same tuple from the previous SYS
// edge, including pixel bypass, field selection, and asynchronous reset.
module TMS34020_OPERAND_STAGE (
    input CLK, RST_N,
    input bit [31:0] RAW, PIX_VALUE,
    input bit [5:0] FIELD0, FIELD1,
    input bit FIELD_SELECT, PIX_SELECT,
    input bit [1:0] EXTEND_OP,
    output bit [31:0] Q
);
    bit [31:0] raw_q, pixel_q;
    bit [5:0] field0_q, field1_q;
    bit field_select_q, pixel_select_q;
    bit [1:0] extend_q;
    (* keep = "true" *) wire [31:0] extended0 = Ext(raw_q,field0_q,extend_q);
    (* keep = "true" *) wire [31:0] extended1 = Ext(raw_q,field1_q,extend_q);
    always @(posedge CLK or negedge RST_N) begin
        if (!RST_N) begin
            raw_q <= 0; pixel_q <= 0;
            field0_q <= 0; field1_q <= 0;
            field_select_q <= 0; pixel_select_q <= 0; extend_q <= EO_NONE;
        end else begin
            raw_q <= RAW; pixel_q <= PIX_VALUE;
            field0_q <= FIELD0; field1_q <= FIELD1;
            field_select_q <= FIELD_SELECT; pixel_select_q <= PIX_SELECT;
            extend_q <= EXTEND_OP;
        end
    end
    always_comb Q = pixel_select_q ? pixel_q : (field_select_q ? extended1 : extended0);
endmodule
