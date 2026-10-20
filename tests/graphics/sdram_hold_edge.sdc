# Diagnostic override: a one-word read can release DQ on the next SDRAM
# edge. Check that edge, not a further clock cycle introduced by hold=1.
set_multicycle_path -hold -start 0 -from [get_ports {SDRAM_DQ[*]}] \
    -to [get_registers {*|sdram|sampled_data[*]}]
