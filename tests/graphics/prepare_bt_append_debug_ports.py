"""Repair only the class-port position in frozen v12 CPU/MC declarations."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE_ROOT = ROOT / 'build/timing_closure_20261011/vram_request_v12_private'
BASE = {
    'rtl/TMS34020/TMS34020.sv': '691e53a54c1796dc391e90afdc74679b9b10e285baafee6fec5151c5623efff3',
    'rtl/TMS34020/TMS34020_MC.sv': '026ffd76251e84a532fd749076f8fbc11d0792941df67140c69f9f8fd05adce0',
}
sha = lambda data: hashlib.sha256(data).hexdigest()


def lf(data):
    text = data.decode().replace('\r\n', '\n')
    assert '\r' not in text
    return text


def transform(name, before):
    assert sha(before) == BASE[name], 'Exact frozen v12 input required: ' + name
    text = lf(before)
    boundary = text.index(');') + 2
    header, body = text[:boundary], text[boundary:]
    class_name = 'DBUS_ADDR_CLASS' if name.endswith('_MC.sv') else 'ADDR_CLASS'
    previous = 'DBUS_ANY_BE_FG' if name.endswith('_MC.sv') else 'WRITE_ANY_FG'
    pattern = r'(?m)^(\toutput[^\n]*\b' + previous + r'),\n(\toutput[^\n]*\b' + class_name + r')\n'
    found = list(re.finditer(pattern, header))
    assert len(found) == 1, ('Exact two declaration lines required', name)
    match = found[0]
    declaration = match[2]
    first_old = match[0]
    first_new = match[1] + '\n'
    result = header.replace(first_old, first_new, 1)
    second_old = '`endif\n\t, output'
    assert result.count(second_old) == 1 and 'VRAM_REQUEST' in result[result.index(second_old):]
    second_new = '`endif\n\t, ' + declaration.strip() + '\n\t, output'
    result = result.replace(second_old, second_new, 1)
    restored = result.replace(second_new, second_old, 1).replace(first_new, first_old, 1)
    assert restored == header and result[result.index(');') + 2:] == ''
    newline = '\r\n' if b'\r\n' in before else '\n'
    after = (result + body).replace('\n', newline).encode()
    assert lf(after).split(');', 1)[1] == lf(before).split(');', 1)[1]
    return after, [{'before': first_old, 'after': first_new}, {'before': second_old, 'after': second_new}]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Keep frozen source edges immutable'
    sources, changes = {}, {}
    for name, expected in BASE.items():
        before = (BASE_ROOT / name).read_bytes()
        after, edits = transform(name, before)
        for folder, data in (('oracle', before), ('candidate', after)):
            path = output / folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        sources[name] = {'before_sha256': expected, 'sha256': sha(after),
                         'before_lf_sha256': sha(lf(before).encode()), 'lf_sha256': sha(lf(after).encode()),
                         'candidate': str(output / 'candidate' / name)}
        changes[name] = edits
    manifest = {'schema': 'bt-v12-debug-append-only-declaration-edge-v1', 'sources': sources,
                'changes': changes, 'helper_sha256': sha(Path(__file__).read_bytes()),
                'functional_bodies_byte_identical': True, 'root_modified': False,
                'scope': 'Preparation only; compiler preprocessing/profile and ABI proof are separate.'}
    path = output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'manifest': str(path), 'sources': sources}))


if __name__ == '__main__':
    main()
