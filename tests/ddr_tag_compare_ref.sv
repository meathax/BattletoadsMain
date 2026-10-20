// Compare before selecting a request address. Late foreground transfer flags
// select one-bit matches instead of a wide address followed by a comparator.
module bt_ddr_tag_compare_ref #(parameter BOARD_ADDRESS_CLASSES=0) (
    input [3:0][23:0] tags,
    input [4:0][22:0] addresses,
    input [4:0] select_address,
    input eram,efg,envram,espr,erom,
    output [3:0] hit
);
    wire bank_ram=eram;
    wire bank_fg=!eram && efg;
    wire bank_nv=!eram && !efg && envram;
    wire bank_sp=!eram && !efg && !envram && espr;
    wire bank_rom=!eram && !efg && !envram && !espr && erom;
    wire valid_bank=eram || efg || envram || espr || erom;
    genvar bank,candidate;
    generate for(bank=0;bank<4;bank=bank+1) begin : tag_bank
        wire [4:0] candidate_hits;
        for(candidate=0;candidate<5;candidate=candidate+1) begin : tag_candidate
            (* keep = "true" *) wire low_match=tags[bank][16:0]==addresses[candidate][20:4];
            if (BOARD_ADDRESS_CLASSES && candidate<4) begin : foreground_class
                // These alternatives assert EFG by construction. Keep the
                // existing ERAM priority even if the CPU address overlaps.
                wire prefix_match=(eram && tags[bank][23:17]==7'h04) ||
                                  (!eram && tags[bank][23:17]==7'h10);
                assign candidate_hits[candidate]=low_match && prefix_match && select_address[candidate];
            end else if (BOARD_ADDRESS_CLASSES) begin : cpu_class
                // The final alternative is selected only when EFG is low.
                wire valid_cpu=eram || envram || espr || erom;
                wire prefix_match=
                    (eram && tags[bank][23:17]==7'h04) ||
                    (!eram && envram && tags[bank][23:17]==7'h08) ||
                    (!eram && !envram && espr && tags[bank][23:17]==7'h0c) ||
                    (!eram && !envram && !espr && erom && tags[bank][23:19]==0 &&
                     tags[bank][18:17]==addresses[candidate][22:21]);
                assign candidate_hits[candidate]=select_address[candidate] &&
                    (valid_cpu ? low_match && prefix_match : tags[bank]==0);
            end else begin : arbitrary_classes
            (* keep = "true" *) wire prefix_match=
                (bank_ram && tags[bank][23:17]==7'h04) ||
                (bank_fg && tags[bank][23:17]==7'h10) ||
                (bank_nv && tags[bank][23:17]==7'h08) ||
                (bank_sp && tags[bank][23:17]==7'h0c) ||
                (bank_rom && tags[bank][23:19]==0 &&
                 tags[bank][18:17]==addresses[candidate][22:21]);
            assign candidate_hits[candidate]=low_match && prefix_match && select_address[candidate];
            end
        end
        assign hit[bank]=BOARD_ADDRESS_CLASSES ? |candidate_hits :
                         valid_bank ? |candidate_hits : tags[bank]==0;
    end endgenerate
endmodule
