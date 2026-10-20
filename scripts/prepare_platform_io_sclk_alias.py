"""Prepare a strict, reversible mapped SCLK replica alias repair privately."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ALIAS_PROC = '''# Quartus may split the same SCLK FF for internal and pad fan-out.
# Source i2c.v, capture edge and physical pad budgets are unchanged. Accept
# only the observed physical SCLK clone; unknown/new aliases require review.
proc bt_platform_validate_scl_names {names} {
    set canonical {}
    foreach name $names {
        set normalized [string map [list "mcp23009:mcp23009|" "mcp23009|" "i2c:i2c|" "i2c|"] $name]
        switch -exact -- $normalized {
            {mcp23009|i2c|I2C_CLOCK} -
            {mcp23009|i2c|SCLK} -
            {mcp23009|i2c|SCLK~DUPLICATE} {lappend canonical $normalized}
            default {error "Unproved MCP23009 SCL register alias: $name"}
        }
    }
    if {[llength $canonical] != [llength [lsort -unique $canonical]]} {
        error {Repeated MCP23009 SCL register aliases}
    }
    foreach mandatory {{mcp23009|i2c|I2C_CLOCK} {mcp23009|i2c|SCLK}} {
        if {[lsearch -exact $canonical $mandatory] < 0} {
            error "Missing mandatory MCP23009 SCL register: $mandatory"
        }
    }
    return [lsort $canonical]
}
'''
OLD_SELECTION = 'set bt_io_scl_regs [get_registers {mcp23009|i2c|I2C_CLOCK mcp23009|i2c|SCLK}]'
NEW_SELECTION = ALIAS_PROC + OLD_SELECTION + '''
set bt_io_scl_raw_names {}
foreach_in_collection bt_io_scl_node $bt_io_scl_regs {
    lappend bt_io_scl_raw_names [get_node_info -name $bt_io_scl_node]
}
set bt_io_scl_names [bt_platform_validate_scl_names $bt_io_scl_raw_names]'''
OLD_COUNT = 'if {[get_collection_size $bt_io_scl_regs] != 2 ||\n    [get_collection_size $bt_io_sda_reg] != 1 ||'
NEW_COUNT = 'if {[get_collection_size $bt_io_sda_reg] != 1 ||'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(raw):
    text = raw.decode()
    assert text.count(OLD_SELECTION) == text.count(OLD_COUNT) == 1
    revised = text.replace(OLD_SELECTION, NEW_SELECTION, 1).replace(OLD_COUNT, NEW_COUNT, 1)
    assert revised.replace(NEW_COUNT, OLD_COUNT, 1).replace(NEW_SELECTION, OLD_SELECTION, 1) == text
    # Exact remaining bytes preserve all source/phase/clock/max/min contracts.
    return revised.encode()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT / 'build') and not output.exists()
    original = (ROOT / 'rtl/bt_platform_io.sdc').read_bytes()
    # Pin from the immutable fitted source guard rather than a regenerated SDC.
    fitted = Path('C:/Users/meath/QuartusFast/workspaces/2748733f002cf79ba9d0/08c47a3898345eeb2c23/project/rtl/bt_platform_io.sdc').read_bytes()
    assert original == fitted
    revised = transform(original)
    target = output / 'rtl/bt_platform_io.sdc'
    target.parent.mkdir(parents=True)
    target.write_bytes(revised)
    manifest = {'schema': 'bt-platform-sclk-alias-edge-v1', 'status': 'PREPARED', 'old_sha256': sha(original),
                'new_sha256': sha(revised), 'candidate': str(target), 'helper_sha256': sha(Path(__file__).read_bytes()),
                'source_phase_and_budget_bytes_unchanged': True, 'reversible_transform': True,
                'required_logical_names': ['mcp23009|i2c|I2C_CLOCK', 'mcp23009|i2c|SCLK'],
                'optional_proven_physical_replica': 'mcp23009|i2c|SCLK~DUPLICATE',
                'native_inventory': 'C:/Users/meath/QuartusFast/runs/diagnose-fit-20261011-062927-9400/all-corners.log:67',
                'release_timing_accepted': False}
    path = output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'candidate': str(target), 'manifest': str(path), 'new_sha256': sha(revised)}))
