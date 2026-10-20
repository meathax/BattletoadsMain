`timescale 1ns/1ps
module audio_ram_tb;
    reg clock = 0;
    always #5 clock = !clock;
    reg [14:0] load_addr = 0;
    reg [15:0] load_data = 0;
    reg load_we = 0;
    reg [15:0] cpu_addr = 0;
    reg [7:0] cpu_data = 0;
    reg cpu_we = 0;
    wire [7:0] cpu_q;
    bt_audio_ram dut(.*);
    function automatic [7:0] pattern(input integer address);
        pattern = address ^ (address >> 8) ^ (address >> 5);
    endfunction
    task automatic check_byte(input integer address, input [7:0] expected);
        reg [7:0] previous;
        @(negedge clock);
        previous = cpu_q;
        cpu_addr = address;
        #1;
        if (cpu_q !== previous) $fatal(1, "asynchronous CPU output change");
        @(posedge clock); #1;
        if (cpu_q !== expected)
            $fatal(1, "audio address=%h actual=%h expected=%h", address, cpu_q, expected);
    endtask
    integer address;
    initial begin
        for (address = 0; address < 65536; address = address + 1)
            check_byte(address, 0);
        // Shipping ROM fills the lower 32 KiB; upper RAM starts at zero.
        for (address = 0; address < 16384; address = address + 1) begin
            @(negedge clock);
            load_addr = address;
            load_data = {pattern(address*2+1), pattern(address*2)};
            load_we = 1;
            @(posedge clock); #1;
        end
        @(negedge clock); load_we = 0;
        for (address = 32768; address < 65536; address = address + 1) begin
            @(negedge clock);
            cpu_addr = address;
            cpu_data = pattern(address);
            cpu_we = 1;
            @(posedge clock); #1;
        end
        @(negedge clock); cpu_we = 0;
        for (address = 0; address < 65536; address = address + 1)
            check_byte(address, pattern(address));
        // Both write owners can address either bank; the loader wins conflicts.
        @(negedge clock);
        load_addr = 32767; load_data = 16'h1234; load_we = 1;
        cpu_addr = 0; cpu_data = 8'hfe; cpu_we = 1;
        @(posedge clock); #1;
        @(negedge clock); load_we = 0; cpu_we = 0;
        check_byte(65534, 8'h34); check_byte(65535, 8'h12);
        check_byte(0, pattern(0));
        @(negedge clock); cpu_addr = 32767; cpu_data = 8'hca; cpu_we = 1;
        @(posedge clock); #1;
        @(negedge clock); cpu_we = 0;
        check_byte(32767, 8'hca); check_byte(32766, pattern(32766));
        $display("PASS 65536 initialized bytes, 32768 ROM bytes, 32768 CPU-written bytes, both byte lanes and registered reads");
        $display("PASS both bank boundaries, both write owners and loader priority");
        $finish;
    end
endmodule
