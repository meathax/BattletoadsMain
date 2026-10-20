# Diagnostic only: isolate remaining paths in a fitted snapshot. No assembly.
package require ::quartus::project
package require ::quartus::sta
project_open [lindex $quartus(args) 0]
create_timing_netlist -model slow -voltage 1100 -temperature 100 -force_dat
read_sdc
set sys_clock [get_clocks {*emu|pll|*general[0]*|divclk}]
set mem_clock [get_clocks {*emu|pll|*general[1]*|divclk}]
set return_words [get_registers {*|CPU|MC|READ_WORD* *|CPU|MC|DATA_OLD*}]
set cache_inputs [get_registers {*|CPU|CACHE|CACHE_RAM|*DATAINREGOUT*}]
set tags [get_registers {*|ddram|read_addr*}]
set cache_words [get_registers {*|ddram|rbuf*}]
puts "FOCUS clocks=[get_collection_size $sys_clock]/[get_collection_size $mem_clock] return=[get_collection_size $return_words] cache_inputs=[get_collection_size $cache_inputs] tags=[get_collection_size $tags] cache_words=[get_collection_size $cache_words]"
if {[lsearch -exact $quartus(args) --scoped-return] >= 0} {
    # Diagnostic removal of the old clock-wide return exception. Reapply only
    # the explicitly named cache sources; this does not qualify the snapshot.
    foreach target [list $return_words $cache_inputs] {
        set_multicycle_path -setup -start 1 -from $mem_clock -to $target
        set_multicycle_path -hold -start 0 -from $mem_clock -to $target
    }
    source {D:/Arcade/AI/aCORES/BT/rtl/bt_ddr_phase.sdc}
} elseif {[llength $quartus(args)] > 1} {
    # Hypothesis only. These do not qualify this fit for assembly.
    foreach target [list $return_words $cache_inputs] {
        set_multicycle_path -setup -start 2 -from $mem_clock -to $target
        set_multicycle_path -hold -start 1 -from $mem_clock -to $target
    }
    set_multicycle_path -setup -end 2 -from $tags -to $cache_words
    set_multicycle_path -hold -end 1 -from $tags -to $cache_words
}
update_timing_netlist
file mkdir timing_focus
report_timing -setup -from_clock $sys_clock -to_clock $sys_clock -npaths 20 -nworst 1 -detail full_path -file timing_focus/sys_only.rpt
report_timing -setup -to_clock $mem_clock -npaths 30 -nworst 1 -detail full_path -file timing_focus/to_mem.rpt
report_timing -setup -to_clock $sys_clock -npaths 30 -nworst 1 -detail full_path -file timing_focus/to_sys.rpt
report_timing -setup -to [get_registers {*|SPR_VRAM|BLIT_WORD*}] -npaths 10 -nworst 1 -detail full_path -file timing_focus/sprite_word.rpt
report_timing -setup -from [get_registers {*|sdram|sampled_data*}] -to [get_registers {*|sdram|last_data*}] -npaths 16 -nworst 1 -detail full_path -file timing_focus/sdram_bridge.rpt
delete_timing_netlist
project_close
