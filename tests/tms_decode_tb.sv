`timescale 1ns/1ps
module tms_decode_tb;
    bit [15:0] instruction;
    bit [4:0] state;
    bit [19:0] flags;
    wire [31:0] state_oh=32'b1 << state;
    TMS34020_PKG::DecInstr_t current;
    TMS34020_PKG::DecInstr_t flipped;
    TMS34020_PKG_BASELINE::DecInstr_t original;
    TMS34020_ID candidate(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b1),.CE_R(1'b1),
        .IC(instruction),.STATE(state),.STATE_OH(state_oh),
        .MD_COND(flags[0]),.MD_NEG(flags[1]),.DIV_V(flags[2]),.J_COND(flags[3]),
        .DS_COND(flags[4]),.MM_COND(flags[5]),.FE0(flags[6]),.FE1(flags[7]),
        .RP_COND(flags[8]),.LINE_GZ(flags[9]),.LINE_COND(flags[10]),
        .PIX_XEND(flags[11]),.PIX_YEND(flags[12]),.PIX_WINEN(flags[13]),
        .PIX_WINCC(flags[17:14]),.PIX_BL(flags[18]),.PIX_WE(flags[19]),.DECI(current));
    TMS34020_ID predicate_check(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b1),.CE_R(1'b1),
        .IC(instruction),.STATE(state),.STATE_OH(state_oh),
        .MD_COND(flags[0]),.MD_NEG(flags[1]),.DIV_V(flags[2]),.J_COND(flags[3]),
        .DS_COND(flags[4]),.MM_COND(flags[5]),.FE0(flags[6]),.FE1(flags[7]),
        .RP_COND(flags[8]),.LINE_GZ(flags[9]),.LINE_COND(flags[10]),
        .PIX_XEND(flags[11]),.PIX_YEND(flags[12]),.PIX_WINEN(flags[13]),
        .PIX_WINCC(flags[17:14]),.PIX_BL(flags[18]),.PIX_WE(!flags[19]),.DECI(flipped));
    TMS34020_ID_BASELINE baseline(.CLK(1'b0),.RST_N(1'b1),.EN(1'b1),.CE_F(1'b1),.CE_R(1'b1),
        .IC(instruction),.STATE(state),
        .MD_COND(flags[0]),.MD_NEG(flags[1]),.DIV_V(flags[2]),.J_COND(flags[3]),
        .DS_COND(flags[4]),.MM_COND(flags[5]),.FE0(flags[6]),.FE1(flags[7]),
        .RP_COND(flags[8]),.LINE_GZ(flags[9]),.LINE_COND(flags[10]),
        .PIX_XEND(flags[11]),.PIX_YEND(flags[12]),.PIX_WINEN(flags[13]),
        .PIX_WINCC(flags[17:14]),.PIX_BL(flags[18]),.PIX_WE(flags[19]),.DECI(original));
    integer decodes=0, masks=0, one_bit_masks=0, simultaneous_writes=0;
    integer logical_ops=0,logical_shifts=0;
    task automatic decode_check;
        TMS34020_PKG::DecInstr_t normalized;
        #1;
        if(current.ALU.OP==TMS34020_PKG::ALUOP_LOG) begin
            logical_ops++;
            if(current.SHC.AMS!=TMS34020_PKG::SS_CONST || current.AIB.CV!=TMS34020_PKG::CV_0) begin
                logical_shifts++;
                if(logical_shifts<=4)
                    $display("logical shift instruction=%h state=%0d ams=%h cv=%h shop=%h",instruction,state,current.SHC.AMS,current.AIB.CV,current.SHC.SHOP);
            end
        end
        if(current.RWA.WS==3'b100 || current.RWB.WS==3'b100)
            $fatal(1,"decoder selected an undefined register-write source instruction=%h state=%0d",instruction,state);
        if(current!==original)
            $fatal(1,"decoder mismatch instruction=%h state=%0d flags=%h current=%h original=%h",
                instruction,state,flags,current,original);
        if(current!==flipped) begin
            if(current.PIXO.PATS!=TMS34020_PKG::PATS_B || flipped.PIXO.PATS!=TMS34020_PKG::PATS_B)
                $fatal(1,"PIX_WE used outside bitmap expansion instruction=%h state=%0d",instruction,state);
            normalized=flipped;
            normalized.MC.AT=current.MC.AT;
            if(normalized!==current)
                $fatal(1,"PIX_WE changes a non-write decoder output instruction=%h state=%0d",instruction,state);
        end
        decodes++;
        if(current.RWA.WE && current.RWB.WE) begin
            simultaneous_writes++;
            if(simultaneous_writes<=4)
                $display("simultaneous register writes instruction=%h state=%0d flags=%h",instruction,state,flags);
        end
    endtask
    task automatic mask_check(input bit [31:0] pat,col,input bit [5:0] size);
        bit [31:0] expected;
        expected=TMS34020_PKG_BASELINE::PatternEqual(pat,col,size);
        if(size==1) begin
            // MAME write_pixel_t_1: the low source bit writes only when nonzero.
            // Apply that scalar rule to each lane, with the configured transparent
            // color removed first (CONTROL.TM=0 selects zero).
            for(integer lane=0;lane<32;lane++)
                expected[lane]=!((pat[lane]^col[lane]) & 1'b1);
            one_bit_masks++;
        end
        if(TMS34020_PKG::PatternEqual(pat,col,size)!==expected)
            $fatal(1,"transparency lane mask mismatch pat=%h col=%h size=%0d",pat,col,size);
        if(TMS34020_PKG::PatternWritable(pat,col,size) !==
           (|~expected))
            $fatal(1,"aggregate transparency mismatch pat=%h col=%h size=%0d",pat,col,size);
        masks++;
    endtask
    initial begin
        for(integer profile=0;profile<2;profile++) begin
            flags=profile ? '1 : '0;
            for(integer code=0;code<65536;code++)
                for(integer s=0;s<32;s++) begin
                    instruction=code; state=s; decode_check();
                end
        end
        for(integer flag=0;flag<20;flag++)
            for(integer code=0;code<4096;code++) begin
                flags=20'b1 << flag; instruction=code*17; state=code%32;
                decode_check();
            end
        for(integer i=0;i<200000;i++) begin
            flags=$urandom; instruction=$urandom; state=$urandom; decode_check();
        end
        for(integer size=0;size<64;size++)
            for(integer bit_number=0;bit_number<33;bit_number++) begin
                mask_check(0,bit_number==32 ? 0 : 32'b1<<bit_number,size);
                mask_check('1,bit_number==32 ? '1 : ~(32'b1<<bit_number),size);
            end
        for(integer i=0;i<200000;i++) begin
            bit [31:0] pat,col;
            pat=$urandom; col=(i%2) ? pat : $urandom;
            mask_check(pat,col,$urandom);
        end
        $display("PASS TMS34020: %0d full decode comparisons; %0d lane/aggregate transparency comparisons, all 64 size encodings (%0d MAME 1-bit cases); simultaneous register writes=%0d",decodes,masks,one_bit_masks,simultaneous_writes);
        $display("logical_ops=%0d logical_shifts=%0d",logical_ops,logical_shifts);
        $finish;
    end
endmodule
