`timescale 1ns/1ps
module tms_carry_tb;
    integer cases16=0,cases32=0,cases_ext=0,cases_xy=0;
    bit [31:0] values[12]='{0,1,2,32'h7fff,32'h8000,32'hffff,
        32'h10000,32'h7fffffff,32'h80000000,32'hffffffff,32'h55555555,32'haaaaaaaa};
    task automatic check16(input bit[15:0] a,b,input bit ci);
        if(TMS34020_PKG::CarryAdder16(a,b,ci)!==TMS34020_PKG_BASELINE::CarryAdder16(a,b,ci))
            $fatal(1,"16-bit carry mismatch a=%h b=%h ci=%b",a,b,ci);
        cases16++;
    endtask
    task automatic checkext(input bit[31:0] a);
        for(integer fs=0;fs<64;fs++)for(integer op=0;op<4;op++) begin
            if(TMS34020_PKG::Ext(a,fs[5:0],op[1:0])!==
               TMS34020_PKG_BASELINE::Ext(a,fs[5:0],op[1:0]))
                $fatal(1,"field extension mismatch a=%h fs=%0d op=%0d",a,fs,op);
            cases_ext++;
        end
    endtask
    task automatic checkxy(input bit[31:0] a,limits);
        for(integer en=0;en<2;en++) begin
            if(TMS34020_PKG::XYAdjust(a,limits,en[0])!==
               TMS34020_PKG_BASELINE::XYAdjust(a,limits,en[0]))
                $fatal(1,"coordinate wrap mismatch a=%h limits=%h en=%0d",a,limits,en);
            cases_xy++;
        end
    endtask
    task automatic check32(input bit[31:0] a,b);
        for(integer flags=0;flags<32;flags++) begin
            if(TMS34020_PKG::CarryAdder(a,b,flags[0],flags[2:1],flags[3],flags[4])!==
               TMS34020_PKG_BASELINE::CarryAdder(a,b,flags[0],flags[2:1],flags[3],flags[4]))
                $fatal(1,"32-bit carry/XY mismatch a=%h b=%h flags=%h",a,b,flags);
            cases32++;
        end
    endtask
    initial begin
        for(integer a=0;a<65536;a++)
            for(integer ci=0;ci<2;ci++) begin
                check16(a[15:0],0,ci[0]);
                check16(a[15:0],16'hffff,ci[0]);
                check16(a[15:0],~a[15:0],ci[0]);
                check16(a[15:0],a[15:0],ci[0]);
            end
        foreach(values[a])foreach(values[b])check32(values[a],values[b]);
        repeat(20000)check32($urandom,$urandom);
        foreach(values[a])checkext(values[a]);
        repeat(5000)checkext($urandom);
        foreach(values[x])foreach(values[y])foreach(values[mx])foreach(values[my])
            checkxy({values[y][15:0],values[x][15:0]},
                    {values[my][15:0],values[mx][15:0]});
        // Every Y, including 16-bit overflow, at and beside the wrap boundary.
        for(integer y=0;y<65536;y++)for(integer boundary=0;boundary<4;boundary++)begin
            bit[15:0] maxy;
            case(boundary)
                0:maxy=y[15:0];
                1:maxy=y[15:0]+16'd1;
                2:maxy=0;
                3:maxy=16'hffff;
            endcase
            checkxy({y[15:0],16'h0000},{maxy,16'h0000});
            checkxy({y[15:0],16'h0000},{maxy,16'h0001});
        end
        repeat(100000)checkxy($urandom,$urandom);
        $display("PASS CPU math: carry16=%0d carry32=%0d extension=%0d coordinate_wrap=%0d",cases16,cases32,cases_ext,cases_xy);
        $finish;
    end
endmodule
