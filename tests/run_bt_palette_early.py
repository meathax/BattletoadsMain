"""Prove palette early prediction against the immutable original R-edge block.

Defaults test integrated sources. --candidate-root accepts a private overlay
containing BT.sv and TMS34020.sv. No repository or framework source is changed.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import subprocess
import time
import uuid

ORACLE = '8f048ee518f3062506e80d5f5a64585450d062f5'
GIT = 'D:/vibes/fpga/bin/git.EXE'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(data):
    return data.decode('utf-8').replace('\r\n', '\n')


def palette_body(text):
    start = text.index('\t//Misc/sound control')
    end = text.index('\twire [23:0] PAL_Q;', start)
    body = text[start:end]
    return body[:body.rindex('\n\tend') + len('\n\tend')]


def mux_body(text):
    start = text.index('\tbit [ 7: 0] MISC_DO;')
    end = text.index('\t// Parallel data gates', start)
    return text[start:end].rstrip()


def late_body(text, name):
    start = text.index('\tassign ' + name + ' =')
    return text[start:text.index(';', start) + 1]


PORTS = '''input logic CLK,RST_N,EN,CE_R,
input logic [31:0] LA,LDO,
input logic [3:0] CAS_N,
input logic WE_N,QE_N,RAS_N,
input logic [23:0] IO_PAL_Q,
input logic [7:0] P1,P2,P3,SW1,Z80_RESP_DATA,LDI_SELECT,
input logic Z80_CTRL_RDY,SERVICE,Z80_RESP_RDY,LDI_EXTERNAL_VALID,ENVRAM,
input logic [31:0] NVRAM_Q,
output wire [31:0] LDI_CACHE_LATE,LDI_CACHE_LATE_E
'''


def wrapper(name, source, predict=False):
    if predict:
        pstart = source.index('\t// Predict the existing palette register')
        pend = source.index('\tbit [ 7: 0] MISC_DO;', pstart)
        predictor = source[pstart:pend]
        estart = source.index('\twire [7:0] MISC_DO_E =')
        eend = source.index(';', estart) + 1
        early = source[estart:eend] + '\n' + late_body(source, 'LDI_CACHE_LATE_E')
    else:
        predictor = ''
        early = 'assign LDI_CACHE_LATE_E = LDI_CACHE_LATE;'
    return (f'module {name}(\n{PORTS});\nbit [7:0] Z80_CTRL_DATA;\n'
            + palette_body(source) + '\n' + predictor + '\n' + mux_body(source) + '\n'
            + late_body(source, 'LDI_CACHE_LATE') + '\n' + early + '\nendmodule\n')


def blob(root, path):
    run = subprocess.run([GIT, '-C', str(root), 'show', ORACLE + ':' + path], capture_output=True)
    if run.returncode:
        raise RuntimeError(run.stderr.decode('utf-8', 'replace'))
    return run.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--candidate-root', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    candidate = (args.candidate_root or root).resolve()
    out = (args.out or root / ('build/palette-early-' + uuid.uuid4().hex)).resolve()
    assert out.is_relative_to(root), 'proof output must be inside the core workspace'
    out.mkdir(parents=True, exist_ok=False)
    t0 = time.time()
    old_bt_raw = blob(root, 'rtl/BT.sv')
    old_cpu_raw = blob(root, 'rtl/TMS34020/TMS34020.sv')
    bt_raw = (candidate / 'rtl/BT.sv').read_bytes()
    cpu_raw = (candidate / 'rtl/TMS34020/TMS34020.sv').read_bytes()
    old_bt, old_cpu = canonical(old_bt_raw), canonical(old_cpu_raw)
    bt, cpu = canonical(bt_raw), canonical(cpu_raw)
    assert palette_body(bt) == palette_body(old_bt), 'palette state/side effects changed'
    assert mux_body(bt) == mux_body(old_bt), 'final MISC read mux changed'
    assert late_body(bt, 'LDI_CACHE_LATE') == late_body(old_bt, 'LDI_CACHE_LATE'), 'final late bus changed'
    for source in (old_cpu, cpu):
        start = source.index('\twire [31:0] MC_RETURN_WORD =')
        end = source.index('\t// The same word', start)
        final = source[start:end]
        if source == old_cpu:
            old_final = final
        else:
            assert final == old_final, 'final MC consuming word changed'
    assert '''\twire [31:0] MC_RETURN_WORD_E = MC_MEM_SELECTED ?
\t    (MC_DDR_SELECTED ? MC_DDR_RETURN_WORD : MC_MEM_WORD) :
\t    IO_SEL ? IO_DO_NEXT : LDI_CACHE_LATE_E;''' in cpu, 'early interface is not the reviewed predictor'
    assert '.LDI_CACHE_LATE_E(LDI_CACHE_LATE_E)' in bt, 'top predictor port is disconnected'
    (out / 'oracle_BT.sv').write_bytes(old_bt_raw)
    (out / 'candidate_BT.sv').write_bytes(bt_raw)
    (out / 'candidate_CPU.sv').write_bytes(cpu_raw)
    slices = (wrapper('palette_old', old_bt) + wrapper('palette_new', bt, True)).encode()
    (out / 'palette_slices.sv').write_bytes(slices)
    bench = Path(__file__).with_name('bt_palette_early_tb.sv').read_bytes()
    (out / 'bt_palette_early_tb.sv').write_bytes(bench)
    mdir = '/mnt/r/Verilator/BT/palette-early-' + digest(slices)[:12] + '-' + digest(bench)[:12]
    source_path = '/mnt/' + out.drive[0].lower() + out.as_posix()[2:]
    command = ('set -eu\ncd "' + source_path + '"\nmkdir -p "' + mdir + '"\n'
               'verilator --binary --timing --assert -Wno-fatal --top-module bt_palette_early_tb '
               '--Mdir "' + mdir + '" -j 4 -o palette_proof palette_slices.sv bt_palette_early_tb.sv\n'
               '"' + mdir + '/palette_proof"\n')
    run = subprocess.run(['wsl.exe', '-d', 'Ubuntu', '--exec', '/bin/bash', '-lc', command],
                         text=True, encoding='utf-8', errors='replace', capture_output=True)
    (out / 'run.log').write_text(run.stdout + run.stderr, encoding='utf-8')
    match = re.search(r'PASS palette_early (\{[^\n]+\})', run.stdout)
    receipt = {'status': 'PASS' if run.returncode == 0 and match else 'FAIL',
               'oracle_commit': ORACLE, 'oracle_BT_sha256': digest(old_bt_raw),
               'oracle_CPU_sha256': digest(old_cpu_raw), 'candidate_root': str(candidate),
               'candidate_BT_sha256': digest(bt_raw), 'candidate_CPU_sha256': digest(cpu_raw),
               'compiled_slice_sha256': digest(slices), 'testbench_sha256': digest(bench),
               'runner_sha256': digest(Path(__file__).read_bytes()),
               'clocked_palette_identical': True, 'F_return_identical': True,
               'guards': 'RST_N/CE_R; unchanged absence of EN guard',
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
