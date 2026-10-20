"""Validate the immutable v1 physical receipt and the explicit v2 syntax/proof edge."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
V1 = '2c2929ccbe0ecc739badc268378217833362de9874acf1ba99852d8904bc899e'
V2 = 'e006f78f28bddf67f97dbd32b69dd507fc6a11916355c2c57e98ff21a6b44552'
VENDOR = ROOT / 'tests/graphics/evidence/vram-physical/vram-current-75b60b4efa42477695a599e3c07c45ac/receipt.json'
VENDOR_SHA = 'c5a2e4d7375f54d2e3afcf0a7c085a7f40082899547f751b55beb2ba1c95390c'
SYNTAX = ROOT / 'build/fg_serial_replicas_v12_v2/manifest.json'
SYNTAX_SHA = 'e0a4b2a844c6e7895f1bc6a08a9e017a144fe659e267c03f452433c88396934d'
FOCUSED = ROOT / 'build/fg_serial_replicas_v12_v2/proof/receipt.json'
FOCUSED_SHA = 'e50621d4b1ab6481f1ab8ab0c695b586fe128fde1d808624057b66aedec7a066'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load(path: Path, expected: str) -> dict:
    data = path.read_bytes()
    assert sha(data) == expected, f'Frozen receipt changed: {path}'
    return json.loads(data)


def module(data: bytes, name: bytes) -> bytes:
    match = re.search(rb'(?m)^module\s+' + re.escape(name) + rb'\b.*?\bendmodule', data, re.S)
    assert match
    return match.group(0)


def validate(vendor: dict, syntax: dict, focused: dict) -> None:
    assert vendor['schema'] == 'bt-current-vram-intel-model-v1'
    assert vendor['oracle_ref'] == 'b53726397822b9dbebb02d36411294056fd08649'
    assert vendor['sources']['rtl/fg_vram.sv'] == V1
    assert vendor['source_stability_passed'] and vendor['exit_code'] == 0
    assert vendor['intel_model_equivalence_passed'] is True
    results = vendor['results']
    rows = list(results.values()) if isinstance(results, dict) else results
    assert len(rows) == 2 and {row['test'] for row in rows} == {'ram', 'bg'}
    for row in rows:
        assert row['compile_exit_code'] == 0 and row['runs']
        assert all(run['passed'] and run['exit_code'] == 0 for run in row['runs'])
    assert syntax['schema'] == 'bt-fg-serial-replica-genvar-syntax-v1' and syntax['status'] == 'PASS'
    assert syntax['parent_sources']['rtl/fg_vram.sv'] == V1
    assert syntax['candidate_sources']['rtl/fg_vram.sv'] == V2
    assert syntax['edge']['reverse_byte_exact']
    assert syntax['elaborated_replicas'] == [f'serial_write_replicas[{n}].shiftreg' for n in (1, 2, 3)]
    assert focused['status'] == 'PASS' and focused['candidate_fg_sha256'] == V2
    assert focused['immutable_git_ref'] == vendor['oracle_ref']
    assert focused['original_current_serial_ram_body_identical'] is True
    assert focused['no_collision_or_x_masks'] is True
    assert all(row['exit_code'] == 0 for row in focused['results'])
    coverage = focused['intel_coverage']
    assert coverage == {'cycles': 65608, 'bit_checks': 16798720, 'reset_events': 12,
                        'collision_reads': 32704, 'noncollision_reads': 32640}
    assert 'state_edges=1263909 bank_edge_checks=10111272 states=31 pin_fields=13' in ' '.join(focused['native_markers']['fg'])
    assert all(re.search(r'\b' + count + r'\b', ' '.join(focused['native_markers']['fg-ddr'])) for count in ('196608', '128', '512'))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/fg_serial_replicas_v12_v2/applicability.json')
    parser.add_argument('--map-report', type=Path)
    args = parser.parse_args()
    assert args.output.resolve().is_relative_to(ROOT.resolve()) and not args.output.exists()
    vendor, syntax, focused = load(VENDOR, VENDOR_SHA), load(SYNTAX, SYNTAX_SHA), load(FOCUSED, FOCUSED_SHA)
    validate(vendor, syntax, focused)
    v1 = (Path(syntax['parent_dir']) / 'rtl/fg_vram.sv').read_bytes()
    v2 = (SYNTAX.parent / 'candidate/rtl/fg_vram.sv').read_bytes()
    assert sha(v1) == V1 and sha(v2) == V2
    before, after = syntax['edge']['before'].encode(), syntax['edge']['after'].encode()
    assert v2.count(after) == 1 and v2.replace(after, before) == v1
    # The original physical suite actually elaborates this banked helper with
    # the appended SERIAL_DATA_LOCAL default=0. Its whole tested module is
    # byte-identical across the declaration-only edge. The separate v2 full FG
    # and explicit Intel fixtures prove the activated local-word path/replicas.
    banked = module(v1, b'BT_FG_BANKED_VRAM')
    assert banked == module(v2, b'BT_FG_BANKED_VRAM')
    assert re.search(rb'\bSERIAL_DATA_LOCAL\s*=\s*0\b', banked)
    for name, expected in vendor['sources'].items():
        source = Path(vendor['actual_source_paths'].get(name, str(ROOT / name)))
        assert sha(source.read_bytes()) == expected, f'Physical input changed: {source}'
    for name, expected in vendor['fixtures'].items():
        assert sha((ROOT / name).read_bytes()) == expected
    native = Path(focused['native_receipt'])
    assert sha(native.read_bytes()) == focused['native_receipt_sha256']
    native_doc = json.loads(native.read_text())
    assert native_doc['all_passed'] and native_doc['sources']['rtl/fg_vram.sv'] == V2
    for row in focused['results']:
        assert sha(Path(row['log']).read_bytes()) == row['log_sha256']
    negatives = []
    mutations = [
        ('v1_source', 0, ['sources', 'rtl/fg_vram.sv'], V2),
        ('vendor_failed', 0, ['intel_model_equivalence_passed'], False),
        ('wrong_v2', 1, ['candidate_sources', 'rtl/fg_vram.sv'], V1),
        ('lost_replica', 1, ['elaborated_replicas'], ['serial_write_replicas[1].shiftreg']),
        ('reverse_disabled', 1, ['edge', 'reverse_byte_exact'], False),
        ('collision_mask_added', 2, ['no_collision_or_x_masks'], False),
        ('missing_reset', 2, ['intel_coverage', 'reset_events'], 0),
        ('wrong_oracle', 2, ['immutable_git_ref'], 'HEAD'),
    ]
    for label, doc_index, keys, value in mutations:
        docs = copy.deepcopy([vendor, syntax, focused])
        target = docs[doc_index]
        for key in keys[:-1]:
            target = target[key]
        target[keys[-1]] = value
        try:
            validate(*docs)
        except AssertionError:
            negatives.append(label)
        else:
            raise AssertionError('Negative control incorrectly accepted: ' + label)
    mapped = None
    if args.map_report:
        data = args.map_report.read_bytes()
        rows = []
        for line_number, line in enumerate(data.decode().splitlines(), 1):
            fields = [part.strip() for part in line.split(';')][1:-1]
            if len(fields) == 9 and fields[1] == 'M10K block' and re.search(r'FG[01]_VRAM\|VRAM_SHIFTREG:(shiftreg|serial_write_replicas\[[123]\]\.shiftreg)', fields[0]):
                assert fields[2:8] == ['Simple Dual Port', '64', '64', '64', '64', '4096']
                rows.append({'line': line_number, 'fields': fields})
        assert len(rows) == 8 and sum('serial_write_replicas' in row['fields'][0] for row in rows) == 6
        project = args.map_report.parent.parent
        assert sha((project / 'rtl/fg_vram.sv').read_bytes()) == V2
        mapped = {'path': str(args.map_report.resolve()), 'sha256': sha(data), 'ram_rows': rows,
                  'mapped_distinct_stores': 8, 'additional_bits': 24576,
                  'physical_fitter_packing_verified': False}
    record = {
        'schema': 'bt-fg-serial-replicas-physical-applicability-v1', 'status': 'PASS',
        'vendor_receipt': str(VENDOR), 'vendor_receipt_sha256': VENDOR_SHA,
        'syntax_edge': str(SYNTAX), 'syntax_edge_sha256': SYNTAX_SHA,
        'focused_receipt': str(FOCUSED), 'focused_receipt_sha256': FOCUSED_SHA,
        'v1_fg_sha256': V1, 'v2_fg_sha256': V2, 'tested_banked_module_byte_identical': True,
        'tested_banked_module_sha256': sha(banked), 'default_path_only_in_original_vendor_suite': True,
        'activated_full_fg_and_explicit_intel_replicas_proved_by_v2_fixture': True,
        'rejected_controls': negatives, 'native_map': mapped,
        'helper': str(Path(__file__).resolve()), 'helper_sha256': sha(Path(__file__).read_bytes()),
        'scope': 'Immutable receipts retain their executed bytes/scopes. Declaration-only edge and byte-identical banked helper carry v1 physical coverage to v2; fresh v2 fixtures cover activated full FG and explicit replicas. Fitter retention/packing, routed timing and whole-core hardware gates remain separate.',
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'output': str(args.output), 'sha256': sha(args.output.read_bytes()),
                      'rejected_controls': len(negatives), 'mapped_distinct_stores': mapped['mapped_distinct_stores'] if mapped else None}))


if __name__ == '__main__':
    main()
