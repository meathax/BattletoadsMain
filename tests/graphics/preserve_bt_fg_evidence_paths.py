"""Resolve exactly seven archived FG proof inputs to their retained raw bytes.

This changes only the callback used by a freshly loaded evidence verifier. It
does not alter pathlib, an execution log, a source oracle or a frozen helper.
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PARENT_RECEIPT = ROOT / 'build/final_v18_current_input_qualification/receipt.json'
PARENT_SHA = 'a7f8af180aaabfe7257229d43b15698ab32b19d2b92c5c5c7df8e401c25412a7'
OLD_DIRECTORY = Path('R:/Verilator/BT/fg-serial-controls-26bcf762d3d84a4ca07212ede6b3b824')
RETAINED_DIRECTORY = ROOT / 'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2-compiled-inputs'
INPUTS = {
    'fg_vram.sv': 'f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b',
    'reference-fg_vram.sv': '0a2dfc2bba06f8127979b6546671a4361b004732d99767b9ba74930c09780388',
    'ram_models.sv': '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
    'item4_foreground_equivalence_tb.sv': 'af689824790f60bcce1b309cae68071e91fb693281da99a9c672e9e8978bc9aa',
    'ddram.sv': 'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'bt_fg_ddr_clear.sv': 'bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1',
    'foreground_ddr_tb.sv': 'fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c',
}
SCHEMA = 'bt-seven-fg-executed-input-path-preservation-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def expected_records():
    return [{'original_path': str(OLD_DIRECTORY / name),
             'retained_path': str(RETAINED_DIRECTORY / name), 'sha256': digest}
            for name, digest in INPUTS.items()]


def validate_membership(records, ledger):
    assert records == expected_records(), 'Only the exact seven declared substitutions are permitted'
    assert len(records) == len({x['original_path'] for x in records}) == 7
    for item in records:
        assert ledger[item['original_path']] == item['sha256'], 'Historical ledger changed'
        assert ledger[item['retained_path']] == item['sha256'], 'Copy is not the originally retained identical input'


def validate_bytes(records, read, exists):
    for item in records:
        assert sha(read(item['retained_path'])) == item['sha256'], 'Retained copy altered or absent'
        if exists(item['original_path']):
            assert sha(read(item['original_path'])) == item['sha256'], 'Original input altered'


def strict_read(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink(), ('Missing or symbolic retained input', str(path))
    return path.read_bytes()


def verify_manifest(path):
    data = json.loads(strict_read(path))
    assert data['schema'] == SCHEMA and data['status'] == 'PASS_EXACT_RAW_PATH_PRESERVATION'
    assert data['helper_sha256'] == sha(Path(__file__).read_bytes())
    assert data['original_receipt_sha256'] == PARENT_SHA
    parent_raw = strict_read(PARENT_RECEIPT)
    assert sha(parent_raw) == PARENT_SHA
    ledger = json.loads(parent_raw)['bound_evidence_files']
    validate_membership(data['substitutions'], ledger)
    validate_bytes(data['substitutions'], strict_read, lambda p: Path(p).exists())
    assert data['disappearance_cause'] == 'Unknown; no cleanup source inferred'
    assert data['old_receipts_helpers_logs_modified'] is False
    assert data['substitution_count'] == 7
    return data


def evidence_callback_class(original_class, manifest):
    """Use the old verifier unchanged with only these seven callback requests."""
    records = manifest['substitutions']
    assert records == expected_records()
    known = {item['original_path']: item for item in records}

    class PreservedEvidence(original_class):
        def file(self, path, expected=None):
            original = Path(path)
            # Literal absolute names preserve the observed requests, without
            # following a symlink or admitting another file in the old folder.
            item = known.get(str(original.absolute()))
            if item is None:
                return super().file(path, expected)
            assert expected == item['sha256'], 'Undeclared callback digest'
            assert not original.is_symlink(), 'Original callback path became a symlink'
            if original.exists():
                assert sha(strict_read(original)) == item['sha256'], 'Original callback input changed'
            return super().file(item['retained_path'], item['sha256'])

    return PreservedEvidence


def verify_original_receipt(module, manifest):
    """Temporarily select the narrow evidence callback in this loaded module."""
    original = module.Evidence
    module.Evidence = evidence_callback_class(original, manifest)
    try:
        return module.verify_composition_receipt(PARENT_RECEIPT)
    finally:
        module.Evidence = original


def negative_controls(manifest):
    ledger = json.loads(strict_read(PARENT_RECEIPT))['bound_evidence_files']
    records = manifest['substitutions']
    controls = []

    def reject(label, operation):
        try:
            operation()
        except (AssertionError, KeyError, OSError):
            controls.append({'name': label, 'rejected': True})
            return
        raise AssertionError('Path preservation negative accepted: ' + label)

    reject('eighth undeclared path', lambda: validate_membership(records + [records[0]], ledger))
    reject('missing declared path', lambda: validate_membership(records[:-1], ledger))
    changed = [dict(x) for x in records]; changed[0]['sha256'] = '0' * 64
    reject('manifest digest changed', lambda: validate_membership(changed, ledger))
    changed = [dict(x) for x in records]; changed[0]['retained_path'] += '.foreign'
    reject('manifest foreign retained target', lambda: validate_membership(changed, ledger))
    altered_ledger = dict(ledger); altered_ledger[records[0]['original_path']] = '0' * 64
    reject('historical ledger changed', lambda: validate_membership(records, altered_ledger))
    reject('retained copy changed', lambda: validate_bytes(records, lambda p: strict_read(p) + b'changed' if p == records[0]['retained_path'] else strict_read(p), lambda p: False))
    reject('original changed when present', lambda: validate_bytes(records, lambda p: b'changed' if p == records[0]['original_path'] else strict_read(p), lambda p: p == records[0]['original_path']))
    reject('retained copy absent', lambda: validate_bytes(records, lambda p: (_ for _ in ()).throw(FileNotFoundError(p)), lambda p: False))

    class DummyEvidence:
        def file(self, path, expected=None):
            assert expected is not None
            data = strict_read(path)
            assert sha(data) == expected
            return data
    callback = evidence_callback_class(DummyEvidence, manifest)()
    reject('undeclared absent callback path', lambda: callback.file(OLD_DIRECTORY / 'eighth-input.sv', '0' * 64))
    reject('declared callback wrong expected digest', lambda: callback.file(records[0]['original_path'], '0' * 64))
    assert len(controls) == 10
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve(); output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite a preservation record'
    parent = strict_read(PARENT_RECEIPT); assert sha(parent) == PARENT_SHA
    records = expected_records()
    validate_membership(records, json.loads(parent)['bound_evidence_files'])
    validate_bytes(records, strict_read, lambda p: Path(p).exists())
    result = {'schema': SCHEMA, 'status': 'PASS_EXACT_RAW_PATH_PRESERVATION',
              'helper_sha256': sha(Path(__file__).read_bytes()),
              'original_receipt': str(PARENT_RECEIPT), 'original_receipt_sha256': PARENT_SHA,
              'substitution_count': 7, 'substitutions': records,
              'original_absent_at_observation': [x['original_path'] for x in records if not Path(x['original_path']).exists()],
              'disappearance_cause': 'Unknown; no cleanup source inferred',
              'old_receipts_helpers_logs_modified': False,
              'scope': 'Exact raw input byte and declared callback path preservation; no simulation rerun or new execution claim'}
    result['negative_controls'] = negative_controls(result)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes((json.dumps(result, indent=2) + '\n').encode())
    verify_manifest(output)
    print(json.dumps({'manifest': str(output), 'sha256': sha(output.read_bytes()), 'substitutions': 7, 'negative_controls': 10}))


if __name__ == '__main__':
    main()
