// Intel's output clock primitive only. Memory command FSMs use the real RTL.
module altddio_out #(
    parameter extend_oe_disable = "OFF", intended_device_family = "Cyclone V",
    invert_output = "OFF", lpm_hint = "UNUSED", lpm_type = "altddio_out",
    oe_reg = "UNREGISTERED", power_up_high = "OFF", parameter width = 1
)(
    input [width-1:0] datain_h, datain_l,
    input outclock, aclr, aset, oe, outclocken, sclr, sset,
    output [width-1:0] dataout
);
    assign dataout = outclock ? datain_h : datain_l;
endmodule
