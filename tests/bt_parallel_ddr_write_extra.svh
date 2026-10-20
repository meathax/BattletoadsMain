// Inserted verbatim into the immutable DDR-cache fixture by the qualifier.
// The source module is generated from the actual BT assignments, including
// the retained legacy EDATA expression used by the original controller.
    integer owner_override=-1;
    wire [2:0] source_case=owner_override<0 ? 3'(cycles%8) : 3'(owner_override);
    wire [3:0][31:0] raw_sources;
    wire [3:0] raw_owner;
    wire [31:0] accepted_data;
    bt_parallel_ddr_source source_mux(
        .SPR_DDR_REQ(source_case[2]),.FG_HOLE_COPY(source_case[1]),.FG0_HOLE_SEL(source_case[0]),
        .SPR_DRAW_DATA(data[7:0]),.FG0_HOLE_DATA(data^32'h0123abc0),
        .FG1_HOLE_DATA(data^32'h4567caff),.LDO(data),
        .EDATA(accepted_data),.EDATA_CANDIDATES(raw_sources),.EDATA_SELECT(raw_owner));
    wire [3:0] external_hits;
    for(genvar hit=0;hit<4;hit++)
        assign external_hits[hit]=original.read_addr[hit][27:4]==address[27:4];
    wire [2:0] external_miss_parts={2'b0,external_hits[bank]};
    integer acceptance_checks=0, hold_checks=0, reset_blocks=0, priority_collisions=0;
    integer owners_seen[4], masks_seen[4][16];
    integer full_state_checks=0, simultaneous_io_cpu=0, fills_with_patch=0;
    logic [31:0] last_accepted=0;
    bit captured_once=0;
    always @(posedge clk) begin
        if(reset && candidate.write_prepend && sclk) reset_blocks++;
        if(!reset && candidate.write_prepend && sclk) begin
            assert($onehot(raw_owner)) else $fatal(1,"Invalid source owner at acceptance");
            last_accepted=accepted_data;captured_once=1;acceptance_checks++;
            for(integer owner=0;owner<4;owner++)if(raw_owner[owner])begin
                owners_seen[owner]++;masks_seen[owner][write_be]++;
            end
            if(source_case[2] && source_case[1])priority_collisions++;
        end else if(captured_once)hold_checks++;
        if(candidate.write_prepend && sclk && io_write)simultaneous_io_cpu++;
        if(ready && candidate.state==4 && candidate.cache_write_commit)fills_with_patch++;
        #1;
        if(captured_once)begin
            assert(candidate.write_data===last_accepted && candidate.write_data_o===last_accepted &&
                   original.write_data===last_accepted && serial.write_data===last_accepted &&
                   serial.write_data_o===last_accepted)
                else $fatal(1,"Accepted/held write word changed cycle=%0d",cycles);
        end
        assert({candidate.state,candidate.rpos,candidate.write_addr,candidate.write_be,
                candidate.write_cache,candidate.write_pend,candidate.write_prepend,
                candidate.cache_write_commit,candidate.write_tag_hit,candidate.read_bank_sel,
                candidate.read_return_sel,candidate.read_busy,candidate.write_busy,
                candidate.burst_write_busy,candidate.burst_read_busy}===
               {original.state,original.rpos,original.write_addr,original.write_be,
                original.write_cache,original.write_pend,original.write_prepend,
                original.cache_write_commit,original.write_tag_hit,original.read_bank_sel,
                original.read_return_sel,original.read_busy,original.write_busy,
                original.burst_write_busy,original.burst_read_busy})
            else $fatal(1,"Controller state/metadata changed cycle=%0d",cycles);
        assert({busy2,rd2,wr2,io_busy2,burst_tick2}==={busy1,rd1,wr1,io_busy1,burst_tick1})
            else $fatal(1,"Default interface handshake changed cycle=%0d",cycles);
        if(rd1 || wr1)assert({a2,d2,be2,len2}==={a1,d1,be1,len1})
            else $fatal(1,"Default interface DDR payload changed cycle=%0d",cycles);
        if(read_req && !busy1)assert(q2===q1)
            else $fatal(1,"Default interface cache word changed cycle=%0d",cycles);
        if(io_read && !io_busy1)assert(io_q2===io_q1)
            else $fatal(1,"Default interface I/O word changed cycle=%0d",cycles);
        if(burst_tick1)assert({burst_q2,burst_pos2}==={burst_q1,burst_pos1})
            else $fatal(1,"Default interface full64-bit burst changed cycle=%0d",cycles);
        full_state_checks++;
    end
    for(genvar bank_index=0;bank_index<4;bank_index++)begin: parallel_cache_checks
        always @(posedge clk)begin
            #1;
            assert(candidate.read_addr[bank_index]===original.read_addr[bank_index] &&
                   candidate.read_word_sel[bank_index]===original.read_word_sel[bank_index])
                else $fatal(1,"Read metadata changed bank=%0d",bank_index);
        end
        for(genvar word_index=0;word_index<4;word_index++)begin: words
            always @(posedge clk)begin
                #1;
                assert(candidate.rbuf[bank_index][word_index]===original.rbuf[bank_index][word_index] &&
                       candidate.cache_store_bank[bank_index].cache_store_word[word_index].fill_data===
                       original.cache_store_bank[bank_index].cache_store_word[word_index].fill_data &&
                       candidate.cache_store_bank[bank_index].cache_store_word[word_index].patch_data===
                       original.cache_store_bank[bank_index].cache_store_word[word_index].patch_data &&
                       candidate.cache_store_bank[bank_index].cache_store_word[word_index].patch_valid===
                       original.cache_store_bank[bank_index].cache_store_word[word_index].patch_valid)
                    else $fatal(1,"Cache fill/patch byte changed bank=%0d word=%0d",bank_index,word_index);
            end
        end
    end
    task automatic parallel_extra;
        for(integer source=0;source<8;source++)begin
            owner_override=source;
            for(integer cache_id=0;cache_id<4;cache_id++)
                for(integer mask=1;mask<16;mask++)begin
                    write_word(27'h50000+cache_id*8+mask*2,cache_id[1:0],$urandom,mask[3:0]);
                    read_word(27'h50000+cache_id*8+mask*2,cache_id[1:0]);
                end
        end
        // A reset arriving with a pending write and sclk blocks acceptance.
        // Keep state idle, so the reset does not abort an outstanding DDR beat.
        for(integer reset_phase=0;reset_phase<10;reset_phase++)begin
            wait_idle();while(cycles%10!=reset_phase)tick();
            address=27'h60000;data=$urandom;write_be=4'hf;
            tick();reset=1;repeat(10)tick();write_be=0;reset=0;repeat(3)tick();wait_idle();
        end
        // Real overlapping request flags exercise the unchanged arbitration.
        for(integer overlap=0;overlap<32;overlap++)begin
            wait_idle();owner_override=overlap%8;bank=overlap%4;
            address=27'h70000+overlap*16;read_req=1;
            repeat(overlap%8+1)tick();write_be=4'hf;data=$urandom;
            io_address=27'h30000+overlap*2;io_data=$urandom;io_write=4'hf;
            repeat(4)tick();wait_idle();while(io_busy0 || wr0)tick();
            write_be=0;read_req=0;io_write=0;repeat(3)tick();
        end
        owner_override=-1;
        for(integer owner=0;owner<4;owner++)begin
            assert(owners_seen[owner]>0)else $fatal(1,"Owner coverage missing");
            for(integer mask=1;mask<16;mask++)
                assert(masks_seen[owner][mask]>0)else $fatal(1,"Owner/byte-mask coverage missing");
        end
        assert(reset_blocks>0 && priority_collisions>0 && hold_checks>0 && simultaneous_io_cpu>0)
            else $fatal(1,"Pending-reset/priority/hold/collision coverage missing");
        $display("PARALLEL_DDR_PASS acceptance=%0d hold=%0d reset_blocks=%0d priority_collisions=%0d state_checks=%0d io_cpu=%0d fill_patch=%0d owners=%0d,%0d,%0d,%0d owner_masks=60",
            acceptance_checks,hold_checks,reset_blocks,priority_collisions,full_state_checks,
            simultaneous_io_cpu,fills_with_patch,owners_seen[0],owners_seen[1],owners_seen[2],owners_seen[3]);
    endtask
