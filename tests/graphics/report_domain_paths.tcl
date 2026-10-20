package require ::quartus::project
package require ::quartus::sta
project_open [lindex $quartus(args) 0]
create_timing_netlist
read_sdc
if {[llength $argv] > 1} { read_sdc [lindex $argv 1] }
update_timing_netlist
file mkdir domain_paths
set sys_clock ""
set mem_clock ""
foreach_in_collection clock [get_clocks *] {
    set name [get_clock_info -name $clock]
    if {[string first {emu|pll|} $name] != 0} {continue}
    if {[string first {general[0]} $name] >= 0} {set sys_clock $clock}
    if {[string first {general[1]} $name] >= 0} {set mem_clock $clock}
}
if {$sys_clock eq "" || $mem_clock eq ""} {error {Core clocks were not found}}
report_timing -setup -from_clock $sys_clock -to_clock $sys_clock \
    -npaths 5 -nworst 5 -detail full_path -file domain_paths/sys_to_sys.rpt
report_timing -setup -to_clock $mem_clock \
    -npaths 5 -nworst 5 -detail full_path -file domain_paths/to_mem.rpt
report_timing -setup -from_clock $mem_clock -to_clock $mem_clock \
    -npaths 5 -nworst 5 -detail full_path -file domain_paths/mem_to_mem.rpt
delete_timing_netlist
project_close -dont_export_assignments
