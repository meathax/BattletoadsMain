module cpu_field_timing_tb;
    `include "field_functions.svh"
    bit [31:0] value;
    integer be_checks=0, ext_checks=0;
    initial begin
        for(integer ba=0;ba<32;ba++) for(integer fs=0;fs<64;fs++) begin
            assert(candidate_FastDataWriteBE(5'(ba),6'(fs)) == reference_FastDataWriteBE(5'(ba),6'(fs)))
                else $fatal(1,"byte enables differ ba=%0d fs=%0d",ba,fs);
            be_checks++;
        end
        for(integer fs=0;fs<64;fs++) for(integer op=0;op<4;op++) begin
            for(integer sample=0;sample<130;sample++) begin
                if(sample==0) value=0;
                else if(sample==1) value='1;
                else if(sample<34) value=32'b1<<(sample-2);
                else value=$urandom;
                assert(candidate_Ext(value,6'(fs),2'(op)) == reference_Ext(value,6'(fs),2'(op)))
                    else $fatal(1,"extension differs data=%h fs=%0d op=%0d",value,fs,op);
                ext_checks++;
            end
        end
        $display("PASS CPU field timing helpers: byte_enables=%0d extensions=%0d; every field size, byte offset, operation and sign-bit position",be_checks,ext_checks);
        $finish;
    end
endmodule
