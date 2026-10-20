"""Scope LCELL removal options to the single background data-buffer entity."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
BG = 'rtl/bg_vram.sv'
PARENT_SHA = 'a2323df5cb71ce3c9856a0f58720444fe95556917771615cad6f6a173d08b5ad'
OLD_INSTANCE = b'\tlcell write_data_hold_delay(.in(WRITE_DATA[15]), .out(RAM_WRITE_DATA[15]));\r\n'
NEW_INSTANCE = b'\tbt_bg_write_hold_cell write_data_hold_delay(.in(WRITE_DATA[15]), .out(RAM_WRITE_DATA[15]));\r\n'
TAIL = (b'\r\n\r\n// Apply removal control to this buffer entity, preserving the global optimization.\r\n'
        b'(* altera_attribute = "-name REMOVE_REDUNDANT_LOGIC_CELLS OFF; -name IGNORE_LCELL_BUFFERS OFF" *)\r\n'
        b'module bt_bg_write_hold_cell(input wire in, output wire out);\r\n'
        b'\tlcell buffer_cell(.in(in), .out(out));\r\n'
        b'endmodule\r\n')
sha = lambda data: hashlib.sha256(data).hexdigest()


def transform(data):
    assert sha(data) == PARENT_SHA, 'Exact v25 background parent required'
    assert data.count(OLD_INSTANCE) == 1 and b'bt_bg_write_hold_cell' not in data
    new = data.replace(OLD_INSTANCE, NEW_INSTANCE, 1) + TAIL
    assert reverse(new) == data
    return new


def reverse(data):
    assert data.endswith(TAIL) and data.count(NEW_INSTANCE) == 1
    return data[:-len(TAIL)].replace(NEW_INSTANCE, OLD_INSTANCE, 1)


def verify_edge(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    old = (directory / 'oracle' / BG).read_bytes()
    new = (directory / 'candidate' / BG).read_bytes()
    assert sha(old) == PARENT_SHA and transform(old) == new and reverse(new) == old
    assert manifest['helper_sha256'] == sha(Path(__file__).read_bytes())
    assert manifest['parent_sha256'] == sha(old) and manifest['candidate_sha256'] == sha(new)
    assert manifest['changed_source_files'] == [BG]
    assert manifest['local_entity_options'] == {'REMOVE_REDUNDANT_LOGIC_CELLS': 'OFF', 'IGNORE_LCELL_BUFFERS': 'OFF'}
    assert manifest['new_registers'] == 0 and manifest['qsf_sdc_clock_changes'] == 0
    assert manifest['global_settings_changed'] is False
    return old, new, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Never overwrite an executed source edge'
    old = (args.parent_dir / BG).read_bytes()
    new = transform(old)
    for kind, data in (('oracle', old), ('candidate', new)):
        path = args.output / kind / BG
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        'schema': 'bt-bg-write-hold-entity-source-edge-v1',
        'parent_source_root': str(args.parent_dir.resolve()), 'parent_sha256': sha(old),
        'candidate_sha256': sha(new), 'candidate_lf_sha256': sha(new.replace(b'\r\n', b'\n')),
        'helper_sha256': sha(Path(__file__).read_bytes()), 'full_file_byte_inverse': True,
        'changed_source_files': [BG], 'cells_per_instance': 1, 'delayed_ram_data_bits': [15],
        'local_entity_options': {'REMOVE_REDUNDANT_LOGIC_CELLS': 'OFF', 'IGNORE_LCELL_BUFFERS': 'OFF'},
        'new_registers': 0, 'new_modules': ['bt_bg_write_hold_cell'],
        'qsf_sdc_clock_changes': 0, 'global_settings_changed': False,
        'scope': 'Exact identity wrapper and narrow entity options only; actual mapped retention, functional simulation and original-budget timing remain separate gates.'}
    path = args.output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    verify_edge(args.output)
    print(json.dumps({'candidate': str(args.output / 'candidate' / BG),
                      'candidate_sha256': sha(new), 'manifest': str(path), 'manifest_sha256': sha(path.read_bytes())}))


if __name__ == '__main__':
    main()
