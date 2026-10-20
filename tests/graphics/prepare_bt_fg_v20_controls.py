"""Prepare three reversible same-edge foreground controls from immutable v20."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / 'build/timing_closure_20261011/fg_sprite_controls_v20_private/rtl/fg_vram.sv'
PARENT_SHA = 'ddf9c579f24837042d1eb0e700f4e6f7f27896d0e93f4538525d66bfa1efbdd9'

RAW_FUNCTIONS = '''\t// These predicates are evaluated inside the original raw-command edge.
\t// bit-valued arguments match the original individual flag X/Z captures.
\tfunction automatic bit FG_TRANSFER_COMMAND;
\t\tinput bit ras_n, oe_n, transfer;
\t\tbegin FG_TRANSFER_COMMAND = !ras_n && !oe_n && transfer; end
\tendfunction
\tfunction automatic bit FG_RMT_COMMAND;
\t\tinput bit ras_n, oe_n, we_n, transfer, se_n;
\t\tbegin FG_RMT_COMMAND = !ras_n && !oe_n && !we_n && transfer && !se_n; end
\tendfunction
\t(* preserve, dont_merge *) bit [2:0] HOLE_RAS_N_M = '1;
\t(* preserve, dont_merge *) bit [2:0] HOLE_TRANSFER_REQUEST_M = '0;
\t(* preserve, dont_merge *) bit [2:0] HOLE_RMT_REQUEST_M = '0;
'''

POSITION_FUNCTION = '''\t// Factor the original next-position equality at its original capture.
\t// logic inputs retain X/Z through arithmetic/equality; only the returned
\t// bit converts the result, exactly as the original flag assignment did.
\tfunction automatic bit FG_POSITION_END_NEXT;
\t\tinput logic [8:0] pos;
\t\tinput logic step_ram, step_ddr, restart;
\t\tinput bit ddr_end;
\t\tbegin
\t\t\tif (step_ddr) FG_POSITION_END_NEXT = pos == (ddr_end ? 9'h1fc : 9'h1f6);
\t\t\telse if (step_ram) FG_POSITION_END_NEXT = pos == (ddr_end ? 9'h1f6 : 9'h1f0);
\t\t\telse if (restart) FG_POSITION_END_NEXT = 1'b0;
\t\t\telse FG_POSITION_END_NEXT = pos == (ddr_end ? 9'h1fe : 9'h1f8);
\t\tend
\tendfunction
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def edits_for(parent):
    assert sha(parent) == PARENT_SHA
    assert parent.count(b'\r\n') == parent.count(b'\n')
    pairs = []
    def add(name, before, after):
        pairs.append({'name': name, 'before': before.replace('\n', '\r\n'), 'after': after.replace('\n', '\r\n')})
    add('owner-local-declaration', '\tbit          COPY_DDR, COPY_ODD;',
        '\tbit          COPY_DDR, COPY_ODD;\n\t// Four copies of the original owner D, one per gathered 16-bit pair.\n\t(* preserve, dont_merge *) bit [3:0] COPY_DDR_CHUNK;')
    add('raw-command-functions', "\t(* preserve, dont_merge *) bit [7:0] COPY_READ_REQUEST_M = '0;",
        RAW_FUNCTIONS + "\t(* preserve, dont_merge *) bit [7:0] COPY_READ_REQUEST_M = '0;")
    add('raw-command-same-edge-captures', '\t\tCOPY_READ_REQUEST_M <= {8{FG_READ_COMMAND(RAS_N, OE_N, WE_N, TRANSFER)}};',
        '\t\tHOLE_RAS_N_M <= {3{RAS_N}};\n\t\tHOLE_TRANSFER_REQUEST_M <= {3{FG_TRANSFER_COMMAND(RAS_N, OE_N, TRANSFER)}};\n\t\tHOLE_RMT_REQUEST_M <= {3{FG_RMT_COMMAND(RAS_N, OE_N, WE_N, TRANSFER, SE_N)}};\n\t\tCOPY_READ_REQUEST_M <= {8{FG_READ_COMMAND(RAS_N, OE_N, WE_N, TRANSFER)}};')
    for name, line, extra in [
        ('owner-reset', '\t\t\tCOPY_DDR <= 0;', "\t\t\tCOPY_DDR_CHUNK <= '0;"),
        ('owner-read-start', '\t\t\t\t\tCOPY_DDR <= |A_M[9:8];', '\t\t\t\t\tCOPY_DDR_CHUNK <= {4{|A_M[9:8]}};'),
        ('owner-collect', '\t\t\t\t\t\tCOPY_DDR <= |next_addr[9:8];', '\t\t\t\t\t\tCOPY_DDR_CHUNK <= {4{|next_addr[9:8]}};'),
    ]:
        add(name, line, line + '\n' + extra)
    add('owner-pair-consumer', 'COPY_WORD[(copy_word_bank*2 + byte_index)*8 +: 8] <= COPY_DDR ? COPY_DDR_BYTE : COPY_RAM_BYTE;',
        'COPY_WORD[(copy_word_bank*2 + byte_index)*8 +: 8] <= COPY_DDR_CHUNK[copy_word_bank] ? COPY_DDR_BYTE : COPY_RAM_BYTE;')
    add('position-equality-function', '\t// Decode the original position D at the position capture edge.',
        POSITION_FUNCTION + '\t// Decode the original position D at the position capture edge.')
    add('remove-global-position-reset', "\t\t\tHOLE_POS_END_RAM_B <= '0;\n\t\t\tHOLE_POS_END_DDR_B <= '0;", '')
    add('remove-global-position-capture', "\t\t\tHOLE_POS_END_RAM_B <= {3{HOLE_NEXT_POS == 9'h1f8}};\n\t\t\tHOLE_POS_END_DDR_B <= {3{HOLE_NEXT_POS == 9'h1fe}};", '')
    add('local-raw-ras-consumer', '\t\t(* keep *) wire start_ras = !RAS_N_M && COPY_ADDR_RAS_OLD_B[hole_group];',
        '\t\t(* keep *) wire start_ras = !HOLE_RAS_N_M[hole_group] && COPY_ADDR_RAS_OLD_B[hole_group];')
    add('local-transfer-consumer', '\t\t(* keep *) wire start_transfer = start_ras && !OE_N_M && TRANSFER_M;',
        '\t\t(* keep *) wire start_transfer = HOLE_TRANSFER_REQUEST_M[hole_group] && COPY_ADDR_RAS_OLD_B[hole_group];')
    add('local-rmt-consumer', '\t\t(* keep *) wire start_rmt = start_transfer && !WE_N_M && !SE_N_M;',
        '\t\t(* keep *) wire start_rmt = HOLE_RMT_REQUEST_M[hole_group] && COPY_ADDR_RAS_OLD_B[hole_group];')
    add('local-position-reset', '\t\t\t\tCOPY_ADDR_N[6*hole_group +: 6] <= COPY_RESET_VALUE;',
        '\t\t\t\tCOPY_ADDR_N[6*hole_group +: 6] <= COPY_RESET_VALUE;\n\t\t\t\tHOLE_POS_END_RAM_B[hole_group] <= 1\'b0;\n\t\t\t\tHOLE_POS_END_DDR_B[hole_group] <= 1\'b0;')
    add('local-position-capture', '\t\t\tend else begin\n\t\t\t\tHOLE_A_FF[6*hole_group +: 6] <=',
        '\t\t\tend else begin\n\t\t\t\tHOLE_POS_END_RAM_B[hole_group] <= FG_POSITION_END_NEXT(SREG_POS, step_ram, step_ddr, start_transfer, 1\'b0);\n\t\t\t\tHOLE_POS_END_DDR_B[hole_group] <= FG_POSITION_END_NEXT(SREG_POS, step_ram, step_ddr, start_transfer, 1\'b1);\n\t\t\t\tHOLE_A_FF[6*hole_group +: 6] <=')
    add('owner-identity-assertion', '\t\tassert (COPY_DDR == |COPY_ADDR[9:8] && COPY_ODD == COPY_ADDR[0] &&',
        '\t\tassert (COPY_DDR_CHUNK == {4{COPY_DDR}})\n\t\t\telse $fatal(1,"foreground local copy-owner changed capture edge");\n\t\tassert (COPY_DDR == |COPY_ADDR[9:8] && COPY_ODD == COPY_ADDR[0] &&')
    add('local-predicate-identity-assertions', '\t\t\tassert (next_rmt == RDY_NEXT_RMT_EXEC && next_pos == HOLE_NEXT_POS &&',
        '\t\t\tassert (HOLE_RAS_N_M[hole_group] == RAS_N_M &&\n\t\t\t        HOLE_TRANSFER_REQUEST_M[hole_group] == (!RAS_N_M && !OE_N_M && TRANSFER_M) &&\n\t\t\t        HOLE_RMT_REQUEST_M[hole_group] == (!RAS_N_M && !OE_N_M && !WE_N_M && TRANSFER_M && !SE_N_M))\n\t\t\t\telse $fatal(1,"foreground local raw command differs after capture");\n\t\t\tassert (HOLE_POS_END_RAM_B[hole_group] == (SREG_POS == 9\'h1f8) &&\n\t\t\t        HOLE_POS_END_DDR_B[hole_group] == (SREG_POS == 9\'h1fe))\n\t\t\t\telse $fatal(1,"foreground local position completion differs after capture");\n\t\t\tassert (next_rmt == RDY_NEXT_RMT_EXEC && next_pos == HOLE_NEXT_POS &&')
    return pairs


def forward(data, edits):
    text = data.decode('latin1')
    for e in edits:
        assert text.count(e['before']) == 1, (e['name'], text.count(e['before']))
        text = text.replace(e['before'], e['after'], 1)
    return text.encode('latin1')


def reverse(data, edits):
    text = data.decode('latin1')
    for e in reversed(edits):
        if not e['after']:
            # Removal records use the exact original neighbor context supplied
            # separately below: empty-string reinsertion is never permitted.
            raise AssertionError('reverse requires contextual edits')
        assert text.count(e['after']) == 1, (e['name'], text.count(e['after']))
        text = text.replace(e['after'], e['before'], 1)
    return text.encode('latin1')


def transform(parent):
    edits = edits_for(parent)
    # Bind the two removed assignments to their unchanged preceding history D.
    # This makes every inverse anchor nonempty and preserves exact raw bytes.
    for e in edits:
        if e['name'] == 'remove-global-position-reset':
            prefix = "\t\t\tCOPY_ADDR_RAS_OLD_B <= '1;\r\n"
            e['before'], e['after'] = prefix + e['before'], prefix.rstrip('\r\n')
        elif e['name'] == 'remove-global-position-capture':
            prefix = '\t\t\tCOPY_ADDR_RAS_OLD_B <= {3{RAS_N_M}};\r\n'
            e['before'], e['after'] = prefix + e['before'], prefix.rstrip('\r\n')
    candidate = forward(parent, edits)
    assert reverse(candidate, edits) == parent
    return candidate, edits


def verify_predicates():
    command = 0
    for value in range(32):
        ras, oe, we, trans, se = [bool(value & (1 << i)) for i in range(5)]
        for history in (False, True):
            a = (not ras) and history
            assert (a and (not oe) and trans) == ((not ras) and (not oe) and trans and history)
            assert (a and (not oe) and trans and (not we) and (not se)) == ((not ras) and (not oe) and (not we) and trans and (not se) and history)
            command += 1
    position = 0
    for pos in range(512):
        for controls in range(8):
            ram, ddr, restart = [bool(controls & (1 << i)) for i in range(3)]
            old = 0 if restart else pos
            if ram:
                old = (pos + 8) & 511
            if ddr:
                old = (pos + 2) & 511
            for ddr_end in (False, True):
                end = 510 if ddr_end else 504
                factored = pos == (508 if ddr_end else 502) if ddr else pos == (502 if ddr_end else 496) if ram else False if restart else pos == end
                assert factored == (old == end)
                position += 1
    return {'binary_command_history_cases': command, 'all_512_position_priority_cases': position,
            'four_state_obligation': 'Compiled actual functions with raw X/Z flag captures, unknown continuous position/equality, and original bit conversion remain required.'}


def record(p):
    b = p.read_bytes()
    return {'path': str(p), 'sha256': sha(b), 'bytes': len(b)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    assert not out.exists(), out
    parent = PARENT.read_bytes()
    candidate, edits = transform(parent)
    coverage = verify_predicates()
    target = out / 'candidate/rtl/fg_vram.sv'
    target.parent.mkdir(parents=True)
    target.write_bytes(candidate)
    oracle = out / 'immutable-parent/rtl/fg_vram.sv'
    oracle.parent.mkdir(parents=True)
    oracle.write_bytes(parent)
    manifest = {'schema': 'bt-v20-fg-local-control-source-edge-v1', 'status': 'SOURCE_EDGE_PASS_COMPILED_PROOFS_PENDING', 'parent': record(PARENT), 'oracle': record(oracle), 'candidate': record(target), 'helper': record(Path(__file__).resolve()), 'edits': edits, 'coverage': coverage, 'inverse_raw_equal': True, 'clock_reset_startup_contract': 'COPY_DDR_CHUNK copies every original owner assignment in the same async-reset controller; raw predicates capture in the original unconditional raw MEM edge with bit arguments; completion flags move between same-edge/same-async-reset blocks with logic arguments and original final bit conversion; no latency/data/priority/leaf/interface/SDC changes.'}
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'candidate': record(target), 'manifest': record(out / 'manifest.json'), 'coverage': coverage, 'inverse_raw_equal': True}, separators=(',', ':')))


if __name__ == '__main__':
    main()
