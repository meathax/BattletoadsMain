"""Prove actual phase-aware board/NVRAM ownership and complete upload images."""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid
import run_bt_pause_bridge as phase


def sha(data):
    return hashlib.sha256(data).hexdigest()


def nvram_slice(top):
    start = top.index('\tbt_nvram nvram (')
    return top[start:top.index('\n\t);', start) + len('\n\t);')]


PORTS = '''input wire clk_sys,reset,OSD_STATUS,
input wire [31:0] joy0,joy1,joy2,
input wire [12:0] BT_NVRAM_ADDR,input wire [7:0] BT_NVRAM_DATA,
input wire BT_NVRAM_WE,rom_download,
input wire ioctl_download,ioctl_upload,ioctl_wr,
input wire [15:0] ioctl_index,ioctl_dout,input wire [26:0] ioctl_addr,
output wire gated_f,gated_r,vce,nvram_pause,nvram_ready,
output wire [7:0] nvram_q,output wire [15:0] nvram_ioctl_din,
output wire nvram_upload_req
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    source = (args.source_root or root).resolve()
    out = (args.out or root / ('build/pause-nvram-' + uuid.uuid4().hex)).resolve()
    assert out.is_relative_to(root), 'proof output must be inside the core workspace'
    out.mkdir(parents=True, exist_ok=False)
    t0 = time.time()
    oracle_top = phase.blob(root, 'Arcade-Battletoads.sv')
    oracle_ram = phase.blob(root, 'rtl/bt_nvram.sv')
    top = (source / 'Arcade-Battletoads.sv').read_bytes()
    ram = (source / 'rtl/bt_nvram.sv').read_bytes()
    bridge = (source / 'rtl/bt_pause_bridge.sv').read_bytes()
    clock = (source / 'rtl/bt_clock_enables.sv').read_bytes()
    assert phase.canonical(top) == phase.expected_top(phase.canonical(oracle_top)), 'unreviewed top change'
    assert phase.canonical(ram) == phase.expected_nvram(phase.canonical(oracle_ram)), 'unreviewed RAM ownership change'
    assert phase.canonical(bridge) == phase.MODULE, 'unreviewed phase bridge change'
    assert phase.canonical(clock) == phase.canonical(phase.blob(root, 'rtl/bt_clock_enables.sv')), 'generator changed'
    top_text = phase.canonical(top)
    # Compile the complete original controller beside the new one. The old
    # board uses the same new phase gate but retains original write masking:
    # this reproduces the closing-R integration bug rather than changing the
    # legacy reference's RAM behavior.
    common = phase.board_slice(top_text)
    new_board = ('module nvram_phase_board(\n' + PORTS + ');\n' + common + nvram_slice(top_text) + '''
assign gated_f=CE_F_CPU;assign gated_r=CE_R_CPU;assign vce=VCE_R;
endmodule
''')
    old_inst = nvram_slice(phase.canonical(oracle_top)).replace('bt_nvram nvram (', 'bt_nvram_old nvram (')
    old_board = ('module nvram_phase_board_old(\n' + PORTS + ');\n' + common + old_inst + '''
assign gated_f=CE_F_CPU;assign gated_r=CE_R_CPU;assign vce=VCE_R;
endmodule
''')
    boards = (new_board + old_board).encode()
    old_ram = phase.canonical(oracle_ram).replace('module bt_nvram(', 'module bt_nvram_old(', 1).encode()
    bench = Path(__file__).with_name('bt_pause_nvram_tb.sv').read_bytes()
    files = {'board_slices.sv': boards, 'bt_nvram.sv': ram,
             'bt_nvram_old.sv': old_ram, 'bt_pause_bridge.sv': bridge,
             'bt_clock_enables.sv': clock, 'bt_pause_nvram_tb.sv': bench}
    for name, data in files.items():
        (out / name).write_bytes(data)
    mdir = '/mnt/r/Verilator/BT/pause-nvram-' + sha(boards + ram)[:12] + '-' + sha(bench)[:12]
    source_path = '/mnt/' + out.drive[0].lower() + out.as_posix()[2:]
    command = ('set -eu\ncd "' + source_path + '"\nmkdir -p "' + mdir + '"\n'
               'verilator --binary --timing --assert -Wno-fatal --top-module bt_pause_nvram_tb '
               '--Mdir "' + mdir + '" -j 4 -o nvram_proof ' + ' '.join(files) + '\n'
               '"' + mdir + '/nvram_proof"\n')
    run = subprocess.run(['wsl.exe', '-d', 'Ubuntu', '--exec', '/bin/bash', '-lc', command],
                         text=True, encoding='utf-8', errors='replace', capture_output=True)
    (out / 'run.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    match = re.search(r'PASS pause_nvram (\{[^\n]+\})', run.stdout)
    receipt = {'status': 'PASS' if run.returncode == 0 and match else 'FAIL',
               'oracle_commit': phase.ORACLE, 'oracle_top_sha256': sha(oracle_top),
               'oracle_nvram_sha256': sha(oracle_ram), 'source_root': str(source),
               'candidate_top_sha256': sha(top), 'candidate_nvram_sha256': sha(ram),
               'candidate_bridge_sha256': sha(bridge), 'unchanged_generator_sha256': sha(clock),
               'compiled_inputs': {n: sha(d) for n, d in files.items()},
               'runner_sha256': sha(Path(__file__).read_bytes()),
               'phase_helper_sha256': sha(Path(phase.__file__).read_bytes()),
               'coverage': json.loads(match.group(1)) if match else None,
               'returncode': run.returncode, 'build_directory': mdir,
               'elapsed_seconds': round(time.time() - t0, 3)}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(out / 'receipt.json'), **receipt}, sort_keys=True))
    if run.returncode or not match:
        print((run.stdout + run.stderr)[-6000:])
        raise SystemExit(run.returncode or 1)


if __name__ == '__main__':
    main()
