"""Freeze an attribute-only FG lane write-enable fan-out contingency."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
PARENTS = {
    'e006f78f28bddf67f97dbd32b69dd507fc6a11916355c2c57e98ff21a6b44552': 'frozen v14-v2 serial RAM replicas',
    'f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b': 'frozen v13 same-edge serial controls',
}
OLD = b'(* preserve *) bit [3:0][1:0] BANK_LANE_WREN_R;'
NEW = b'(* preserve, maxfan = 4 *) bit [3:0][1:0] BANK_LANE_WREN_R;'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'build/fg_serial_replicas_v12_v2/candidate/rtl/fg_vram.sv')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/fg_lane_maxfan_v14_v1')
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT.resolve()) and not output.exists()
    original = args.source.read_bytes()
    parent = sha(original)
    assert parent in PARENTS, 'Only explicitly frozen v13/v14 parents are admitted'
    assert original.count(OLD) == 1 and NEW not in original
    candidate = original.replace(OLD, NEW)
    assert candidate.count(NEW) == 1 and candidate.replace(NEW, OLD) == original
    for part, data in [('immutable_parent', original), ('candidate', candidate)]:
        path = output / part / 'rtl/fg_vram.sv'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        'schema': 'bt-fg-lane-maxfan-attribute-edge-v1', 'status': 'PASS',
        'parent_source': str(args.source.resolve()), 'parent_fg_sha256': parent,
        'parent_profile': PARENTS[parent], 'candidate_fg_sha256': sha(candidate),
        'helper': str(Path(__file__).resolve()), 'helper_sha256': sha(Path(__file__).read_bytes()),
        'before': OLD.decode(), 'after': NEW.decode(), 'full_file_reverse_byte_exact': True,
        'whole_functional_rtl_byte_identical_after_attribute_strip': True,
        'original_declaration_width_type_and_initialization_unchanged': True,
        'original_always_body_edge_reset_priority_and_data_unchanged': True,
        'ports_parameters_ram_configuration_and_clock_constraints_unchanged': True,
        'synthesis_directive': 'Supported Quartus 17 maxfan=4 on the existing eight-bit register; preserve retained.',
        'official_reference': 'https://resources.altera.com/quartushelp/17.0/hdl/vlog/vlog_file_dir.htm',
        'motivation': 'v13 routed BANK_LANE_WREN_R[3][1] has seven sinks and a reported -0.124ns write-enable path dominated by routing; no existing maxfan directive covers this register.',
        'scope': 'Private contingency, source identity only. No simulation, fit, hardware, or timing improvement claim; use only if v14 still has FG write-enable negatives.',
    }
    path = output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'candidate': str(output / 'candidate/rtl/fg_vram.sv'),
                      'candidate_sha256': sha(candidate), 'manifest': str(path),
                      'manifest_sha256': sha(path.read_bytes())}))


if __name__ == '__main__':
    main()
