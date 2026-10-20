"""Prepare an isolated fitted DB for read-only MCP pad register inventory.

No SDC is evaluated and no timing verdict is produced by this inventory.
The separate native TimeQuest call reads only the disposable fitted copy.
"""
import argparse
import json
from pathlib import Path
from qualify_platform_io_diagnostics import ROOT, catalog, copy_fitted, physical_db, project_paths, safe_output, sha


parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--workspace', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
workspace = args.workspace.resolve()
output = safe_output(args.output, workspace)
qpf, qsf = project_paths(workspace, None)
before_sources, before_db = catalog(workspace), catalog(workspace, True)
assert physical_db(before_db), 'Closed fitted DB is required'
info = copy_fitted(workspace, output, qsf, 'bt_inventory_only.sdc')
assert info['database'] == before_db, 'Native DB copy differs'
(output / 'bt_inventory_only.sdc').write_text('# Inventory only. Never sign off or assemble.\n')
tcl = '''load_package sta
project_open -revision {REVISION} {PROJECT}
create_timing_netlist -model slow
set bt_inventory [open {platform_io_inventory.tsv} w]
puts $bt_inventory "# Read-only fitted-node inventory; no read_sdc or timing acceptance"
foreach_in_collection bt_node [get_registers {*mcp23009*|i2c|*}] {
    puts $bt_inventory "REGISTER\t[get_node_info -name $bt_node]"
}
foreach {bt_key bt_pattern} {
    expected_scl {mcp23009|i2c|I2C_CLOCK mcp23009|i2c|SCLK}
    expected_sda {mcp23009|i2c|SDO[3]}
    expected_inputs {mcp23009|i2c|ACK mcp23009|i2c|rdata[*]}
} {
    set bt_nodes [get_registers $bt_pattern]
    puts $bt_inventory "COLLECTION\t$bt_key\t[get_collection_size $bt_nodes]"
    foreach_in_collection bt_node $bt_nodes {puts $bt_inventory "MEMBER\t$bt_key\t[get_node_info -name $bt_node]"}
}
foreach bt_pin {IO_SCL IO_SDA} {
    set bt_nodes [get_ports $bt_pin]
    puts $bt_inventory "PORT\t$bt_pin\t[get_collection_size $bt_nodes]"
}
close $bt_inventory
delete_timing_netlist
project_close
'''.replace('REVISION', qsf.stem).replace('PROJECT', qpf.stem)
script = output / 'inspect_platform_io.tcl'
script.write_text(tcl, newline='\n')
assert catalog(workspace) == before_sources and catalog(workspace, True) == before_db, 'Original source/DB changed'
manifest = {'schema': 'bt-platform-io-inventory-copy-v1', 'purpose': 'Read-only mapped alias inventory; never timing acceptance',
            'original_workspace': str(workspace), 'original_sources': before_sources, 'original_database': before_db,
            'original_physical_database': physical_db(before_db), 'copy': info, 'prepared_sources': catalog(output),
            'script': str(script), 'script_sha256': sha(script), 'generate_rbf_file': False, 'read_sdc': False}
target = output / 'inventory_provenance.json'
target.write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({'copy': str(output), 'tcl': str(script), 'manifest': str(target)}))
