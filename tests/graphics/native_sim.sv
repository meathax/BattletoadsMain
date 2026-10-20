// Native game-board harness. Only the external DDR and ROM devices are supplied
// by the host; the CPUs, memory controller, graphics and clock enables are RTL.
module BT_NATIVE_SIM (
    input CLK, CLK2X, RESET,
    input [7:0] P1,
    input [14:0] AUDIO_ADDR,
    input [15:0] AUDIO_DATA,
    input AUDIO_WE,
    output [20:0] SAMPLE_ADDR,
    input [7:0] SAMPLE_DATA,
    input DDR_BUSY,
    input [63:0] DDR_Q,
    input DDR_Q_READY,
    output [7:0] DDR_BURST, DDR_BE,
    output [28:0] DDR_ADDR,
    output [63:0] DDR_DATA,
    output DDR_RD, DDR_WE,
    output [23:0] RGB,
    output HS_N, VS_N, HBL_N, VBL_N, PIXEL_CE, INIT_READY,
    output [31:0] PC, ADDRESS, WRITE_DATA,
    output [15:0] INSTRUCTION,
    output [4:0] MICRO_STATE,
    output BUS_READ, BUS_WRITE, CPU_CE,
    output [15:0] DISPLAY_CONTROL
);
    timeunit 1ps; timeprecision 1ps;
    wire ce_f, ce_r, vce;
    wire fast_we, fast_done;
    wire [27:1] fast_addr;
    wire [63:0] fast_data;
    wire reset_cpu=RESET || !INIT_READY;
    bt_clock_enables enables(.clk(CLK),.reset(reset_cpu),.ce_f(ce_f),.ce_r(ce_r),.vce(vce));
    wire VCE_R=vce,CLK_VIDEO=CLK,MIX_CE;
    `include "mixer_enable.svh"
    assign PIXEL_CE=MIX_CE;
    reg [6:0] sound_acc=0;
    reg sound_tick=0, sound_phase=0;
    always @(posedge CLK) begin
        if(reset_cpu) begin sound_acc<=0; sound_tick<=0; sound_phase<=0; end
        else begin
            sound_tick<=sound_acc+7'd12 >= 7'd80;
            sound_acc<=sound_acc+7'd12 >= 7'd80 ? sound_acc+7'd12-7'd80 : sound_acc+7'd12;
            if(sound_tick) sound_phase<=~sound_phase;
        end
    end
    wire [22:0] eaddr;
    wire [4:0][22:0] eaddr_candidates;
    wire [4:0] eaddr_select;
    wire [31:0] edata, eq, ddr_q;
    wire [3:0][31:0] edata_candidates;
    wire [3:0] edata_select;
    wire [3:0] ewe;
    wire ewe_any;
    wire erd, eram, erom, efg, envram, espr, ddr_busy;
    wire [12:0] nvram_addr;
    wire [7:0] nvram_data;
    wire nvram_we;
    wire [17:0] baddr;
    wire [63:0] bin,bout;
    wire bwr,brd,bte;
    wire [9:3] ba;
    BT #(.FG_FAST(1)) core(.CLK(CLK),.CLK2X(CLK2X),.RST_N(!reset_cpu),.EN(1'b1),
        .CE_F(ce_f),.CE_R(ce_r),.VCE_R(vce),
        .SCE_F(sound_tick && !sound_phase),.SCE_R(sound_tick && sound_phase),.SERVICE(1'b1),
        .EADDR(eaddr),.EDATA(edata),.EWE(ewe),.EWE_ANY(ewe_any),.ERD(erd),.EQ(eq),.NVRAM_Q(eq),.FG_DDR_Q(ddr_q),
        .EADDR_CANDIDATES(eaddr_candidates),.EADDR_SELECT(eaddr_select),
        .EDATA_CANDIDATES(edata_candidates),.EDATA_SELECT(edata_select),
        .NVRAM_ADDR(nvram_addr),.NVRAM_DATA(nvram_data),.NVRAM_WE(nvram_we),
        .ERAM(eram),.EROM(erom),.EFG(efg),.ENVRAM(envram),.ESPR(espr),.ERDY(envram || !ddr_busy),
        .ESADDR(baddr),.ESDATA(bin),.ESWR(bwr),.ESRD(brd),.ESQ(bout),.ESTE(bte),.SRDY(!ddr_busy),
        .EFAST_WE(fast_we),.EFAST_ADDR(fast_addr),.EFAST_DATA(fast_data),.EFAST_DONE(fast_done),
        .BSMT_ROM_A(SAMPLE_ADDR),.BSMT_ROM_DI(SAMPLE_DATA),
        .AUDIO_ROM_A(AUDIO_ADDR),.AUDIO_ROM_D(AUDIO_DATA),.AUDIO_ROM_WR(AUDIO_WE),
        .SW1(8'hf0),.P1(P1),.P2(8'hff),.P3(8'hff),
        .R(RGB[23:16]),.G(RGB[15:8]),.B(RGB[7:0]),
        .HS_N(HS_N),.VS_N(VS_N),.HBL_N(HBL_N),.VBL_N(VBL_N),.BG_EN(3'b111),.GRID_EN(3'b000));
    reg [7:0] nvram[8192];
    initial for(integer i=0;i<8192;i++) nvram[i]=0;
    always @(posedge CLK) if(nvram_we && ce_r && !reset_cpu)
        nvram[nvram_addr]<=nvram_data;
    assign eq=envram ? {24'b0,nvram[nvram_addr]} : ddr_q;
    wire [27:0] addr=eram ? {7'b0000100,eaddr[20:0]} :
        efg ? {7'b0010000,eaddr[20:0]} :
        envram ? {7'b0001000,eaddr[20:0]} :
        espr ? {7'b0001100,eaddr[20:0]} :
        erom ? {5'b00000,eaddr[22:0]} : 28'b0;
    wire [27:1] init_addr;
    wire [3:0] init_we;
    wire io_busy;
    bt_fg_ddr_clear init_fg(.clk(CLK2X),.init_n(!RESET),.io_busy(io_busy),
        .io_addr(init_addr),.io_we(init_we),.ready(INIT_READY));
    wire [3:0][23:0] tag_keys;
    wire [3:0] tag_hit;
    wire [2:0] tag_hit_part;
    bt_ddr_tag_compare tag_compare(.clk(CLK2X),.tags(tag_keys),.addresses(eaddr_candidates),
        .select_address(eaddr_select),.eram(eram),.efg(efg),.envram(envram),
        .espr(espr),.erom(erom),.hit(tag_hit),.hit_part(tag_hit_part));
    wire ddr_bank_valid = eram || efg || envram || espr || erom;
	// Decode each source's word before the late graphics/CPU address mux.
	// Invalid address classes preserve the original forced-zero address.
	wire [3:0] ddr_read_word;
	genvar request_word_index, address_index;
	generate for (request_word_index=0; request_word_index<4; request_word_index=request_word_index+1) begin : ddr_words
		wire [4:0] word_matches;
		for (address_index=0; address_index<5; address_index=address_index+1) begin : addresses
			assign word_matches[address_index] = eaddr_select[address_index] &&
				eaddr_candidates[address_index][3:2] == request_word_index;
		end
		assign ddr_read_word[request_word_index] = (ddr_bank_valid && |word_matches) ||
			(!ddr_bank_valid && request_word_index == 0);
	end endgenerate
    ddram #(.USE_PREDECODED_TAGS(1),.USE_PREDECODED_WORD(0),.USE_PREDECODED_WE(1),.USE_PREDECODED_MISS(1),.USE_PARALLEL_DIN(1),.FG_FAST(1)) memory(.clk(CLK2X),.rst(RESET),.sclk(ce_r),
        .DDRAM_BUSY(DDR_BUSY),.DDRAM_BURSTCNT(DDR_BURST),.DDRAM_ADDR(DDR_ADDR),
        .DDRAM_DOUT(DDR_Q),.DDRAM_DOUT_READY(DDR_Q_READY),.DDRAM_RD(DDR_RD),
        .DDRAM_DIN(DDR_DATA),.DDRAM_BE(DDR_BE),.DDRAM_WE(DDR_WE),
        .io_addr(init_addr),.io_din(32'b0),.io_we(init_we),.io_rd(1'b0),.io_busy(io_busy),
        .fg_we(fast_we && INIT_READY),.fg_addr(fast_addr),.fg_din(fast_data),.fg_done(fast_done),
        .addr(addr[27:1]),.dout(ddr_q),.din(edata),.parallel_din(edata_candidates),.parallel_din_sel(edata_select),.rd(erd && (eram || espr || erom || efg)),
        .we(ewe & {4{eram || espr || efg}}),.cache(addr[24:23]),.busy(ddr_busy),
        .external_tag_hit(tag_hit),.external_read_hit_part(tag_hit_part),.tag_keys(tag_keys),
        .external_read_word(ddr_read_word),.external_we_any(ewe_any && (eram || espr || efg)),
        .baddr({7'b0001100,1'b0,baddr[17:9],2'b00,baddr[8:1]}),
        .bin(bin),.bout(bout),.bwr(bwr),.brd(brd),.ba(ba),.bte(bte));
    assign ADDRESS=core.BIT_ADDR;
    assign WRITE_DATA=core.LDO;
    assign PC=core.CPU.PC;
    assign INSTRUCTION=core.CPU.IC;
    assign MICRO_STATE=core.CPU.STATE;
    assign BUS_READ=!core.QE_N;
    assign BUS_WRITE=!core.WE_N;
    assign CPU_CE=ce_r;
    assign DISPLAY_CONTROL=core.DISP_CONTROL;

    // Measure the phase budget of the actual board/controller connection.
    // An ordinary read follows F-phase address publication. Write metadata
    // is accepted only after write_prepend and the next CE_R window.
    longint unsigned memory_ticks=0, last_address_change=0, last_strobe_change=0;
    longint unsigned last_f_metadata_change=0, last_write_buffer_change=0;
    longint unsigned last_code_change=0, last_be_change=0;
    longint unsigned last_align_change=0, last_old_data_change=0;
    longint unsigned last_return_change=0, last_tag_change[4]='{default:0};
    longint unsigned return_phase_checks=0, cache_patch_phase_checks=0;
    // Track capture enables as well as output changes: writing an identical
    // value still launches a physical timing path. Only the selected cache
    // word can propagate through the fixed one-hot return mux.
    // The host advances each quarter clock by a fixed simulation step;
    // measure the MEM period so this proof depends on edge spacing rather
    // than the simulator's chosen time units or procedural counter ordering.
    realtime previous_memory_edge=0, memory_edge_period=0;
    always @(posedge CLK2X) begin
        memory_edge_period=$realtime-previous_memory_edge;
        previous_memory_edge=$realtime;
    end
    realtime last_return_bank_capture=0;
    realtime last_return_selector_capture[4]='{default:0};
    realtime last_return_word_capture[4][4]='{default:'{default:0}};
    realtime last_return_combined_capture[4]='{default:0};
    realtime previous_return_combined_capture[4]='{default:0};
    realtime previous_return_word_capture[4][4]='{default:'{default:0}};
    realtime physical_consuming_edge=0, physical_consuming_period=0;
    logic [15:0] physical_consuming_selector=0;
    bit physical_return_check_pending=0;
    longint unsigned physical_return_phase_checks=0;
    always @(posedge CLK2X) begin
        if(memory.rd && !memory.old_rd && !memory.rst)
            last_return_bank_capture=$realtime;
        for(int bank=0;bank<4;bank++) begin
            if(memory.rst ||
               (memory.rd && !memory.old_rd && memory.cache==bank) ||
               (!memory.rst && memory.cache_write_commit &&
                memory.write_cache==bank && !memory.write_tag_hit[bank]))
                last_return_selector_capture[bank]=$realtime;
        end
    end
    // Stamp every physical combined-selector write enable, including equal
    // values and writes which clear an unselected bank. This is the exact
    // read_return_sel always-block priority in the shipping DDR controller.
    for(genvar flat_bank=0;flat_bank<4;flat_bank++) begin : flat_return_phase
        always @(posedge CLK2X)
            if(memory.rst || (memory.rd && !memory.old_rd) ||
               (memory.cache_write_commit && memory.write_cache==flat_bank &&
                !memory.write_tag_hit[flat_bank] && memory.read_bank_sel[flat_bank]))
            begin
                previous_return_combined_capture[flat_bank]=last_return_combined_capture[flat_bank];
                last_return_combined_capture[flat_bank]=$realtime;
            end
    end
    for(genvar rb=0;rb<4;rb++) begin : return_bank_phase
        for(genvar rw=0;rw<4;rw++) begin : return_word_phase
            always @(posedge CLK2X)
                if(memory.cache_store_bank[rb].cache_store_word[rw].fill ||
                   (memory.cache_store_bank[rb].cache_store_word[rw].patch_word &&
                    |memory.write_be))
                begin
                    previous_return_word_capture[rb][rw]=last_return_word_capture[rb][rw];
                    last_return_word_capture[rb][rw]=$realtime;
                end
        end
    end
    // This is the existing later-F return budget only. Earlier MC/CACHE
    // held-word FFs retain ordinary timing and receive no extra age here.
    always @(posedge CLK) if(!reset_cpu && core.CPU.CE_F &&
        (core.CPU.CACHE.CACHE_RAM.WREN || core.CPU.MC.READ_LATCH) &&
        (eram || erom || espr || efg)) begin
        assert(!physical_return_check_pending)
            else $fatal(1,"DDR physical event journal did not finish before next F");
        physical_consuming_edge=$realtime;
        physical_consuming_period=memory_edge_period;
        physical_consuming_selector=memory.read_return_sel;
        assert($onehot(physical_consuming_selector))
            else $fatal(1,"DDR physical combined selector is not onehot at F");
        for(int bit_index=0;bit_index<16;bit_index++)
            assert(physical_consuming_selector[bit_index] ==
                (memory.read_bank_sel[bit_index/4] && memory.read_word_sel[bit_index/4][bit_index%4]))
                else $fatal(1,"DDR physical selector differs from original metadata at F");
        physical_return_check_pending=1;
    end
    // Drain at a MEM falling edge, after any coincident positive-edge writes
    // are stamped. At most one later MEM positive edge can intervene. Keep
    // its predecessor so a later event is not mistaken for a pre-F launch.
    always @(negedge CLK2X) if(physical_return_check_pending) begin
        realtime selector_launch, word_launch;
        assert(physical_consuming_period>0)
            else $fatal(1,"DDR physical memory period was not measured");
        for(int flat_index=0;flat_index<16;flat_index++) if(physical_consuming_selector[flat_index]) begin
            selector_launch=last_return_combined_capture[flat_index/4];
            if(selector_launch>physical_consuming_edge)
                selector_launch=previous_return_combined_capture[flat_index/4];
            word_launch=last_return_word_capture[flat_index/4][flat_index%4];
            if(word_launch>physical_consuming_edge)
                word_launch=previous_return_word_capture[flat_index/4][flat_index%4];
            assert(selector_launch<=physical_consuming_edge && word_launch<=physical_consuming_edge)
                else $fatal(1,"DDR physical event journal has no pre-F provenance");
            assert(physical_consuming_edge-selector_launch>=(2.0-1.0e-6)*physical_consuming_period)
                else $fatal(1,"DDR physical combined-selector budget_cycles=%0.3f bank=%0d",(physical_consuming_edge-selector_launch)/physical_consuming_period,flat_index/4);
            assert(physical_consuming_edge-word_launch>=(2.0-1.0e-6)*physical_consuming_period)
                else $fatal(1,"DDR physical cache-word capture budget_cycles=%0.3f bank=%0d word=%0d",(physical_consuming_edge-word_launch)/physical_consuming_period,flat_index/4,flat_index%4);
        end
        physical_return_check_pending=0;
        physical_return_phase_checks++;
    end
    always @(core.LDI) if(!reset_cpu) last_return_change=memory_ticks;
    // Margin of the DDR return word (the source of the CPU-side capture
    // registers) at every consuming CE_F: smallest age in memory ticks.
    longint unsigned last_ddr_q_change=0, min_ddr_q_age=64'hffffffff;
    // Age of the sprite blitter's draw address/data at every DDR write edge it
    // causes (SPR_DDR_REQ): it is published >=1 system clock before the request.
    longint unsigned last_draw_change=0, min_draw_age=64'hffffffff;
    always @(core.SPR_DRAW_ADDR or core.SPR_DRAW_DATA) if(!reset_cpu) last_draw_change=memory_ticks;
    always @(posedge CLK2X) if(!reset_cpu && core.SPR_DDR_REQ && |memory.we && !memory.old_we &&
        memory_ticks-last_draw_change<min_draw_age) min_draw_age=memory_ticks-last_draw_change;
    always @(core.FG_DDR_Q) if(!reset_cpu) last_ddr_q_change=memory_ticks;
    // Request-side stability at each DDR read/write start edge: the controller's
    // address/cache inputs, and the youngest of its four tag keys.
    longint unsigned last_req_addr_change=0, min_rd_addr_age=64'hffffffff, min_wr_addr_age=64'hffffffff;
    longint unsigned min_rd_tag_age=64'hffffffff, min_wr_tag_age=64'hffffffff;
    always @(memory.addr or memory.cache) if(!reset_cpu) last_req_addr_change=memory_ticks;
    function automatic longint unsigned youngest_tag_age();
        longint unsigned a=64'hffffffff;
        for(int b=0;b<4;b++) if(memory_ticks-last_tag_change[b]<a) a=memory_ticks-last_tag_change[b];
        return a;
    endfunction
    always @(posedge CLK2X) if(!reset_cpu && !memory.rst) begin
        if(memory.rd && !memory.old_rd) begin
            if(memory_ticks-last_req_addr_change<min_rd_addr_age) min_rd_addr_age=memory_ticks-last_req_addr_change;
            assert(youngest_tag_age()>=2)
                else $fatal(1,"DDR tag key age at read start=%0d (<2)",youngest_tag_age());
            if(youngest_tag_age()<min_rd_tag_age) min_rd_tag_age=youngest_tag_age();
        end
        if(|memory.we && !memory.old_we) begin
            if(memory_ticks-last_req_addr_change<min_wr_addr_age) min_wr_addr_age=memory_ticks-last_req_addr_change;
            assert(youngest_tag_age()>=2)
                else $fatal(1,"DDR tag key age at write start=%0d (<2)",youngest_tag_age());
            if(youngest_tag_age()<min_wr_tag_age) min_wr_tag_age=youngest_tag_age();
        end
    end
    for(genvar phase_bank=0;phase_bank<4;phase_bank++) begin : tag_phase
        always @(memory.read_addr[phase_bank])
            if(!reset_cpu) last_tag_change[phase_bank]=memory_ticks;
    end
    always @(posedge CLK) if(!reset_cpu && core.CPU.CE_F &&
        (core.CPU.CACHE.CACHE_RAM.WREN || core.CPU.MC.READ_LATCH)) begin
        assert(memory_ticks-last_return_change>=2)
            else $fatal(1,"CPU memory-return capture budget=%0d",memory_ticks-last_return_change);
        if(core.LDI_CACHE_DDR) begin
            // bt_ddr_phase.sdc: the CPU capture registers sample the word <=2
            // ticks before this consumption; they get a 2-tick setup allowance.
            assert(memory_ticks-last_ddr_q_change>=4)
                else $fatal(1,"DDR return word age at consumption=%0d (<4)",memory_ticks-last_ddr_q_change);
            if(memory_ticks-last_ddr_q_change<min_ddr_q_age) min_ddr_q_age=memory_ticks-last_ddr_q_change;
        end
        return_phase_checks++;
    end
    // Sprite source pixels come from the memory-clock mirror RAM. The blitter
    // samples them only at CE_R emissions, so require two quiet memory cycles
    // before each sample. This bounds the constrained mirror-to-draw-strobe paths.
    longint unsigned last_blit_source_change=0, blit_source_checks=0;
    always @(core.SPR_SOURCE_Q) if(!reset_cpu) last_blit_source_change=memory_ticks;
    always @(posedge CLK) if(!reset_cpu && core.CE_R && core.blitter.exec &&
        (!core.blitter.DRAW_WE || core.blitter.DRAW_READY)) begin
        assert(memory_ticks-last_blit_source_change>=2)
            else $fatal(1,"Sprite source capture budget=%0d",memory_ticks-last_blit_source_change);
        blit_source_checks++;
    end
    // BT_PARALLEL_NATIVE_PHASE_BEGIN
    // Exact launch predicates include identical-value reloads. Independent
    // NBA probes attached to every actual private-copy MC assignment verify
    // these predicates against the unchanged original control branches. A
    // coincident MEM capture samples pre-NBA Q and therefore its prior launch;
    // the next MEM edge sees the new source launch, even for identical values.
    realtime parallel_last_mem_edge=0,parallel_mem_period=0;
    realtime parallel_ext_launch=0,parallel_fs_launch=0,parallel_ba_launch=0,parallel_buf_launch=0;
    longint unsigned parallel_ext_reloads=0,parallel_fs_reloads=0,parallel_ba_reloads=0,parallel_buf_reloads=0;
    longint unsigned parallel_capture_checks=0,parallel_cpu_captures=0,parallel_sprite_captures=0;
    longint unsigned parallel_fg0_captures=0,parallel_fg1_captures=0,parallel_launch_age_checks=0;
    longint unsigned parallel_min_ext_age='1,parallel_min_fs_age='1,parallel_min_ba_age='1,parallel_min_buf_age='1;
    logic[31:0] parallel_captured_word=0;
    logic[3:0] parallel_captured_owner=0;
    bit parallel_captured_valid=0;
    string parallel_last_ext_event,parallel_last_fs_event,parallel_last_ba_event,parallel_last_buf_event;
    realtime parallel_last_any_f=0;
    logic parallel_last_any_f_state=0;
    logic[3:0] parallel_last_any_f_probes=0;
    longint unsigned parallel_conservative_false_count=0;
    logic[3:0] parallel_expected_probes=0;
    bit parallel_probe_valid=0;
    longint unsigned parallel_probe_checks=0;
    wire parallel_f_idle=core.CPU.MC.RST_N && core.CPU.MC.EN && ce_f && !core.CPU.MC.MC_STATE;
    wire parallel_r_idle=core.CPU.MC.RST_N && core.CPU.MC.EN && ce_r && !core.CPU.MC.MC_STATE;
    wire parallel_buf_load=parallel_r_idle &&
        ((core.CPU.MC.MC_READ_PEND && core.CPU.MC.RMW) || core.CPU.MC.MC_WRITE_PEND);
    wire parallel_ba_load=parallel_f_idle && !core.CPU.MC.MC_READ_EXT && core.CPU.MC.MC_WRITE_EXT;
    wire parallel_fs_load=parallel_f_idle && !core.CPU.MC.MC_READ_EXT && !core.CPU.MC.MC_WRITE_EXT &&
        !core.CPU.MC.SCRREF_PEND && !core.CPU.MC.READ && core.CPU.MC.WRITE && !core.CPU.MC.CACHE;
    always @(posedge CLK or negedge core.CPU.MC.RST_N) begin
        parallel_expected_probes<={(!core.CPU.MC.RST_N || parallel_f_idle),
            (!core.CPU.MC.RST_N || parallel_fs_load),parallel_ba_load,
            (!core.CPU.MC.RST_N || parallel_buf_load)};
        parallel_probe_valid<=1;
        if(!core.CPU.MC.RST_N) begin
            parallel_ext_launch<=$realtime;parallel_fs_launch<=$realtime;
            parallel_buf_launch<=$realtime;
        end else begin
            if(core.CPU.MC.EN && ce_f)begin
                parallel_last_any_f<=$realtime;parallel_last_any_f_state<=core.CPU.MC.MC_STATE;
                parallel_last_any_f_probes<={parallel_f_idle,parallel_fs_load,parallel_ba_load,parallel_buf_load};
            end
            if(parallel_f_idle)begin parallel_ext_launch<=$realtime;parallel_ext_reloads++;
                parallel_last_ext_event<=$sformatf("EXT t=%0t state=%b old=%b rdext=%b wrext=%b",$time,
                    core.CPU.MC.MC_STATE,core.CPU.MC.MC_EXT_WORD,core.CPU.MC.MC_READ_EXT,core.CPU.MC.MC_WRITE_EXT);
            end
            if(parallel_fs_load)begin parallel_fs_launch<=$realtime;parallel_fs_reloads++;
                parallel_last_fs_event<=$sformatf("FS t=%0t old=%h new=%h",$time,core.CPU.MC.DOUT_FS,core.CPU.MC.FS);end
            if(parallel_ba_load)begin parallel_ba_launch<=$realtime;parallel_ba_reloads++;
                parallel_last_ba_event<=$sformatf("BA t=%0t old=%h new=%h",$time,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DBUS_A[4:0]);end
            if(parallel_buf_load)begin parallel_buf_launch<=$realtime;parallel_buf_reloads++;
                parallel_last_buf_event<=$sformatf("BUF t=%0t old=%h new=%h state=%b readpend=%b writepend=%b rmw=%b",$time,
                    core.CPU.MC.DOUT_BUF,core.CPU.MC.DOUT,core.CPU.MC.MC_STATE,core.CPU.MC.MC_READ_PEND,
                    core.CPU.MC.MC_WRITE_PEND,core.CPU.MC.RMW);end
        end
    end
    always @(negedge CLK)if(parallel_probe_valid)begin
        assert({core.CPU.MC.bt_probe_ext,core.CPU.MC.bt_probe_fs,core.CPU.MC.bt_probe_ba,core.CPU.MC.bt_probe_buf}
               ===parallel_expected_probes)else $fatal(1,"Exact MC launch predicates differ from actual assignment probes");
        parallel_probe_checks++;
    end
    always @(posedge CLK2X) begin
        if(parallel_last_mem_edge!=0)parallel_mem_period<=$realtime-parallel_last_mem_edge;
        parallel_last_mem_edge<=$realtime;
        if(!reset_cpu && !RESET && memory.write_prepend && ce_r)begin
            assert(parallel_mem_period>0 && $onehot(edata_select))
                else $fatal(1,"Parallel DDR acceptance owner/clock contract missing");
            // Check every raw capture, including inactive CPU data. DATA_OLD
            // keeps its original ordinary single-cycle path and is not added.
            if($realtime-parallel_last_any_f<2*parallel_mem_period)begin
                parallel_conservative_false_count++;
                if(parallel_conservative_false_count<=8)begin
                    $display("DDR_CONSERVATIVE_FALSE t=%0t owner=%h word=%h rawCPU=%h current_state=%b lastF=%0f lastF_state=%b actualFloads=%b exact_ages=%0f/%0f/%0f/%0f period=%0f ext=%b fs=%h ba=%h buf=%h pend=%b%b%b",
                        $time,edata_select,edata,edata_candidates[3],core.CPU.MC.MC_STATE,
                        parallel_last_any_f,parallel_last_any_f_state,parallel_last_any_f_probes,
                        $realtime-parallel_ext_launch,$realtime-parallel_fs_launch,
                        $realtime-parallel_ba_launch,$realtime-parallel_buf_launch,parallel_mem_period,
                        core.CPU.MC.MC_EXT_WORD,core.CPU.MC.DOUT_FS,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DOUT_BUF,
                        core.CPU.MC.MC_READ_PEND,core.CPU.MC.MC_WRITE_PEND,core.CPU.MC.MC_WRITE_PEND2);
                    $display("DDR_CONSERVATIVE_LAST %s | %s | %s | %s",parallel_last_ext_event,
                        parallel_last_fs_event,parallel_last_ba_event,parallel_last_buf_event);
                end
            end
            if($realtime-parallel_ext_launch<2*parallel_mem_period ||
               $realtime-parallel_fs_launch<2*parallel_mem_period ||
               $realtime-parallel_ba_launch<2*parallel_mem_period ||
               $realtime-parallel_buf_launch<2*parallel_mem_period)begin
                $display("DDR_PARALLEL_EVENT t=%0t owner=%h word=%h rawCPU=%h state=%b F=%b R=%b age=%0f/%0f/%0f/%0f period=%0f ext=%b fs=%h ba=%h buf=%h loads=%b%b%b%b pend=%b%b%b",
                    $time,edata_select,edata,edata_candidates[3],core.CPU.MC.MC_STATE,ce_f,ce_r,
                    $realtime-parallel_ext_launch,$realtime-parallel_fs_launch,$realtime-parallel_ba_launch,
                    $realtime-parallel_buf_launch,parallel_mem_period,core.CPU.MC.MC_EXT_WORD,
                    core.CPU.MC.DOUT_FS,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DOUT_BUF,
                    parallel_f_idle,parallel_fs_load,parallel_ba_load,parallel_buf_load,
                    core.CPU.MC.MC_READ_PEND,core.CPU.MC.MC_WRITE_PEND,core.CPU.MC.MC_WRITE_PEND2);
                $display("DDR_PARALLEL_PREVIOUS %s | %s | %s | %s",parallel_last_ext_event,
                    parallel_last_fs_event,parallel_last_ba_event,parallel_last_buf_event);
            end
            assert($realtime-parallel_ext_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR MC_EXT_WORD exact reload age too short");
            assert($realtime-parallel_fs_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR DOUT_FS exact reload age too short");
            assert($realtime-parallel_ba_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR DOUT_BA_OLD exact reload age too short");
            assert($realtime-parallel_buf_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR DOUT_BUF reload age too short");
            parallel_launch_age_checks++;
            if(($realtime-parallel_ext_launch)/parallel_mem_period<parallel_min_ext_age)
                parallel_min_ext_age=$rtoi(($realtime-parallel_ext_launch)/parallel_mem_period);
            if(($realtime-parallel_fs_launch)/parallel_mem_period<parallel_min_fs_age)
                parallel_min_fs_age=$rtoi(($realtime-parallel_fs_launch)/parallel_mem_period);
            if(($realtime-parallel_ba_launch)/parallel_mem_period<parallel_min_ba_age)
                parallel_min_ba_age=$rtoi(($realtime-parallel_ba_launch)/parallel_mem_period);
            if(($realtime-parallel_buf_launch)/parallel_mem_period<parallel_min_buf_age)
                parallel_min_buf_age=$rtoi(($realtime-parallel_buf_launch)/parallel_mem_period);
            parallel_captured_word<=edata;parallel_captured_owner<=edata_select;parallel_captured_valid<=1;
            parallel_capture_checks++;
            if(edata_select[0])parallel_sprite_captures++;
            if(edata_select[1])parallel_fg0_captures++;
            if(edata_select[2])parallel_fg1_captures++;
            if(edata_select[3])parallel_cpu_captures++;
        end
    end
    always @(negedge CLK2X)if(parallel_captured_valid)begin
        assert(memory.parallel_write_capture.cache_owner===parallel_captured_owner &&
               memory.parallel_write_capture.beat_owner===parallel_captured_owner &&
               memory.write_data===parallel_captured_word && memory.write_data_o===parallel_captured_word)
            else $fatal(1,"Parallel DDR selected/held captured source differs from legacy EDATA");
    end
    // BT_PARALLEL_NATIVE_PHASE_END

    // DBUS_BE loads in the CE_R after each launch (TMS34020_MC.sv); it is
    // checked in the CPU R-phase stability view instead.
    wire [79:0] f_metadata={core.CPU.MC.DBUS_A,
        core.CPU.MC.DBUS_CODE,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DOUT_FS,
        core.CPU.MC.MC_EXT_WORD,core.CPU.MC.DATA_OLD};
    longint unsigned normal_read_phase_checks=0, write_phase_checks=0, write_edge_phase_checks=0;
    bit previous_memory_rd;
    always @(core.CPU.MC.DBUS_A) if(!reset_cpu) last_address_change=memory_ticks;
    always @(core.CPU.MC.DBUS_WE) if(!reset_cpu) last_strobe_change=memory_ticks;
    always @(f_metadata) if(!reset_cpu) last_f_metadata_change=memory_ticks;
    always @(core.CPU.MC.DBUS_CODE) if(!reset_cpu) last_code_change=memory_ticks;
    always @(core.CPU.MC.DBUS_BE) if(!reset_cpu) last_be_change=memory_ticks;
    always @(core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DOUT_FS,core.CPU.MC.MC_EXT_WORD)
        if(!reset_cpu) last_align_change=memory_ticks;
    always @(core.CPU.MC.DATA_OLD) if(!reset_cpu) last_old_data_change=memory_ticks;
    always @(core.CPU.MC.DOUT_BUF) if(!reset_cpu) last_write_buffer_change=memory_ticks;
    always @(posedge CLK2X) begin
        memory_ticks=memory_ticks+1;
        if(!reset_cpu) begin
            if(memory.cache_write_commit &&
               memory.read_addr[memory.write_cache][27:4]==memory.write_addr[27:4]) begin
                assert(memory_ticks-last_tag_change[memory.write_cache]>=2)
                    else $fatal(1,"DDR cache-patch tag budget=%0d",
                                memory_ticks-last_tag_change[memory.write_cache]);
                cache_patch_phase_checks++;
            end
            if(memory.rd && !previous_memory_rd) begin
                assert(memory_ticks-last_address_change>=2)
                    else $fatal(1,"DDR read address capture budget=%0d efg=%0d copy=%0d",
                                memory_ticks-last_address_change,efg,core.FG_HOLE_COPY);
                assert(memory_ticks-last_code_change>=2)
                    else $fatal(1,"DDR read code capture budget=%0d",memory_ticks-last_code_change);
                normal_read_phase_checks++;
            end
            // The write strobe edge detector receives the same two-memory-clock
            // address/code budget as the registers it sets (bt_ddr_phase.sdc).
            if(|memory.we && !memory.old_we) begin
                assert(memory_ticks-last_address_change>=2)
                    else $fatal(1,"DDR write strobe-edge address budget=%0d efg=%0d copy=%0d",
                                memory_ticks-last_address_change,efg,core.FG_HOLE_COPY);
                assert(memory_ticks-last_code_change>=2)
                    else $fatal(1,"DDR write strobe-edge code budget=%0d",memory_ticks-last_code_change);
                write_edge_phase_checks++;
            end
            if(memory.write_prepend && ce_r) begin
                assert(memory_ticks-last_address_change>=2)
                    else $fatal(1,"DDR write address capture budget=%0d efg=%0d copy=%0d",
                                memory_ticks-last_address_change,efg,core.FG_HOLE_COPY);
                assert(memory_ticks-last_strobe_change>=2)
                    else $fatal(1,"DDR write strobe capture budget=%0d efg=%0d copy=%0d",
                                memory_ticks-last_strobe_change,efg,core.FG_HOLE_COPY);
                assert(memory_ticks-last_align_change>=2)
                    else $fatal(1,"DDR write alignment capture budget=%0d",memory_ticks-last_align_change);
                assert(memory_ticks-last_write_buffer_change>=2)
                    else $fatal(1,"DDR write data buffer capture budget=%0d",memory_ticks-last_write_buffer_change);
                assert(memory_ticks-last_code_change>=2)
                    else $fatal(1,"DDR write code capture budget=%0d",memory_ticks-last_code_change);
                write_phase_checks++;
            end
        end
        previous_memory_rd=memory.rd;
    end
    bit bus_phase_valid, bus_phase_f, bus_phase_r;
    bit [79:0] previous_f_bus;
    bit [31:0] previous_write_buffer;
    always @(posedge CLK) begin
        bus_phase_f<=ce_f;
        bus_phase_r<=ce_r;
    end
    always @(negedge CLK) begin
        if(!reset_cpu && bus_phase_valid) begin
            if(!bus_phase_f)
                assert(f_metadata===previous_f_bus)
                    else $fatal(1,"CPU transaction metadata changed outside F phase");
            if(!bus_phase_r)
                assert(core.CPU.MC.DOUT_BUF===previous_write_buffer)
                    else $fatal(1,"CPU write buffer changed outside R phase");
        end
        previous_f_bus=f_metadata;
        previous_write_buffer=core.CPU.MC.DOUT_BUF;
        bus_phase_valid=!reset_cpu;
    end
    localparam DSP_R_WIDTH=$bits({core.BSMT.ACC,core.BSMT.AR[0],core.BSMT.AR[1],
        core.BSMT.T,core.BSMT.P,core.BSMT.ST,core.BSMT.PC,core.BSMT.STATE,
        core.BSMT.STACK[0],core.BSMT.STACK[1],core.BSMT.STACK[2],core.BSMT.STACK[3]});
    wire [DSP_R_WIDTH-1:0] dsp_r_view={core.BSMT.ACC,core.BSMT.AR[0],core.BSMT.AR[1],
        core.BSMT.T,core.BSMT.P,core.BSMT.ST,core.BSMT.PC,core.BSMT.STATE,
        core.BSMT.STACK[0],core.BSMT.STACK[1],core.BSMT.STACK[2],core.BSMT.STACK[3]};
    bit [DSP_R_WIDTH-1:0] previous_dsp_r;
    bit [31:0] previous_dsp_f;
    bit dsp_valid,dsp_edge_r,dsp_edge_f;
    longint unsigned system_ticks=0,last_dsp_r=0,last_dsp_f=0,dsp_phase_checks=0;
    always @(posedge CLK) begin
        system_ticks++;
        dsp_edge_r<=core.BSMT.CE_R;
        dsp_edge_f<=core.BSMT.CE_F;
        if(!reset_cpu && core.BSMT.RS_N) begin
            if(core.BSMT.CE_R) begin
                if(last_dsp_f) assert(system_ticks-last_dsp_f>=6) else $fatal(1,"DSP F/R phase spacing");
                if(last_dsp_r) assert(system_ticks-last_dsp_r>=13) else $fatal(1,"DSP R/R phase spacing");
                last_dsp_r=system_ticks;
                dsp_phase_checks++;
            end
            if(core.BSMT.CE_F) begin
                if(last_dsp_r) assert(system_ticks-last_dsp_r>=6) else $fatal(1,"DSP R/F phase spacing");
                last_dsp_f=system_ticks;
            end
        end else begin last_dsp_r=0;last_dsp_f=0;end
    end
    always @(negedge CLK) begin
        if(!reset_cpu && core.BSMT.RS_N && dsp_valid) begin
            if(!dsp_edge_r) assert(dsp_r_view===previous_dsp_r)
                else $fatal(1,"DSP architectural registers changed outside R phase");
            if(!dsp_edge_f) assert({core.BSMT.IC,core.BSMT.IW}===previous_dsp_f)
                else $fatal(1,"DSP instruction registers changed outside F phase");
        end
        previous_dsp_r=dsp_r_view;
        previous_dsp_f={core.BSMT.IC,core.BSMT.IW};
        dsp_valid=!reset_cpu && core.BSMT.RS_N;
    end
    integer phase_report_frames=0;
    always @(negedge VS_N) if(!reset_cpu) begin
        phase_report_frames++;
        if(phase_report_frames==1 || phase_report_frames%128==0)begin
            $display("DDR_PARALLEL_PHASE frame=%0d captures=%0d cpu=%0d sprite=%0d fg0=%0d fg1=%0d launch_age_checks=%0d ext_reloads=%0d fs_reloads=%0d ba_reloads=%0d buf_reloads=%0d min_ext=%0d min_fs=%0d min_ba=%0d min_buf=%0d probe_checks=%0d conservative_false=%0d",
                phase_report_frames,parallel_capture_checks,parallel_cpu_captures,parallel_sprite_captures,
                parallel_fg0_captures,parallel_fg1_captures,parallel_launch_age_checks,
                parallel_ext_reloads,parallel_fs_reloads,parallel_ba_reloads,parallel_buf_reloads,
                parallel_min_ext_age,parallel_min_fs_age,parallel_min_ba_age,parallel_min_buf_age,
                parallel_probe_checks,parallel_conservative_false_count);
        end
        if(phase_report_frames%128==0)
            $display("DDR_PHASE frame=%0d normal_reads=%0d accepted_writes=%0d write_edges=%0d DSP_phase_checks=%0d return_captures=%0d cache_patches=%0d physical_return_captures=%0d",
                     phase_report_frames,normal_read_phase_checks,write_phase_checks,write_edge_phase_checks,dsp_phase_checks,
                     return_phase_checks,cache_patch_phase_checks,physical_return_phase_checks);
        if(phase_report_frames%128==0)
            $display("SPRITE_SOURCE_PHASE frame=%0d checks=%0d",phase_report_frames,blit_source_checks);
        if(phase_report_frames%128==0)
            $display("DDR_Q_MIN_AGE frame=%0d memory_ticks=%0d draw_min_age=%0d rd_addr=%0d rd_tag=%0d wr_addr=%0d wr_tag=%0d",phase_report_frames,min_ddr_q_age,min_draw_age,min_rd_addr_age,min_rd_tag_age,min_wr_addr_age,min_wr_tag_age);
    end
endmodule
