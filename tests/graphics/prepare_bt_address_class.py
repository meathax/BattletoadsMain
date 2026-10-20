"""Prepare same-edge CPU address classes from the immutable v9 inputs."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = {
    'rtl/BT.sv': '69e8eef01824c66356c4e1427f5bab3509534aba39c23df01a3dce713be2672b',
    'rtl/TMS34020/TMS34020.sv': 'b559dd361d02705cc19088d9b09389b1f978645b7c7f3cb8cb761877226de1a9',
    'rtl/TMS34020/TMS34020_MC.sv': '01bc6d0da7355616fa615b3c75132e85ab30810f68c5474620fb045b8be25531',
}
sha = lambda data: hashlib.sha256(data).hexdigest()

CLASS_FUNCTION = '''\t// Published with DBUS_A, so the fast VRAM input needs no wide decode.
\t// Bits: normal foreground, serial foreground, background 0, background 1.
\tfunction automatic [3:0] AddressClass(input logic [31:0] address);
\t\tAddressClass = {
\t\t\taddress[31:22] == {8'hB4,2'b00},
\t\t\taddress[31:22] == {8'hB0,2'b00},
\t\t\t(address[31:27] & 5'b10111) == 5'b10100,
\t\t\taddress[31:27] == 5'b10100 && address[25:22] == 4'b0000
\t\t};
\tendfunction
'''
OLD_ADDRESS_LOAD = '''\t\t\t\tif (!MC_STATE && (MC_READ_EXT || MC_WRITE_EXT || SCRREF_PEND || READ || WRITE_PRE || CACHE))
\t\t\t\t\tDBUS_A <= MC_READ_EXT || MC_WRITE_EXT ? MC_ADDR :
\t\t\t\t\t          SCRREF_PEND ? {SCRREF_ADDR[31:5],5'b00000} :
\t\t\t\t\t          (READ || WRITE_PRE) && !CACHE ? MC_ADDR :
\t\t\t\t\t          {PC[31:7],PC[6:5]+FETCH_LSB,5'b00000};'''
NEW_ADDRESS_LOAD = '''\t\t\t\tif (!MC_STATE && (MC_READ_EXT || MC_WRITE_EXT || SCRREF_PEND || READ || WRITE_PRE || CACHE)) begin
\t\t\t\t\tbit [31:0] address_next;
\t\t\t\t\taddress_next = MC_READ_EXT || MC_WRITE_EXT ? MC_ADDR :
\t\t\t\t\t               SCRREF_PEND ? {SCRREF_ADDR[31:5],5'b00000} :
\t\t\t\t\t               (READ || WRITE_PRE) && !CACHE ? MC_ADDR :
\t\t\t\t\t               {PC[31:7],PC[6:5]+FETCH_LSB,5'b00000};
\t\t\t\t\tDBUS_A <= address_next;
\t\t\t\t\tDBUS_ADDR_CLASS <= AddressClass(address_next);
\t\t\t\tend'''


def replace_once(text, before, after):
    assert text.count(before) == 1, 'Source anchor is not unique: ' + before[:100]
    return text.replace(before, after, 1)


def address_class_transform(name, data):
    assert sha(data) == BASE[name], 'The exact v9 baseline changed: ' + name
    newline = '\r\n' if b'\r\n' in data else '\n'
    text = data.decode().replace('\r\n', '\n')
    assert '\r' not in text, 'Only LF/CRLF newline handling is allowed'
    if name.endswith('_MC.sv'):
        text = replace_once(text, '\toutput reg         DBUS_ANY_BE_FG\n',
                            '\toutput reg         DBUS_ANY_BE_FG,\n\toutput reg [ 3: 0] DBUS_ADDR_CLASS\n')
        text = replace_once(text, '\timport TMS34020_PKG::*;\n',
                            '\timport TMS34020_PKG::*;\n\n' + CLASS_FUNCTION)
        text = replace_once(text, '\t\t\tDBUS_A <= \'0;\n',
                            '\t\t\tDBUS_A <= \'0;\n\t\t\tDBUS_ADDR_CLASS <= 4\'b0000;\n')
        text = replace_once(text, OLD_ADDRESS_LOAD, NEW_ADDRESS_LOAD)
        anchor = '\talways @(posedge CLK) if (RST_N) begin\n'
        text = replace_once(text, anchor, anchor +
                            '\t\tassert (DBUS_ADDR_CLASS === AddressClass(DBUS_A))\n' +
                            '\t\t\telse $fatal(1,"Published address class differs from DBUS_A");\n')
    elif name.endswith('TMS34020.sv'):
        text = replace_once(text, '\toutput             WRITE_ANY_FG\n',
                            '\toutput             WRITE_ANY_FG,\n\toutput     [ 3: 0] ADDR_CLASS\n')
        text = replace_once(text, '\t\t.DBUS_A(DBUS_A),\n',
                            '\t\t.DBUS_A(DBUS_A),\n\t\t.DBUS_ADDR_CLASS(ADDR_CLASS),\n')
    elif name == 'rtl/BT.sv':
        matches = list(re.finditer(r'\tTMS34020 CPU\s*\(', text))
        assert len(matches) == 1
        offset = matches[0].start()
        text = text[:offset] + '\twire [3:0] CPU_ADDR_CLASS;\n' + text[offset:]
        text = replace_once(text, '\t\t.LA(LA),\n',
                            '\t\t.LA(LA),\n\t\t.ADDR_CLASS(CPU_ADDR_CLASS),\n')
        text = replace_once(text, "wire BG0_SEL = LA[31:22] == {8'hB0,2'b00};",
                            'wire BG0_SEL = CPU_ADDR_CLASS[2];')
        text = replace_once(text, "wire BG1_SEL = LA[31:22] == {8'hB4,2'b00};",
                            'wire BG1_SEL = CPU_ADDR_CLASS[3];')
        text = replace_once(text, "\twire FG_DISP_SEL = LA[3:0] == 4'b0101 ?\n\t\t(LA[31:26] & 6'b101111) == 6'b101000 : LA[31:22] == {8'hA0,2'b00};",
                            '\twire FG_DISP_SEL = FG_CPU_ADDR_MATCH && !LA[26];')
        text = replace_once(text, "\twire FG_DRAW_SEL = LA[3:0] == 4'b0101 ?\n\t\t(LA[31:26] & 6'b101111) == 6'b101001 : LA[31:22] == {8'hA4,2'b00};",
                            '\twire FG_DRAW_SEL = FG_CPU_ADDR_MATCH && LA[26];')
        text = replace_once(text, "\twire FG_CPU_ADDR_MATCH = LA[3:0] == 4'b0101 ?\n\t\t(LA[31:27] & 5'b10111) == 5'b10100 :\n\t\tLA[31:27] == 5'b10100 && LA[25:22] == 4'b0000;",
                            "\twire FG_CPU_ADDR_MATCH = CPU_ADDR_CLASS[0] ||\n\t\t(LA[3:0] == 4'b0101 && CPU_ADDR_CLASS[1]);")
        old_transfer = "(LA[3:0] == 4'b0101 && (LA[31:26] & 6'b101111) == 6'b101000) || LA[3:0] == 4'b0100"
        new_transfer = "(LA[3:0] == 4'b0101 && CPU_ADDR_CLASS[1] && !LA[26]) || LA[3:0] == 4'b0100"
        assert text.count(old_transfer) == 2
        text = text.replace(old_transfer, new_transfer)
    else:
        raise AssertionError(name)
    return text.replace('\n', newline).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    destination = args.output.resolve()
    destination.relative_to(ROOT / 'build')
    destination.mkdir(parents=True, exist_ok=False)
    sources = {}
    for name, expected in BASE.items():
        source = (args.source_root / name).resolve()
        before = source.read_bytes()
        after = address_class_transform(name, before)
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(after)
        sources[name] = {'before': str(source), 'before_sha256': expected,
                         'path': str(target), 'sha256': sha(after)}
    receipt = destination / 'preparation_edge.json'
    receipt.write_text(json.dumps({'schema': 'bt-address-class-preparation-v1',
        'scope': 'exact same-edge address-class transform; no simulation or timing claim',
        'sources': sources}, indent=2) + '\n')
    print(json.dumps({'receipt': str(receipt), 'sources': sources}))


if __name__ == '__main__':
    main()
