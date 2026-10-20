"""Prepare a private, byte-guarded MC snapshot correction; never edit root RTL."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
BASE_MC_SHA256 = 'd7ab5a420cad7c035f561b16342aca1524d58528864576ce1fa30621415ff4dc'
BASE_MC_GIT_COMMIT = 'b53726397822b9dbebb02d36411294056fd08649'
BASE_MC_CANONICAL_SHA256 = '9f0ea99c77b5651c356d5495bdc1ac67ee15db815ff76f6b13ed6dc4f1828f70'
MC_NAME = 'rtl/TMS34020/TMS34020_MC.sv'
MC_ORACLE_NAME = 'tests/fixtures/tms34020_mc_en0_oracle.sv'
sha = lambda value: hashlib.sha256(value).hexdigest()


def canonical_lf(data):
    normalized = data.replace(b'\r\n', b'\n')
    assert b'\r' not in normalized, 'Only LF/CRLF normalization is allowed'
    return normalized


def git_mc_oracle():
    result = subprocess.run(['git', 'show', BASE_MC_GIT_COMMIT + ':' + MC_NAME],
                            cwd=ROOT, capture_output=True, check=True)
    assert sha(canonical_lf(result.stdout)) == BASE_MC_CANONICAL_SHA256
    return result.stdout

EARLY_BLOCK = '''\t\t\t// Early read capture: every clock from the CE_R after READ_LATCH up to
\t\t\t// (not including) the CE_F capture, so the last load is one clock
\t\t\t// before the CE_F capture and sees exactly the word it will load
\t\t\t// (DBUS_DI_E is next clock's bus view). The CPU consumes at the CE_R
\t\t\t// after that CE_F: always >= 2 clocks after the last early load
\t\t\t// (asserted below), which is what bt_cpu_phase.sdc relies on.
\t\t\tif (READ_LATCH && !CE_F) begin
\t\t\t\tREAD_WORD_E <= DBUS_DI_E;
\t\t\t\tREAD_PREVIOUS_E <= DIN_BUF;
\t\t\t\tREAD_ALIGN_E <= DIN_BA;
\t\t\t\tREAD_SIZE_E <= DIN_FS;
\t\t\t\tREAD_OLD_SIZE_E <= DIN_FS_OLD;
\t\t\t\tREAD_EXTENDED_E <= MC_EXT_WORD;
\t\t\tend
`ifndef SYNTHESIS
\t\t\t// The early capture group must be >= 2 clocks old at every CE_R.
\t\t\tif (CE_R) assert (!early_loaded_last_edge)
\t\t\t\telse $fatal(1,"early read capture loaded one clock before a CE_R");
\t\t\tearly_loaded_last_edge <= READ_LATCH && !CE_F;
`endif
'''

NEW_EARLY_BLOCK = EARLY_BLOCK.replace(
    EARLY_BLOCK[:EARLY_BLOCK.index('\t\t\tif (READ_LATCH')],
    '''\t\t\t// Prepare the return snapshot on every SYS edge, including EN pauses.
\t\t\t// READ_LATCH and its metadata remain held until an admitted CE_F;
\t\t\t// a resumed F must see the current word, not the previous transaction.
\t\t\t// The following admitted R still requires two clocks of snapshot age.
''', 1).replace('if (CE_R) assert', 'if (EN && CE_R) assert', 1)


def en0_snapshot_transform(original):
    assert sha(canonical_lf(original)) == BASE_MC_CANONICAL_SHA256, 'The immutable full-MC baseline changed'
    newline = '\r\n' if b'\r\n' in original else '\n'
    text = original.decode().replace('\r\n', '\n')
    assert '\r' not in text and text.count(EARLY_BLOCK) == 1
    text = text.replace(EARLY_BLOCK, '', 1)
    before = '\t\telse if (EN) begin\n\t\t\tif (SCRREF_RUN && CE_R) begin'
    assert text.count(before) == 1
    text = text.replace(before, '\t\telse begin\n' + NEW_EARLY_BLOCK +
                        '\t\t\tif (EN) begin\n\t\t\tif (SCRREF_RUN && CE_R) begin', 1)
    reset = '\t\t\tREAD_EXTENDED_E <= 0;\n'
    assert text.count(reset) == 1
    text = text.replace(reset, reset + '`ifndef SYNTHESIS\n\t\t\tearly_loaded_last_edge <= 0;\n`endif\n', 1)
    close = '\t\tend\n\tend\n\tassign WAIT = '
    assert text.count(close) == 1
    text = text.replace(close, '\t\t\tend // Only architectural/bus state is EN-gated.\n' + close, 1)
    return text.replace('\n', newline).encode()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-source-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    base, output = args.base_source_root.resolve(), args.output.resolve()
    assert output.is_relative_to(ROOT / 'build'), 'Private candidates must remain inside ignored build/'
    assert not output.exists(), 'Keep prior candidates and evidence immutable'
    baseline = (ROOT / MC_ORACLE_NAME).read_bytes()
    git_blob = git_mc_oracle()
    assert canonical_lf(baseline) == canonical_lf(git_blob)
    candidate = en0_snapshot_transform(baseline)
    names = ['Arcade-Battletoads.sv', 'files.qip', 'rtl/BT.sv',
             'rtl/TMS34020/TMS34020.sv', 'rtl/bt_pause_bridge.sv',
             'rtl/bt_clock_enables.sv', 'rtl/bt_nvram.sv']
    frozen = {name: (base / name).read_bytes() for name in names}
    output.mkdir(parents=True, exist_ok=False)
    for name, data in frozen.items():
        target = output / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    target = output / MC_NAME
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(candidate)
    oracle = output.parent / 'immutable_oracle' / MC_NAME
    oracle.parent.mkdir(parents=True, exist_ok=True)
    if oracle.exists():
        assert oracle.read_bytes() == baseline
    else:
        oracle.write_bytes(baseline)
    receipt = {
        'schema': 'bt-private-en0-preparatory-snapshot-v1',
        'base_source_root': str(base), 'source_root': str(output),
        'immutable_full_mc': {'path': str(oracle), 'sha256': sha(baseline),
                             'canonical_lf_sha256': sha(canonical_lf(baseline)),
                             'git_commit': BASE_MC_GIT_COMMIT, 'git_blob_path': MC_NAME,
                             'git_blob_raw_sha256': sha(git_blob)},
        'candidate_mc': {'path': str(target), 'sha256': sha(candidate),
                         'canonical_lf_sha256': sha(canonical_lf(candidate))},
        'unchanged_base_inputs': {name: sha(data) for name, data in frozen.items()},
        'allowed_change': 'Move only six preparatory E snapshot loads outside EN. Track actual immediately preceding SYS load every clock, reset that age flag, and require >=2 clocks at EN-qualified R. Every architectural/bus/F capture remains EN-gated and byte-identical.',
        'root_rtl_changed': False, 'timing_accepted': False,
        'prepared_by': {'path': str(Path(__file__).resolve()), 'sha256': sha(Path(__file__).read_bytes())},
    }
    path = output.parent / 'candidate_manifest.json'
    path.write_text(json.dumps(receipt, indent=2) + '\n')
    print('candidate=' + str(output))
    print('mc_sha256=' + sha(candidate))
    print('manifest=' + str(path))


if __name__ == '__main__':
    main()
