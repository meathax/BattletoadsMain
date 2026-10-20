`timescale 1ns/1ps
module tms_memory_tb;
    bit clk=0;
    always #5 clk=~clk;
    bit reset_n=0,enable=1;
    wire f,r,vce;
    bt_clock_enables phases(.clk(clk),.reset(!reset_n),.ce_f(f),.ce_r(r),.vce(vce));
    bit[31:0] addr,data,pc,bus_data,mask,screen_addr;
    bit[5:0] size;
    bit[5:0] field0,field1;
    bit field_select;
    bit read_req,write_req,pixel,cache,vector_req,ready,screen_run,cst;
    wire[31:0] din0,din1,a0,a1,d0,d1;
    wire[3:0] be0,be1,code0,code1;
    wire ras0,ras1,rd0,rd1,we0,we1,cw0,cw1,wait0,wait1;
    wire rd_ext0;
    // Late pause-finish mask: must equal removing the request on the baseline.
    bit kill;
    always @(negedge clk) kill = ($urandom % 5) == 0;
    TMS34020_MC candidate(.CLK(clk),.RST_N(reset_n),.EN(enable),.CE_F(f),.CE_R(r),.RES_N(1'b1),
        .ADDR(addr),.DOUT(data),.DIN(din0),.DIN_F(),.FS(size),.FS0(field0),.FS1(field1),.FIELD_SELECT(field_select),
        .LAUNCH_KILL(kill),.READ(read_req),.WRITE(write_req),.WRITE_PRE(write_req),.PIX(pixel),
        .DBUS_ANY_BE(),.DBUS_ANY_BE_FG(),.PC(pc),.CACHE(cache),.CACHE_ADDRESS(cache),.DBUS_ADDR_CLASS(),.VRAM_REQUEST(),.PAUSE_READY(),.CACHE_WR(cw0),.VECT(vector_req),.WAIT(wait0),.PIX_WMASK(mask),
        .SCRREF_ADDR(screen_addr),.SCRREF_RUN(screen_run),.DBUS_A(a0),.DBUS_DI(bus_data),.DBUS_DI_E(bus_data),
        .DBUS_DO(d0),.DBUS_RAS(ras0),.DBUS_WE(we0),.DBUS_RD(rd0),.DBUS_RD_EXT(rd_ext0),.DBUS_BE(be0),
        .DBUS_CODE(code0),.DBUS_RDY(ready),.CST(cst));
    TMS34020_MC_BASELINE baseline(.CLK(clk),.RST_N(reset_n),.EN(enable),.CE_F(f),.CE_R(r),.RES_N(1'b1),
        .ADDR(addr),.DOUT(data),.DIN(din1),.FS(size),.READ(read_req && !kill),.WRITE(write_req && !kill),.PIX(pixel),
        .PC(pc),.CACHE(cache && !kill),.CACHE_WR(cw1),.VECT(vector_req),.WAIT(wait1),.PIX_WMASK(mask),
        .SCRREF_ADDR(screen_addr),.SCRREF_RUN(screen_run),.DBUS_A(a1),.DBUS_DI(bus_data),
        .DBUS_DO(d1),.DBUS_RAS(ras1),.DBUS_WE(we1),.DBUS_RD(rd1),.DBUS_BE(be1),
        .DBUS_CODE(code1),.DBUS_RDY(ready),.CST(cst));
    integer cycles=0,commands=0,word_cases=0,last_r=-100;
    task automatic check;
        if(reset_n && ((rd_ext0 && !rd0) || ((rd0 && code0[3]) != (rd_ext0 && code0[3]))))
            $fatal(1,"external-read strobe differs from external bus read at cycle=%0d",cycles);
        // DIN is the CPU's R-phase view: the candidate loads its early capture
        // group one CE_R before the CE_F capture, so DIN is compared only at
        // CE_R edges (where every CPU register that selects it commits).
        if({a0,d0,ras0,we0,rd0,code0,cw0,wait0}!==
           {a1,d1,ras1,we1,rd1,code1,cw1,wait1} || (r && din0!==din1))
            $fatal(1,"memory-controller cycle mismatch cycle=%0d size=%0d bitaddr=%0d din=%h/%h bus=%h/%h data=%h/%h control=%b/%b",cycles,size,addr[4:0],din0,din1,a0,a1,d0,d1,{ras0,we0,rd0,code0,cw0,wait0},{ras1,we1,rd1,code1,cw1,wait1});
        // BE now commits on CE_R. The old unstrobed CE_F value never drove
        // a CAS write lane; demand equality whenever a write or external
        // read strobe can consume it, while retaining all-cycle parity above.
        if(reset_n && (we0 || (rd0 && code0[3])) && be0!==be1)
            $fatal(1,"memory-controller active byte enables differ cycle=%0d candidate=%h baseline=%h",cycles,be0,be1);
    endtask
    initial begin
        for(integer offset=0;offset<32;offset++) begin
            for(integer width=0;width<64;width++) begin
                bit[63:0] expected_mask;
                expected_mask=TMS34020_PKG::DataWriteMask(5'(offset),6'(width));
                if(candidate.FastDataWriteMask(5'(offset),6'(width))!==expected_mask)
                    $fatal(1,"write mask mismatch bitaddr=%0d size=%0d",offset,width);
                if(candidate.FastDataWriteBE(5'(offset),6'(width))!==
                   {|expected_mask[31:24],|expected_mask[23:16],|expected_mask[15:8],|expected_mask[7:0]})
                    $fatal(1,"write byte enable mismatch bitaddr=%0d size=%0d",offset,width);
            end
        end
        repeat(4)@(negedge clk);reset_n=1;
        for(integer i=0;i<250000;i++) begin
            @(negedge clk);check();
            cycles++;
            if(r) begin
                if(cycles-last_r<2)$fatal(1,"CPU R phase has less than two-clock separation");
                last_r=cycles;
            end
            // The bus word is stable from the CE_R after READ_LATCH to the
            // CE_F capture on the board (native replay evidence): change it
            // only ahead of CE_R edges, so it holds through the idle slot and
            // the CE_F capture.
            ready=(i%13>=4);if(r) bus_data=$urandom;
            // EN is fixed high on the board. Exercise an idle pause before
            // issuing traffic; removing a single R edge during a live bus
            // handshake is not a valid CPU phase sequence.
            enable=i>=16;
            screen_run=enable && r && i%257==0;
            screen_addr=$urandom;
            // CPU control changes after R; place the next request before F.
            if(f && !wait0 && enable) begin
                addr=$urandom;data=$urandom;pc=$urandom & 32'hfffffff0;
                size=(word_cases%32)+1;addr[4:0]=(word_cases/32)%32;
                field_select=word_cases%2;
                field0=field_select ? 6'($urandom) : size;
                field1=field_select ? size : 6'($urandom);
                cache=word_cases%7==0;
                read_req=!cache && word_cases%3==0;write_req=!cache && word_cases%3==1;
                pixel=!cache && word_cases%4==0;vector_req=read_req && word_cases%11==0;
                mask=$urandom;cst=word_cases%5==0;
                word_cases++;
            end
            if(r && ready && (rd0 || we0))commands++;
            #1;check();
        end
        if(commands<1000 || word_cases<4096)$fatal(1,"memory-controller coverage incomplete: commands=%0d fields=%0d wait=%b state=%b pend=%b%b%b%b%b",commands,word_cases,wait0,candidate.MC_STATE,candidate.MC_READ_PEND,candidate.MC_WRITE_PEND,candidate.MC_WRITE_PEND2,candidate.MC_FETCH_PEND,candidate.MC_SCRREF_PEND);
        $display("PASS memory-controller equivalence: %0d cycles, %0d commands, %0d field/offset cases; stalls, extended fields, RMW, pixels, cache, refresh, pause; R spacing >=2",cycles,commands,word_cases);
        $finish;
    end
endmodule
