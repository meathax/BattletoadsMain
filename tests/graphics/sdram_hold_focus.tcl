# Diagnostic only. Apply the single-word hold edge to an existing fit.
package require ::quartus::project
package require ::quartus::sta
project_open Arcade-Battletoads
create_timing_netlist -model fast -voltage 1100 -temperature -40 -force_dat
read_sdc
read_sdc [lindex $quartus(args) 0]
update_timing_netlist
file mkdir sdram_hold_focus
report_timing -hold -from [get_ports {SDRAM_DQ[*]}] -npaths 16 -nworst 1 \
    -detail full_path -file sdram_hold_focus/single_word_hold.rpt
delete_timing_netlist
project_close
