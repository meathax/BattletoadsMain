package require ::quartus::project
package require ::quartus::sta
project_open [lindex $quartus(args) 0]
create_timing_netlist
read_sdc
update_timing_netlist
file mkdir memory_path
set found 0
foreach_in_collection clock [get_clocks *] {
    set name [get_clock_info -name $clock]
    if {[string first {general[1]} $name] >= 0} {
        report_timing -setup -to_clock $clock -npaths 5 -nworst 5 -detail full_path \
            -file memory_path/setup.rpt
        set found 1
    }
}
if {!$found} {error {Memory clock was not found}}
delete_timing_netlist
project_close -dont_export_assignments
