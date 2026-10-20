"""Prepare one timing-only maxfan attribute on the exact v15 emu reset FF."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/timing_closure_20261011/cpu_locator_v15_private'
TOP = 'Arcade-Battletoads.sv'
PARENT_SHA = 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf'
REPORT = Path('C:/Users/meath/QuartusFast/runs/v2-20261011-075016-56808-turbo_fit/all-corners/corner_1/setup.txt')
OLD = b"\treg reset = 1'b1;\r\n"
NEW = b"\t(* maxfan = 64 *) reg reset = 1'b1;\r\n"
ATTRIBUTE = b'(* maxfan = 64 *) '
sha = lambda data: hashlib.sha256(data).hexdigest()


def transform(data):
    assert sha(data) == PARENT_SHA, 'Not the exact v15 full top'
    assert data.count(OLD) == 1 and ATTRIBUTE not in data
    return data.replace(OLD, NEW)


def reverse(data):
    assert data.count(NEW) == 1 and data.count(ATTRIBUTE) == 1
    restored = data.replace(NEW, OLD)
    assert sha(restored) == PARENT_SHA, 'Change outside the one reset declaration attribute'
    return restored


def producer(data):
    pattern = (rb"\treg \[1:0\] fg_ddr_ready_sys = 2'b00;\r\n.*?"
               rb'\talways @\(posedge clk_mem\) begin\r\n'
               rb'\t\treset_mem <= reset;\r\n'
               rb'\t\tfg_ddr_clear_init_n <= locked && rom_ready && !rom_download;\r\n'
               rb'\tend')
    matches = list(re.finditer(pattern, data, re.S))
    assert len(matches) == 1
    block = matches[0][0]
    assert block.count(b'always @(posedge clk_sys)') == 2 and block.count(b'always @(posedge clk_mem)') == 1
    assert b"reg reset = 1'b1;" in block and b"reg reset_mem = 1'b1;" in block
    assert b"reg fg_ddr_clear_init_n = 1'b0;" in block
    return block


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT / 'build')
    assert not output.exists(), 'Never overwrite a private candidate/proof'
    old = (BASE / TOP).read_bytes()
    candidate = transform(old)
    assert reverse(candidate) == old
    assert producer(candidate).replace(ATTRIBUTE, b'') == producer(old)
    report = REPORT.read_bytes()
    summary = report.decode().split('Path #1:', 1)[0]
    rows = re.findall(r';\s*(-[0-9.]+)\s*;\s*emu:emu\|reset\s*;\s*emu:emu\|BT:BT\|TMS34020:CPU\|PIX_BITV\[(\d+)\]', summary)
    assert len(rows) == 10 and {int(bit) for _, bit in rows} == {20, 21, 26, 27}
    assert re.search(r';\s*CELL\s*;\s*2919\s*;\s*FF_X29_Y45_N14\s*;\s*emu\|reset\|q\s*;', report.decode())
    for relative, data in [('oracle/' + TOP, old), ('candidate/' + TOP, candidate), ('evidence/v15-corner1-setup.txt', report)]:
        path = output / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    manifest = {
        'schema': 'bt-v15-reset-maxfan64-edge-v1', 'parent': str(BASE / TOP),
        'parent_sha256': PARENT_SHA, 'candidate_sha256': sha(candidate),
        'helper_sha256': sha(Path(__file__).read_bytes()),
        'old_producer_sha256': sha(producer(old)), 'new_producer_sha256': sha(producer(candidate)),
        'attribute': 'maxfan = 64', 'raw_full_top_inverse_identical': True,
        'producer_behavior_without_attribute_byte_identical': True,
        'registers_added': 0, 'reset_latency_edges_added': 0,
        'init': {'reset': 1, 'fg_ddr_ready_sys': 0, 'reset_mem': 1, 'fg_ddr_clear_init_n': 0},
        'fit_evidence': {'path': str(REPORT), 'sha256': sha(report), 'worst_slack_ns': -0.590,
                         'reset_q_fanout': 2919, 'reset_clock': 'clk_sys', 'top10_from_reset': rows,
                         'downstream_fanouts': [136, 113, 32], 'data_delay_ns': 12.198,
                         'clock_skew_ns': -0.562, 'relationship_ns': 12.5},
        'timing_accepted': False,
        'scope': 'One synthesis fanout attribute only; every declaration init, reset RHS, clock/edge, consumer and other top byte is unchanged',
    }
    (output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'output': str(output), 'candidate_sha256': manifest['candidate_sha256'],
                      'parent_sha256': PARENT_SHA, 'reset_q_fanout': 2919, 'maxfan_request': 64}, indent=2))


if __name__ == '__main__':
    main()
