"""Run the unchanged read/storage fixtures on frozen current production inputs.

Missing historical temporary oracles are replaced explicitly by immutable
b537 Git blobs. This proves the stated parent relationship, never an invented
historical shipping image. Fixtures and behavioral RAM models are copied intact.
Only the original qualifier's module-name adaptations are applied.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

from verify_bt_current_qualification import (ROOT, REF, SPECS, sha, git_blob,
    adapt_input, parse_read_coverage, current_read_suite_verified, validate_parallel_ddr_edge)


def relative(path):
    return Path(path).resolve().relative_to(ROOT).as_posix()


def wsl(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(source_root, out):
    assert out.is_relative_to(ROOT / 'build') or out.is_relative_to(ROOT / 'tests/graphics/evidence')
    assert not out.exists(), 'Evidence directory already exists'
    out.mkdir(parents=True)
    manifest = {'schema': 'bt-current-read-storage-suite-v1', 'status': 'PREPARED',
                'oracle_commit': REF, 'source_root': str(source_root), 'sources': {}, 'jobs': {},
                'scope': 'Unchanged directed fixtures; immutable b537 parent for three comparisons. Behavioral RAMs; physical storage and complete CPU/native behavior are separate.'}
    current_ddr=(source_root/'rtl/ddram.sv').read_bytes().replace(b'\r\n',b'\n')
    if current_ddr!=git_blob('rtl/ddram.sv').replace(b'\r\n',b'\n'):
        manifest['ddr_controller_edge']=validate_parallel_ddr_edge(source_root)
    helpers = ['tests/graphics/qualify_current_read_storage.py',
               'tests/graphics/verify_bt_current_qualification.py']
    for name in helpers:
        manifest['sources'][name] = sha((ROOT / name).read_bytes())
    for family, spec in SPECS.items():
        directory = out / family
        directory.mkdir()
        job = {'family': family, 'top': spec['top'], 'sources': {}, 'compiled_inputs': [],
               'oracle': None, 'commands': [], 'compile_exit_code': None,
               'run_exit_code': None, 'exit_code': None, 'testbench_passed': False}
        for name in spec['needed']:
            path = source_root / name if (source_root / name).is_file() else ROOT / name
            data = path.read_bytes()
            job['sources'][name] = manifest['sources'][name] = sha(data)
        for name in spec['compile']:
            path = source_root / name if (source_root / name).is_file() else ROOT / name
            raw = path.read_bytes()
            transform = (spec.get('candidate_transform', 'identity') if name == spec.get('oracle_file') else
                         spec.get('fixture_transform', 'identity') if name == spec['compile'][-1] else 'identity')
            data = adapt_input(raw, transform)
            target = directory / Path(name).name
            target.write_bytes(data)
            job['compiled_inputs'].append({'name': name, 'path': relative(target),
                'role': 'current', 'transform': transform, 'sha256': sha(data), 'raw_sha256': sha(raw)})
        if spec.get('oracle_file'):
            name = spec['oracle_file']
            raw = git_blob(name)
            raw_path = directory / 'immutable_oracle_raw.sv'
            raw_path.write_bytes(raw)
            data = adapt_input(raw, spec['oracle_transform'])
            target = directory / 'immutable_oracle_compiled.sv'
            target.write_bytes(data)
            job['oracle'] = {'kind': 'immutable-git', 'commit': REF, 'file': name,
                'raw_path': relative(raw_path), 'raw_sha256': sha(raw),
                'compiled_path': relative(target), 'compiled_sha256': sha(data),
                'transform': spec['oracle_transform'],
                'parent_body_identical_lf': raw.replace(b'\r\n', b'\n') ==
                    (source_root / name if (source_root / name).is_file() else ROOT / name).read_bytes().replace(b'\r\n', b'\n')}
            job['compiled_inputs'].append({'name': name, 'path': relative(target), 'role': 'oracle',
                'transform': spec['oracle_transform'], 'sha256': sha(data), 'raw_sha256': sha(raw)})
        manifest['jobs'][family] = job
    write_json(out / 'manifest.json', manifest)
    print(json.dumps({'prepared': str(out / 'manifest.json'), 'families': list(manifest['jobs']),
                      'oracle_commit': REF}, sort_keys=True), flush=True)
    return out / 'manifest.json'


def run_prepared(manifest_path):
    manifest = json.loads(manifest_path.read_text())
    assert manifest['schema'] == 'bt-current-read-storage-suite-v1'
    assert manifest['status'] == 'PREPARED', 'Suite is not an unrun prepared input set'
    assert manifest['oracle_commit'] == REF
    for name, digest in manifest['sources'].items():
        assert sha((ROOT / name).read_bytes()) == digest, 'Current input changed: ' + name
    out = manifest_path.parent
    started = time.monotonic()
    manifest['status'] = 'RUNNING'
    write_json(manifest_path, manifest)
    for family, job in manifest['jobs'].items():
        directory = out / family
        for item in job['compiled_inputs']:
            assert sha((ROOT / item['path']).read_bytes()) == item['sha256']
        workspace = Path('R:/Verilator/BT') / ('current-read-' + family + '-' + uuid.uuid4().hex)
        (workspace / 'obj').mkdir(parents=True)
        command = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', '/usr/bin/verilator',
                   '--binary', '--assert', '--timing', '-j', '2', '--threads', '1',
                   '-Wno-fatal', '-Wno-BLKANDNBLK', '--top-module', job['top'],
                   '--Mdir', wsl(workspace / 'obj')]
        if SPECS[family].get('unique_x'):
            command += ['--x-initial', 'unique', '--x-assign', 'unique']
        command += [wsl(ROOT / item['path']) for item in job['compiled_inputs']]
        run = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(ROOT), '--exec', wsl(workspace / 'obj' / ('V' + job['top']))]
        job['commands'] = [command, run]
        print('compile=' + family, flush=True)
        with (directory / 'build.log').open('w') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, timeout=600)
        job['compile_exit_code'] = result.returncode
        if result.returncode == 0:
            print('simulate=' + family, flush=True)
            with (directory / 'run.log').open('w') as log:
                result = subprocess.run(run, stdout=log, stderr=subprocess.STDOUT, timeout=180)
            job['run_exit_code'] = result.returncode
        job['exit_code'] = result.returncode
        if result.returncode == 0:
            report = (directory / 'run.log').read_text(errors='replace')
            job['coverage'] = parse_read_coverage(family, report)
            job['testbench_passed'] = True
        job['logs'] = {relative(path): sha(path.read_bytes()) for path in
                       (directory / 'build.log', directory / 'run.log') if path.is_file()}
        job['scope'] = SPECS[family]['scope']
        write_json(directory / 'receipt.json', job)
        write_json(manifest_path, manifest)
        if result.returncode:
            manifest['status'] = 'FAIL'
            write_json(out / 'receipt.json', manifest)
            print((directory / ('run.log' if job['run_exit_code'] is not None else 'build.log')).read_text(errors='replace')[-2300:])
            return result.returncode
        print(json.dumps({'family': family, 'status': 'PASS', 'coverage': job['coverage']}, sort_keys=True), flush=True)
    for name, digest in manifest['sources'].items():
        assert sha((ROOT / name).read_bytes()) == digest, 'Input changed during suite: ' + name
    manifest['status'] = 'PASS'
    manifest['wall_seconds'] = round(time.monotonic() - started, 3)
    receipt = out / 'receipt.json'
    write_json(receipt, manifest)
    assert current_read_suite_verified(receipt, ROOT), 'Strict current source/input/coverage validation failed'
    print('receipt=' + str(receipt), flush=True)
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=ROOT)
    parser.add_argument('--out', type=Path)
    parser.add_argument('--prepare-only', action='store_true')
    parser.add_argument('--run-prepared', type=Path)
    args = parser.parse_args()
    if args.run_prepared:
        assert args.out is None and not args.prepare_only
        return run_prepared(args.run_prepared.resolve())
    out = (args.out or ROOT / 'tests/graphics/evidence/current-read-storage' /
           ('current-read-storage-' + uuid.uuid4().hex)).resolve()
    path = prepare(args.source_root.resolve(), out)
    return 0 if args.prepare_only else run_prepared(path)


if __name__ == '__main__':
    sys.exit(main())
