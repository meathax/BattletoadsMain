`timescale 1ns/1ps
// PIX_WE predecode (PatternBitView + PatternWriteNE + PatternWriteEval) against the
// original PatternWritable(transparent_source, transparent_color, PSIZE) expression.
module pix_we_predecode_tb;
    longint unsigned cases = 0, writes = 0;
    function automatic bit ref_we(input bit [31:0] bset, c0, c1, input bit [4:0] px,
                                  input bit [2:0] tm, input bit t, input bit [5:0] ps);
        bit [31:0] bitmap, src, col;
        bitmap = TMS34020_PKG_BASELINE::PatternExpand(bset, c0, c1, px, ps);
        src = tm == 3'b101 ? 32'b0 : bitmap;
        col = c0 & {32{tm[0]}};
        casex ({t,tm})
            4'b1x0x: return TMS34020_PKG_BASELINE::PatternWritable(src, col, ps);
            default: return 1'b1;
        endcase
    endfunction
    task automatic check(input bit [31:0] bset, c0, c1, input bit [4:0] px,
                         input bit [2:0] tm, input bit t, input bit [5:0] ps);
        bit [63:0] ne; bit [31:0] view, mask, wmask_ref, pat_ref, pat0, pat1, tmask, expand; bit got, want;
        ne = TMS34020_PKG::PatternWriteNE(c0, c1, tm, t, ps);
        view = TMS34020_PKG::PatternBitView(bset, px, ps);
        mask = TMS34020_PKG::PatternWriteMask(ne, view);
        got = |mask;
        want = ref_we(bset, c0, c1, px, tm, t, ps);
        if (got !== want)
            $fatal(1,"PIX_WE mismatch bset=%h c0=%h c1=%h px=%0d tm=%b t=%b ps=%0d got=%b want=%b",
                   bset,c0,c1,px,tm,t,ps,got,want);
        // original TMASK of the PATS_B source
        expand = TMS34020_PKG_BASELINE::PatternExpand(bset, c0, c1, px, ps);
        pat0 = tm == 3'b101 ? 32'b0 : expand;
        pat1 = c0 & {32{tm[0]}};
        casex ({t,tm})
            4'b1x0x: tmask = TMS34020_PKG_BASELINE::PatternEqual(pat0, pat1, ps);
            default: tmask = 0;
        endcase
        wmask_ref = ~tmask;
        if (mask !== wmask_ref)
            $fatal(1,"PIX_WMASK mismatch bset=%h c0=%h c1=%h px=%0d tm=%b t=%b ps=%0d got=%h want=%h",
                   bset,c0,c1,px,tm,t,ps,mask,wmask_ref);
        if (((view & c1) | (~view & c0)) !== expand)
            $fatal(1,"PIX_PAT mismatch bset=%h c0=%h c1=%h px=%0d ps=%0d",bset,c0,c1,px,ps);
        cases++; writes += want;
    endtask
    bit [5:0] psizes[10] = '{6'h01,6'h02,6'h04,6'h08,6'h10,6'h20,6'h00,6'h03,6'h3f,6'h07};
    // random colour biased towards equal/zero lanes so the compare is exercised both ways
    function automatic bit [31:0] rcol(input bit [31:0] other, input bit [5:0] ps);
        bit [31:0] r; int k;
        r = $urandom(); k = $urandom_range(0,5);
        case (k)
            0: r = other;
            1: r = 0;
            2: r = other ^ (32'b1 << $urandom_range(0,31));
            3: r = other & $urandom();
            4: r = {32{$urandom_range(0,1)}};
            default: ;
        endcase
        return r;
    endfunction
    initial begin
        // directed: every ps, px, tm, t with extreme colours/bitmaps
        for (int p = 0; p < 10; p++) for (int px = 0; px < 32; px++) for (int tm = 0; tm < 8; tm++) for (int t = 0; t < 2; t++) begin
            bit [31:0] bs[4]; bit [31:0] cs[4];
            bs = '{32'h0,32'hffffffff,32'h55555555,32'haaaaaaaa};
            cs = '{32'h0,32'hffffffff,32'h12345678,32'h80000001};
            for (int a = 0; a < 4; a++) for (int b = 0; b < 4; b++) for (int c = 0; c < 4; c++)
                check(bs[a], cs[b], cs[c], px[4:0], tm[2:0], t[0], psizes[p]);
        end
        // randomized
        for (int n = 0; n < 6000000; n++) begin
            bit [31:0] c0, c1, bset; bit [5:0] ps;
            ps = psizes[$urandom_range(0,9)];
            if ($urandom_range(0,3) != 0) ps = psizes[$urandom_range(0,5)];
            c0 = $urandom(); c1 = rcol(c0, ps); if ($urandom_range(0,3)==0) c0 = rcol(c1, ps);
            bset = $urandom(); if ($urandom_range(0,7)==0) bset = 0; if ($urandom_range(0,7)==0) bset = '1;
            check(bset, c0, c1, $urandom_range(0,31), $urandom_range(0,7), $urandom_range(0,1), ps);
        end
        $display("pix_we_predecode_tb PASS cases=%0d writes=%0d", cases, writes);
        $finish;
    end
endmodule
