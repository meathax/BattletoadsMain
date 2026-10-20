"""Guarded v22 background SQ predicate edge; never edits the source project."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/timing_closure_20261011/q17_local_paths_v22_private'
PARENTS = {
    'rtl/BT.sv': '56101c47567332ede1fe4067468786556f4846bf6942e9cd87dded50336578d7',
    'rtl/bg_vram.sv': 'ba42376b22889cf0dc0f1b55203e21e1cf121daa7b4ab690ad24eb8586ba31d1',
}

def sha(data):
    return hashlib.sha256(data).hexdigest()

def replace_one(data, before, after):
    if data.count(before) != 1:
        raise AssertionError('guarded edge anchor must occur exactly once')
    return data.replace(before, after, 1)

def forward(data, edits):
    for edit in edits:
        data = replace_one(data, edit['before'].encode(), edit['after'].encode())
    return data

def inverse(data, edits):
    for edit in reversed(edits):
        data = replace_one(data, edit['after'].encode(), edit['before'].encode())
    return data

def transform(relative, parent):
    if relative not in PARENTS or sha(parent) != PARENTS[relative]:
        raise AssertionError('not the immutable v22 parent')
    newline = '\r\n' if b'\r\n' in parent else '\n'
    text = parent.decode().replace('\r\n', '\n')
    edits = []
    def add(role, before, after):
        nonlocal text
        if text.count(before) != 1:
            raise AssertionError(f'nonunique {role}')
        text = text.replace(before, after, 1)
        edits.append({'role': role, 'before': before.replace('\n', newline),
                      'after': after.replace('\n', newline)})
    if relative == 'rtl/bg_vram.sv':
        add('append-two-output-ports', 'output logic   GRID\n',
            'output logic   GRID,\noutput bit     SQ_NZ,\noutput bit     SQ_HIGH\n')
        sq = re.search(r'\t\t\tSQ <= (\(.*?);', text, re.S)
        if sq is None or text.count('SQ <=') != 2:
            raise AssertionError('SQ reset and capture sites changed')
        rhs = sq.group(1)
        capture = sq.group(0)
        comment = '\t// The 10 MHz serial pixel cadence leaves sixteen 160 MHz clocks per\n'
        nz_rhs = ' |\n\t\t'.join(
            f'(VIDEO_LANE_OH[{lane}] & (|VIDEO_WORD[{lane*8+7}: {lane*8}]))'
            for lane in range(8))
        add('same-original-sq-d-expression', comment,
            '\t// These predicates use the exact SQ D value on its original MEM edge.\n'
            '\t// bit outputs match the BT bit-byte conversion even for X/Z inputs.\n'
            '\twire [7:0] SERIAL_BYTE_D = ' + rhs + ';\n'
            '\t// Reduce each lane before the one-hot mask and scalar OR.\n'
            '\twire SERIAL_NZ_D = ' + nz_rhs + ';\n\n' + comment)
        add('same-async-reset', "\t\t\tSQ <= '0;\n",
            "\t\t\tSQ <= '0;\n\t\t\tSQ_NZ <= 1'b0;\n\t\t\tSQ_HIGH <= 1'b0;\n")
        add('same-mem-edge-capture', capture,
            '\t\t\tSQ <= SERIAL_BYTE_D;\n'
            '\t\t\tSQ_NZ <= SERIAL_NZ_D;\n'
            '\t\t\tSQ_HIGH <= SERIAL_BYTE_D[7];')
    else:
        for bg in (0, 1):
            add(f'bank-{bg}-predicate-nets', f'\tbit  [15: 0] BG{bg}_SQ;\n',
                f'\tbit  [15: 0] BG{bg}_SQ;\n'
                f'\twire [1:0] BG{bg}_SQ_NZ;\n\twire [1:0] BG{bg}_SQ_HIGH;\n')
            for bank, sl in ((0, '7:0'), (1, '15:8')):
                add(f'bg-{bg}-bank-{bank}-ports', f'\t\t.SQ(BG{bg}_SQ[{sl}]),\n',
                    f'\t\t.SQ(BG{bg}_SQ[{sl}]),\n'
                    f'\t\t.SQ_NZ(BG{bg}_SQ_NZ[{bank}]),\n'
                    f'\t\t.SQ_HIGH(BG{bg}_SQ_HIGH[{bank}]),\n')
        add('function-appended-predicates', '\t\tinput logic [2:0] enabled;\n',
            '\t\tinput logic [2:0] enabled;\n'
            '\t\tinput bit bg0_pixel_nz, bg1_pixel_nz, bg1_pixel_high;\n')
        for original, current in (
            ('bg0_nz = bg0 && enabled[0];', 'bg0_nz = bg0_pixel_nz && enabled[0];'),
            ('bg1_nz = bg1 && enabled[1];', 'bg1_nz = bg1_pixel_nz && enabled[1];'),
            ('bg1_high = bg1[7] && enabled[1];', 'bg1_high = bg1_pixel_high && enabled[1];')):
            add('function-consumes-producer-predicate', original, current)
        add('held-bit-local-predicates', '\t\tbit [7:0] SPR_PIX;\n',
            '\t\tbit [7:0] SPR_PIX;\n'
            '\t\tbit BG0_PIX_NZ, BG1_PIX_NZ, BG1_PIX_HIGH;\n')
        for bg in (0, 1):
            for bank, sl in ((0, ' 7: 0'), (1, '15: 8')):
                before = f"\t\t\t\t1'b{bank}: BG{bg}_PIX = BG{bg}_SQ[{sl}];"
                after = f"\t\t\t\t1'b{bank}: begin\n\t\t\t\t\tBG{bg}_PIX = BG{bg}_SQ[{sl}];\n"
                after += f'\t\t\t\t\tBG{bg}_PIX_NZ = BG{bg}_SQ_NZ[{bank}];\n'
                if bg == 1:
                    after += f'\t\t\t\t\tBG1_PIX_HIGH = BG1_SQ_HIGH[{bank}];\n'
                after += '\t\t\t\tend'
                add(f'hold-case-bg-{bg}-bank-{bank}', before, after)
        add('same-sys-edge-pixel-function-call',
            '\t\t\tPIX_OUT <= BT_SELECT_PIXEL(DISP_CONTROL[9:8], SPR_PIX, BG0_PIX, BG1_PIX, PIX_OUT, BG_EN);',
            '\t\t\tPIX_OUT <= BT_SELECT_PIXEL(DISP_CONTROL[9:8], SPR_PIX, BG0_PIX, BG1_PIX, PIX_OUT, BG_EN,\n'
            '\t\t\t                           BG0_PIX_NZ,BG1_PIX_NZ,BG1_PIX_HIGH);')
    candidate = text.replace('\n', newline).encode()
    if forward(parent, edits) != candidate or inverse(candidate, edits) != parent:
        raise AssertionError('whole-byte reversible edge failed')
    return candidate, edits

def verify_edge(directory):
    directory = Path(directory).resolve()
    manifest = json.loads((directory / 'manifest.json').read_text())
    if manifest['schema'] != 'bt-v22-bg-pixel-predicate-source-edge-v1':
        raise AssertionError('wrong source edge schema')
    result = {}
    for relative, entry in manifest['files'].items():
        parent = Path(entry['parent']).read_bytes()
        child = Path(entry['candidate']).read_bytes()
        expected, edits = transform(relative, parent)
        if sha(parent) != entry['parent_sha256'] or sha(child) != entry['candidate_sha256']:
            raise AssertionError('source digest changed')
        if expected != child or entry['edits'] != edits or inverse(child, edits) != parent:
            raise AssertionError('edge operations changed')
        result[relative] = (parent, child, edits)
    if set(result) != set(PARENTS):
        raise AssertionError('two exact source edges required')
    return result, manifest

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--parent-root', type=Path, default=BASE)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    files = {}
    negatives = []
    for relative in PARENTS:
        parent = (args.parent_root / relative).resolve()
        child, edits = transform(relative, parent.read_bytes())
        target = out / 'candidate' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(child)
        files[relative] = dict(parent=str(parent), parent_sha256=sha(parent.read_bytes()),
                               candidate=str(target), candidate_sha256=sha(child), edits=edits)
        for index, edit in enumerate(edits):
            changed = child.replace(edit['after'].encode(), edit['after'].encode() + b' ', 1)
            try:
                recovered = inverse(changed, edits)
                if recovered == parent.read_bytes():
                    raise RuntimeError('mutation accepted')
            except AssertionError:
                pass
            negatives.append(f'{relative}:changed-edge-{index}')
        try:
            transform(relative, parent.read_bytes() + b'\n')
        except AssertionError:
            negatives.append(f'{relative}:foreign-parent')
        else:
            raise AssertionError('foreign parent accepted')
    manifest = dict(schema='bt-v22-bg-pixel-predicate-source-edge-v1', status='PASS_SOURCE_EDGE_ONLY',
                    helper=str(Path(__file__).resolve()), helper_sha256=sha(Path(__file__).read_bytes()),
                    files=files, whole_file_raw_inverse=True, new_clock_edges=0,
                    bg_old_positional_ports_retained=True,
                    reset_and_unknown_bank_selector_holding_preserved=True,
                    source_guard_negative_controls=negatives,
                    simulation_qualified=False, mapped_or_timing_qualified=False)
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    verify_edge(out)
    print(json.dumps(dict(status='PASS_SOURCE_EDGE_ONLY', manifest=str(out/'manifest.json'),
                         manifest_sha256=sha((out/'manifest.json').read_bytes()),
                         files={key: value['candidate_sha256'] for key,value in files.items()},
                         negative_controls=len(negatives))))

if __name__ == '__main__':
    main()
