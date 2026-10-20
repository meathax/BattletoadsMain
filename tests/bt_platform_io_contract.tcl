# Tcl syntax/source-contract check only. Real TimeQuest collections and fitted
# delays must be checked by the native all-corner build. No Quartus reporting
# command or database operation runs here.
set bt_contract_calls {}
proc get_registers {pattern} {
    if {$pattern eq {mcp23009|i2c|ACK mcp23009|i2c|rdata[*]}} {
        return {ack rdata0 rdata1 rdata2 rdata3 rdata4}
    }
    return $pattern
}
proc get_ports {pattern} {
    set result {}
    foreach item $pattern {
        if {$item eq {SDIO_DAT[*]}} {
            lappend result {SDIO_DAT[0]} {SDIO_DAT[1]} {SDIO_DAT[2]} {SDIO_DAT[3]}
        } else {lappend result $item}
    }
    return $result
}
proc get_clocks {pattern} {return $pattern}
proc get_collection_size {collection} {return [llength $collection]}
foreach command {
    set_max_delay set_min_delay set_false_path create_generated_clock
    set_output_delay set_multicycle_path derive_clock_uncertainty
} {
    proc $command {args} {
        lappend ::bt_contract_calls [linsert $args 0 [lindex [info level 0] 0]]
    }
}
set bt_i2s_q {audio_sclk_q}
set bt_audio_registers {audio_sdata audio_lrclk}
source [lindex $argv 0]
if {[llength $bt_contract_calls] != 17} {error {Unexpected platform constraint count}}
puts {PASS Tcl syntax, source bindings, endpoint guard shape and 17 scoped constraints}
