"""Guarded private identity delay for the measured BG RAM write-data hold path."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
BG = 'rtl/bg_vram.sv'
PARENT_SHA = '748ba22e42d57d618ffce46800a7f66f023fe79b27a3186f9a04b9748af1273c'
DECL = b'\tbit [15:0]   WRITE_DATA;\r\n'
OLD_DATA = b'\t\t.DATA(WRITE_DATA),\r\n'
NEW_DATA = b'\t\t.DATA(RAM_WRITE_DATA),\r\n'
INSERT = (b'\t// Retain one identity cell on the measured short RAM data branch.\r\n'
          b'\t// The CPU packet, RAM capture edge and every other consumer are unchanged.\r\n'
          b'\t(* keep *) wire [15:0] RAM_WRITE_DATA;\r\n'
          b'\tassign RAM_WRITE_DATA[14:0] = WRITE_DATA[14:0];\r\n'
          b'\tlcell write_data_hold_delay(.in(WRITE_DATA[15]), .out(RAM_WRITE_DATA[15]));\r\n')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def transform(data):
    assert sha(data) == PARENT_SHA, 'Exact v24 background parent required'
    assert data.count(DECL) == 1 and data.count(OLD_DATA) == 1
    assert b'RAM_WRITE_DATA' not in data and b'write_data_hold_delay' not in data
    candidate = data.replace(DECL, DECL + INSERT, 1).replace(OLD_DATA, NEW_DATA, 1)
    assert reverse(candidate) == data
    return candidate


def reverse(data):
    assert data.count(INSERT) == 1 and data.count(NEW_DATA) == 1
    return data.replace(INSERT, b'', 1).replace(NEW_DATA, OLD_DATA, 1)


def verify_edge(directory):
    directory = Path(directory)
    manifest = json.loads((directory / 'manifest.json').read_bytes())
    old = (directory / 'oracle' / BG).read_bytes()
    new = (directory / 'candidate' / BG).read_bytes()
    assert sha(old) == PARENT_SHA
    assert transform(old) == new and reverse(new) == old
    assert manifest['parent_sha256'] == sha(old)
    assert manifest['candidate_sha256'] == sha(new)
    assert manifest['helper_sha256'] == sha(Path(__file__).read_bytes())
    assert manifest['changed_source_files'] == [BG]
    assert manifest['cells_per_instance'] == 1 and manifest['delayed_ram_data_bits'] == [15]
    assert not any(manifest[key] for key in ('new_registers', 'capture_cycle_changed', 'reset_changed', 'qsf_sdc_clock_changes'))
    return old, new, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Never overwrite a frozen source edge'
    old = (args.parent_dir / BG).read_bytes()
    new = transform(old)
    for kind, data in (('oracle', old), ('candidate', new)):
        target = args.output / kind / BG
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    manifest = {
        'schema': 'bt-bg-ram-write-hold-lcell-source-edge-v1',
        'parent_source_root': str(args.parent_dir.resolve()),
        'parent_sha256': sha(old), 'candidate_sha256': sha(new),
        'candidate_lf_sha256': sha(new.replace(b'\r\n', b'\n')),
        'helper_sha256': sha(Path(__file__).read_bytes()),
        'full_file_byte_inverse': True, 'changed_source_files': [BG],
        'cells_per_instance': 1, 'delayed_ram_data_bits': [15],
        'keep_output_nets': True, 'new_registers': 0,
        'capture_cycle_changed': False, 'reset_changed': False,
        'raw_write_packet_other_consumers_unchanged': True,
        'qsf_sdc_clock_changes': 0,
        'scope': 'Exact source identity transform only. Functional simulation, retained native cells and all eight original timing corners remain separate gates.'}
    path = args.output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    verify_edge(args.output)
    print(json.dumps({'candidate': str(args.output / 'candidate' / BG),
                      'candidate_sha256': sha(new), 'manifest': str(path),
                      'manifest_sha256': sha(path.read_bytes())}))


if __name__ == '__main__':
    main()
