"""Compile exact board pause wiring and exhaust request/start/reset phases.

--prepare-private creates only an isolated overlay under build, combining the
frozen palette candidate with the immutable board source. Normal invocation
tests integrated sources or --source-root without changing them.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid

ORACLE = 'b53726397822b9dbebb02d36411294056fd08649'
GIT = 'D:/vibes/fpga/bin/git.EXE'
MODULE = '''// Complete the current R edge before halting; resume with an F edge.
// The free-running clock/pixel generator and CPU EN are independent.
module bt_pause_bridge (
    input wire clk, reset, pause_req,
    input wire raw_ce_f, raw_ce_r,
    output wire ce_f, ce_r, halted
);
    reg halted_reg = 0;
    assign halted = halted_reg;
    assign ce_f = !reset && raw_ce_f && (!halted_reg || !pause_req);
    assign ce_r = !reset && raw_ce_r && !halted_reg;
    always @(posedge clk) begin
        if (reset) halted_reg <= 0;
        else if (halted_reg) begin
            if (!pause_req && raw_ce_f) halted_reg <= 0;
        end else if (pause_req && raw_ce_r) halted_reg <= 1;
    end
endmodule
'''
INSERT = '''\twire CE_F_CPU, CE_R_CPU, cpu_pause_halted;
\tbt_pause_bridge cpu_pause_bridge(
\t    .clk(clk_sys), .reset(reset), .pause_req(pause_cpu),
\t    .raw_ce_f(CE_F), .raw_ce_r(CE_R),
\t    .ce_f(CE_F_CPU), .ce_r(CE_R_CPU), .halted(cpu_pause_halted));
'''


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return data.decode('utf-8').replace('\r\n', '\n')


def blob(root, path):
    run = subprocess.run([GIT, '-C', str(root), 'show', ORACLE + ':' + path], capture_output=True)
    if run.returncode:
        raise RuntimeError(run.stderr.decode('utf-8', 'replace'))
    return run.stdout


def replace(text, old, new):
    assert text.count(old) == 1, f'nonunique source anchor: {old!r}'
    return text.replace(old, new)


def expected_top(old):
    old_comment = '''\t// Registered: the NVRAM/loader status otherwise reaches the CPU enables and
\t// VRAM controls combinationally. Uploads are always preceded by save_pending,
\t// so the one-clock delay never lets the CPU touch NVRAM during an upload.'''
    new_comment = '''\t// Register the NVRAM/loader request before the CPU phase gate.
\t// The gate completes the current R edge; NVRAM requests its upload only
\t// after the gate acknowledges that the CPU has halted.'''
    old = replace(old, old_comment, new_comment)
    anchor = '\talways @(posedge clk_sys) pause_cpu <= user_pause | OSD_STATUS | nvram_pause;\n'
    new = replace(old, anchor, anchor + INSERT)
    new = replace(new, '.CE_F(CE_F && !pause_cpu)', '.CE_F(CE_F_CPU)')
    new = replace(new, '.CE_R(CE_R && !pause_cpu)', '.CE_R(CE_R_CPU)')
    return replace(new, '.cpu_we(BT_NVRAM_WE && CE_R && !pause_cpu),',
                   '.cpu_we(BT_NVRAM_WE && CE_R_CPU), .cpu_halted(cpu_pause_halted),')


def expected_nvram(old):
    # Append the new ownership input, retaining every existing positional port.
    new = replace(old, 'output pause_cpu\n', 'output pause_cpu,\n    input cpu_halted\n')
    new = replace(new, 'reg dirty = 0, save_pending = 0;',
                  'reg dirty = 0, save_pending = 0, save_issued = 0;')
    new = replace(new, 'wire cpu_write = cpu_we && !pause_cpu;',
                  '''// A save request waits for the final admitted R write to complete.
    // Physical port owners and an acknowledged halt still exclude CPU writes.
    wire cpu_write = cpu_we && !initializing && !restoring && !uploading && !cpu_halted;''')
    new = replace(new, 'assign cpu_ready = read_valid && read_addr == cpu_addr;',
                  '''assign cpu_ready = read_valid && read_addr == cpu_addr &&
                       !initializing && !restoring && !uploading;''')
    new = replace(new, 'read_valid <= !uploading;',
                  'read_valid <= !initializing && !restoring && !uploading;')
    new = replace(new, '''            save_pending <= 0;
        end else if (initializing)''', '''            save_pending <= 0;
            save_issued <= 0;
        end else if (initializing)''')
    new = replace(new, 'if (cpu_we && !pause_cpu) dirty <= 1;', 'if (cpu_write) dirty <= 1;')
    new = replace(new, '''                upload_req <= 1;
                save_pending <= 1;
            end
            if (old_upload && !uploading)''', '''                save_pending <= 1;
                save_issued <= 0;
            end
            // The closing R write has settled before this acknowledgement.
            // Never issue again for the same request or during port ownership.
            if (save_pending && cpu_halted && !save_issued &&
                !restoring && !uploading && !old_upload) begin
                upload_req <= 1;
                save_issued <= 1;
            end
            if (old_upload && !uploading)''')
    return replace(new, '''                dirty <= 0;
                save_pending <= 0;
            end''', '''                dirty <= 0;
                save_pending <= 0;
                save_issued <= 0;
            end''')


def board_slice(text):
    start = text.index('\twire CE_F, CE_R, VCE_R;')
    end = text.index('\twire SCLKX2;', start)
    return text[start:end]


def prepare(root, out, palette):
    candidate = out / 'candidate'
    top = expected_top(canonical(blob(root, 'Arcade-Battletoads.sv'))).encode()
    old_qip = canonical(blob(root, 'files.qip'))
    anchor = 'set_global_assignment -name SYSTEMVERILOG_FILE rtl/bt_clock_enables.sv\n'
    qip = replace(old_qip, anchor, anchor + 'set_global_assignment -name SYSTEMVERILOG_FILE rtl/bt_pause_bridge.sv\n').encode()
    files = {'Arcade-Battletoads.sv': top, 'files.qip': qip,
             'rtl/bt_pause_bridge.sv': MODULE.encode(),
             'rtl/bt_clock_enables.sv': blob(root, 'rtl/bt_clock_enables.sv'),
             'rtl/bt_nvram.sv': expected_nvram(canonical(blob(root, 'rtl/bt_nvram.sv'))).encode()}
    pins = {'rtl/BT.sv': '69e8eef01824c66356c4e1427f5bab3509534aba39c23df01a3dce713be2672b',
            'rtl/TMS34020/TMS34020.sv': 'd658300d7d8fd58845b299b1c92d1e62488f66f878b337d6716df991c151e05e'}
    for path, pin in pins.items():
        data = (palette / path).read_bytes()
        assert sha(data) == pin, 'frozen palette source changed: ' + path
        files[path] = data
    for path, data in files.items():
        target = candidate / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            assert target.read_bytes() == data, 'private frozen file changed: ' + str(target)
        else:
            target.write_bytes(data)
    receipt = {'oracle_commit': ORACLE, 'candidate_root': str(candidate),
               'sources': {p: sha(d) for p, d in files.items()},
               'contract': 'original startup; pause includes R; acknowledged pause resumes F first'}
    (out / 'candidate_manifest.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(receipt, sort_keys=True))
    return candidate


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--prepare-private', action='store_true')
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--palette-root', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    out = (args.out or root / ('build/pause-bridge-' + uuid.uuid4().hex)).resolve()
    assert out.is_relative_to(root), 'proof output must be inside the core workspace'
    out.mkdir(parents=True, exist_ok=True)
    source = (args.source_root or root).resolve()
    if args.prepare_private:
        palette = (args.palette_root or root / 'build/palette_early_8v20261011/candidate').resolve()
        source = prepare(root, out, palette)
    if args.prepare_only:
        return
    t0 = time.time()
    old_top = blob(root, 'Arcade-Battletoads.sv')
    top = (source / 'Arcade-Battletoads.sv').read_bytes()
    bridge = (source / 'rtl/bt_pause_bridge.sv').read_bytes()
    clock = (source / 'rtl/bt_clock_enables.sv').read_bytes()
    qip = (source / 'files.qip').read_bytes()
    assert canonical(top) == expected_top(canonical(old_top)), 'unreviewed board source change'
    assert canonical(bridge) == MODULE, 'unreviewed phase bridge change'
    assert canonical(clock) == canonical(blob(root, 'rtl/bt_clock_enables.sv')), 'clock/pixel generator changed'
    old_qip = canonical(blob(root, 'files.qip'))
    assert canonical(qip) == replace(old_qip,
        'set_global_assignment -name SYSTEMVERILOG_FILE rtl/bt_clock_enables.sv\n',
        'set_global_assignment -name SYSTEMVERILOG_FILE rtl/bt_clock_enables.sv\nset_global_assignment -name SYSTEMVERILOG_FILE rtl/bt_pause_bridge.sv\n'), 'unreviewed QIP change'
    board = ('''module pause_board(input wire clk_sys, reset,
input wire [31:0] joy0,joy1,joy2,input wire OSD_STATUS,nvram_pause,
output wire gated_f,gated_r,vce);
''' + board_slice(canonical(top)) + '''assign gated_f=CE_F_CPU;
assign gated_r=CE_R_CPU;
assign vce=VCE_R;
endmodule
''').encode()
    bench = Path(__file__).with_name('bt_pause_bridge_tb.sv').read_bytes()
    for name, data in [('board_slice.sv', board), ('bt_pause_bridge.sv', bridge),
                       ('bt_clock_enables.sv', clock), ('bt_pause_bridge_tb.sv', bench)]:
        (out / name).write_bytes(data)
    mdir = '/mnt/r/Verilator/BT/pause-bridge-' + sha(board)[:12] + '-' + sha(bench)[:12]
    source_path = '/mnt/' + out.drive[0].lower() + out.as_posix()[2:]
    command = ('set -eu\ncd "' + source_path + '"\nmkdir -p "' + mdir + '"\n'
               'verilator --binary --timing --assert -Wno-fatal --top-module bt_pause_bridge_tb '
               '--Mdir "' + mdir + '" -j 4 -o pause_proof bt_clock_enables.sv '
               'bt_pause_bridge.sv board_slice.sv bt_pause_bridge_tb.sv\n'
               '"' + mdir + '/pause_proof"\n')
    run = subprocess.run(['wsl.exe', '-d', 'Ubuntu', '--exec', '/bin/bash', '-lc', command],
                         text=True, encoding='utf-8', errors='replace', capture_output=True)
    (out / 'run.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    match = re.search(r'PASS pause_bridge (\{[^\n]+\})', run.stdout)
    receipt = {'status': 'PASS' if run.returncode == 0 and match else 'FAIL',
               'oracle_commit': ORACLE, 'oracle_top_sha256': sha(old_top),
               'source_root': str(source), 'candidate_top_sha256': sha(top),
               'candidate_bridge_sha256': sha(bridge), 'candidate_qip_sha256': sha(qip),
               'unchanged_clock_generator_sha256': sha(clock),
               'compiled_board_slice_sha256': sha(board), 'testbench_sha256': sha(bench),
               'runner_sha256': sha(Path(__file__).read_bytes()),
               'contract': 'original startup; pause includes R; acknowledged pause resumes F first',
               'coverage': json.loads(match.group(1)) if match else None,
               'build_directory': mdir, 'returncode': run.returncode,
               'elapsed_seconds': round(time.time() - t0, 3)}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'receipt': str(out / 'receipt.json'), **receipt}, sort_keys=True))
    if run.returncode or not match:
        print((run.stdout + run.stderr)[-6000:])
        raise SystemExit(run.returncode or 1)


if __name__ == '__main__':
    main()
