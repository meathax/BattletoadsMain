`timescale 1ns/1ps
module foreground_clear_tb;
    reg clk=0;
    always #5 clk=!clk;
    reg init_n=0;
    reg io_busy=1;
    wire [27:1] io_addr;
    wire [3:0] io_we;
    wire ready;
    integer accepted=0, completed=0, delay=7, runs=0;
    reg pending=0;
    reg [27:1] pending_addr;
    bt_fg_ddr_clear dut(.*);
    always @(posedge clk) begin
        if (io_we) begin
            if (io_busy || pending) $fatal(1,"overlapping clear writes");
            if (io_we!=4'hf) $fatal(1,"wrong clear byte mask");
            if ({io_addr,1'b0} !== (28'h2000000 |
                (((accepted/384)*512 + 128 + (accepted%384))*4)))
                $fatal(1,"wrong page/row/column at pair %0d address=%h",accepted,{io_addr,1'b0});
            accepted=accepted+1;
            pending_addr=io_addr;
            pending=1;
            delay=2+(accepted%11);
            io_busy<=1;
        end else if (pending) begin
            if (io_addr!==pending_addr) $fatal(1,"address changed while write pending");
            if (delay==0) begin
                completed=completed+1;
                pending=0;
                io_busy<=0;
            end else delay=delay-1;
        end else if (io_busy) begin
            if (delay==0) io_busy<=0;
            else delay=delay-1;
        end
        #1;
        if (ready && (completed!=196608 || pending))
            $fatal(1,"CPU released before final clear write completed");
    end
    initial begin
        repeat(4) @(negedge clk);
        init_n=1;
        wait(ready);
        repeat(16) @(negedge clk);
        if (accepted!=196608) $fatal(1,"missing or repeated writes");
        init_n=0;
        accepted=0; completed=0; io_busy=1; delay=7;
        repeat(4) @(negedge clk);
        init_n=1;
        wait(ready);
        repeat(16) @(negedge clk);
        if (accepted!=196608) $fatal(1,"new ROM did not restart initialization");
        $display("PASS two complete foreground clear passes, 393216 stalled writes, visible-column exclusion, page/row boundaries and final-write readiness");
        $finish;
    end
    initial begin #100000000; $fatal(1,"clear watchdog"); end
endmodule
