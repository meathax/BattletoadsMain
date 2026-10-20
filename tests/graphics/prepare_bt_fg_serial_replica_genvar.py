"""Freeze the Quartus 17 declaration-only edge from replica v1 to v2."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
PARENT = {
    'rtl/fg_vram.sv': '2c2929ccbe0ecc739badc268378217833362de9874acf1ba99852d8904bc899e',
    'rtl/spr_vram.sv': '14546df8bd1a8e701f31051300518a294cd444d037a9b08d2c223b1ea9721c05',
}
PARENT_MANIFEST = 'cce03f1cdade6a6e1ab69bef6b3a6fe144b93dcc2501e2f8e93ec97909299e5f'
OLD = b'\tgenerate for (genvar serial_replica=1; serial_replica<4; serial_replica=serial_replica+1) begin : serial_write_replicas'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent-dir', type=Path, default=ROOT / 'build/fg_serial_replicas_v12_v1/candidate')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/fg_serial_replicas_v12_v2')
    args = parser.parse_args()
    parent_dir, output = args.parent_dir.resolve(), args.output.resolve()
    assert output.is_relative_to(ROOT.resolve()), 'Output must stay inside this repository'
    assert not output.exists(), f'Refusing to replace preserved evidence: {output}'
    parent_manifest = parent_dir.parent / 'manifest.json'
    assert sha(parent_manifest.read_bytes()) == PARENT_MANIFEST
    sources = {name: (parent_dir / name).read_bytes() for name in PARENT}
    assert {name: sha(data) for name, data in sources.items()} == PARENT
    before = sources['rtl/fg_vram.sv']
    assert before.count(OLD) == 1
    newline = b'\r\n' if b'\r\n' in before else b'\n'
    new = b'\tgenvar serial_replica;' + newline + OLD.replace(b'for (genvar ', b'for (')
    after = before.replace(OLD, new)
    assert after.count(new) == 1 and after.replace(new, OLD) == before
    assert not re.search(rb'for\s*\(\s*genvar\s+serial_replica', after)
    # Check the production original and generated RAM inputs without modifying
    # either instance. The generate range is the constant indices 1, 2, and 3.
    blocks = re.findall(rb'VRAM_SHIFTREG #\(9,1,1\) shiftreg\s*\((.*?)\n\s*\);', after, re.S)
    assert len(blocks) == 2
    pins = [dict(re.findall(rb'\.(\w+)\(([^\n]+)\)', block)) for block in blocks]
    assert pins[0].pop(b'Q') == b'SR_Q'
    assert pins[1].pop(b'Q') == b'SERIAL_WRITE_WORD_B[serial_replica]'
    assert pins[0] == pins[1]
    assert set(pins[0]) == {b'CLK', b'ACLR', b'WADDR', b'DATA', b'WREN', b'RADDR'}
    assert b'serial_replica=1; serial_replica<4; serial_replica=serial_replica+1' in after
    final = dict(sources, **{'rtl/fg_vram.sv': after})
    for directory, mapping in [('immutable_v1', sources), ('candidate', final)]:
        for name, data in mapping.items():
            target = output / directory / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    manifest = {
        'schema': 'bt-fg-serial-replica-genvar-syntax-v1', 'status': 'PASS',
        'qualification': 'Declaration-only compiler syntax edge; no hardware timing/resource claim.',
        'parent_dir': str(parent_dir), 'parent_manifest': str(parent_manifest),
        'parent_manifest_sha256': PARENT_MANIFEST,
        'parent_sources': PARENT, 'candidate_sources': {name: sha(data) for name, data in final.items()},
        'helper': str(Path(__file__).resolve()), 'helper_sha256': sha(Path(__file__).read_bytes()),
        'edge': {'before': OLD.decode(), 'after': new.decode(), 'reverse_byte_exact': True},
        'checks': {'only_genvar_declaration_moved': True, 'sprite_byte_identical': True,
                   'original_ram_instance_byte_identical': True,
                   'generated_ram_instance_byte_identical': True,
                   'identical_parameters_and_all_input_pins': True,
                   'original_video_and_bank0_q_unchanged': True},
        'ram_inputs': {key.decode(): value.decode() for key, value in pins[0].items()},
        'elaborated_replicas': [f'serial_write_replicas[{i}].shiftreg' for i in range(1, 4)],
        'elaborated_instance_count_per_fg': 4,
        'simulation_applicability': 'v1 simulation inputs remain immutable; v2 differs solely in equivalent genvar declaration syntax.',
    }
    target = output / 'manifest.json'
    target.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'candidate_dir': str(output / 'candidate'),
                      'candidate_sources': manifest['candidate_sources'],
                      'manifest': str(target), 'manifest_sha256': sha(target.read_bytes())}))


if __name__ == '__main__':
    main()
