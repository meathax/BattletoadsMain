`timescale 1ns/1ps
module platform_features_tb;
    reg clk=0, reset=1;
    always #6.25 clk=~clk; // Exact 80 MHz.
    wire ce_f,ce_r,vce;
    bt_clock_enables clocks(clk,reset,ce_f,ce_r,vce);
    reg new_game=0,osd_open=0,cpu_we=0,download=0,upload=0,wr=0;
    reg [12:0] cpu_addr=0;
    reg [7:0] cpu_data=0;
    reg [15:0] index=0,dout=0;
    reg [26:0] addr=0;
    wire [7:0] cpu_q;
    wire [15:0] din;
    wire req,nvram_pause,ready,cpu_ce_f,cpu_ce_r,cpu_halted;
    // Exact board request register and admitted phase/closing-write wiring.
    // The user pause term is held zero for these original platform scenarios.
    reg pause_cpu=0;
    always @(posedge clk) pause_cpu <= nvram_pause;
    bt_pause_bridge pause_bridge(.clk(clk),.reset(reset),.pause_req(pause_cpu),
        .raw_ce_f(ce_f),.raw_ce_r(ce_r),.ce_f(cpu_ce_f),.ce_r(cpu_ce_r),.halted(cpu_halted));
    bt_nvram nvram(.clk(clk),.new_game(new_game),.osd_open(osd_open),
        .cpu_addr(cpu_addr),.cpu_data(cpu_data),.cpu_we(cpu_we && cpu_ce_r),
        .cpu_q(cpu_q),.cpu_ready(ready),.ioctl_download(download),.ioctl_upload(upload),
        .ioctl_wr(wr),.ioctl_index(index),.ioctl_addr(addr),.ioctl_dout(dout),
        .ioctl_din(din),.upload_req(req),.pause_cpu(nvram_pause),.cpu_halted(cpu_halted));
    integer i,nf,nr,np,lastpixel,cycle;
    integer halt_acks=0,resumed_f=0,resumed_r=0,closing_writes=0,save_pulses=0;
    integer sys_edges=0,last_cpu_write=-1;
    reg previous_halted=0,await_resume=0,seen_resume_f=0,previous_req=0;
    always @(posedge clk) begin
        sys_edges++;
        if(!reset) begin
            if(cpu_halted && !previous_halted) begin
                halt_acks++;await_resume=1;seen_resume_f=0;
            end
            if(cpu_halted && pause_cpu && (cpu_ce_f || cpu_ce_r))
                $fatal(1,"Acknowledged platform halt emitted a CPU phase");
            if(await_resume && cpu_ce_f) begin resumed_f++;seen_resume_f=1;end
            if(await_resume && cpu_ce_r) begin
                if(!seen_resume_f)$fatal(1,"Platform resumed R before an admitted F");
                resumed_r++;await_resume=0;
            end
        end
        previous_halted=cpu_halted;
        if(nvram.cpu_write) begin
            last_cpu_write=sys_edges;
            if(nvram.save_pending)closing_writes++;
        end
        #0.02;
        if(req) begin
            if(!cpu_halted || sys_edges<=last_cpu_write || previous_req)
                $fatal(1,"Save pulse preceded settled closing R/halt or lasted multiple cycles");
            save_pulses++;
        end
        previous_req=req;
    end
    task tick;
        begin @(posedge clk); #1; @(negedge clk); end
    endtask
    task read_byte(input integer a,input [7:0] expected);
        begin
            cpu_addr=a; tick(); tick();
            if (!ready || cpu_q !== expected) $fatal(1,"NVRAM read %0d got %h expected %h",a,cpu_q,expected);
        end
    endtask
    task wait_cpu_r;
        integer guard;
        begin
            guard=0;
            while(!cpu_ce_r) begin
                @(negedge clk);#0.01;guard++;
                if(guard>10)$fatal(1,"CPU did not admit a write R");
            end
        end
    endtask
    task wait_save;
        integer guard;
        begin
            guard=0;
            while(!req)begin tick();guard++;if(guard>6)$fatal(1,"Save did not follow bounded board halt");end
            if(!pause_cpu || !cpu_halted)$fatal(1,"Save did not retain acknowledged CPU pause");
        end
    endtask
    task wait_resume;
        integer guard;
        begin
            guard=0;
            while(pause_cpu || cpu_halted)begin tick();guard++;if(guard>8)$fatal(1,"CPU did not resume after upload");end
        end
    endtask
    initial begin
        tick(); reset=0;
        nf=0;nr=0;np=0;lastpixel=-1;
        // 10,000 cycles: verify clock counts and every individual pixel interval.
        for(cycle=0;cycle<10000;cycle=cycle+1) begin
            if(ce_f && ce_r) $fatal(1,"CPU phases overlap");
            nf=nf+ce_f;nr=nr+ce_r;
            if(vce) begin
                np=np+1;
                if(lastpixel>=0 && cycle-lastpixel!=8) $fatal(1,"Pixel jitter");
                lastpixel=cycle;
            end
            tick();
        end
        if(nf!=4000 || nr!=4000 || np!=1250) $fatal(1,"Clock rates %0d %0d %0d",nf,nr,np);
        $display("PASS steady 10 MHz pixel enable (every 8 clocks), both CPU phases 32 MHz");
        if(pause_cpu) $fatal(1,"Initialization did not finish");
        for(i=0;i<8192;i=i+1) read_byte(i,0);
        // Restore all bytes through actual 16-bit WIDE transfers, with a pattern
        // distinguishing adjacent lanes, endpoints, and every address bit.
        index=4;download=1;wr=1;
        for(i=0;i<8192;i=i+2) begin
            addr=i;dout={8'(i*7+13),8'(i*3+1)};tick();
        end
        wr=0;download=0;tick();
        for(i=0;i<8192;i=i+1)
            read_byte(i,i[0] ? 8'((i-1)*7+13) : 8'(i*3+1));
        // CPU updates only the low byte lane in the TMS address map, preserving
        // its adjacent NVRAM byte in the packed host image.
        wait_cpu_r();cpu_addr=8191;cpu_data=8'ha5;cpu_we=1;tick();cpu_we=0;
        read_byte(8191,8'ha5);read_byte(8190,8'(8190*3+1));
        osd_open=1;tick();
        // A pending save must include the final admitted R write before
        // issuing its single upload pulse. Its byte stays in the upload image.
        cpu_addr=8191;cpu_data=8'ha5;cpu_we=1;wait_save();cpu_we=0;
        if(!req || !pause_cpu) $fatal(1,"OSD open did not request/pause save");
        tick();if(req) $fatal(1,"Save request is not a pulse");
        osd_open=0;tick();if(!pause_cpu) $fatal(1,"Premature resume before host upload");
        upload=1;tick();
        cpu_we=1;cpu_addr=8191;cpu_data=0;
        for(i=0;i<8192;i=i+2) begin
            addr=i;tick();tick();
            if(din !== {i==8190 ? 8'ha5 : 8'(i*7+13),8'(i*3+1)})
                $fatal(1,"Packed upload differs at %0d: %h",i,din);
        end
        cpu_we=0;upload=0;tick();tick();
        wait_resume();
        if(pause_cpu) $fatal(1,"CPU not resumed after upload");
        osd_open=1;tick();if(req) $fatal(1,"Unchanged NVRAM saved again");
        osd_open=0;tick();
        // Foreign downloads do not corrupt the battery-backed RAM.
        index=254;download=1;wr=1;addr=8190;dout=0;tick();
        download=0;wr=0;read_byte(8191,8'ha5);
        new_game=1;tick();new_game=0;repeat(4100) tick();
        read_byte(8191,0);read_byte(0,0);
        wait_resume();
        if(halt_acks<4 || resumed_f<4 || resumed_r<4 || closing_writes!=1 || save_pulses!=1)
            $fatal(1,"Missing board halt/resume/final-R/single-save coverage %0d %0d %0d %0d %0d",halt_acks,resumed_f,resumed_r,closing_writes,save_pulses);
        $display("PASS platform pause/NVRAM: halt_acks=%0d resumed_F=%0d resumed_R=%0d closing_R_writes=%0d save_pulses=%0d",halt_acks,resumed_f,resumed_r,closing_writes,save_pulses);
        $display("PASS all 8192 NVRAM bytes: zero init, wide restore/upload, CPU lanes, OSD save, pause, foreign indices, reload");
        $finish;
    end
endmodule
