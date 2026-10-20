# Run only against a successfully fitted, immutable source snapshot.
# This script reports timing; it never invokes the assembler or creates an RBF.
package require ::quartus::project
package require ::quartus::sta
project_open [lindex $quartus(args) 0]
create_timing_netlist
read_sdc
if {[llength $quartus(args)] > 1} {
    read_sdc [lindex $quartus(args) 1]
}
if {![info exists bt_cpu_rf_r_memory] ||
    [get_collection_size $bt_cpu_rf_r_memory] == 0} {
    error {Fitted CPU register-file memory phase endpoints did not resolve}
}
if {![info exists bt_dsp_ram_stored] ||
    [get_collection_size $bt_dsp_ram_stored] == 0} {
    error {Fitted BSMT data-RAM stored-data phase endpoints did not resolve}
}
update_timing_netlist
file mkdir timing_audit
report_clocks -file timing_audit/clocks.rpt
check_timing -include {no_clock multiple_clock generated_clock uncertainty
    partial_multicycle multicycle_consistency partial_min_max_delay
    io_min_max_delay_consistency no_input_delay no_output_delay
    partial_input_delay partial_output_delay} -file timing_audit/constraints.rpt
report_ucp -file timing_audit/unconstrained.rpt
set models {}
foreach_in_collection op [get_available_operating_conditions -all] {
    lappend models [list [get_operating_conditions_info -display_name $op] \
        [get_operating_conditions_info -model $op] \
        [get_operating_conditions_info -voltage $op] \
        [get_operating_conditions_info -temperature $op]]
}
delete_timing_netlist
set output [open timing_audit/slacks.tsv w]
puts $output "corner\tanalysis\tslack_ns\tfrom\tto"
set inventory [open timing_audit/models.tsv w]
puts $inventory "corner\tmodel\tvoltage_mv\ttemperature_c"
set phase_endpoints [open timing_audit/phase_endpoints.tsv w]
puts $phase_endpoints "corner\tcpu_rf_stored_nodes\tdsp_ram_stored_nodes\tcpu_r_min_sys_cycles\tdsp_r_min_sys_cycles\tdsp_f_to_r_min_sys_cycles\tqualified_setup_sys_cycles"
set held_capture_endpoints [open timing_audit/held_capture_endpoints.tsv w]
puts $held_capture_endpoints "corner\tmc_ram_nodes\tmc_ddr_nodes\tcache_ram_nodes\tcache_ddr_nodes"
set violations [open timing_audit/violations.tsv w]
puts $violations "corner\tanalysis\tslack_ns\tfrom\tto"
set failed 0
set corners 0
foreach condition $models {
    incr corners
    lassign $condition label model voltage temperature
    puts $inventory "$label\t$model\t$voltage\t$temperature"
    regsub -all {[^[:alnum:]_.-]} $label _ tag
    # Quartus 17 HPS delay annotation can fail when a netlist is reused
    # across corners. Recreate and annotate the actual routed design.
    create_timing_netlist -model $model -voltage $voltage \
        -temperature $temperature -force_dat
    read_sdc
    if {[llength $quartus(args)] > 1} {read_sdc [lindex $quartus(args) 1]}
    # MEMORYREGOUT can be absent in the fitter's early netlist. Every routed
    # corner must resolve it before the phase exceptions qualify that corner.
    if {![info exists bt_cpu_rf_r_memory] ||
        [get_collection_size $bt_cpu_rf_r_memory] == 0} {
        error "Fitted CPU register-file memory phase endpoints did not resolve: $label"
    }
    if {![info exists bt_dsp_ram_stored] ||
        [get_collection_size $bt_dsp_ram_stored] == 0} {
        error "Fitted BSMT data-RAM stored-data phase endpoints did not resolve: $label"
    }
    # Each physical held-word input retains the ordinary MEM->SYS relationship.
    # Explicitly reject accidental membership in an existing exception target.
    array unset held_exception_targets
    foreach target_group {bt_cpu_r_targets bt_cpu_return_words bt_cpu_cache_inputs} {
        if {![info exists $target_group]} {error "Missing constraint target group: $target_group"}
        foreach_in_collection node [set $target_group] {
            set held_exception_targets([get_node_info -name $node]) 1
        }
    }
    set held_capture_groups {}
    set held_capture_counts {}
    foreach description {
        {mc_ram {*|CPU|MC_MEM_WORD*}}
        {mc_ddr {*|CPU|MC_DDR_WORD*}}
        {cache_ram {*|CPU|CACHE|CACHE_MEM_WORD*}}
        {cache_ddr {*|CPU|CACHE|CACHE_DDR_WORD*}}
    } {
        lassign $description capture_name capture_pattern
        set capture_nodes [get_registers $capture_pattern]
        set capture_count [get_collection_size $capture_nodes]
        if {$capture_count == 0} {error "Held-word endpoint missing: $label $capture_name"}
        foreach_in_collection node $capture_nodes {
            set node_name [get_node_info -name $node]
            if {[info exists held_exception_targets($node_name)]} {
                error "Held-word capture inherited a phase exception: $label $node_name"
            }
        }
        lappend held_capture_groups [list $capture_name $capture_nodes]
        lappend held_capture_counts $capture_count
    }
    puts $held_capture_endpoints "$label\t[join $held_capture_counts \t]"
    # These intervals describe the ownership/spacing qualified by the native
    # assertions and the conservative SDC budget; counts alone are not proof.
    puts $phase_endpoints "$label\t[get_collection_size $bt_cpu_rf_r_memory]\t[get_collection_size $bt_dsp_ram_stored]\t2\t13\t6\t2"
    update_timing_netlist
    check_timing -include {no_clock multiple_clock generated_clock uncertainty
        partial_multicycle multicycle_consistency partial_min_max_delay
        io_min_max_delay_consistency no_input_delay no_output_delay
        partial_input_delay partial_output_delay} \
        -file "timing_audit/${tag}_constraints.rpt"
    set held_mem_clock {}
    foreach_in_collection clock [get_clocks *] {
        set name [get_clock_info -name $clock]
        if {[string first {emu|pll|} $name] != 0} {continue}
        if {![string match {*|divclk} $name]} {continue}
        set domain {}
        if {[string first {general[0]} $name] >= 0} {set domain sys}
            if {[string first {general[1]} $name] >= 0} {set domain mem; set held_mem_clock $clock}
            if {[string first {general[2]} $name] >= 0} {set domain sdram_sample}
        if {$domain ne {}} {
            report_timing -setup -to_clock $clock -npaths 10 -nworst 1 \
                -detail full_path -file "timing_audit/${tag}_to_${domain}.rpt"
        }
    }
    if {$held_mem_clock eq {}} {error "Held-word MEM launch clock missing: $label"}
    foreach capture_group $held_capture_groups {
        lassign $capture_group capture_name capture_nodes
        report_timing -setup -from_clock $held_mem_clock -to $capture_nodes \
            -npaths 1 -nworst 1 -detail full_path \
            -file "timing_audit/${tag}_${capture_name}_capture.rpt"
    }
    foreach type {setup hold recovery removal} {
        set paths [get_timing_paths -$type -npaths 1]
        if {[get_collection_size $paths] == 0} {
            puts $output "$label\t$type\tN/A\t\t"
        } else {
            foreach_in_collection path $paths {
                set slack [get_path_info -slack $path]
                set from [get_node_info -name [get_path_info -from $path]]
                set to [get_node_info -name [get_path_info -to $path]]
                puts $output "$label\t$type\t$slack\t$from\t$to"
                if {$slack < 0} {set failed 1}
            }
        }
        report_timing -$type -npaths 10 -nworst 10 -detail full_path \
            -file "timing_audit/${tag}_${type}.rpt"
        foreach_in_collection path [get_timing_paths -$type -npaths 500 -nworst 1] {
            set slack [get_path_info -slack $path]
            if {$slack < 0} {
                puts $violations "$label\t$type\t$slack\t[get_node_info -name [get_path_info -from $path]]\t[get_node_info -name [get_path_info -to $path]]"
            }
        }
    }
    foreach type {setup hold} {
        report_timing -$type -from [get_ports {SDRAM_DQ[*]}] -npaths 16 -nworst 1 \
            -detail full_path -file "timing_audit/${tag}_sdram_input_${type}.rpt"
        report_timing -$type -to [get_ports {SDRAM_A[*] SDRAM_BA[*] SDRAM_DQ[*] SDRAM_DQML SDRAM_DQMH SDRAM_nRAS SDRAM_nCAS SDRAM_nWE}] \
            -npaths 40 -nworst 1 -detail full_path \
            -file "timing_audit/${tag}_sdram_output_${type}.rpt"
        report_timing -$type -to [get_ports {HDMI_TX_D[*] HDMI_TX_DE HDMI_TX_HS HDMI_TX_VS}] \
            -npaths 54 -nworst 2 -detail full_path \
            -file "timing_audit/${tag}_hdmi_video_${type}.rpt"
        report_timing -$type -to [get_ports {HDMI_I2S HDMI_LRCLK}] -npaths 2 -nworst 1 \
            -detail full_path -file "timing_audit/${tag}_hdmi_audio_${type}.rpt"
    }
    report_min_pulse_width -nworst 10 -detail full_path \
        -file "timing_audit/${tag}_pulse_width.rpt"
    set pulse_file [open "timing_audit/${tag}_pulse_width.rpt" r]
    set pulse_text [read $pulse_file]
    close $pulse_file
    if {![regexp {Worst case slack is\s+(-?[\d.]+)} $pulse_text -> pulse_slack]} {
        error "Missing pulse-width slack for $label"
    }
    puts $output "$label\tpulse_width\t$pulse_slack\t\t"
    if {$pulse_slack < 0} {set failed 1}
    delete_timing_netlist
}
close $output
close $inventory
close $phase_endpoints
close $held_capture_endpoints
close $violations
project_close -dont_export_assignments
puts "TIMING_AUDIT corners=$corners negative_path_slack=$failed"
if {$corners == 0 || $failed} {error "Timing closure is not established"}
# Pulse width, constraint completeness and existing exceptions must also be
# reviewed before assembly; a zero exit code alone is not RBF authorization.
