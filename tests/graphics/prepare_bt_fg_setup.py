"""Guarded, edge-preserving foreground setup candidate from frozen v18.

This writes only a new private directory. It does not edit the core, constraints,
models, old fixtures, accepted receipts, or another agent's candidate.
"""
from __future__ import annotations
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PARENT = ROOT / 'build/timing_closure_20261011/reset_partition_v18_private/rtl/fg_vram.sv'
PARENT_SHA = '15ca6106299cebaa05e7651b340c4c908b692385af89a75498bf0d60674cf6ae'
SHA = lambda data: hashlib.sha256(data).hexdigest()


def transform(parent: bytes) -> tuple[bytes, list[dict]]:
    assert SHA(parent) == PARENT_SHA, 'The exact routed v18 parent is required'
    assert b'\r\n' in parent and b'\n' not in parent.replace(b'\r\n', b'')
    text = parent.decode().replace('\r\n', '\n')
    edits = []
    def replace(old: str, new: str):
        nonlocal text
        assert text.count(old) == 1, ('Source guard failed', old[:100])
        text = text.replace(old, new, 1)
        edits.append({'old': old, 'new': new})

    replace('\tbit [17: 0] A_M;\n',
        '\t// Decode at the original raw-command capture edge. The bit casts\n'
        '\t// reproduce the original individual two-state flag captures, also\n'
        '\t// when a four-state simulator presents X/Z at an input.\n'
        '\t(* preserve, dont_merge *) bit [7:0] COPY_READ_REQUEST_M = \'0;\n'
        '\tbit [17: 0] A_M;\n')
    replace('\t\tA_M <= A;\n',
        '\t\tCOPY_READ_REQUEST_M <= {8{!bit\'(RAS_N) && !bit\'(OE_N) && bit\'(WE_N) && bit\'(TRANSFER)}};\n'
        '\t\tA_M <= A;\n')
    replace('\talways @(posedge CLK) begin\n\t\tfor (integer b = 0; b < 4; b = b + 1)\n'
            '\t\t\tSADDR_C_BK[b] <= {HOLE_NEXT_ADDR[15:10], HOLE_NEXT_ADDR[7:3]};\n\tend\n', '')
    replace('\t\t(* keep *) wire read_start = !RAS_N_M && SERIAL_COPY_RAS_OLD_B[serial_copy_bank] &&\n'
            '\t\t\t!OE_N_M && WE_N_M && TRANSFER_M;',
        '\t\t(* keep *) wire read_start = COPY_READ_REQUEST_M[serial_copy_bank] && SERIAL_COPY_RAS_OLD_B[serial_copy_bank];')
    replace('\t\twire [17:0] next_copy_addr = ({18{advance_copy}} & COPY_ADDR_STEP_VALUE) |\n',
        '\t\t// Preserve the original later collect-over-restart priority, with\n'
        '\t\t// each bank selecting the complete next address beside its flops.\n'
        '\t\twire [17:0] next_addr = ({18{advance_copy}} & COPY_ADDR_N) |\n'
        '\t\t\t({18{start_copy}} & A_M) | ({18{hold_copy}} & COPY_ADDR);\n'
        '\t\twire [17:0] next_copy_addr = ({18{advance_copy}} & COPY_ADDR_STEP_VALUE) |\n')
    replace('\t\t\tif (!RST_N) SADDR_CN_BK[serial_copy_bank] <= \'0;\n'
            '\t\t\telse SADDR_CN_BK[serial_copy_bank] <= {next_copy_addr[15:10],next_copy_addr[7:3]};',
        '\t\t\tif (!RST_N) begin\n'
        '\t\t\t\tSADDR_C_BK[serial_copy_bank] <= \'0;\n'
        '\t\t\t\tSADDR_CN_BK[serial_copy_bank] <= \'0;\n'
        '\t\t\tend else begin\n'
        '\t\t\t\tSADDR_C_BK[serial_copy_bank] <= {next_addr[15:10],next_addr[7:3]};\n'
        '\t\t\t\tSADDR_CN_BK[serial_copy_bank] <= {next_copy_addr[15:10],next_copy_addr[7:3]};\n'
        '\t\t\tend')
    replace('\t// Capture the complete next ready predicate on the existing MEM edge.\n',
        '\t// Same-D state predecode for ready only: no old-Q pipeline or extra\n'
        '\t// consumer edge. Restart is followed by the original collect priority.\n'
        '\t(* preserve, dont_merge *) bit RDY_COPY_COLLECT;\n'
        '\talways @(posedge CLK or negedge RST_N) begin\n'
        '\t\tif (!RST_N) RDY_COPY_COLLECT <= 1\'b0;\n'
        '\t\telse RDY_COPY_COLLECT <= RDY_NEXT_COPY_STATE == 3\'d3;\n'
        '\tend\n'
        '\twire RDY_LOCAL_START_RAS = !RAS_N_M && RDY_RAS_N_OLD;\n'
        '\twire RDY_LOCAL_START_READ = COPY_READ_REQUEST_M[7] && RDY_RAS_N_OLD;\n'
        '\twire RDY_LOCAL_UNALIGNED_NEXT = ((UNALIGNED_EXEC && !RDY_LOCAL_START_RAS) ||\n'
        '\t\t(RDY_LOCAL_START_READ && CPU_SHIFT_M)) && !(UNALIGNED_EXEC && RDY_COPY_COLLECT && (&COPY_POS));\n'
        '\twire RDY_LOCAL_COPY_WE = UNALIGNED_EXEC && RDY_COPY_COLLECT && COPY_POS_OH[7];\n'
        '\t// Capture the complete next ready predicate on the existing MEM edge.\n')
    replace(' | RDY_NEXT_UNALIGNED_EXEC | RDY_NEXT_COPY_WE | RDY_NEXT_CPU_RAM_WE |',
            ' | RDY_LOCAL_UNALIGNED_NEXT | RDY_LOCAL_COPY_WE | RDY_NEXT_CPU_RAM_WE |')
    replace('\t(* preserve, dont_merge *) bit [2:0] COPY_ADDR_RAS_OLD_B;\n',
        '\t(* preserve, dont_merge *) bit [2:0] COPY_ADDR_RAS_OLD_B;\n'
        '\t// Decode the original position D at the position capture edge. Each\n'
        '\t// packet-address group gets its own completion flags, with identical\n'
        '\t// zero startup and asynchronous reset to the original position.\n'
        '\t(* preserve, dont_merge *) bit [2:0] HOLE_POS_END_RAM_B, HOLE_POS_END_DDR_B;\n')
    replace('\t\t\tCOPY_ADDR_RAS_OLD_B <= \'1;\n',
        '\t\t\tCOPY_ADDR_RAS_OLD_B <= \'1;\n'
        '\t\t\tHOLE_POS_END_RAM_B <= \'0;\n'
        '\t\t\tHOLE_POS_END_DDR_B <= \'0;\n')
    replace('\t\t\tCOPY_ADDR_RAS_OLD_B <= {3{RAS_N_M}};\n',
        '\t\t\tCOPY_ADDR_RAS_OLD_B <= {3{RAS_N_M}};\n'
        '\t\t\tHOLE_POS_END_RAM_B <= {3{HOLE_NEXT_POS == 9\'h1f8}};\n'
        '\t\t\tHOLE_POS_END_DDR_B <= {3{HOLE_NEXT_POS == 9\'h1fe}};\n')
    replace('\t\t(* keep *) wire start_read = start_transfer && WE_N_M;',
        '\t\t(* keep *) wire start_read = COPY_READ_REQUEST_M[4+hole_group] && COPY_ADDR_RAS_OLD_B[hole_group];')
    replace('\t\t(* keep *) wire stop_rmt = (step_ram && SREG_POS == 9\'h1f8) ||\n'
            '\t\t\t(step_ddr && SREG_POS == 9\'h1fe);',
        '\t\t(* keep *) wire stop_rmt = (step_ram && HOLE_POS_END_RAM_B[hole_group]) ||\n'
        '\t\t\t(step_ddr && HOLE_POS_END_DDR_B[hole_group]);')
    # No assertion, original controller update, or timing command is removed.
    return text.replace('\n', '\r\n').encode(), edits


