"""Prepare explicit same-SYS-edge reset domains from the immutable v15 top."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT / 'build/timing_closure_20261011/cpu_locator_v15_private'
BASE_MANIFEST = BASE.with_name(BASE.name + '-snapshot.json')
BASE_MANIFEST_SHA = '40e06ad6b48607845413f1216e39bf180a8659fb8382fd4983cdc64b18f0858e'
FUNCTIONAL = ROOT / 'build/final_v15_current_input_qualification/receipt.json'
FUNCTIONAL_SHA = '31fcfe88957ee3cf4e584a15bb3c21968142a77e73e5e15c76d7b39a9aeb742f'
TOP = 'Arcade-Battletoads.sv'
PARENT_SHA = 'ba4977deb04e399143800f81a7354280e2fe4180775c53bc816825844e43e5cf'
CLONES = ('reset_bt', 'reset_phase', 'reset_ddr', 'reset_video')
BINDINGS = (
    (b'\t\treset_mem <= reset;\r\n', b'\t\treset_mem <= reset_ddr;\r\n', 'MEM reset copy'),
    (b'\tbt_clock_enables clock_enables(.clk(clk_sys), .reset(reset),\r\n',
     b'\tbt_clock_enables clock_enables(.clk(clk_sys), .reset(reset_phase),\r\n', 'Clock enables'),
    (b'\t\tif (reset) user_pause <= 0;\r\n', b'\t\tif (reset_phase) user_pause <= 0;\r\n', 'User pause'),
    (b'\t    .clk(clk_sys), .reset(reset), .pause_req(pause_cpu),\r\n',
     b'\t    .clk(clk_sys), .reset(reset_phase), .pause_req(pause_cpu),\r\n', 'CPU pause bridge'),
    (b'\t\t.RST_N(~reset),\r\n', b'\t\t.RST_N(~reset_bt),\r\n', 'BT active-low reset'),
    (b'\t\t.reset(reset), .video_clk(clk_sys), .mem_clk(clk_mem),\r\n',
     b'\t\t.reset(reset_video), .video_clk(clk_sys), .mem_clk(clk_mem),\r\n', 'Video DDR bridge'),
)
sha = lambda data: hashlib.sha256(data).hexdigest()


def capture(data):
    pattern = (rb'\talways @\(posedge clk_sys\) reset <= RESET \| buttons\[1\] \| status\[0\] \| rom_download \| ~rom_ready \|\r\n'
               rb'\t +~fg_ddr_ready_sys\[1\] \| ~locked;\r\n')
    matches = list(re.finditer(pattern, data))
    assert len(matches) == 1, 'Original seven-term capture edge changed'
    return matches[0][0]


def clone_block(original_capture):
    block = b'\t// Same-SYS-edge reset domains: each captures the original D, not the old reset Q.\r\n'
    for name in CLONES:
        block += b"\t(* preserve, dont_merge *) reg " + name.encode() + b" = 1'b1;\r\n"
    for name in CLONES:
        block += original_capture.replace(b' reset <=', b' ' + name.encode() + b' <=', 1)
    return block


def transform(data):
    assert sha(data) == PARENT_SHA, 'Not the immutable complete v15 top'
    assert data.count(b"\treg reset = 1'b1;\r\n") == 1
    assert not any(re.search(rb'\b' + name.encode() + rb'\b', data) for name in CLONES)
    cap = capture(data)
    result = data.replace(cap, cap + clone_block(cap), 1)
    for old, new, role in BINDINGS:
        assert result.count(old) == 1, ('Ambiguous original consumer', role)
        result = result.replace(old, new, 1)
    return result


def reverse(data):
    cap = capture(data)
    block = clone_block(cap)
    assert data.count(block) == 1, 'Clone declarations, init, edge or original D changed'
    result = data.replace(block, b'', 1)
    for old, new, role in BINDINGS:
        assert result.count(new) == 1, ('Missing or foreign consumer', role)
        result = result.replace(new, old, 1)
    assert sha(result) == PARENT_SHA, 'Unrelated top edit or original producer/audio change'
    return result


def scopes(data):
    start = data.index(b"\treg [1:0] fg_ddr_ready_sys = 2'b00;\r\n")
    end = data.index(b'\t\tfg_ddr_clear_init_n <= locked && rom_ready && !rom_download;\r\n\tend', start)
    end += len(b'\t\tfg_ddr_clear_init_n <= locked && rom_ready && !rom_download;\r\n\tend')
    phase_start = data.index(b'\twire CE_F, CE_R, VCE_R;\r\n')
    phase_end = data.index(b'\twire SCLKX2;', phase_start)
    audio_start = data.index(b'\tbit SCE_DIV;\r\n')
    audio_end = data.index(b'\twire SCE_F =', audio_start)
    video = re.findall(rb'\tbt_video_ddr video_ddr \(.*?\r\n\t\);', data, re.S)
    assert len(video) == 1
    return {'producer': data[start:end], 'phase': data[phase_start:phase_end],
            'audio': data[audio_start:audio_end], 'video': video[0]}


def source_equivalence(old, new):
    assert transform(old) == new and reverse(new) == old
    assert capture(old) == capture(new)
    assert b"\treg reset = 1'b1;\r\n" in new
    before, after = scopes(old), scopes(new)
    assert before['audio'] == after['audio'], 'Original async audio process changed'
    roles = []
    for old_binding, new_binding, role in BINDINGS:
        assert old.count(old_binding) == new.count(new_binding) == 1
        roles.append({'role': role, 'original': old_binding.decode().strip(),
                      'candidate': new_binding.decode().strip()})
    roles.append({'role': 'Async audio SCE_DIV', 'original': 'posedge reset; if (reset)',
                  'candidate': 'posedge reset; if (reset)', 'body_byte_identical': True})
    for name in CLONES:
        decl = b"\t(* preserve, dont_merge *) reg " + name.encode() + b" = 1'b1;\r\n"
        edge = capture(old).replace(b' reset <=', b' ' + name.encode() + b' <=', 1)
        assert new.count(decl) == new.count(edge) == 1
        assert edge.replace(b' ' + name.encode() + b' <=', b' reset <=', 1) == capture(old)
    return {'raw_full_top_inverse_identical': True, 'original_reset_init_and_capture_bytes_unchanged': True,
            'four_state_induction': 'All copies initialize to the original 1; at every same SYS edge each evaluates the byte-identical original D using the same pre-NBA state; all hold between edges. Thus all reset Qs are case-equal for every trace, including X/Z inputs.',
            'clones': list(CLONES), 'registers_added': 4, 'latency_edges_added': 0,
            'consumer_roles': roles, 'original_audio_body_sha256': sha(before['audio']),
            'old_scopes': {key: sha(value) for key, value in before.items()},
            'new_scopes': {key: sha(value) for key, value in after.items()},
            'all_other_top_bytes_preserved_after_guarded_alias_inverse': True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--full-project', type=Path, required=True)
    args = parser.parse_args()
    output, full = args.output.resolve(), args.full_project.resolve()
    output.relative_to(ROOT / 'build'); full.relative_to(ROOT / 'build')
    snapshot_path = full.with_name(full.name + '-snapshot.json')
    assert not any(path.exists() for path in (output, full, snapshot_path))
    assert sha(BASE_MANIFEST.read_bytes()) == BASE_MANIFEST_SHA
    assert sha(FUNCTIONAL.read_bytes()) == FUNCTIONAL_SHA
    parent = json.loads(BASE_MANIFEST.read_text())
    sources = {name.replace('\\', '/'): digest for name, digest in parent['sources'].items()}
    assert len(sources) == 144 and sources[TOP] == PARENT_SHA
    for name, digest in sources.items():
        path = (BASE / name).resolve(); path.relative_to(BASE)
        assert path.is_file() and not path.is_symlink() and sha(path.read_bytes()) == digest
    old = (BASE / TOP).read_bytes(); new = transform(old)
    proof = source_equivalence(old, new)
    for relative, content in [('oracle/' + TOP, old), ('candidate/' + TOP, new)]:
        path = output / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(content)
    new_sources = dict(sources); new_sources[TOP] = sha(new)
    for name in sources:
        target = full / name; target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(new if name == TOP else (BASE / name).read_bytes())
        assert sha(target.read_bytes()) == new_sources[name]
    manifest_path = output / 'manifest.json'
    manifest = {'schema': 'bt-v15-reset-partition-edge-v1', 'parent': str(BASE / TOP),
                'parent_sha256': PARENT_SHA, 'candidate_sha256': sha(new),
                'helper_sha256': sha(Path(__file__).read_bytes()),
                'parent_snapshot': {'path': str(BASE_MANIFEST), 'sha256': BASE_MANIFEST_SHA},
                'functional_parent': {'path': str(FUNCTIONAL), 'sha256': FUNCTIONAL_SHA},
                'source_equivalence': proof, 'full_project': str(full / 'Arcade-Battletoads.qpf'),
                'full_snapshot': str(snapshot_path), 'all144_sources': new_sources,
                'unchanged_other143_sources': True, 'timing_accepted': False,
                'mapped_copies_proven': False,
                'scope': 'Four explicitly separate reset registers, each same original SYS capture and init; six consumer bindings; original async audio and all other top behavior retained.'}
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    frozen = dict(parent)
    frozen.update(schema='bt-isolated-reset-partition-snapshot-v18', project=str(full / 'Arcade-Battletoads.qpf'),
                  sources=new_sources, derived_from_snapshot={'path': str(BASE_MANIFEST), 'sha256': BASE_MANIFEST_SHA},
                  source_edge={'path': str(manifest_path), 'sha256': sha(manifest_path.read_bytes())},
                  functional_parent={'path': str(FUNCTIONAL), 'sha256': FUNCTIONAL_SHA},
                  source_files=144, unchanged_parent143_source_hashes=True,
                  compiled=False, assembled=False)
    snapshot_path.write_text(json.dumps(frozen, indent=2) + '\n')
    print(json.dumps({'status': 'PASS_SOURCE_EDGE', 'candidate_sha256': sha(new),
                      'manifest': str(manifest_path), 'manifest_sha256': sha(manifest_path.read_bytes()),
                      'project': str(full / 'Arcade-Battletoads.qpf'),
                      'snapshot': str(snapshot_path), 'snapshot_sha256': sha(snapshot_path.read_bytes()),
                      'source_files': 144, 'unchanged_other_sources': 143}, indent=2))


if __name__ == '__main__':
    main()
