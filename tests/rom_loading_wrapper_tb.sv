`timescale 1ns/1ps
// ROM stream through the release wrapper DDR path: ddram -> bt_video_ddr -> HPS DDR.
// Regression for main-CPU ROM writes silently dropped by a reset command slice.
module rom_loading_wrapper_tb;
    localparam SIZE = 'ha08000;
    reg clk = 0, memclk = 0;
    always #10 clk = ~clk;
    always #5 memclk = ~memclk;
    reg ioctl_download = 0, ioctl_wr = 0;
    reg [15:0] ioctl_index = 0, ioctl_dout = 0;
    reg [26:0] ioctl_addr = 0;
    wire ioctl_wait, downloading, ready, ddr_busy, sdr_busy;
    wire [27:1] ddr_addr;
    wire [3:0] ddr_we;
    wire [24:0] sample_addr;
    wire [14:0] audio_addr;
    wire sample_we, audio_we;
    wire [15:0] data;
    wire reset = downloading || !ready;
    bt_rom_loader loader(.*);

    wire [28:0] DDRAM_ADDR;
    wire [7:0] DDRAM_BURSTCNT, DDRAM_BE;
    wire [63:0] DDRAM_DIN;
    reg [63:0] DDRAM_DOUT = 0;
    reg DDRAM_DOUT_READY = 0;
    wire DDRAM_RD, DDRAM_WE;
    wire [28:0] mem_addr; wire [7:0] mem_burst, mem_be; wire [63:0] mem_data;
    wire mem_rd, mem_we, mem_busy;
    integer ticks = 0;
    wire DDRAM_BUSY = ticks % 17 < 6;
    reg [27:1] cpu_addr = 0;
    reg cpu_rd = 0;
    wire [31:0] cpu_data;
    wire cpu_busy;
    ddram dram(
        .DDRAM_CLK(), .DDRAM_BUSY(mem_busy), .DDRAM_BURSTCNT(mem_burst),
        .DDRAM_ADDR(mem_addr), .DDRAM_DOUT(DDRAM_DOUT),
        .DDRAM_DOUT_READY(DDRAM_DOUT_READY), .DDRAM_RD(mem_rd),
        .DDRAM_DIN(mem_data), .DDRAM_BE(mem_be), .DDRAM_WE(mem_we),
        .clk(memclk), .rst(reset), .io_addr(ddr_addr), .io_dout(),
        .io_din({2{data}}), .io_rd(1'b0), .io_we(ddr_we), .io_busy(ddr_busy),
        .sclk(1'b1), .addr(cpu_addr), .dout(cpu_data), .din(32'd0),
        .rd(cpu_rd), .we(4'd0), .cache(2'd0), .busy(cpu_busy),
        .baddr(27'd0), .bin(64'd0), .bout(), .bwr(1'b0), .brd(1'b0),
        .ba(), .bte(), .dbg_din()
    );
    bt_video_ddr video_ddr(
        .reset(1'b0), .video_clk(clk), .mem_clk(memclk),
        .rot_we(1'b0), .rot_addr(29'd0), .rot_data(64'd0), .rot_be(8'd0),
        .mem_burst(mem_burst), .mem_addr(mem_addr), .mem_data(mem_data), .mem_be(mem_be),
        .mem_we(mem_we), .mem_rd(mem_rd), .ddr_busy(DDRAM_BUSY), .mem_busy(mem_busy),
        .ddr_burst(DDRAM_BURSTCNT), .ddr_addr(DDRAM_ADDR), .ddr_data(DDRAM_DIN),
        .ddr_be(DDRAM_BE), .ddr_we(DDRAM_WE), .ddr_rd(DDRAM_RD));
    wire [12:0] SDRAM_A;
    wire [1:0] SDRAM_BA;
    tri [15:0] SDRAM_DQ;
    wire SDRAM_nRAS, SDRAM_nCAS, SDRAM_nWE;
    sdram samples(
        .SDRAM_DQ(SDRAM_DQ), .SDRAM_A(SDRAM_A), .SDRAM_BA(SDRAM_BA),
        .SDRAM_nRAS(SDRAM_nRAS), .SDRAM_nCAS(SDRAM_nCAS), .SDRAM_nWE(SDRAM_nWE),
        .SDRAM_DQML(), .SDRAM_DQMH(), .SDRAM_nCS(), .SDRAM_CLK(), .SDRAM_CKE(),
        .init(1'b0), .clk(memclk), .addr(sample_addr), .rd(1'b0),
        .wr(sample_we), .word(1'b1), .din(data), .dout(), .busy(sdr_busy)
    );

    reg [7:0] image [0:SIZE-1];
    reg [63:0] memory [0:1048575];
    integer main_bytes = 0, sample_bytes = 0, audio_bytes = 0;
    integer read_left = 0, read_pos = 0;
    integer responses_while_busy = 0;
    reg [12:0] rows [0:3];
    reg check_writes = 1;
    integer wait_cycles = 0;
    always @(posedge clk) begin
        wait_cycles <= (ioctl_wait || cpu_busy) ? wait_cycles + 1 : 0;
        if (wait_cycles == 4096)
            $fatal(1, "Stalled addr=%x wait=%b seen=%b DDR busy/state=%b/%d SDR busy/state/mode=%b/%d/%d cpu=%b counts=%x/%x/%x",
                   ioctl_addr,ioctl_wait,loader.busy_seen,ddr_busy,dram.state,
                   sdr_busy,samples.state,samples.mode,cpu_busy,main_bytes,sample_bytes,audio_bytes);
    end
    always @(posedge memclk) begin
        ticks <= ticks + 1;
        DDRAM_DOUT_READY <= 0;
        if (DDRAM_DOUT_READY && DDRAM_BUSY)
            responses_while_busy <= responses_while_busy + 1;
        if (read_left != 0) begin
            DDRAM_DOUT <= memory[read_pos];
            DDRAM_DOUT_READY <= 1;
            read_pos <= read_pos + 1;
            read_left <= read_left - 1;
        end
        if (!DDRAM_BUSY && DDRAM_RD) begin
            read_pos <= int'(DDRAM_ADDR - 29'h6000000);
            read_left <= int'(DDRAM_BURSTCNT);
        end
        if (!DDRAM_BUSY && DDRAM_WE) begin
            for (int lane = 0; lane < 8; lane++) begin
                if (DDRAM_BE[lane]) begin
                    // The existing DDR controller reverses its two 32-bit halves.
                    int offset;
                    offset = int'(DDRAM_ADDR - 29'h6000000) * 8 + ((lane / 4) ^ 1) * 4 + lane % 4;
                    if (check_writes && DDRAM_DIN[lane*8+:8] != image[offset])
                        $fatal(1, "DDR byte mismatch at %x", offset);
                    memory[DDRAM_ADDR - 29'h6000000][lane*8+:8] <= DDRAM_DIN[lane*8+:8];
                    if (check_writes) main_bytes <= main_bytes + $countones(DDRAM_BE);
                end
            end
        end
        if ({SDRAM_nRAS,SDRAM_nCAS,SDRAM_nWE} == 3'b011)
            rows[SDRAM_BA] <= SDRAM_A;
        if ({SDRAM_nRAS,SDRAM_nCAS,SDRAM_nWE} == 3'b100) begin
            int offset;
            offset = int'({SDRAM_BA, SDRAM_A[8:0], rows[SDRAM_BA], 1'b0});
            if (check_writes && (offset != sample_bytes ||
                SDRAM_DQ != {image['h800001 + offset],image['h800000 + offset]}))
                $fatal(1, "SDRAM command/data mismatch at %x expected %x", offset, sample_bytes);
            if (check_writes) sample_bytes <= sample_bytes + 2;
        end
    end
    always @(posedge clk) begin
        if (audio_we && check_writes) begin
            if (int'(audio_addr) * 2 != audio_bytes ||
                data != {image['ha00001 + audio_bytes],image['ha00000 + audio_bytes]})
                $fatal(1, "Z80 byte mismatch at %x", audio_bytes);
            audio_bytes <= audio_bytes + 2;
        end
    end
    task automatic send_word(input integer address);
        @(negedge clk);
        while (ioctl_wait) @(negedge clk);
        ioctl_addr = 27'(address);
        ioctl_dout = {image[address+1],image[address]};
        ioctl_wr = 1;
        @(negedge clk);
        ioctl_wr = 0;
    endtask
    task automatic finish_load;
        while (ioctl_wait) @(negedge clk);
        ioctl_download = 0;
        repeat(5) @(negedge clk);
    endtask
    task automatic read_word(input integer address);
        reg [31:0] expected;
        expected = {image[address+3],image[address+2],image[address+1],image[address]};
        @(negedge memclk);
        cpu_addr = 27'(address >> 1);
        cpu_rd = 1;
        repeat(3) @(negedge memclk);
        while (cpu_busy) @(negedge memclk);
        if (cpu_data != expected) $fatal(1, "CPU read mismatch at %x: %x != %x", address,cpu_data,expected);
        cpu_rd = 0;
        repeat(3) @(negedge memclk);
    endtask
    initial begin
        integer filehandle, count;
        string filename;
        if (!$value$plusargs("image=%s", filename)) $fatal(1,"Missing +image");
        filehandle = $fopen(filename,"rb");
        count = $fread(image,filehandle);
        $fclose(filehandle);
        if (count != SIZE) $fatal(1,"Incorrect test image size %d", count);
        repeat(300) @(negedge clk);
        if (!reset) $fatal(1,"CPU released before ROM download");
        ioctl_download = 1;
        for (int address=0; address<SIZE; address+=2) send_word(address);
        if (!reset) $fatal(1,"CPU released during ROM download");
        finish_load();
        if (!ready || reset) $fatal(1,"Complete stream did not release CPU");
        $display("COUNTS main=%x sample=%x audio=%x", main_bytes, sample_bytes, audio_bytes);
        if (main_bytes != 'h800000 || sample_bytes != 'h200000 || audio_bytes != 'h8000)
            $fatal(1,"Dropped/duplicate writes: main=%x sample=%x audio=%x",main_bytes,sample_bytes,audio_bytes);
        for (int address=0; address<1024; address+=4) read_word(address);
        read_word('h123450); read_word('h400004); read_word('h7ffffc);
        $display("PASS %d read responses received while DDR command port busy", responses_while_busy);
        $display("PASS full ZIP stream: 8 MiB DDR + 2 MiB SDRAM pin writes + 32 KiB Z80; CPU reset vector and cache reads match");
        check_writes = 0;
        ioctl_index = 254;
        ioctl_download = 1;
        send_word(0);
        finish_load();
        if (!ready || ioctl_wait || ddr_we || sample_we || audio_we)
            $fatal(1,"DIP upload disturbed ROM readiness");
        // Match the complete 16-bit index, so 256 must not alias ROM index 0.
        ioctl_index = 256;
        ioctl_download = 1;
        send_word(0);
        finish_load();
        if (!ready || ioctl_wait) $fatal(1,"Index 256 aliased ROM index 0");
        ioctl_index = 0;
        ioctl_download = 1;
        repeat(2) @(negedge clk);
        if (ready || !reset) $fatal(1,"Reload did not assert reset");
        send_word(0); send_word(2);
        finish_load();
        if (ready) $fatal(1,"Truncated download released CPU");
        ioctl_download = 1;
        send_word(SIZE-2);
        finish_load();
        if (ready) $fatal(1,"Nonsequential download released CPU");
        $display("PASS DIP/foreign indexes ignored, reload resets, truncated/nonsequential loads rejected");
        $finish;
    end
    initial begin
        #2000000000;
        $fatal(1,"ROM loading timed out addr=%x counts=%x/%x/%x",ioctl_addr,main_bytes,sample_bytes,audio_bytes);
    end
endmodule
