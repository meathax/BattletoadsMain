"""Freeze project inputs for isolated native checks; never compile or assemble."""
from __future__ import annotations
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PROJECT = 'Arcade-Battletoads'
ROOT_FILES = {PROJECT + suffix for suffix in ('.qpf', '.qsf', '.sdc', '.sv')}
ROOT_FILES.update({'files.qip', 'build_id.v'})
SOURCE_DIRS = {'rtl', 'sys', 'src'}

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--label', required=True)
    parser.add_argument('--git-ref')
    parser.add_argument('--build-date', default=datetime.now().strftime('%y%m%d'))
    args = parser.parse_args()
    if not args.label.replace('-', '').replace('_', '').isalnum():
        raise ValueError('Snapshot label must be alphanumeric with hyphens/underscores')
    if len(args.build_date) != 6 or not args.build_date.isdigit():
        raise ValueError('BUILD_DATE must have six decimal digits')
    target = ROOT / 'build/timing_closure_20261011' / args.label
    if target.exists():
        raise FileExistsError('Keep previous native databases intact: ' + str(target))
    target.mkdir(parents=True)
    head = subprocess.run(['git', 'rev-parse', args.git_ref or 'HEAD'], cwd=ROOT,
                          capture_output=True, text=True, check=True).stdout.strip()
    if args.git_ref:
        archive = target.parent / (args.label + '-source.zip')
        subprocess.run(['git', 'archive', '--format=zip', '-o', str(archive), head], cwd=ROOT, check=True)
        with zipfile.ZipFile(archive) as bundle:
            for entry in bundle.infolist():
                rel = Path(entry.filename)
                if entry.is_dir() or (entry.filename not in ROOT_FILES and rel.parts[0] not in SOURCE_DIRS):
                    continue
                if '..' in rel.parts or rel.is_absolute():
                    raise ValueError('Archive path escaped snapshot')
                dest = target / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(bundle.read(entry))
    else:
        for name in ROOT_FILES:
            shutil.copy2(ROOT / name, target / name)
        for name in SOURCE_DIRS:
            shutil.copytree(ROOT / name, target / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    original_qsf = (target / (PROJECT + '.qsf')).read_bytes()
    # Review: sys/build_id.tcl generates only BUILD_DATE and JTAG CDF. Partial
    # map/fit does not run it; reproduce BUILD_DATE inside this snapshot only.
    (target / 'build_id.v').write_text('`define BUILD_DATE "' + args.build_date + '"', encoding='utf-8')
    with (target / (PROJECT + '.qsf')).open('a', encoding='utf-8') as qsf:
        qsf.write('\n# Isolated partial-check safety; original settings are preserved.\n'
                  'set_global_assignment -name GENERATE_RBF_FILE OFF\n')
    manifest = {str(p.relative_to(target)).replace('\\', '/'): sha(p)
                for p in target.rglob('*') if p.is_file()}
    receipt = {'schema': 'bt-isolated-source-v1', 'project': str(target / (PROJECT + '.qpf')),
               'git_head': head, 'git_ref': args.git_ref, 'sources': manifest,
               'original_qsf_sha256': hashlib.sha256(original_qsf).hexdigest(),
               'build_date': args.build_date, 'partial_check_rbf_generation': False,
               'preprocessing_review': 'sys/build_id.tcl BUILD_DATE regenerated; JTAG CDF is packaging-only',
               'compiled': False, 'assembled': False}
    (target.parent / (args.label + '-snapshot.json')).write_text(json.dumps(receipt, indent=2))
    print(json.dumps({'project': receipt['project'], 'git_head': head, 'source_files': len(manifest),
                      'receipt': str(target.parent / (args.label + '-snapshot.json'))}))

if __name__ == '__main__':
    main()
