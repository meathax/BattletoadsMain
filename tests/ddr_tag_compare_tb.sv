`timescale 1ns/1ps
// The restructured compare is checked against the original board-class
// compare (ddr_tag_compare_ref.sv) and against the complete address mapping.
// The restructure only promises the addressed bank (ddr_addr[24:23]) and the
// legal candidate/EFG combinations (one-hot, candidate 4 <=> !EFG).
module ddr_tag_compare_tb;
    bit clk=0;
    bit [3:0][23:0] tags;
    bit [4:0][22:0] addresses;
    bit [4:0] select_address;
    bit eram,efg,envram,espr,erom;
    wire [3:0] hit,ref_hit;
    wire [2:0] hit_part;
    integer checks=0, hits=0, misses=0;
    bt_ddr_tag_compare dut(.*);
    bt_ddr_tag_compare_ref #(.BOARD_ADDRESS_CLASSES(1)) ref_dut(.hit(ref_hit),.tags(tags),
        .addresses(addresses),.select_address(select_address),.eram(eram),.efg(efg),
        .envram(envram),.espr(espr),.erom(erom));
    function automatic bit[27:0] original_address(input bit[22:0] selected);
        return eram ? {7'b0000100,selected[20:0]} :
               efg ? {7'b0010000,selected[20:0]} :
               envram ? {7'b0001000,selected[20:0]} :
               espr ? {7'b0001100,selected[20:0]} :
               erom ? {5'b00000,selected} : 28'b0;
    endfunction
    // ddr_addr[24:23] of Arcade-Battletoads.sv (the controller's cache bank).
    function automatic bit[1:0] cache_bank();
        bit fg=!eram && efg;
        bit nv=!eram && !efg && envram;
        bit sp=!eram && !efg && !envram && espr;
        return {nv|sp,eram|sp};
    endfunction
    task automatic tick();
        #1 clk=1; #1 clk=0; #1;
    endtask
    task automatic check_address(input integer chosen,input integer pattern,input integer tagmode);
        bit [27:0] expected;
        bit [1:0] bank;
        bit expected_hit;
        for(integer candidate=0;candidate<5;candidate++) addresses[candidate]=23'($urandom);
        if(pattern<23) addresses[chosen]=23'b1<<pattern;
        else if(pattern==23) addresses[chosen]=0;
        else if(pattern==24) addresses[chosen]='1;
        select_address=5'b1<<chosen;
        expected=original_address(addresses[chosen]);
        bank=cache_bank();
        for(integer b=0;b<4;b++) begin
            case((tagmode+b)%6)
                0: tags[b]=expected[27:4];
                1: tags[b]=expected[27:4] ^ (24'b1<<((checks+b)%24));
                2: tags[b]=24'($urandom);
                3: tags[b]=0;
                4: tags[b]={7'($urandom_range(0,3)*4+(b==0?0:b==1?1:b==2?2:3)),expected[20:4]};
                default: tags[b]={expected[27:21]^7'(1<<($urandom_range(0,6))),expected[20:4]};
            endcase
        end
        // A mismatching or matching tag of every class for the ROM region.
        if(tagmode>=6) tags[bank][23:17]=7'(tagmode*5);
        tick();
        #1;
        expected_hit=tags[bank]==expected[27:4];
        assert(hit[bank]==expected_hit && ref_hit[bank]==expected_hit)
            else $fatal(1,"DDR tag mismatch regions=%b chosen=%0d bank=%0d expected=%h tag=%h hit=%b ref=%b",
                        {eram,efg,envram,espr,erom},chosen,bank,expected,tags[bank],hit,ref_hit);
        assert((!(|hit_part))==!ref_hit[bank])
            else $fatal(1,"DDR miss mismatch regions=%b chosen=%0d bank=%0d expected=%h tag=%h",
                        {eram,efg,envram,espr,erom},chosen,bank,expected,tags[bank]);
        if(expected_hit) hits++; else misses++;
        checks++;
    endtask
    initial begin
        for(integer regions=0;regions<32;regions++) begin
            {eram,efg,envram,espr,erom}=5'(regions);
            // Legal candidate/EFG combinations only: candidates 0..3 with EFG, candidate 4 without.
            for(integer chosen=0;chosen<5;chosen++) begin
                if((chosen==4)==efg) continue;
                for(integer pattern=0;pattern<26;pattern++)
                    for(integer mode=0;mode<8;mode++) check_address(chosen,pattern,mode);
            end
        end
        repeat(200000) begin
            {eram,efg,envram,espr,erom}=5'($urandom);
            check_address(efg ? $urandom_range(0,3) : 4,25,$urandom_range(0,11));
        end
        $display("PASS DDR tag compare: %0d addressed-bank checks (%0d hits, %0d misses) against the original board classes and the complete address map, all 32 region combinations, five alternatives, every address/tag bit",checks,hits,misses);
        $finish;
    end
endmodule
