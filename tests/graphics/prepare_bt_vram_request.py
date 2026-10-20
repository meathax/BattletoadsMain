"""Prepare a reversible same-edge VRAM-request candidate from immutable v11."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE_ROOT = ROOT / 'build/timing_closure_20261011/address_ddr_v11_private'
BASE = {
    'rtl/BT.sv': '4d01a2fcc84ea12ab800c420f5107b26cd6b373fd5a154deb4cdba7639db66e6',
    'rtl/TMS34020/TMS34020_MC.sv': '165a7d5a0265c8c98822b3771fcdf62b9a51d2bcd85cc45abbf1fb6bdd8d650a',
    'rtl/TMS34020/TMS34020.sv': '46f0743c4b3186796c19d6fe1a2d1a3a5fa4750763f5890ff95e87789a057d1c',
}
REQUEST_FUNCTION = '''\t// Bank-independent requests, published on the original bus update edge.
\t// Display page selection stays live in BT; no bus state or cycle moves.
\tfunction automatic [3:0] VramRequests(input logic [31:0] address,
\t                                      input logic [3:0] code,
\t                                      input logic ras_active);
\t\tlogic [3:0] classes;
\t\tlogic fg_match;
\t\tclasses = AddressClass(address);
\t\tfg_match = classes[0] || (code == 4'b0101 && classes[1]);
\t\tVramRequests = {
\t\t\tras_active && (classes[3] || code == 4'b0100),
\t\t\tras_active && (classes[2] || code == 4'b0100),
\t\t\tras_active && fg_match && address[26],
\t\t\tras_active && ((fg_match && !address[26]) || code == 4'b0100)
\t\t};
\tendfunction
'''
PROJECTION_START = '''\t\t\t// Same-edge projection only; all original nonblocking assignments remain.
\t\t\tlogic [31:0] vram_address_next;
\t\t\tlogic [3:0] vram_code_next;
\t\t\tlogic vram_ras_next;
\t\t\tvram_address_next = DBUS_A;
\t\t\tvram_code_next = DBUS_CODE;
\t\t\tvram_ras_next = DBUS_RAS;
'''
PROJECTION_END = '\t\t\tVRAM_REQUEST <= VramRequests(vram_address_next, vram_code_next, vram_ras_next);\n'
sha = lambda data: hashlib.sha256(data).hexdigest()


def replace_once(text, before, after, edits):
    assert text.count(before) == 1, ('Nonunique source anchor', before[:120])
    edits.append({'before': before, 'after': after})
    return text.replace(before, after, 1)


def append_port(text, declaration, edits):
    end = text.index(');')
    before = text[:end + 2]
    after = text[:end] + '\t, ' + declaration + '\n' + text[end:end + 2]
    return replace_once(text, before, after, edits)


def transform(name, data):
    assert sha(data) == BASE[name], (name, 'Exact immutable v11 source required')
    newline = '\r\n' if b'\r\n' in data else '\n'
    text = data.decode().replace('\r\n', '\n')
    assert '\r' not in text
    edits, assignments = [], []
    if name.endswith('_MC.sv'):
        text = append_port(text, 'output reg [3:0] VRAM_REQUEST', edits)
        anchor = '\tendfunction\n\t\n'
        # AddressClass is followed by a blank line without a tab in this source.
        if anchor not in text:
            anchor = '\tendfunction\n\n'
        text = replace_once(text, anchor, anchor + REQUEST_FUNCTION + '\n', edits)
        reset = "\t\t\tDBUS_RD_EXT <= 0;\n\t\t\tDBUS_CODE <= 4'b1111;\n"
        text = replace_once(text, reset, reset + "\t\t\tVRAM_REQUEST <= 4'b0000;\n", edits)
        start = '\t\telse begin\n\t\t\t// Prepare the return snapshot'
        text = replace_once(text, start, '\t\telse begin\n' + PROJECTION_START + '\t\t\t// Prepare the return snapshot', edits)
        first = text.index(PROJECTION_START) + len(PROJECTION_START)
        last = text.index('\t\t\tend // Only architectural/bus state is EN-gated.', first)
        block = text[first:last]
        lines = block.splitlines(keepends=True)
        projected = []
        names = {'DBUS_A': 'vram_address_next', 'DBUS_CODE': 'vram_code_next', 'DBUS_RAS': 'vram_ras_next'}
        counts = {name: 0 for name in names}
        for line in lines:
            projected.append(line)
            match = re.fullmatch(r'(\s*)(DBUS_A|DBUS_CODE|DBUS_RAS)\s*<=\s*(.+);\s*\n', line)
            if match:
                indent, target, rhs = match.groups()
                counts[target] += 1
                added = indent + names[target] + ' = ' + rhs + ';\n'
                projected.append(added)
                assignments.append({'target': target, 'original_rhs': rhs, 'projection': added.strip()})
        assert counts == {'DBUS_A': 1, 'DBUS_CODE': 7, 'DBUS_RAS': 8}, counts
        text = replace_once(text, block, ''.join(projected), edits)
        tail = '\t\t\tend // Only architectural/bus state is EN-gated.\n\t\tend\n\tend\n\tassign WAIT'
        text = replace_once(text, tail, '\t\t\tend // Only architectural/bus state is EN-gated.\n' + PROJECTION_END + '\t\tend\n\tend\n\tassign WAIT', edits)
        assertion = '\t\tassert (DBUS_ADDR_CLASS === AddressClass(DBUS_A))\n'
        text = replace_once(text, assertion, '\t\tassert (VRAM_REQUEST === VramRequests(DBUS_A, DBUS_CODE, DBUS_RAS))\n\t\t\telse $fatal(1,"Published VRAM request differs from current bus state");\n' + assertion, edits)
    elif name.endswith('TMS34020.sv'):
        text = append_port(text, 'output [3:0] VRAM_REQUEST', edits)
        anchor = '\t\t.DBUS_ADDR_CLASS(ADDR_CLASS),\n'
        text = replace_once(text, anchor, anchor + '\t\t.VRAM_REQUEST(VRAM_REQUEST),\n', edits)
    elif name == 'rtl/BT.sv':
        anchor = '\twire [3:0] CPU_ADDR_CLASS;\n'
        text = replace_once(text, anchor, anchor + '\twire [3:0] CPU_VRAM_REQUEST;\n', edits)
        anchor = '\t\t.ADDR_CLASS(CPU_ADDR_CLASS),\n'
        text = replace_once(text, anchor, anchor + '\t\t.VRAM_REQUEST(CPU_VRAM_REQUEST),\n', edits)
        replacements = {
            'RAS_N | ~(FG0_SEL | FG0_SCRN)': '~(DISP_CONTROL[15] ? CPU_VRAM_REQUEST[0] : CPU_VRAM_REQUEST[1])',
            'RAS_N | ~(FG1_SEL | FG1_SCRN)': '~(DISP_CONTROL[15] ? CPU_VRAM_REQUEST[1] : CPU_VRAM_REQUEST[0])',
            'RAS_N | ~(BG0_SEL || LA[3:0] == 4\'b0100)': '~CPU_VRAM_REQUEST[2]',
            'RAS_N | ~(BG1_SEL || LA[3:0] == 4\'b0100)': '~CPU_VRAM_REQUEST[3]',
        }
        for before, after in replacements.items():
            count = text.count('.RAS_N(' + before + ')')
            assert count == (2 if 'BG' in before else 1), (before, count)
            for index in range(count):
                # Whole instance context makes each repeated BG port reversible.
                old = '.RAS_N(' + before + ')'
                new = '.RAS_N(' + after + ')'
                text = text.replace(old, new, 1)
                edits.append({'before': old, 'after': new, 'repeated_index': index})
    else:
        raise AssertionError(name)
    # Reverse the complete recorded transform, retaining all original NBAs.
    reverse = text
    for edit in reversed(edits):
        assert edit['after'] in reverse
        reverse = reverse.replace(edit['after'], edit['before'], 1)
    assert reverse.replace('\n', newline).encode() == data, (name, 'Reversible source edge')
    return text.replace('\n', newline).encode(), edits, assignments


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Keep frozen candidates immutable'
    sources, all_edits, assignments = {}, {}, []
    for name, expected in BASE.items():
        before = (BASE_ROOT / name).read_bytes()
        after, edits, recorded = transform(name, before)
        source = output / 'candidate' / name
        original = output / 'oracle' / name
        source.parent.mkdir(parents=True, exist_ok=True)
        original.parent.mkdir(parents=True, exist_ok=True)
        source.write_bytes(after)
        original.write_bytes(before)
        sources[name] = {'before': str(original), 'before_sha256': expected, 'candidate': str(source), 'sha256': sha(after)}
        all_edits[name] = edits
        assignments.extend(recorded)
    receipt = {'schema': 'bt-vram-request-private-transform-v1', 'sources': sources, 'edits': all_edits, 'projection_assignments': assignments, 'helper_sha256': sha(Path(__file__).read_bytes()), 'scope': 'Reversible immutable-v11 preparation only. Same-edge reset/load/hold and complete bus/pin/stage simulation remain to be qualified.', 'legacy_ras_reset_added': False, 'ports_append_only': True, 'constraints_changed': False}
    path = output / 'manifest.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({'manifest': str(path), 'sources': sources, 'projection_assignments': len(assignments)}))


if __name__ == '__main__':
    main()
