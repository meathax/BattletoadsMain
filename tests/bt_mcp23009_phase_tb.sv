`timescale 1ns/1ps

// Exercise the shipping I2C engine. Slave data reaches the FPGA 4650 ns
// after the master's logical falling edge, beyond the conservative pad
// envelope in verify_bt_platform_io.py (4630 ns), before the 5020 ns sample.
module bt_mcp23009_phase_tb;
    reg clk = 0;
    always #10 clk = ~clk;
    reg start = 0, rd = 0, wlen = 0;
    reg [7:0] wdata1 = 0, wdata2 = 0, read_byte = 0;
    wire [7:0] rdata;
    wire ready, error;
    tri1 scl, sda;
    reg slave_low = 0;
    assign sda = slave_low ? 1'b0 : 1'bz;
    i2c #(50_000_000, 100_000) unit (
        .CLK(clk), .START(start), .READ(rd), .I2C_ADDR(7'h20),
        .I2C_WLEN(wlen), .I2C_WDATA1(wdata1), .I2C_WDATA2(wdata2),
        .I2C_RDATA(rdata), .END(ready), .ACK(error),
        .I2C_SCL(scl), .I2C_SDA(sda));

    reg [2:0] led = 3'b101;
    wire [2:0] btn;
    wire sd_cd, present, mode;
    tri1 m_scl, m_sda;
    reg m_slave_low = 0;
    reg [7:0] m_read_byte = 8'hD8;
    assign m_sda = m_slave_low ? 1'b0 : 1'bz;
    mcp23009 board (.clk(clk), .btn(btn), .led(led),
        .flg_sd_cd(sd_cd), .flg_present(present), .flg_mode(mode),
        .scl(m_scl), .sda(m_sda));

    integer cycles = 0, transfers = 0, samples = 0, sda_edges = 0;
    integer m_frames = 0, m_writes = 0, m_reads = 0, m_retries = 0;
    reg [7:0] address_byte = 0, byte1 = 0, byte2 = 0;
    reg [7:0] m_address = 0, m_byte1 = 0, m_byte2 = 0;
    reg [15:0] m_expected_word = 0;
    reg m_expected_read = 0;
    reg prev_clock = 0;
    time last_fall = 0, last_scl_edge = 0, last_scl_rise = 0;
    time start_time = 0, stop_time = 0;
    time min_low = 64'h7fff_ffff_ffff_ffff;
    time min_high = 64'h7fff_ffff_ffff_ffff;
    time min_start_hold = 64'h7fff_ffff_ffff_ffff;
    time min_stop_setup = 64'h7fff_ffff_ffff_ffff;
    time min_bus_free = 64'h7fff_ffff_ffff_ffff;
    reg have_scl_edge = 0, have_start = 0, have_stop = 0;

    function automatic [15:0] init_word(input integer index);
        case (index)
            0: init_word = 16'h00F8;
            1: init_word = 16'h0138;
            2: init_word = 16'h0200;
            3: init_word = 16'h0300;
            4: init_word = 16'h0400;
            5: init_word = 16'h0524;
            6: init_word = 16'h06FF;
            7: init_word = 16'h0700;
            8: init_word = 16'h0800;
            9: init_word = 16'h0900;
            10: init_word = 16'h0A00;
            default: init_word = {8'h09, 5'b0, led};
        endcase
    endfunction

    task automatic tick;
        @(posedge clk); #1;
    endtask

    // Explicitly select one legal accumulator phase. No reset/power-up
    // guarantee is claimed: all 500 possible steady-state START phases run.
    initial begin
        unit.cnt = 0;
        unit.I2C_CLOCK = 0;
        board.i2c.cnt = 0;
        board.i2c.I2C_CLOCK = 0;
    end

    always @(posedge clk) begin
        cycles = cycles + 1;
        if (!prev_clock && unit.I2C_CLOCK &&
            ((unit.SD_COUNTER >= 11 && unit.SD_COUNTER <= 18) ||
             unit.SD_COUNTER == 10 ||
             (!rd && (unit.SD_COUNTER == 19 || unit.SD_COUNTER == 28)))) begin
            if ($time - last_fall != 5020)
                $fatal(1, "Input capture phase is %0t, expected 5020 ns", $time-last_fall);
            samples = samples + 1;
        end
        prev_clock <= unit.I2C_CLOCK;
    end

    always @(negedge unit.I2C_CLOCK) begin
        reg low_next;
        last_fall = $time;
        low_next = unit.SD_COUNTER == 10 ||
            (!rd && (unit.SD_COUNTER == 19 || unit.SD_COUNTER == 28));
        if (rd && unit.SD_COUNTER >= 11 && unit.SD_COUNTER <= 18)
            low_next = !read_byte[18-unit.SD_COUNTER];
        slave_low <= #4650 low_next;
    end

    always @(negedge board.i2c.I2C_CLOCK) begin
        reg low_next;
        // First transaction deliberately receives NACK to prove retry.
        low_next = m_frames != 1 && (board.i2c.SD_COUNTER == 10 ||
            (!board.rw && (board.i2c.SD_COUNTER == 19 || board.i2c.SD_COUNTER == 28)));
        if (board.rw && board.i2c.SD_COUNTER >= 11 && board.i2c.SD_COUNTER <= 18)
            low_next = !m_read_byte[18-board.i2c.SD_COUNTER];
        m_slave_low <= #4650 low_next;
    end

    always @(unit.SDO[3]) begin
        if ($time > 0 && unit.SD_COUNTER > 0 && unit.SD_COUNTER <= 32) begin
            if ($time-last_fall != 80)
                $fatal(1, "Master SDA delay is %0t, expected 80 ns", $time-last_fall);
            sda_edges = sda_edges + 1;
        end
        if ($time > 0 && scl) begin
            if (!unit.SDO[3]) begin
                start_time = $time;
                have_start = 1;
                if (have_stop && $time-stop_time < min_bus_free)
                    min_bus_free = $time-stop_time;
            end else if (have_start) begin
                if ($time-last_scl_rise < min_stop_setup)
                    min_stop_setup = $time-last_scl_rise;
                stop_time = $time;
                have_stop = 1;
                have_start = 0;
            end
        end
    end

    always @(scl) begin
        if ($time > 0) begin
            if (scl) begin
                last_scl_rise = $time;
                if (have_scl_edge && $time-last_scl_edge < min_low)
                    min_low = $time-last_scl_edge;
            end else begin
                if (have_scl_edge && $time-last_scl_edge < min_high)
                    min_high = $time-last_scl_edge;
                if (have_start && $time-start_time < min_start_hold)
                    min_start_hold = $time-start_time;
            end
            have_scl_edge = 1;
            last_scl_edge = $time;
        end
    end

    // Observe bytes at the actual open-drain SCL output, not the command word.
    always @(posedge scl) begin
        if (unit.SD_COUNTER >= 2 && unit.SD_COUNTER <= 9)
            address_byte = {address_byte[6:0], sda};
        if (!rd && unit.SD_COUNTER >= 11 && unit.SD_COUNTER <= 18)
            byte1 = {byte1[6:0], sda};
        if (!rd && wlen && unit.SD_COUNTER >= 20 && unit.SD_COUNTER <= 27)
            byte2 = {byte2[6:0], sda};
    end

    always @(posedge board.start) begin
        m_frames = m_frames + 1;
        m_address = 0; m_byte1 = 0; m_byte2 = 0;
        m_expected_read = board.rw;
        m_expected_word = init_word(m_writes);
        if (board.din !== m_expected_word)
            $fatal(1, "MCP init/poll command mismatch frame %0d", m_frames);
    end

    always @(posedge m_scl) begin
        if (board.i2c.SD_COUNTER >= 2 && board.i2c.SD_COUNTER <= 9)
            m_address = {m_address[6:0], m_sda};
        if (!m_expected_read && board.i2c.SD_COUNTER >= 11 && board.i2c.SD_COUNTER <= 18)
            m_byte1 = {m_byte1[6:0], m_sda};
        if (!m_expected_read && board.i2c.SD_COUNTER >= 20 && board.i2c.SD_COUNTER <= 27)
            m_byte2 = {m_byte2[6:0], m_sda};
    end

    always @(posedge board.ready) begin
        if (m_frames > 0) begin
            if (m_address !== (m_expected_read ? 8'h41 : 8'h40))
                $fatal(1, "MCP wire address mismatch %02x", m_address);
            if (!m_expected_read && {m_byte1,m_byte2} !== m_expected_word)
                $fatal(1, "MCP wire data mismatch %04x != %04x", {m_byte1,m_byte2}, m_expected_word);
            if (m_frames == 1) begin
                if (!board.error) $fatal(1, "Injected NACK not reported");
                m_retries = m_retries + 1;
            end else begin
                if (board.error) $fatal(1, "Unexpected MCP NACK");
                if (!m_expected_read) m_writes = m_writes + 1;
                else begin
                    @(posedge clk); #1;
                    if (!present || {sd_cd,mode,btn} !== m_read_byte[7:3])
                        $fatal(1, "MCP flag/button poll mismatch");
                    m_reads = m_reads + 1;
                    m_read_byte = (m_reads & 1) ? 8'h48 : 8'hD8;
                    led = (m_reads & 1) ? 3'b010 : 3'b101;
                end
            end
        end
    end

    initial begin : stimulus
        integer phase, kind, guard;
        repeat (5) tick();
        for (phase = 0; phase < 500; phase = phase + 1) begin
            for (kind = 0; kind < 3; kind = kind + 1) begin
                while ((cycles % 500) != phase) tick();
                @(negedge clk);
                rd = kind == 2;
                wlen = kind == 1;
                wdata1 = 8'(phase) ^ 8'hA5;
                wdata2 = 8'(phase >> 1) ^ 8'h3C;
                read_byte = 8'(phase) ^ 8'h5A;
                address_byte = 0; byte1 = 0; byte2 = 0;
                start = 1;
                repeat (2) tick();
                @(negedge clk); start = 0;
                guard = 0;
                while (!ready && guard < 40000) begin tick(); guard = guard + 1; end
                if (!ready || error) $fatal(1, "Transfer timeout/NACK phase %0d kind %0d", phase,kind);
                if (address_byte !== (rd ? 8'h41 : 8'h40))
                    $fatal(1, "Wire address mismatch phase %0d", phase);
                if (rd && rdata !== read_byte)
                    $fatal(1, "Read mismatch phase %0d: %02x != %02x", phase,rdata,read_byte);
                if (!rd && byte1 !== wdata1) $fatal(1, "First wire byte mismatch");
                if (!rd && wlen && byte2 !== wdata2) $fatal(1, "Second wire byte mismatch");
                transfers = transfers + 1;
            end
        end
        if (m_writes < 13 || m_reads < 2 || m_retries != 1)
            $fatal(1, "MCP polling/retry coverage missing");
        if (min_low != 5000 || min_high != 5000 || min_start_hold < 4000 ||
            min_stop_setup < 4000 || min_bus_free < 4700)
            $fatal(1, "Logical standard-mode timing bounds failed");
        $display("PHASE low_ns=%0d high_ns=%0d start_hold_ns=%0d stop_setup_ns=%0d bus_free_ns=%0d capture_ns=5020 sda_after_fall_ns=80", min_low,min_high,min_start_hold,min_stop_setup,min_bus_free);
        $display("PASS transfers=%0d start_phases=500 kinds=3 cycles=%0d samples=%0d sda_edges=%0d init_writes=11 poll_reads=%0d nack_retries=%0d", transfers,cycles,samples,sda_edges,m_reads,m_retries);
        $finish;
    end
    initial begin #600_000_000; $fatal(1, "Global watchdog"); end
endmodule
