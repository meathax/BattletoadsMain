"""Prepare a private, reversible zero-flag edge from immutable v22 CPU inputs."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
CPU = 'rtl/TMS34020/TMS34020.sv'
PKG = 'rtl/TMS34020/TMS34020_pkg.sv'
SNAPSHOT = ROOT / 'build/timing_closure_20261011/q17_local_paths_v22_private-snapshot.json'
SNAPSHOT_SHA = '339bf281bad4f0235b0effb5b1b468a9ac6854421634aaec8d489bcc93520aed'
FUNCTIONS = """\tfunction automatic bit BtShiftZero(input bit [31:0] val, input bit [4:0] sa, input bit [3:0] code);
\t\tbit [31:0] kept;
\t\t// Test the original bits that survive. Right counts use -sa modulo32;
\t\t// sign-fill adds no nonzero bit unless the retained sign is already1.
\t\tfor (int n = 0; n < 32; n = n + 1)
\t\t\tkept[n] = val[n] & (code[0]
\t\t\t\t? ((sa == 5'd0) | ({1'b0,sa} >= 6'(32 - n)))
\t\t\t\t: (code[2] | ({1'b0,sa} < 6'(32 - n))));
\t\treturn ~|kept;
\tendfunction

\tfunction automatic bit BtLoggerZero(input bit [31:0] a, input bit [31:0] b, input bit [3:0] code, input bit a_zero);
\t\tbit [31:0] b2, bmask;
\t\tbit zero;
\t\tb2 = b ^ {32{code[0]}};
\t\tbmask = 32'h00000001 << b2[4:0];
\t\t// Reduce each operation before the flag selector. The data result and
\t\t// its original Logger/overflow/carry paths remain independent.
\t\tcase (code[2:1])
\t\t\t2'b00: zero = ~|(a & b2);
\t\t\t2'b01: zero = a_zero & ~|b2;
\t\t\t2'b10: zero = ~|(a ^ b2);
\t\t\t2'b11: zero = ~|(a & bmask);
\t\tendcase
\t\treturn zero;
\tendfunction

"""


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pinned_parent():
    raw = SNAPSHOT.read_bytes()
    assert sha(raw) == SNAPSHOT_SHA
    selected = json.loads(raw)
    assert len(selected['sources']) == 144
    directory = Path(selected['project']).parent
    cpu, pkg = (directory / CPU).read_bytes(), (directory / PKG).read_bytes()
    assert sha(cpu) == selected['sources'][CPU]
    assert sha(pkg) == selected['sources'][PKG]
    return cpu, pkg, selected


def operations(parent):
    assert parent == pinned_parent()[0]
    eol = b'\r\n' if b'\r\n' in parent else b'\n'
    anchor = b'\tbit         ADDXY_CX;'
    functions = FUNCTIONS.replace('\n', eol.decode()).encode()
    return [
        (anchor, functions + anchor),
        (b'\t\tbit         SHIFT_V;', b'\t\tbit         SHIFT_V;' + eol + b'\t\tbit         SHIFT_Z, LOG_Z;'),
        (b'\t\tSHIFT_V = BtShiftLeftOvf(ALU_A, ALU_SA);', b'\t\tSHIFT_V = BtShiftLeftOvf(ALU_A, ALU_SA);' + eol + b'\t\tSHIFT_Z = BtShiftZero(ALU_A, ALU_SA, DECI.SHC.SHOP);'),
        (b'\t\tLOG_RES = Logger(SHIFT_RES, ALU_B, DECI.ALU.CD);', b'\t\tLOG_RES = Logger(SHIFT_RES, ALU_B, DECI.ALU.CD);' + eol + b'\t\tLOG_Z = BtLoggerZero(SHIFT_RES, ALU_B, DECI.ALU.CD, SHIFT_Z);'),
        (b'{1\'b0         ,~|LOG_RES   ,LOG_V', b'{1\'b0         ,LOG_Z       ,LOG_V'),
        (b'{1\'b0         ,~|SHIFT_RES ,SHIFT_V', b'{1\'b0         ,SHIFT_Z     ,SHIFT_V'),
    ]


def transform(parent):
    data = parent
    for old, new in operations(parent):
        assert data.count(old) == 1, old
        data = data.replace(old, new, 1)
    return data


def reverse(candidate):
    parent = pinned_parent()[0]
    data = candidate
    for old, new in reversed(operations(parent)):
        assert data.count(new) == 1, new[:120]
        data = data.replace(new, old, 1)
    assert data == parent
    return data


def verify_edge(directory):
    directory = Path(directory)
    parent, pkg, selected = pinned_parent()
    candidate = (directory / CPU).read_bytes()
    assert candidate == transform(parent) and reverse(candidate) == parent
    assert (directory / PKG).read_bytes() == pkg
    for start, end in ((b'\t//Conditions', b'\t//Pixel unit'), (b'\t// Decode and execute are separate', b'\tfunction bit [4:0] BtOneLocate')):
        assert parent[parent.index(start):parent.index(end, parent.index(start))] == candidate[candidate.index(start):candidate.index(end, candidate.index(start))]
    return {'parent_sha256': sha(parent), 'candidate_sha256': sha(candidate), 'package_sha256': sha(pkg),
            'exact_full_raw_inverse': True, 'original_DS_Z_ST_capture_reset_hold_priority_byte_identical': True,
            'all_original_registers_ports_operand_capture_clock_and_SDC_unchanged': True}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to((ROOT / 'build').resolve()) and not output.exists()
    parent, pkg, selected = pinned_parent()
    candidate = transform(parent)
    candidate_dir = output / 'candidate'
    (candidate_dir / CPU).parent.mkdir(parents=True)
    (candidate_dir / CPU).write_bytes(candidate)
    (candidate_dir / PKG).write_bytes(pkg)
    oracle = output / 'oracle'
    (oracle / CPU).parent.mkdir(parents=True)
    (oracle / CPU).write_bytes(parent)
    (oracle / PKG).write_bytes(pkg)
    edge = verify_edge(candidate_dir)
    manifest = {'schema': 'bt-v22-cpu-zero-flags-source-edge-v1', 'status': 'PASS_RAW_SOURCE_INVERSE_SIMULATION_TIMING_PENDING',
                'selected_parent_snapshot': str(SNAPSHOT), 'selected_parent_snapshot_sha256': SNAPSHOT_SHA,
                'candidate_directory': str(candidate_dir), 'oracle_directory': str(oracle),
                'helper': str(Path(__file__).resolve()), 'helper_sha256': sha(Path(__file__).read_bytes()),
                'operations': [{'old': old.decode(), 'new': new.decode(), 'count': 1} for old, new in operations(parent)],
                **edge, 'scope': 'Combinational selected ALU zero predicates only; original data/other flags/register capture paths byte-exact. No simulation, mapped timing, RBF, hardware or MAME claim.'}
    path = output / 'manifest.json'
    path.write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'manifest': str(path), 'manifest_sha256': sha(path.read_bytes()), **edge}))


if __name__ == '__main__':
    main()
