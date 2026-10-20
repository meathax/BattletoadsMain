`timescale 1ns/1ps
module tms_arithmetic_tb;
    bit [63:0] acc, shift;
    bit [31:0] operand, alu;
    bit [5:0] step;
    bit neg;
    bit [2:0] accs, shs;
    wire [63:0] result, old_result, shifted, old_shifted;
    wire carry, old_carry, zero, old_zero;
    md_candidate candidate(.MD_ACC(acc),.MD_SHIFT(shift),.RF_RA_Q(operand),.ALU_R(alu),
        .MD_STEP(step),.MD_NEG(neg),.accs(accs),.shs(shs),
        .MDALU_R(result),.MDSHT_R(shifted),.MDALU_C(carry),.MDALU_Z(zero));
    md_baseline baseline(.MD_ACC(acc),.MD_SHIFT(shift),.RF_RA_Q(operand),.ALU_R(alu),
        .MD_STEP(step),.MD_NEG(neg),.accs(accs),.shs(shs),
        .MDALU_R(old_result),.MDSHT_R(old_shifted),.MDALU_C(old_carry),.MDALU_Z(old_zero));
    integer checks=0;
    function automatic [63:0] boundary(input integer index);
        case(index)
            0: boundary=0;
            1: boundary=1;
            2: boundary='1;
            3: boundary=64'h8000000000000000;
            4: boundary=64'h7fffffffffffffff;
            5: boundary=64'hffffffff00000000;
            6: boundary=64'h0000000080000000;
            default: boundary=64'h000000007fffffff;
        endcase
    endfunction
    task automatic check;
        #1;
        if({carry,zero,result,shifted} !== {old_carry,old_zero,old_result,old_shifted})
            $fatal(1,"MD mismatch mode=%0d shift=%0d step=%0d neg=%0d acc=%h operand=%h alu=%h",
                accs,shs,step,neg,acc,operand,alu);
        checks++;
    endtask
    initial begin
        for(integer mode=0;mode<8;mode++)
            for(integer smode=0;smode<8;smode++)
                for(integer s=0;s<64;s++)
                    for(integer sign=0;sign<2;sign++)
                        for(integer value=0;value<8;value++) begin
                            accs=mode; shs=smode; step=s; neg=sign;
                            acc=boundary(value); shift=boundary((value+3)%8);
                            alu=boundary((value+5)%8); operand=boundary((value+6)%8);
                            check();
                        end
        for(integer i=0;i<200000;i++) begin
            accs=$urandom; shs=$urandom; step=$urandom; neg=$urandom;
            acc={32'($urandom),32'($urandom)};
            shift={32'($urandom),32'($urandom)};
            operand=$urandom; alu=$urandom;
            check();
        end
        $display("PASS TMS34020 arithmetic: %0d production/baseline multiply-divide-load results, carry, zero and shift outputs",checks);
        $finish;
    end
endmodule