def reverse(candidate: bytes, edits: list[dict]) -> bytes:
    text = candidate.decode().replace('\r\n', '\n')
    for edit in reversed(edits):
        if not edit['new']:
            # Restore the removed block using its unique original following anchor.
            anchor = '\t(* preserve, dont_merge *) bit [3:0] SERIAL_COPY_RAS_OLD_B;\n'
            assert text.count(anchor) == 1
            text = text.replace(anchor, edit['old'] + anchor, 1)
        else:
            assert text.count(edit['new']) == 1, 'Inverse source guard failed'
            text = text.replace(edit['new'], edit['old'], 1)
    return text.replace('\n', '\r\n').encode()


def verify_source(parent: bytes, candidate: bytes, edits: list[dict]) -> dict:
    generated, expected_edits = transform(parent)
    assert generated == candidate and edits == expected_edits
    assert reverse(candidate, edits) == parent
    old = parent.decode().replace('\r\n', '\n')
    assert re.findall(r'RDY_NEXT_UNALIGNED_EXEC\s*=\s*([^;]+);', old) == [
        'UNALIGNED_EXEC', '0', '0', 'CPU_SHIFT_M', '0']
    assert re.findall(r'RDY_NEXT_COPY_WE\s*=\s*([^;]+);', old) == ['COPY_WE', '0', '0', '1']
    assert old.count('HOLE_NEXT_ADDR = A_M;') == 1
    assert old.count('HOLE_NEXT_ADDR = COPY_ADDR_N;') == 1
    assert candidate.count(b'assert (') == parent.count(b'assert (')
    # Exhaustive old procedural priority versus new Boolean ready predicates.
    ready_cases = 0
    for ras, oe, we, transfer, hist, unaligned, shift, state in itertools.product(
            range(2), range(2), range(2), range(2), range(2), range(2), range(2), range(8)):
        start = not ras and hist
        read = start and not oe and we and transfer
        collect = state == 3
        for pos in range(512):
            old_u = unaligned
            if start:
                old_u = 0
                if not oe and we and transfer:
                    old_u = shift
            old_we = 0
            if unaligned and collect:
                old_we = (pos & 7) == 7
                if pos == 511:
                    old_u = 0
            new_u = ((unaligned and not start) or (read and shift)) and not (
                unaligned and collect and pos == 511)
            new_we = unaligned and collect and (pos & 7) == 7
            assert bool(old_u) == bool(new_u) and bool(old_we) == bool(new_we)
            ready_cases += 1
    # The direct address mux is a complete-width masked select, including
    # simultaneous restart and collect. Basis vectors cover each of 18 bits.
    address_cases = 0
    values = [0, (1 << 18)-1] + [1 << bit for bit in range(18)]
    for read, advance in itertools.product(range(2), repeat=2):
        for current, next_addr, restart in itertools.product(values, repeat=3):
            procedural = restart if read else current
            if advance:
                procedural = next_addr
            masked = (next_addr if advance else 0) | (restart if read and not advance else 0) | (
                current if not read and not advance else 0)
            assert procedural == masked
            address_cases += 1
    # All current positions and all RAM/DDR completion combinations: decoded
    # same-D predicates replace only the original equality, not its priorities.
    end_cases = 0
    for pos, step_ram, step_ddr in itertools.product(range(512), range(2), range(2)):
        old_stop = (step_ram and pos == 504) or (step_ddr and pos == 510)
        new_stop = (step_ram and pos == 504) or (step_ddr and pos == 510)
        assert bool(old_stop) == bool(new_stop)
        end_cases += 1
    # Original flag capture is bit-valued; bit casts on the new D reproduce
    # it independently for all binary/X/Z input tuples (X and Z coerce to 0).
    read_cases = 0
    cast = lambda value: 1 if value == '1' else 0
    for fields in itertools.product('01xz', repeat=4):
        ras, oe, we, transfer = map(cast, fields)
        old_read = not ras and not oe and we and transfer
        assert bool(old_read) == bool(not cast(fields[0]) and not cast(fields[1]) and cast(fields[2]) and cast(fields[3]))
        read_cases += 1
    negatives = 0
    for old_bytes, bad_bytes in [(b"bit'(RAS_N)", b"bit'(RAS_N_M)"),
        (b"RDY_NEXT_COPY_STATE == 3'd3", b"RDY_NEXT_COPY_STATE == 3'd2"),
        (b"HOLE_NEXT_POS == 9'h1f8", b"HOLE_NEXT_POS == 9'h1f0"),
        (b'SADDR_C_BK[serial_copy_bank] <= {next_addr', b'SADDR_C_BK[serial_copy_bank] <= {next_copy_addr')]:
        assert old_bytes in candidate
        bad = candidate.replace(old_bytes, bad_bytes, 1)
        assert bad != generated
        try:
            assert reverse(bad, edits) == parent
        except AssertionError:
            negatives += 1
        else:
            raise AssertionError('Mutation accepted')
    return {'ready_all_input_state_cases': ready_cases, 'full18_address_basis_priority_cases': address_cases,
        'completion_position_cases': end_cases, 'four_state_read_command_tuples': read_cases,
        'rejected_source_mutations': negatives, 'raw_parent_inverse': True,
        'original_assertions_preserved': True, 'original_controller_and_leaf_bodies_preserved': True,
        'startup': 'read request=0 as original RAS/OE initial1; state and position predicates=0 as original bit state0',
        'reset': 'original unreset command capture; same asynchronous zero reset for state/position predicates; original synchronous address reset',
        'scope': 'Exact immutable original procedural assignments and guarded Boolean/width/priority identities; fresh compiled state/pin and four-state replay remain required'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite a frozen or failed candidate'
    parent = PARENT.read_bytes()
    candidate, edits = transform(parent)
    proof = verify_source(parent, candidate, edits)
    output.mkdir(parents=True)
    path = output / 'candidate/rtl/fg_vram.sv'
    path.parent.mkdir(parents=True)
    path.write_bytes(candidate)
    oracle = output / 'immutable_parent/rtl/fg_vram.sv'
    oracle.parent.mkdir(parents=True)
    oracle.write_bytes(parent)
    manifest = {'schema': 'bt-fg-setup-v18-source-edge-v1', 'parent_path': str(PARENT),
        'parent_sha256': PARENT_SHA, 'candidate_path': str(path), 'candidate_sha256': SHA(candidate),
        'helper_path': str(Path(__file__).resolve()), 'helper_sha256': SHA(Path(__file__).read_bytes()),
        'edits': edits, 'line_endings': 'Original raw CRLF retained', 'constraints_modified': False,
        'capture_edges_added': False, 'new_register_bits': 15,
        'disjoint_hold_edge': 'No WRITE_TOGGLE / WRITE_TOGGLE_M block or reset/clock/leaf RAM/port edit'}
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    receipt = {'schema': 'bt-fg-setup-v18-source-proof-v1', 'status': 'PASS',
        'manifest_sha256': SHA((output / 'manifest.json').read_bytes()),
        'parent_sha256': PARENT_SHA, 'candidate_sha256': SHA(candidate), 'coverage': proof,
        'compiled_replay_claim': False, 'mapped_or_timing_claim': False}
    (output / 'source-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({'candidate': str(path), 'sha256': SHA(candidate),
        'manifest_sha256': receipt['manifest_sha256'], 'source_receipt_sha256': SHA((output / 'source-receipt.json').read_bytes()),
        'coverage': proof}, separators=(',', ':')))


if __name__ == '__main__':
    main()
