"""Replay unchanged full FG assertions, then qualify explicit Intel RAM replicas."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents if (p / '.git').exists())
WORKER = ROOT / 'build/fg_serial_controls_v12_v2/full-pin-proof-v2/worker.py'
WORKER_SHA = '3be1c0ac9e6c750438d72937ce5e364c8864da99cfd5714de8cae8b02e354803'
OLD_NAME = 'fg-serial-controls-26bcf762d3d84a4ca07212ede6b3b824'
FG_SHA = 'e006f78f28bddf67f97dbd32b69dd507fc6a11916355c2c57e98ff21a6b44552'
UNCHANGED = {
    'rtl/BT_mem.sv': '903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'rtl/ddram.sv': 'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'rtl/bt_fg_ddr_clear.sv': 'bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1',
    'tests/graphics/ram_models.sv': '039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
    'tests/foreground_read_equivalence_tb.sv': '684b4cc42c88d5216292eab1fee2cb2c37deaecc0c3cc778e396c291663487c1',
    'tests/foreground_ddr_tb.sv': 'fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c',
}
MODELSIM = Path('D:/q17/modelsim_ase/win32aloem')
VENDOR = Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
GIT = Path('D:/vibes/fpga/bin/git.EXE')


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def once(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f'Exact one occurrence required: {old[:80]}'
    return text.replace(old, new)


def sv_module(text: str, name: str) -> str:
    match = re.search(r'(?m)^module\s+' + re.escape(name) + r'\b.*?\bendmodule', text, re.S)
    assert match, f'Missing module {name}'
    return match.group(0)


def run(command: list[str], cwd: Path, log: Path, timeout: int) -> dict:
    with log.open('w', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
    return {'command': command, 'cwd': str(cwd), 'exit_code': result.returncode,
            'log': str(log), 'log_sha256': sha(log.read_bytes())}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate-dir', type=Path, default=ROOT / 'build/fg_serial_replicas_v12_v2/candidate')
    parser.add_argument('--output', type=Path, default=ROOT / 'build/fg_serial_replicas_v12_v2/proof')
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    assert output.is_relative_to(ROOT.resolve()) and not output.exists()
    fg = (args.candidate_dir / 'rtl/fg_vram.sv').read_bytes()
    assert sha(fg) == FG_SHA
    raw_worker = WORKER.read_bytes()
    assert sha(raw_worker) == WORKER_SHA
    captured = {name: (ROOT / name).read_bytes() for name in UNCHANGED}
    assert {name: sha(data) for name, data in captured.items()} == UNCHANGED
    output.mkdir(parents=True)
    overlay = output / 'source_overlay'
    for name, data in dict(captured, **{'rtl/fg_vram.sv': fg}).items():
        target = overlay / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    name = 'fg-serial-replicas-' + uuid.uuid4().hex
    worker_text = raw_worker.decode('utf-8')
    changed_worker = once(worker_text, "name = '" + OLD_NAME + "'", "name = '" + name + "'").encode('utf-8')
    assert changed_worker.decode().replace("name = '" + name + "'", "name = '" + OLD_NAME + "'").encode() == raw_worker
    worker = output / 'worker.py'
    worker.write_bytes(changed_worker)
    # Keep all workload/assertion transformations byte-identical. Only the
    # unique output directory literal changes from the accepted frozen worker.
    native_command = [sys.executable, '-X', 'utf8', '-B', str(worker), '--tests', 'fg', 'fg-ddr', '--candidate-dir', str(overlay)]
    git_ref = subprocess.check_output([str(GIT), '-C', str(ROOT), 'rev-parse', 'b537^{commit}']).decode().strip()
    old_leaf_file = subprocess.check_output([str(GIT), '-C', str(ROOT), 'show', git_ref + ':rtl/BT_mem.sv'])
    leaf_text = captured['rtl/BT_mem.sv'].decode().replace('\r\n', '\n')
    original_leaf = sv_module(old_leaf_file.decode().replace('\r\n', '\n'), 'VRAM_SHIFTREG')
    current_leaf = sv_module(leaf_text, 'VRAM_SHIFTREG')
    assert original_leaf == current_leaf, 'Original serial RAM body/configuration must be unchanged'
    fg_text = fg.decode().replace('\r\n', '\n')
    instance = re.search(r'\tVRAM_SHIFTREG #\(9,1,1\) shiftreg\s*\(.*?\n\t\);', fg_text, re.S)
    replicas = re.search(r'\tgenvar serial_replica;\n\tgenerate for \(serial_replica=1;.*?\tend endgenerate', fg_text, re.S)
    assert instance and replicas
    production_block = instance.group(0) + '\n' + replicas.group(0)
    oracle_instance = once(instance.group(0), 'VRAM_SHIFTREG #(9,1,1) shiftreg', 'VRAM_SHIFTREG_REFERENCE #(9,1,1) shiftreg_reference')
    oracle_instance = once(oracle_instance, '.Q(SR_Q)', '.Q(oracle_q)')
    template = (ROOT / 'tests/graphics/bt_fg_serial_replicas_intel_tb.sv').read_bytes()
    generated_tb = once(template.decode(), '// @@PRODUCTION_RAM_BLOCK@@', production_block)
    generated_tb = once(generated_tb, '// @@IMMUTABLE_ORACLE_INSTANCE@@', oracle_instance)
    intel = output / 'intel'
    intel.mkdir()
    leaf_path, oracle_path, tb_path = intel / 'BT_mem.sv', intel / 'VRAM_SHIFTREG_REFERENCE.sv', intel / 'bt_fg_serial_replicas_intel_tb.sv'
    leaf_path.write_bytes(captured['rtl/BT_mem.sv'])
    oracle_path.write_text(once(original_leaf, 'module VRAM_SHIFTREG', 'module VRAM_SHIFTREG_REFERENCE') + '\n', encoding='utf-8')
    tb_path.write_text(generated_tb, encoding='utf-8')
    preparation = {
        'schema': 'bt-fg-serial-replicas-proof-v1', 'candidate_dir': str(args.candidate_dir.resolve()),
        'candidate_fg_sha256': FG_SHA, 'captured_sources': UNCHANGED,
        'helper': str(Path(__file__).resolve()), 'helper_sha256': sha(Path(__file__).read_bytes()),
        'worker_parent': str(WORKER), 'worker_parent_sha256': WORKER_SHA,
        'worker_sha256': sha(changed_worker), 'worker_edge': 'Only unique run/output-directory literal changed; full byte-exact reversal PASS.',
        'worker_run_name': name, 'native_command': native_command,
        'immutable_git_ref': git_ref, 'immutable_BT_mem_blob_sha256': sha(old_leaf_file),
        'original_current_serial_ram_body_identical': True,
        'serial_ram_body_lf_sha256': sha(current_leaf.encode()),
        'production_original_and_three_instances_sha256': sha(production_block.encode()),
        'template_sha256': sha(template), 'generated_tb_sha256': sha(tb_path.read_bytes()),
        'compiled_leaf_sha256': sha(leaf_path.read_bytes()), 'oracle_module_sha256': sha(oracle_path.read_bytes()),
        'vendor_path': str(VENDOR), 'vendor_sha256': sha(VENDOR.read_bytes()),
        'scope': 'Original full FG pin/state/workload assertions plus explicit exact production original+three Intel RAM replicas; full data and X case equality, all masks/rows/routes and collisions/reset. No physical retention/timing/hardware claim.',
    }
    (output / 'preparation.json').write_text(json.dumps(preparation, indent=2) + '\n', encoding='utf-8')
    if args.prepare_only:
        print(json.dumps({'status': 'PREPARED', 'output': str(output), 'native_command': native_command}))
        return
    results = [run(native_command, ROOT, output / 'native.log', 3600)]
    assert results[0]['exit_code'] == 0, (output / 'native.log').read_text(errors='replace')[-3000:]
    native_receipt_path = ROOT / 'build' / name / 'receipt.json'
    native_receipt = json.loads(native_receipt_path.read_text())
    assert native_receipt['all_passed'] and len(native_receipt['results']) == 2
    native_markers = {}
    for result in native_receipt['results']:
        text = Path(result['log']).read_text(errors='replace')
        markers = [line for line in text.splitlines() if line.startswith('PASS ')]
        assert markers and not re.search(r'\bFAIL\b|\bFATAL\b|\bERROR\b', text, re.I)
        native_markers[result['test']] = markers
    assert any('PASS serial chunk complete pins/state:' in marker for marker in native_markers['fg'])
    assert all(re.search(r'\b' + value + r'\b', ' '.join(native_markers['fg-ddr'])) for value in ('196608', '128', '512'))
    commands = [
        [str(MODELSIM / 'vlib.exe'), 'work'],
        [str(MODELSIM / 'vlog.exe'), '-sv', '-work', 'work', str(leaf_path), str(oracle_path), str(tb_path), str(VENDOR)],
        [str(MODELSIM / 'vsim.exe'), '-c', 'work.bt_fg_serial_replicas_intel_tb', '-do', 'onerror {quit -code 1}; run -all; quit -code 0'],
    ]
    for index, command in enumerate(commands):
        result = run(command, intel, intel / ('compile' + str(index) + '.log' if index < 2 else 'run.log'), 1800)
        results.append(result)
        assert result['exit_code'] == 0, Path(result['log']).read_text(errors='replace')[-3000:]
    log = (intel / 'run.log').read_text(errors='replace')
    marker = re.search(r'PASS FG serial RAM replicas: cycles=(\d+) bit_checks=(\d+) mask_cases=256 rows=64 replicas=3 reset_events=(\d+) collision_reads=(\d+) noncollision_reads=(\d+)', log)
    assert marker and not re.search(r'\bFAIL\b|\bFATAL\b|\bERROR\b', log, re.I)
    coverage = dict(zip(('cycles', 'bit_checks', 'reset_events', 'collision_reads', 'noncollision_reads'), map(int, marker.groups())))
    assert coverage['cycles'] > 65536 and coverage['bit_checks'] >= coverage['cycles'] * 256
    assert coverage['reset_events'] >= 12 and min(coverage['collision_reads'], coverage['noncollision_reads']) > 30000
    assert (args.candidate_dir / 'rtl/fg_vram.sv').read_bytes() == fg
    assert {name: sha((ROOT / name).read_bytes()) for name in UNCHANGED} == UNCHANGED
    receipt = dict(preparation, status='PASS', results=results, native_receipt=str(native_receipt_path),
                   native_receipt_sha256=sha(native_receipt_path.read_bytes()), native_markers=native_markers,
                   intel_coverage=coverage, no_collision_or_x_masks=True)
    path = output / 'receipt.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': 'PASS', 'receipt': str(path), 'receipt_sha256': sha(path.read_bytes()), 'intel_coverage': coverage}), flush=True)


if __name__ == '__main__':
    main()
