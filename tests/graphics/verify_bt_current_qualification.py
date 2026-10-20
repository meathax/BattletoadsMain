"""Strict supplemental current-image read and consuming-stage validation.

Legacy validators and receipts remain unchanged. No timing, Intel storage,
native raster, hardware, or RBF eligibility is granted by this component check.
"""
from __future__ import annotations
import argparse
import ast
import copy
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import types

ROOT = Path(__file__).resolve().parents[2]
REF = 'b53726397822b9dbebb02d36411294056fd08649'
GIT = 'D:/vibes/fpga/bin/git.EXE'
CURRENT_STAGE_RUNNER_SHA = '6a1bf36913cbcc3364a327b5e7bd8b450ff17899dff5de6dd453e14dd611b16d'
TYPED_STAGE_RUNNER_SHA = 'e2671b083ae908fcdca5df51f83007d1b349b7c48ed971b8641ce19b46d6f0c4'
TYPED_STAGE_HELPERS = {'tests/graphics/bt_address_class_fixture.py': 'fe751d52100598a239e5acc4f8af3a17ce5ce73d64e9cb72bebcc94292c6bc00', 'tests/graphics/bt_combined_stage_fixture.py': '57056d51f91cb0033456b58e776164a3eb13e26962f5fc367a4216138f305159', 'tests/graphics/prepare_bt_address_class.py': 'd433e7536bd74fdc305c4f0196358d46416275df42318f54b0be9fe81142595d', 'tests/graphics/prepare_bt_parallel_ddr_write.py': 'cb61d4ce35648066f6c31a463f64420ed4f08bae0ecbdf0e7810a8b1cdaf1f57', 'tests/graphics/prepare_bt_en0_snapshot_candidate.py': '2698b977b0122d702d73e66a2b631443255a163dd8f93497975f5d4f9f55f58f'}
REQUEST_STAGE_RUNNER = 'tests/graphics/qualify_bt_vram_request_stage.py'
REQUEST_STAGE_HELPERS = {
    REQUEST_STAGE_RUNNER: '01d79a9ad3a8a6fc490a38734c3ed5ae2f68cd61b871d2f917d9b7244f51045c',
    'tests/graphics/bt_vram_request_fixture.py': '79bfbb26e67b2a2c086cd0bf1bd5250615241c4b562db307a59a85bc076b4288',
    'tests/graphics/prepare_bt_vram_request.py': 'ab16e532b42d05cdef638b4b5926cad50d23ee788b38db532594b3695884e5cb',
}
RETAINED_READ_VALIDATOR_SHA = '1749235b3ca18fba4c6935c42c5464183283bf1fe2327c3a25ab3d2a94834931'
PARALLEL_DDR_RECEIPT = 'build/ddr_parallel_sources_v9_v2/proof/receipt.json'
RAM = 'tests/graphics/ram_models.sv'
SPECS = {
    'ddram-cache': {
        'top': 'ddram_cache_tb', 'compile': ['rtl/ddram.sv', 'tests/ddram_cache_tb.sv'],
        'needed': ['rtl/ddram.sv', 'tests/ddram_cache_tb.sv', 'tests/graphics/qualify_ddram_cache.py'],
        'oracle_file': 'rtl/ddram.sv', 'oracle_transform': 'ddram-baseline', 'unique_x': True,
        'scope': 'Accepted DDR command/data/handshake equality to immutable b537, plus unchanged complete controller-body identity; original cache fixture assertions.'},
    'sprite-packet': {
        'top': 'sprite_packet_tb', 'compile': ['rtl/spr_vram.sv', RAM, 'tests/sprite_packet_tb.sv'],
        'needed': ['rtl/spr_vram.sv', RAM, 'tests/sprite_packet_tb.sv', 'tests/graphics/qualify_sprite_packet.py'],
        'scope': 'Actual current sprite packet ordering/completion, original fixture and behavioral RAM.'},
    'sprite-read': {
        'top': 'sprite_read_equivalence_tb', 'compile': ['rtl/spr_vram.sv', RAM, 'tests/sprite_read_equivalence_tb.sv'],
        'needed': ['rtl/spr_vram.sv', RAM, 'rtl/BT_mem.sv', 'tests/sprite_read_equivalence_tb.sv', 'tests/graphics/qualify_sprite_read.py'],
        'oracle_file': 'rtl/spr_vram.sv', 'candidate_transform': 'sprite-candidate', 'oracle_transform': 'identity',
        'scope': 'Sprite transactions/serial/consumer equality to immutable b537; unchanged controller identity; hardware wrapper binding is separate from physical Intel qualification.'},
    'foreground-read': {
        'top': 'foreground_read_equivalence_tb', 'compile': ['rtl/fg_vram.sv', RAM, 'tests/foreground_read_equivalence_tb.sv'],
        'needed': ['rtl/fg_vram.sv', RAM, 'rtl/BT_mem.sv', 'tests/foreground_read_equivalence_tb.sv', 'tests/graphics/qualify_foreground_read.py'],
        'oracle_file': 'rtl/fg_vram.sv', 'oracle_transform': 'foreground-reference',
        'fixture_transform': 'foreground-fixture-b537',
        'scope': 'Current foreground transaction/copy/readback/serial equality to immutable b537 using original assertions and independent response adapters; full pin/Intel proofs remain separate.'},
    'foreground-ddr': {
        'top': 'foreground_ddr_tb', 'compile': ['rtl/fg_vram.sv', 'rtl/ddram.sv', 'rtl/bt_fg_ddr_clear.sv', RAM, 'tests/foreground_ddr_tb.sv'],
        'needed': ['rtl/fg_vram.sv', 'rtl/ddram.sv', 'rtl/bt_fg_ddr_clear.sv', RAM, 'tests/foreground_ddr_tb.sv', 'tests/graphics/qualify_foreground_ddr.py'],
        'unique_x': True,
        'scope': 'Actual current foreground transfer through shipping DDR controller, cold-clear/masked writes/cache/backpressure; unchanged complete fixture.'},
}


class QualificationError(Exception):
    pass


def check(condition, message):
    if not condition:
        raise QualificationError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def wsl_path(path):
    path = Path(path).resolve()
    return '/mnt/' + path.drive[0].lower() + path.as_posix()[2:]


def git_blob(name, root=ROOT):
    result = subprocess.run([GIT, '-C', str(root), 'show', REF + ':' + name], capture_output=True)
    check(result.returncode == 0, 'Immutable Git oracle unavailable: ' + name)
    return result.stdout


def contained(root, name):
    path = (root / name).resolve()
    check(path.is_relative_to(root.resolve()) and path.is_file(), 'Missing/out-of-root input: ' + name)
    return path


def adapt_input(data, transform):
    if transform == 'identity':
        return data
    if transform == 'foreground-fixture-b537':
        # The historical oracle predates these ports and the registered cache.
        # Immutable b537 already owns both contracts. Keep every assertion and
        # stimulus; bind its real inputs and use independent equal pipelines.
        changes = [
            (b'reference_CPU_SHIFT_Q=0;', b'reference_CPU_SHIFT_Q=0, reference_CPU_SHIFT_Q1=0;'),
            (b'.DRAW_WE(DRAW_WE),\n    .DRAW_ADDR(DRAW_ADDR),',
             b'.DRAW_WE(DRAW_WE),\n    .DRAW_BANK_WE(DRAW_BANK_WE), .DRAW_RAM_BANK_WE(DRAW_RAM_BANK_WE),\n    .DRAW_ADDR(DRAW_ADDR),'),
            (b'reference_CPU_SHIFT_Q<=cache_word(reference_CPU_SHIFT_A);',
             b'reference_CPU_SHIFT_Q1<=cache_word(reference_CPU_SHIFT_A);\n    reference_CPU_SHIFT_Q<=reference_CPU_SHIFT_Q1;'),
        ]
        newline = b'\r\n' if b'\r\n' in data else b'\n'
        for before, after in changes:
            before, after = before.replace(b'\n', newline), after.replace(b'\n', newline)
            check(data.count(before) == 1, 'Immutable-parent fixture binding anchor changed')
            data = data.replace(before, after, 1)
        return data
    changes = {
        'ddram-baseline': (b'module ddram', b'module ddram_baseline'),
        'sprite-candidate': (b'module SPR_VRAM', b'module SPR_VRAM_SYNC'),
        'foreground-reference': (b'module FG_VRAM', b'module FG_VRAM_REFERENCE'),
    }
    check(transform in changes, 'Unqualified source transformation')
    before, after = changes[transform]
    check(data.count(before) == 1, 'Module rename anchor changed')
    data = data.replace(before, after, 1)
    if transform == 'foreground-reference':
        check(data.count(b'BT_FG_BANKED_VRAM') == 2, 'Foreground helper namespace anchor changed')
        data = data.replace(b'BT_FG_BANKED_VRAM', b'BT_FG_BANKED_VRAM_REFERENCE')
    return data


def parse_read_coverage(family, report):
    patterns = {
        'ddram-cache': (r'PASS DDR cache pipeline: (\d+) masked/burst/I/O writes, (\d+) checked reads, (\d+) DDR read commands;', ('writes', 'reads', 'DDR_read_commands'), (3080, 2176, 176)),
        'sprite-packet': (r'SPRITE_PACKET_PASS packets=(\d+) readbacks=(\d+) completion_checks=(\d+)', ('packets', 'readbacks', 'completion_checks'), (512, 512, 528)),
        'sprite-read': (r'PASS sprite transaction equivalence: transfers=(\d+) comparisons=(\d+)', ('transfers', 'comparisons'), (16, 15424)),
        'foreground-read': (r'PASS foreground transaction equivalence: transactions=(\d+) comparisons=(\d+)', ('transactions', 'comparisons'), (240, 83344)),
        'foreground-ddr': (r'PASS shipping DDR controller: (\d+) cold-clear writes during reset, (\d+) masked writes, (\d+) round-trip copy bytes', ('cold_clear_writes', 'masked_writes', 'copy_bytes'), (196608, 128, 512)),
    }
    check(family in patterns, 'Unexpected read/storage family')
    pattern, names, minima = patterns[family]
    matches = list(re.finditer(pattern, report))
    check(len(matches) == 1, 'Missing or ambiguous original PASS marker: ' + family)
    values = tuple(map(int, matches[0].groups()))
    check(all(value >= minimum for value, minimum in zip(values, minima)), 'Insufficient original coverage: ' + family)
    return dict(zip(names, values))


def source_map_verified(sources, root, needed=()):
    check(isinstance(sources, dict) and bool(sources), 'Sources must be explicit')
    normalized = {name.replace('\\', '/'): digest for name, digest in sources.items()}
    check(len(normalized) == len(sources) and set(needed) <= normalized.keys(), 'Source list incomplete/ambiguous')
    for name, digest in normalized.items():
        check(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest), 'Malformed digest')
        check(sha(contained(root, name).read_bytes()) == digest, 'Source changed: ' + name)
    return normalized


def validate_parallel_ddr_edge(root, proof=None):
    """Exact reversible controller edge; default and activated paths both proved."""
    from bt_combined_stage_fixture import DDR_BASE, PARALLEL_SHA, parallel_transform
    path = contained(root, PARALLEL_DDR_RECEIPT)
    proof = json.loads(path.read_text()) if proof is None else proof
    check(proof.get('schema') == 'bt-parallel-ddr-write-proof-v1' and proof.get('status') == 'PASS', 'Parallel DDR proof failed')
    check(proof.get('oracle_commit') == REF and proof.get('oracle_git_file') == 'rtl/ddram.sv', 'Parallel DDR immutable origin changed')
    raw = git_blob('rtl/ddram.sv', root)
    baseline = contained(root, 'build/timing_closure_20261011/integrated_v9_private/rtl/ddram.sv').read_bytes()
    check(proof.get('oracle_sha256') == sha(raw) and proof.get('v9_parent_sha256') == sha(baseline) == DDR_BASE['rtl/ddram.sv'] and
          raw.replace(b'\r\n', b'\n') == baseline.replace(b'\r\n', b'\n') and proof.get('parent_body_identical_lf') is True, 'Full DDR oracle/parent identity changed')
    candidate = Path(proof['candidate_dir']).resolve()
    check(candidate == root / 'build/ddr_parallel_sources_v9_v2/candidate' and proof['candidate_sources'] == PARALLEL_SHA, 'Unreviewed parallel DDR candidate')
    for name, digest in PARALLEL_SHA.items():
        parent = contained(root, 'build/timing_closure_20261011/integrated_v9_private/' + name).read_bytes()
        data = contained(candidate, name).read_bytes()
        check(sha(parent) == DDR_BASE[name] and sha(data) == digest and data.replace(b'\r\n', b'\n') == parallel_transform(name, parent), 'Undeclared parallel DDR source change: ' + name)
    check(contained(root, 'rtl/ddram.sv').read_bytes() == contained(candidate, 'rtl/ddram.sv').read_bytes(), 'Current DDR differs from qualified exact controller')
    pinned_helpers = {
        'tests/graphics/prepare_bt_parallel_ddr_write.py': 'cb61d4ce35648066f6c31a463f64420ed4f08bae0ecbdf0e7810a8b1cdaf1f57',
        'tests/graphics/qualify_bt_parallel_ddr_write.py': '8bb0949e7ee338200872d08bde5e02169173fd5805004c4a23b0a5d569ddf801',
        'tests/bt_parallel_ddr_write_extra.svh': '15b91417d342d1b02a4cb57b8bf8beb81441e2e7a749017374c9abb4e7e3cad8',
        'tests/ddram_cache_tb.sv': 'a9a0c240d1cc0c0e0814cec8b3816ad331d90850707cddaca4590072eb7b3281'}
    check(proof.get('helper_sources') == pinned_helpers, 'Parallel DDR proof helpers changed')
    source_map_verified(pinned_helpers, root)
    bt = contained(candidate, 'rtl/BT.sv').read_text()
    begin, end = '\t// BT_PARALLEL_DDR_DATA_BEGIN', '\t// BT_PARALLEL_DDR_DATA_END'
    check(bt.count(begin) == bt.count(end) == 1, 'Parallel source slice ambiguous')
    start = bt.index(begin)
    legacy = re.search(r'\tassign EDATA = SPR_DDR_REQ.*?;', bt, re.S).group()
    producer = '''module bt_parallel_ddr_source(
 input SPR_DDR_REQ, FG_HOLE_COPY, FG0_HOLE_SEL,
 input [7:0] SPR_DRAW_DATA, input [31:0] FG0_HOLE_DATA, FG1_HOLE_DATA, LDO,
 output [31:0] EDATA, output [3:0][31:0] EDATA_CANDIDATES, output [3:0] EDATA_SELECT);
''' + bt[start:bt.index(end, start) + len(end)] + '\n' + legacy + '\nendmodule\n'
    check(proof.get('actual_bt_source_slice') == sha(producer.encode()), 'Actual BT producer not bound')
    fixture = contained(root, 'tests/ddram_cache_tb.sv').read_text()
    extra = contained(root, 'tests/bt_parallel_ddr_write_extra.svh').read_text()
    original_instance = re.search(r'    ddram_baseline original\(.*?;', fixture, re.S).group()
    serial = original_instance.replace('ddram_baseline original', 'ddram serial', 1)
    for name in ('q', 'busy', 'io_q', 'io_busy', 'burst_q', 'burst_pos', 'burst_tick', 'a', 'd', 'be', 'len', 'rd', 'wr'):
        serial = re.sub(r'\b' + name + r'1\b', name + '2', serial)
    declarations = '''    wire[31:0] q2,io_q2;wire busy2,io_busy2;
    wire[63:0] burst_q2,d2;wire[9:3] burst_pos2;wire burst_tick2;
    wire[28:0] a2;wire[7:0] be2,len2;wire rd2,wr2;
'''
    changes = [
        ('    ddram candidate(', '    ddram #(.USE_PARALLEL_DIN(1),.USE_PREDECODED_TAGS(1),.USE_PREDECODED_WE(1),.USE_PREDECODED_MISS(1)) candidate('),
        ('.dout(q0),.din(data),', '.dout(q0),.din(accepted_data),\n        .parallel_din(raw_sources),.parallel_din_sel(raw_owner),\n        .external_tag_hit(external_hits),.external_read_hit_part(external_miss_parts),.external_we_any(|write_be),'),
        ('.dout(q1),.din(data),', '.dout(q1),.din(accepted_data),'),
        ('    initial begin\n', declarations + '\n' + serial.replace('.din(data)', '.din(accepted_data)') + '\n' + extra + '\n    initial begin\n'),
        ('        if(writes<2048 || checks<2000)', '        parallel_extra();\n        if(writes<2048 || checks<2000)')]
    check(proof.get('fixture_transformations') == [list(item) for item in changes], 'Parallel DDR fixture transformation changed')
    adapted = fixture
    for before, after in changes:
        check(adapted.count(before) == 1, 'Parallel DDR fixture anchor changed')
        adapted = adapted.replace(before, after, 1)
    restored = adapted
    for before, after in reversed(changes):
        check(restored.count(after) == 1, 'Parallel DDR fixture cannot reverse')
        restored = restored.replace(after, before, 1)
    check(restored == fixture and proof.get('exact_fixture_restoration') is True, 'Original full cache fixture not preserved')
    files = {'ddram.sv': contained(candidate, 'rtl/ddram.sv').read_bytes(),
             'ddram_baseline.sv': raw.replace(b'module ddram', b'module ddram_baseline', 1),
             'bt_parallel_ddr_source.sv': producer.encode(), 'ddram_cache_tb.sv': adapted.encode()}
    check(proof.get('compiled_sources') == {name: sha(data) for name, data in files.items()}, 'Parallel compiled source set changed')
    for name, data in files.items():
        check(contained(path.parent, name).read_bytes() == data, 'Parallel compiled body changed: ' + name)
    check(contained(path.parent, 'immutable_oracle_raw.sv').read_bytes() == raw, 'Parallel full oracle raw bytes changed')
    commands = proof.get('commands', [])
    check(len(commands) == 2 and '--Mdir' in commands[0], 'Parallel actual commands missing')
    obj = commands[0][commands[0].index('--Mdir') + 1]
    check(re.fullmatch('/mnt/r/Verilator/BT/parallel-ddr-[0-9a-f]{32}/obj', obj), 'Parallel simulation isolation changed')
    expected = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(root), '--exec', '/usr/bin/verilator', '--binary', '--assert', '--timing',
                '-Wno-fatal', '-Wno-BLKANDNBLK', '-j', '2', '--threads', '1', '--top-module', 'ddram_cache_tb', '--Mdir', obj]
    expected += [wsl_path(path.parent / name) for name in files]
    check(commands == [expected, ['wsl.exe', '-d', 'Ubuntu', '--cd', str(root), '--exec', obj + '/Vddram_cache_tb']], 'Parallel complete/default controller command changed')
    for kind in ('compile', 'run'):
        check(type(proof.get(kind + '_exit_code')) is int and proof[kind + '_exit_code'] == 0 and
              proof[kind + '_log_sha256'] == sha(contained(path.parent, kind + '.log').read_bytes()), 'Parallel actual process/log failed')
    report = contained(path.parent, 'run.log').read_text()
    coverage = parse_read_coverage('ddram-cache', report)
    pattern = r'^PARALLEL_DDR_PASS acceptance=(\d+) hold=(\d+) reset_blocks=(\d+) priority_collisions=(\d+) state_checks=(\d+) io_cpu=(\d+) fill_patch=(\d+) owners=(\d+),(\d+),(\d+),(\d+) owner_masks=60$'
    matches = list(re.finditer(pattern, report, re.M))
    check(len(matches) == 1, 'Parallel default/activated PASS marker missing')
    names = ('acceptance', 'hold', 'reset_blocks', 'priority_collisions', 'state_checks', 'io_cpu', 'fill_patch', 'sprite', 'foreground0', 'foreground1', 'cpu')
    counts = dict(zip(names, map(int, matches[0].groups())))
    check(proof.get('parallel_coverage') == counts and proof.get('coverage') == coverage and proof.get('owner_mask_cases') == 60 and
          proof.get('source_order') == ['sprite', 'foreground0', 'foreground1', 'cpu'] and all(counts[name] > 0 for name in names), 'Parallel owner/cache/beat/default coverage incomplete')
    return {'edge_type': 'bt-parallel-ddr-controller-v1', 'receipt': PARALLEL_DDR_RECEIPT, 'receipt_sha256': sha(path.read_bytes()),
            'current_controller_sha256': sha(files['ddram.sv']), 'immutable_controller_sha256': sha(raw), 'coverage': counts}


def validate_read_suite(proof, path, root):
    check(proof.get('schema') == 'bt-current-read-storage-suite-v1' and proof.get('status') == 'PASS', 'Read suite incomplete')
    check(proof.get('oracle_commit') == REF and set(proof.get('jobs', {})) == set(SPECS), 'Wrong immutable parent/families')
    needed = {name for spec in SPECS.values() for name in spec['needed']}
    needed |= {'tests/graphics/qualify_current_read_storage.py', 'tests/graphics/verify_bt_current_qualification.py'}
    sources = source_map_verified(proof['sources'], root, needed)
    coverage = {}
    for family, spec in SPECS.items():
        job = proof['jobs'][family]
        check(job.get('family') == family and job.get('top') == spec['top'], 'Wrong fixture')
        check(all(type(job.get(key)) is int and job[key] == 0 for key in ('compile_exit_code', 'run_exit_code', 'exit_code')), 'Fixture process failed')
        check(job.get('testbench_passed') is True, 'Fixture did not pass')
        check(job.get('sources') == {name: sources[name] for name in spec['needed']}, 'Job source binding mismatch')
        inputs = job.get('compiled_inputs', [])
        expected = {(name, 'current') for name in spec['compile']}
        if spec.get('oracle_file'):
            expected.add((spec['oracle_file'], 'oracle'))
        check(len(inputs) == len(expected) and {(item['name'], item['role']) for item in inputs} == expected, 'Compiled input set changed')
        for item in inputs:
            raw = git_blob(item['name'], root) if item['role'] == 'oracle' else contained(root, item['name']).read_bytes()
            transform = spec.get('oracle_transform', 'identity') if item['role'] == 'oracle' else (
                spec.get('candidate_transform', 'identity') if item['name'] == spec.get('oracle_file') else
                spec.get('fixture_transform', 'identity') if item['name'] == spec['compile'][-1] else 'identity')
            check(item.get('transform') == transform and item.get('raw_sha256') == sha(raw), 'Raw input/transform changed')
            data = adapt_input(raw, transform)
            check(item.get('sha256') == sha(data) and contained(root, item['path']).read_bytes() == data, 'Compiled bytes changed')
        oracle = job.get('oracle')
        if spec.get('oracle_file'):
            raw = git_blob(spec['oracle_file'], root)
            check(oracle.get('kind') == 'immutable-git' and oracle.get('commit') == REF and oracle.get('file') == spec['oracle_file'], 'Oracle origin changed')
            check(oracle.get('raw_sha256') == sha(raw) and contained(root, oracle['raw_path']).read_bytes() == raw, 'Oracle is not the immutable blob')
            data = adapt_input(raw, spec['oracle_transform'])
            check(oracle.get('transform') == spec['oracle_transform'] and oracle.get('compiled_sha256') == sha(data) and contained(root, oracle['compiled_path']).read_bytes() == data, 'Oracle compiled adaptation changed')
            identity = raw.replace(b'\r\n', b'\n') == contained(root, spec['oracle_file']).read_bytes().replace(b'\r\n', b'\n')
            check(oracle.get('parent_body_identical_lf') is identity, 'Declared parent identity is false')
            if family in ('ddram-cache', 'sprite-read'):
                if family == 'ddram-cache' and not identity:
                    check(proof.get('ddr_controller_edge') == validate_parallel_ddr_edge(root), 'Exact typed controller edge missing')
                else:
                    check(identity, 'Parent controller body changed beyond this qualified identity edge')
        else:
            check(oracle is None, 'Unexpected oracle for standalone fixture')
        commands = job.get('commands', [])
        check(len(commands) == 2 and '--assert' in commands[0] and '--timing' in commands[0], 'Assertions not compiled')
        check('--top-module' in commands[0] and commands[0][commands[0].index('--top-module') + 1] == spec['top'], 'Wrong compiled top')
        check(not any('SYNTHESIS' in str(arg) for command in commands for arg in command), 'Simulation guards disabled')
        command = commands[0]
        check('--Mdir' in command, 'Missing isolated compilation directory')
        obj = command[command.index('--Mdir') + 1]
        check(re.fullmatch('/mnt/r/Verilator/BT/current-read-' + re.escape(family) + '-[0-9a-f]{32}/obj', obj), 'Unqualified simulation workspace')
        expected_command = ['wsl.exe', '-d', 'Ubuntu', '--cd', str(root), '--exec', '/usr/bin/verilator',
            '--binary', '--assert', '--timing', '-j', '2', '--threads', '1', '-Wno-fatal', '-Wno-BLKANDNBLK',
            '--top-module', spec['top'], '--Mdir', obj]
        if spec.get('unique_x'):
            expected_command += ['--x-initial', 'unique', '--x-assign', 'unique']
        expected_command += [wsl_path(root / item['path']) for item in inputs]
        check(command == expected_command and commands[1] == ['wsl.exe', '-d', 'Ubuntu', '--cd', str(root), '--exec', obj + '/V' + spec['top']], 'Command does not compile/run the exact retained inputs')
        log = path.parent / family / 'run.log'
        check(log.is_file(), 'Retained run log missing')
        source_map_verified(job.get('logs', {}), root)
        check(log.relative_to(root).as_posix() in job['logs'], 'Run log not hashed')
        counts = parse_read_coverage(family, log.read_text(errors='replace'))
        check(job.get('coverage') == counts, 'Coverage differs from actual PASS output')
        coverage[family] = counts
    return coverage


def current_read_suite_verified(receipt, root=ROOT):
    try:
        validate_read_suite(json.loads(Path(receipt).read_text()), Path(receipt).resolve(), Path(root).resolve())
        return True
    except (QualificationError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def retained_read_checker(proof, path, root, provenance=None):
    """Preserve the exact executed read checker through a helper-only edge.

No RTL/source/fixture exception is allowed. Only the validator's recorded old
source path resolves to its immutable retained raw bytes, after proving every
read/DDR function and its constants remain identical in this additive update.
"""
    helper = 'tests/graphics/verify_bt_current_qualification.py'
    check(proof['sources'].get(helper) == RETAINED_READ_VALIDATOR_SHA, 'Unknown executed read validator')
    metadata_path = path.parent / 'helper_provenance.json'
    metadata = json.loads(metadata_path.read_text()) if provenance is None else provenance
    check(metadata.get('schema') == 'bt-executed-helper-retention-v1' and metadata.get('status') == 'PASS' and
          contained(root, metadata['receipt']) == path and metadata['receipt_sha256'] == sha(path.read_bytes()), 'Read helper retention belongs to another proof')
    validation_path = contained(root, metadata['validation'])
    check(metadata['validation_sha256'] == sha(validation_path.read_bytes()) and json.loads(validation_path.read_text()).get('status') == 'PASS', 'Decisive executed read validation changed')
    record = metadata['helpers'][helper]
    retained_path = contained(root, record['retained_path'])
    raw = retained_path.read_bytes()
    check(record['executed_sha256'] == record['retained_sha256'] == sha(raw) == RETAINED_READ_VALIDATOR_SHA, 'Executed validator raw bytes changed')
    current = contained(root, helper).read_bytes()
    before, after = raw.decode(), current.decode()
    functions = ('check', 'sha', 'wsl_path', 'git_blob', 'contained', 'adapt_input', 'parse_read_coverage',
                 'source_map_verified', 'validate_parallel_ddr_edge', 'validate_read_suite',
                 'current_read_suite_verified', 'read_negative_controls', 'parallel_ddr_negative_controls')
    before_tree, after_tree = ast.parse(before), ast.parse(after)
    function_hashes = {}
    for name in functions:
        old = [node for node in before_tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
        new = [node for node in after_tree.body if isinstance(node, ast.FunctionDef) and node.name == name]
        check(len(old) == len(new) == 1 and ast.get_source_segment(before, old[0]) == ast.get_source_segment(after, new[0]), 'Read/DDR checker body changed: ' + name)
        function_hashes[name] = sha(ast.get_source_segment(before, old[0]).encode())
    for name in ('REF', 'GIT', 'RAM', 'SPECS', 'PARALLEL_DDR_RECEIPT'):
        get = lambda tree: [ast.dump(node.value) for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)]
        check(get(before_tree) == get(after_tree) and len(get(before_tree)) == 1, 'Read/DDR checker constant changed: ' + name)
    checker = types.ModuleType('retained_bt_read_checker')
    checker.__file__ = str(retained_path)
    exec(compile(before, str(retained_path), 'exec'), checker.__dict__)
    original_contained = checker.contained
    checker.contained = lambda selected_root, name: retained_path if Path(selected_root).resolve() == root and name == helper else original_contained(selected_root, name)
    edge = {'edge_type': 'bt-read-validator-helper-preservation-v1', 'executed_sha256': sha(raw),
            'retained_path': str(retained_path), 'current_validator_sha256': sha(current),
            'provenance_path': str(metadata_path), 'provenance_sha256': sha(metadata_path.read_bytes()),
            'unchanged_read_function_sha256': function_hashes,
            'scope': 'Only exact executed validator source identity is retained; all compiled RTL/fixtures/logs/oracles/current source checks stay mandatory.'}
    return checker, edge


def validate_current_read_suite(proof, path, root):
    helper = 'tests/graphics/verify_bt_current_qualification.py'
    if proof['sources'].get(helper) == sha(contained(root, helper).read_bytes()):
        return validate_read_suite(proof, path, root), None
    checker, edge = retained_read_checker(proof, path, root)
    try:
        coverage = checker.validate_read_suite(proof, path, root)
    except checker.QualificationError as error:
        raise QualificationError(str(error)) from error
    return coverage, edge


def stage(text):
    first, last = '\t// BEGIN MC_MEM_RETURN_STAGE:', '\t// END MC_MEM_RETURN_STAGE'
    check(text.count(first) == text.count(last) == 1, 'Current stage markers changed')
    a = text.index(first)
    return text[a:text.index(last, a) + len(last)]


def port_map(module, text):
    matches = list(re.finditer(r'\b' + re.escape(module) + r'\s+\w+\s*\((.*?)\);', text, re.S))
    check(len(matches) == 1, 'Board instance ambiguous: ' + module)
    return {port: value.strip() for port, value in re.findall(r'\.(\w+)\s*\(\s*([^()]*)\)', matches[0].group(1))}


def keyed_marker(report, name):
    matches = list(re.finditer(r'^' + re.escape(name) + r' (.+)$', report, re.M))
    check(len(matches) == 1, 'Missing/ambiguous PASS coverage: ' + name)
    values = re.findall(r'(\w+)=(\d+)', matches[0].group(1))
    check(values and len({key for key, _ in values}) == len(values), 'Malformed coverage marker')
    return {key: int(value) for key, value in values}


def parse_stage_coverage(report):
    coverage = keyed_marker(report, 'PASS selector bridge')
    coverage.update({'mc_' + key: value for key, value in keyed_marker(report, 'MC_WORD_PROOF').items()})
    coverage.update({'queued_draw_' + key: value for key, value in keyed_marker(report, 'MC_DRAW_HANDOFF').items()})
    for name in ('SCALAR_WRITE_MIRROR', 'DDR_SPLIT_PROOF', 'CACHE_ORACLE'):
        coverage.update(keyed_marker(report, name))
    cache = keyed_marker(report, 'CACHE_WORD_STAGE')
    coverage.update({'cache_' + key: value for key, value in cache.items()})
    collision = keyed_marker(report, 'QA_COLLISION_EXCLUSION')
    coverage.update({'qa_' + key.replace('_checks', '_collision_checks'): value for key, value in collision.items()})
    coverage['nvram_late_updates'] = keyed_marker(report, 'NVRAM_LATE')['updates']
    for marker, key, count in (('SELECTOR_COUNTS', 'selector_counts', 8), ('FG_COUNTS', 'fg_bank_counts', 8), ('BG_COUNTS', 'bg_page_counts', 2)):
        matches = list(re.finditer(r'^' + marker + r' ([0-9,]+)$', report, re.M))
        check(len(matches) == 1, 'Missing owner-array coverage')
        values = list(map(int, matches[0].group(1).split(',')))
        check(len(values) == count and min(values) > 0, 'Unreached owner/bank')
        coverage[key] = values
    return coverage


def stage_input_path(root, source_root, name):
    if name.startswith('rtl/') or name == 'Arcade-Battletoads.sv':
        candidate = (source_root / name).resolve()
        if candidate.is_file():
            check(candidate.is_relative_to(root), 'Production source overlay leaves this workspace')
            return candidate
    return contained(root, name)


def stage_source_map_verified(sources, root, source_root, needed):
    check(isinstance(sources, dict) and bool(sources), 'Stage sources must be explicit')
    normalized = {name.replace('\\', '/'): digest for name, digest in sources.items()}
    check(len(normalized) == len(sources) and set(needed) <= normalized.keys(), 'Stage source list incomplete/ambiguous')
    for name, digest in normalized.items():
        check(isinstance(digest, str) and re.fullmatch('[0-9a-f]{64}', digest) and
              sha(stage_input_path(root, source_root, name).read_bytes()) == digest, 'Stage input changed: ' + name)
    return normalized


def validate_class_extension(adapter, root, source_root, current_mc, original_mc):
    from bt_address_class_fixture import verify_edge, decoder_checks, augment as class_augment
    from bt_combined_stage_fixture import augment as combined_augment
    check(adapter.get('address_class_sideband') is True, 'Address-class flag lost')
    source_map_verified(TYPED_STAGE_HELPERS, root)
    candidate_read = lambda name: stage_input_path(root, source_root, name).read_bytes()
    request = b'VRAM_REQUEST' in current_mc
    request_edge, request_scope, request_oracle_name = None, None, None
    edge_read, edge_root = candidate_read, source_root
    if request:
        from bt_vram_request_fixture import verify_edge as request_verify_edge, augment as request_augment
        from prepare_bt_vram_request import BASE_ROOT as request_parent_root, BASE as request_parent_hashes
        source_map_verified(REQUEST_STAGE_HELPERS, root)
        edge_read, request_edge = request_verify_edge(root, source_root, candidate_read)
        edge_root = request_parent_root
        check(adapter.get('vram_request_edge') == request_edge, 'Typed exact full-v11 request inverse/projection order changed')
        retained = adapter.get('retained_strict_runner', {})
        check(Path(retained.get('path', '')).resolve() == contained(root, 'tests/graphics/qualify_bt_current_ddr_be.py') and
              retained.get('sha256') == TYPED_STAGE_RUNNER_SHA == sha(contained(root, 'tests/graphics/qualify_bt_current_ddr_be.py').read_bytes()), 'Retained strict runner body changed')
        oracle = adapter.get('vram_request_full_v11_oracle', {})
        before = edge_read('rtl/TMS34020/TMS34020_MC.sv')
        expected = before.replace(b'module TMS34020_MC', b'module TMS34020_MC_V11_REQUEST_ORACLE', 1)
        check(before.count(b'module TMS34020_MC') == 1 and oracle.get('immutable_v11_sha256') == request_parent_hashes['rtl/TMS34020/TMS34020_MC.sv'] == sha(before) and
              oracle.get('sha256') == sha(expected) and contained(root, oracle['path']).read_bytes() == expected and
              oracle.get('transform') == 'Complete v11 MC; module rename only; all original assertions enabled.', 'Complete immutable v11 oracle body/assertions changed')
        request_oracle_name = contained(root, oracle['path']).relative_to(root).as_posix()
    else:
        check(not adapter.get('vram_request_edge') and not adapter.get('vram_request_scope') and
              not adapter.get('vram_request_full_v11_oracle'), 'Unexpected request proof in earlier stage')
    try:
        edge, old_bt, current_bt = verify_edge(root, edge_read, original_mc, edge_root)
    except AssertionError as error:
        raise QualificationError('Undeclared production composition: ' + str(error)) from error
    check(adapter.get('address_class_v9_edge') == edge, 'Exact typed reversible edge changed')
    mc_text = current_mc.decode().replace('\r\n', '\n')
    decoder_text, decoder_scope = decoder_checks(old_bt, current_bt, mc_text)
    check(adapter.get('address_class_decoder_scope') == decoder_scope, 'Actual source decoder scope changed')
    typed_transforms = []
    recorder = lambda before, after: typed_transforms.append([before, after])
    check(class_augment(recorder, mc_text, old_bt, current_bt) == decoder_scope, 'Address decoder generator scope changed')
    combined = edge['edge_type'] == 'bt-class-parallel-ddr-v1'
    if request:
        check(combined, 'Request edge must retain activated complete class/DDR parent')
        seed = contained(root, adapter['legacy_fixture']).read_text()
        marker = ' output [3:0] ADDR_CLASS\n'
        stopped = False
        for transform in adapter['transforms']:
            before, after = transform[:2]
            if before == marker:
                stopped = True
                break
            count = transform[2] if len(transform) == 3 else 1
            check(seed.count(before) == count, 'Request pre-adapter fixture reconstruction changed')
            seed = seed.replace(before, after, count)
        check(stopped, 'Actual request port insertion missing')
        request_scope = request_augment(recorder, seed, mc_text, edge_read('rtl/BT.sv').decode(), candidate_read('rtl/BT.sv').decode())
        request_scope = json.loads(json.dumps(request_scope))
        check(adapter.get('vram_request_scope') == request_scope and len(request_scope['old_mc_state_names']) == 49 and
              len(request_scope['old_mc_outputs']) == 15 and request_scope['new_bus_or_request_force_statements'] == [] and
              request_scope['all_original_stage_assertions_retained'] is True and request_scope['defined_undefined_ram_masks_changed'] is False,
              'Complete old-state/output/request/RAS/undefined RAM scope changed')
    extra_pairs = ()
    if combined:
        oracle = adapter.get('combined_ddr_oracle', {})
        raw = git_blob('rtl/ddram.sv', root)
        expected = raw.replace(b'module ddram', b'module ddram_full_immutable_oracle', 1)
        check(raw.count(b'module ddram') == 1 and oracle.get('git_commit') == REF and oracle.get('git_file') == 'rtl/ddram.sv' and
              oracle.get('git_raw_sha256') == sha(raw) and oracle.get('sha256') == sha(expected) and
              contained(root, oracle['path']).read_bytes() == expected, 'Full immutable DDR oracle must retain every assertion')
        top = candidate_read('Arcade-Battletoads.sv').decode()
        scope = combined_augment(recorder, top)
        check(adapter.get('combined_ddr_scope') == scope, 'Actual activated BT/DDR bank/source/clock binding changed')
        extra_pairs = (oracle['path'], 'rtl/ddram.sv')
    else:
        check(not adapter.get('combined_ddr_scope') and not adapter.get('combined_ddr_oracle'), 'Unexpected parallel DDR claims')
    # Every additive source-bound transformation must be present in the exact
    # reviewed generator's ordered transformation list; old fixture reversal
    # and compiled-input checks below remain mandatory.
    positions = iter(adapter['transforms'])
    for wanted in typed_transforms:
        check(any(actual == wanted for actual in positions), 'Required additive source-bound fixture transformation missing')
    scope = {'edge_type': edge['edge_type'], 'source_root': str(source_root), 'reversible_edge': edge, 'decoder_scope': decoder_scope}
    if request:
        scope['request_projection'] = {'edge_type': 'bt-v11-vram-request-v1', 'reversible_edge': request_edge,
                                       'scope': request_scope, 'oracle_name': request_oracle_name}
    return combined, extra_pairs, scope


def validate_current_stage(proof, path, root, source_root=None):
    source_root = root if source_root is None else Path(source_root).resolve()
    check(source_root.is_relative_to(root), 'Stage overlay must be an explicit workspace snapshot')
    production_path = lambda name: stage_input_path(root, source_root, name)
    selected_source_root = source_root
    request = b'VRAM_REQUEST' in production_path('rtl/TMS34020/TMS34020_MC.sv').read_bytes()
    source_identity = {}
    if request:
        executed = Path(proof.get('current_stage_adapter', {}).get('production_source_overlay', '')).resolve()
        check(executed.is_relative_to(root), 'Request executed overlay leaves workspace')
        # A separate typed identity edge binds this actual executed proof to a
        # full selected snapshot. No receipt/command/source path is retagged.
        for name, digest in proof.get('sources', {}).items():
            if name.startswith('rtl/') or name == 'Arcade-Battletoads.sv':
                actual, selected = stage_input_path(root, executed, name), production_path(name)
                check(sha(actual.read_bytes()) == sha(selected.read_bytes()) == digest, 'Foreign final request snapshot source: ' + name)
                source_identity[name] = {'executed_path': str(actual), 'selected_path': str(selected), 'sha256': digest}
        check({'rtl/BT.sv', 'rtl/TMS34020/TMS34020_MC.sv', 'rtl/TMS34020/TMS34020.sv'} <= source_identity.keys(), 'Request final input identity incomplete')
        source_root = executed
        production_path = lambda name: stage_input_path(root, source_root, name)
    check(all(type(proof.get(key)) is int and proof[key] == 0 for key in ('compile_exit_code', 'run_exit_code', 'exit_code')), 'Consuming-stage process failed')
    flags = ('testbench_passed', 'selector_capture_equivalence_passed', 'cache_word_stage_checked_passed',
             'mc_word_equivalence_passed', 'ddr_split_equivalence_passed', 'scalar_write_mirror_equivalence_passed',
             'postmux_owner_equivalence_passed', 'qa_collision_exclusion_passed', 'cache_placement_and_contents_passed')
    check(all(proof.get(flag) is True for flag in flags), 'Required preserved stage check failed')
    adapter = proof.get('current_stage_adapter', {})
    check(adapter.get('schema') == 'bt-current-ddr-be-stage-adapter-v2', 'Wrong current-stage schema')
    check(adapter.get('phase_mode') in ('production', 'alternating'), 'Unknown phase profile')
    current_mc_bytes = production_path('rtl/TMS34020/TMS34020_MC.sv').read_bytes()
    typed = b'DBUS_ADDR_CLASS' in current_mc_bytes
    expected_runner = REQUEST_STAGE_HELPERS[REQUEST_STAGE_RUNNER] if request else (TYPED_STAGE_RUNNER_SHA if typed else CURRENT_STAGE_RUNNER_SHA)
    expected_runner_path = REQUEST_STAGE_RUNNER if request else 'tests/graphics/qualify_bt_current_ddr_be.py'
    check(adapter.get('runner') == expected_runner_path and adapter.get('runner_sha256') == expected_runner, 'Unreviewed current-stage generator')
    check(Path(adapter['production_source_overlay']).resolve() == source_root, 'Declared production snapshot differs from selected input')
    needed = {'rtl/BT.sv', 'rtl/TMS34020/TMS34020.sv', 'rtl/TMS34020/TMS34020_MC.sv',
              'rtl/TMS34020/TMS34020_CACHE.sv', 'rtl/TMS34020/TMS34020_pkg.sv', 'rtl/TMS34020_mem.sv',
              'rtl/BT_mem.sv', 'rtl/bg_vram.sv', 'rtl/fg_vram.sv', 'rtl/spr_vram.sv', 'rtl/sprite_blitter.sv',
              RAM, 'rtl/ddram.sv', 'Arcade-Battletoads.sv', 'rtl/bt_pause_bridge.sv',
              'rtl/bt_clock_enables.sv', adapter['runner'], adapter['legacy_runner'], adapter['legacy_fixture'], adapter['legacy_stage'], adapter['stage'], adapter['fixture']}
    sources = stage_source_map_verified(proof['sources'], root, source_root, needed)
    check(sources[adapter['runner']] == expected_runner, 'Current runner changed')
    for prefix in ('legacy_runner', 'legacy_fixture', 'legacy_stage', 'stage', 'fixture'):
        check(adapter[prefix + '_sha256'] == sources[adapter[prefix]], 'Adapter input hash mismatch')
    check(all(adapter.get(key) is True for key in ('exact_full_cpu_stage_copied', 'original_assertions_preserved',
          'original_commands_and_minimum_pause_durations_preserved', 'old_capture_block_unchanged_except_early_return_wire')), 'Original checks/stimuli preservation not established')
    cpu = production_path('rtl/TMS34020/TMS34020.sv').read_bytes()
    check(adapter['cpu_sha256'] == sources['rtl/TMS34020/TMS34020.sv'] == sha(cpu), 'Full current CPU not bound')
    current_stage = stage(cpu.decode())
    check(contained(root, adapter['stage']).read_bytes() == current_stage.encode(), 'Copied stage is not the complete actual CPU stage')
    fixture = contained(root, adapter['fixture']).read_bytes().decode()
    check(stage(fixture) == current_stage and sha(fixture.encode()) == adapter['fixture_sha256'], 'Compiled fixture stage changed')
    restored = fixture
    transforms = adapter.get('transforms')
    check(isinstance(transforms, list) and bool(transforms), 'Declared reversible fixture transformations missing')
    for transform in reversed(transforms):
        check(isinstance(transform, list) and len(transform) in (2, 3), 'Unknown transformation schema')
        before, after = transform[:2]
        count = transform[2] if len(transform) == 3 else 1
        check(isinstance(before, str) and isinstance(after, str) and type(count) is int and count > 0 and restored.count(after) == count, 'Transformation cannot be reversed uniquely')
        restored = restored.replace(after, before, count)
    check(restored == contained(root, adapter['legacy_fixture']).read_text(), 'Undeclared original fixture change')

    top = production_path('Arcade-Battletoads.sv').read_bytes().decode()
    pause, clocks, bt, nvram = (port_map(module, top) for module in ('bt_pause_bridge', 'bt_clock_enables', 'BT', 'bt_nvram'))
    check(adapter['actual_top_pause_ports'] == pause and adapter['actual_top_clock_ports'] == clocks and
          adapter['actual_top_bt_phase_ports'] == {key: bt[key] for key in ('CE_F', 'CE_R')} and
          adapter['actual_top_nvram_pause_ports'] == nvram, 'Actual board bindings changed')
    check(pause['pause_req'] == 'pause_cpu' and pause['clk'] == clocks['clk'] and pause['reset'] == clocks['reset'] and
          pause['raw_ce_f'] == clocks['ce_f'] and pause['raw_ce_r'] == clocks['ce_r'] and
          pause['ce_f'] == bt['CE_F'] and pause['ce_r'] == bt['CE_R'] and
          pause['halted'] == nvram['cpu_halted'] == 'cpu_pause_halted' and
          re.sub(r'\s+', '', nvram['cpu_we']) == 'BT_NVRAM_WE&&CE_R_CPU', 'Pause or final-write ownership not proved')
    check(adapter['board_pause_source_sha256'] == sources['rtl/bt_pause_bridge.sv'], 'Actual pause RTL not bound')

    check(adapter['immutable_original_mc_git_commit'] == REF, 'MC oracle commit changed')
    original = git_blob('rtl/TMS34020/TMS34020_MC.sv', root)
    raw_path = 'tests/fixtures/tms34020_mc_en0_oracle.sv'
    raw = contained(root, raw_path).read_bytes()
    check(raw.replace(b'\r\n', b'\n') == original.replace(b'\r\n', b'\n'), 'Original full MC is not immutable b537')
    check(adapter['immutable_original_mc_git_blob_raw_sha256'] == sha(original) and
          adapter['immutable_original_full_mc_sha256'] == sha(raw) and
          adapter['immutable_original_full_mc_canonical_lf_sha256'] == sha(raw.replace(b'\r\n', b'\n')), 'MC oracle provenance changed')
    oracle = adapter['immutable_final_oracle']
    expected_oracle = b'`define SYNTHESIS\n' + raw.replace(b'module TMS34020_MC', b'module TMS34020_MC_FINAL_ORACLE', 1) + b'\n`undef SYNTHESIS\n'
    check(raw.count(b'module TMS34020_MC') == 1 and contained(root, oracle['path']).read_bytes() == expected_oracle and
          oracle['sha256'] == sha(expected_oracle), 'Only the documented full-oracle rename/guard is allowed')
    mc = current_mc_bytes
    check(adapter['current_full_mc_sha256'] == sha(mc) and adapter['current_full_mc_canonical_lf_sha256'] == sha(mc.replace(b'\r\n', b'\n')), 'Actual complete MC not bound')
    combined, extra_pairs, extended = False, (), {}
    if typed:
        combined, extra_pairs, extended = validate_class_extension(adapter, root, source_root, mc, raw)
    else:
        check(not adapter.get('address_class_sideband') and not adapter.get('address_class_v9_edge') and
              not adapter.get('combined_ddr_scope') and not adapter.get('combined_ddr_oracle'), 'Unexpected typed scope in legacy fixture')
    # The exact MC change has its separate immutable full-MC proof. This fixture
    # must compile every byte of the actual candidate, except declaration scope.
    prefix = path.parent.relative_to(root).as_posix() + '/compiled_inputs/'
    compiled = {name[len(prefix):]: name for name in sources if name.startswith(prefix)}
    request_oracle_name = extended.get('request_projection', {}).get('oracle_name')
    pairs = ('rtl/TMS34020/TMS34020_pkg.sv', oracle['path']) + ((request_oracle_name,) if request else ()) + ('rtl/TMS34020/TMS34020_MC.sv',
             'rtl/TMS34020/TMS34020_CACHE.sv', 'rtl/TMS34020_mem.sv', 'rtl/bg_vram.sv', 'rtl/fg_vram.sv',
             'rtl/spr_vram.sv', 'rtl/sprite_blitter.sv', RAM, adapter['fixture']) + extra_pairs + ('rtl/BT.sv',
             'rtl/bt_clock_enables.sv', 'rtl/bt_pause_bridge.sv', adapter['legacy_runner'])
    check(set(compiled) == set(pairs) and len(compiled) == (17 if combined else 15) + int(request), 'Exact complete compiled input set is missing')
    for name in pairs:
        expected = production_path(name).read_bytes()
        if request and name in ('rtl/TMS34020/TMS34020_MC.sv', request_oracle_name):
            text = expected.decode()
            markers = ['\t\tbit         SCRREF_PEND;', '\t\tbit         READ_LATCH;', '\t\tbit         WRITE_LATCH;', '\t\tbit [ 1: 0] FETCH_LSB;']
            event = '\talways @(posedge CLK or negedge RST_N) begin'
            for marker in markers:
                check(text.count(marker) == 1, 'Exact original persistent-state declaration changed')
                text = text.replace(marker, '', 1)
            check(text.count(event) == 1, 'MC clock event visibility changed')
            expected = text.replace(event, ''.join('\t' + marker.strip() + '\n' for marker in markers) + event, 1).encode()
        elif name == 'rtl/TMS34020/TMS34020_MC.sv':
            text = expected.decode()
            marker, event = '\t\tbit         READ_LATCH;', '\talways @(posedge CLK or negedge RST_N) begin'
            check(text.count(marker) == 1, 'MC declaration adapter changed')
            expected = text.replace(marker, '', 1).replace(event, '\tbit READ_LATCH;\n' + event, 1).encode()
        check(contained(root, compiled[name]).read_bytes() == expected, 'Compiled production/oracle body changed: ' + name)
    bound = proof.get('bound_production_inputs', {})
    # NVRAM is bound by the actual board-port contract and its own controller
    # proof; this consuming-stage fixture models its Q, rather than compiling
    # the controller. Require the explicit raw input binding without falsely
    # labelling it a compiled input.
    check(set(pairs) | {'rtl/TMS34020/TMS34020.sv', 'Arcade-Battletoads.sv', 'rtl/bt_nvram.sv', raw_path} <= bound.keys(), 'Overlay bindings incomplete')
    for name, record in bound.items():
        check(record['sha256'] == sha(production_path(name).read_bytes()) and
              Path(record['path']).resolve() == production_path(name).resolve() and sha(Path(record['path']).read_bytes()) == record['sha256'], 'Overlay input changed')
    command = list(map(str, proof.get('command', [])))
    check('--assert' in command and any(arg.startswith('-DMISTER_CPU_PHASE_CHECK') for arg in command) and
          not any(arg.startswith('-D') and 'SYNTHESIS' in arg for arg in command), 'Actual candidate assertions disabled')
    snapshot = Path(proof['snapshot'])
    expected_command = ['D:/vibes/fpga/bin/verilator.exe', '--binary', '--assert', '--timing',
        '-j', '4', '--threads', '1', '--x-initial', 'unique', '--x-assign', 'unique',
        '-DSIM', '-DMISTER_CPU_PHASE_CHECK', '--top-module', 'ddr_be_bridge_tb', '--Mdir', str(snapshot / 'obj'),
        '-MAKEFLAGS', 'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
        '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17', '-LDFLAGS', '-static-libstdc++ -static-libgcc', '-Wno-fatal']
    expected_command += [str(snapshot / 'src' / name) for name in pairs if not name.endswith('.py')]
    check(command == expected_command and proof.get('run_command') == [str(snapshot / 'obj/Vddr_be_bridge_tb.exe')], 'Actual complete stage compile/run command changed')
    report = (path.parent / 'run.log').read_text(errors='replace')
    coverage = parse_stage_coverage(report)
    check(coverage == proof.get('coverage'), 'Coverage differs from retained simulator output')
    positive = ('captures', 'cache', 'en0', 'palette_late', 'extended', 'rmw', 'pause_live', 'pause_ack',
                'pause_resume_f', 'pause_resume_r', 'scan', 'screens', 'draw_overlap', 'draw_mem', 'draw_ddr',
                'draw_handoff', 'partner', 'copy_busy', 'copy_handoff', 'address_checks', 'read_checks',
                'en0_before_ready', 'prepared_resume_r', 'mc_ddr_reads', 'mc_full_reads', 'mc_byte_reads',
                'mc_ram_reads', 'cache_ddr_writes', 'cache_full_writes', 'cache_byte_writes', 'cache_ram_writes',
                'postmux_fg_owner_checks', 'postmux_bg_owner_checks', 'qa_fg_collision_checks', 'qa_bg_collision_checks',
                'cache_nvram_writes', 'nvram_late_updates')
    check(all(type(coverage.get(key)) is int and coverage[key] > 0 for key in positive), 'Required preserved owner/collision/phase case absent')
    minima = {'mc_cycle_checks': 88000, 'mc_read_checks': 5900, 'mc_ext_reads': 1900, 'mc_write_checks': 11900,
              'mc_held_reads': 5900, 'mc_late_reads': 2, 'mc_field_cases': 2048, 'mc_read_en0': 2, 'mc_io_late': 2,
              'queued_draw_reads': 2, 'queued_draw_sameword_writes': 4, 'queued_draw_busy_cycles': 2, 'queued_draw_handoffs': 2}
    check(all(coverage.get(key, 0) >= minimum for key, minimum in minima.items()), 'Original required MC coverage reduced')
    check(coverage['address_checks'] == coverage['cache'] and coverage['read_checks'] >= 60 and
          coverage['cache_mem_writes'] + coverage['cache_late_writes'] == coverage['cache'] and
          coverage['mc_held_reads'] + coverage['mc_late_reads'] == coverage['mc_read_checks'] and
          coverage['mc_ddr_reads'] == coverage['mc_full_reads'] + coverage['mc_byte_reads'] and
          coverage['mc_held_reads'] == coverage['mc_ddr_reads'] + coverage['mc_ram_reads'] and
          coverage['cache_ddr_writes'] == coverage['cache_full_writes'] + coverage['cache_byte_writes'] and
          coverage['cache_mem_writes'] == coverage['cache_ddr_writes'] + coverage['cache_ram_writes'] and
          coverage['scalar_mirror_checks'] == coverage['mc_cycle_checks'] and
          coverage['scalar_write_checks'] == coverage['mc_write_checks'], 'Coverage accounting mismatch')
    for marker, key in (('EARLY_CPU_STAGE', 'early_stage_coverage'), ('EARLY_PALETTE', 'palette_early_coverage'),
                        ('EARLY_PHASE', 'phase_coverage'), ('BOARD_PAUSE', 'board_pause_coverage'),
                        ('ORIGINAL_MC_FINAL', 'original_final_coverage'), ('NATIVE64_MC', 'native64_coverage')):
        counts = proof.get(key)
        check(isinstance(counts, dict) and all(type(value) is int for value in counts.values()) and
              keyed_marker(report, marker) == counts, 'Current-stage counters changed or untyped: ' + marker)
    early, pal, phase, pause = (proof[key] for key in ('early_stage_coverage', 'palette_early_coverage', 'phase_coverage', 'board_pause_coverage'))
    final, native = proof['original_final_coverage'], proof['native64_coverage']
    check(all(early.get(key, 0) > 0 for key in ('checks', 'memory', 'live_late', 'io', 'io_next_changes')) and
          all(pal.get(key, 0) > 0 for key in ('checks', 'changes', 'byte0', 'byte1', 'byte2')), 'Early late-owner/IO/palette coverage absent')
    check(phase['real'] == (1 if adapter['phase_mode'] == 'production' else 0) and
          all(phase.get(key, 0) > 0 for key in ('F', 'R', 'captures_R', 'captures_idle')) and
          (adapter['phase_mode'] != 'production' or phase.get('idle', 0) > 0), 'Actual phase profile not exercised')
    check(pause.get('halt_ack', 0) >= 3 and pause['halt_ack'] == pause['resumed_F'] == pause['resumed_R'] and
          all(pause.get(key, 0) > 0 for key in ('halt_SYS', 'halted_MEM', 'live_halted_MEM', 'request_release_F', 'request_release_R')), 'Live F-first pause/resume proof incomplete')
    check(final['checks'] == coverage['mc_cycle_checks'] and final.get('EN0_checks', 0) > 0 and
          native.get('read_cases') == 4096 and native.get('EN0_cases') == 1024 and
          native.get('EN0_snapshot_loads', 0) > 0 and native.get('EN0_nonconsumer_R_differences', 0) > 0, 'Immutable final-F/full-field/EN0 scope missing')
    if typed:
        for marker, key in (('ADDRESS_CLASS', 'address_class_coverage'), ('ADDRESS_DECODER', 'address_decoder_coverage')):
            counts = proof.get(key)
            check(isinstance(counts, dict) and all(type(value) is int for value in counts.values()) and
                  keyed_marker(report, marker) == counts, 'Typed counters absent or changed: ' + marker)
        addr, decoder = proof['address_class_coverage'], proof['address_decoder_coverage']
        check(addr.get('checks') == final['checks'] + 1 and addr.get('EN0') == final['EN0_checks'] and
              all(addr.get(key, 0) > 0 for key in ('holds', 'read', 'write', 'cache', 'refresh', 'read_ext', 'write_ext')), 'Address hint edge/hold/launch coverage missing')
        check(decoder == {'cases': 65536, 'pixel_skips': 16, 'EN0_holds': 96, 'idle_holds': 64, 'async_resets': 16,
                          'oracle_edges': decoder.get('oracle_edges')} and decoder['oracle_edges'] > final['checks'], 'Exhaustive decoder/reset/skip coverage reduced')
        extended.update(address_class=addr, address_decoder=decoder)
    if combined:
        counts = proof.get('combined_ddr_coverage')
        check(isinstance(counts, dict) and all(type(value) is int for value in counts.values()) and
              keyed_marker(report, 'COMBINED_DDR') == counts, 'Complete-controller counters changed/untyped')
        keys = {'acceptance', 'holds', 'reset_edges', 'pre_views', 'post_views', 'ddr_beats', 'cache_words', 'sprite', 'foreground0', 'foreground1', 'cpu'}
        check(set(counts) == keys and all(counts[key] > 0 for key in keys) and
              all(counts[key] > 100 for key in ('holds', 'pre_views', 'post_views')) and counts['cache_words'] > 1000 and
              counts['acceptance'] == sum(counts[key] for key in ('sprite', 'foreground0', 'foreground1', 'cpu')), 'Actual all-owner accepted/held/cache/beat scope incomplete')
        extended['combined_ddr'] = counts
    if request:
        counts, probe = proof.get('vram_request_coverage'), proof.get('vram_request_probe_coverage')
        for marker, values in [('VRAM_REQUEST', counts), ('VRAM_REQUEST_PROBE', probe)]:
            check(isinstance(values, dict) and all(type(value) is int for value in values.values()) and keyed_marker(report, marker) == values,
                  'Actual request counters absent/changed/untyped: ' + marker)
        check(set(counts) == {'pre', 'post', 'reset', 'EN0', 'F', 'R', 'idle', 'before_state', 'MEM_pre', 'MEM_post', 'page_changes'} and
              counts['pre'] == final['checks'] + 1 and counts['post'] == final['checks'] and counts['before_state'] == counts['post'] + counts['reset'] and
              counts['EN0'] == final['EN0_checks'] and all(counts[key] > 100 for key in ('EN0', 'F', 'R', 'idle')) and
              counts['MEM_pre'] == counts['MEM_post'] and counts['MEM_pre'] > final['checks'] and counts['page_changes'] >= 2,
              'Complete SYS/MEM request, original state, EN0 or live-page coverage reduced')
        check(probe == {'edges': counts['before_state'], 'launches': 32, 'overlaps': 32, 'reset_held_ras': 32, 'EN0': 160, 'transparent': 5},
              'Directed actual MC overlap/held-RAS reset/EN0/transparent launch coverage reduced')
        extended['request_coverage'], extended['request_probe_coverage'] = counts, probe
        extended['selected_input_identity_edge'] = {'edge_type': 'bt-stage-executed-to-selected-input-identity-v1',
            'executed_source_root': str(source_root), 'selected_source_root': str(selected_source_root), 'inputs': source_identity,
            'scope': 'Exact raw bytes of every production input in this complete-stage proof; full144/timing/native/hardware gates remain separate.'}
    return {'phase': adapter['phase_mode'], 'mc_cycles': final['checks'], 'native64': native, 'palette': pal, 'pause': pause,
            'typed_scope': extended}


def current_consuming_stage_verified(receipt, root=ROOT, source_root=None):
    try:
        validate_current_stage(json.loads(Path(receipt).read_text()), Path(receipt).resolve(), Path(root).resolve(), source_root)
        return True
    except (QualificationError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return False


def stage_negative_controls(proof, path, root, source_root=None):
    mutations = []
    def variant(label, edit):
        candidate = copy.deepcopy(proof)
        edit(candidate)
        mutations.append((label, candidate))
    variant('missing full CPU source', lambda p: p['sources'].pop('rtl/TMS34020/TMS34020.sv'))
    variant('false assertion preservation', lambda p: p['current_stage_adapter'].update(original_assertions_preserved=False))
    variant('wrong immutable oracle', lambda p: p['current_stage_adapter'].update(immutable_original_mc_git_commit='8f048ee518f3062506e80d5f5a64585450d062f5'))
    variant('wrong stage hash', lambda p: p['current_stage_adapter'].update(stage_sha256='0' * 64))
    variant('missing actual compiled bridge', lambda p: p['sources'].pop(next(k for k in p['sources'] if '/compiled_inputs/' in k and k.endswith('/rtl/bt_pause_bridge.sv'))))
    variant('missing uncompiled NVRAM binding', lambda p: p['bound_production_inputs'].pop('rtl/bt_nvram.sv'))
    variant('failed run', lambda p: p.update(run_exit_code=1))
    variant('lost BE coverage', lambda p: p['coverage'].update(mc_byte_reads=0))
    variant('lost palette cases', lambda p: p['palette_early_coverage'].update(byte2=0))
    variant('lost EN0 cases', lambda p: p['native64_coverage'].update(EN0_cases=0))
    variant('wrong phase profile', lambda p: p['current_stage_adapter'].update(phase_mode='unknown'))
    variant('untyped phase counter', lambda p: p['phase_coverage'].update(real=bool(p['phase_coverage']['real'])))
    variant('different compiled source command', lambda p: p['command'].append('uncompiled_other_source.sv'))
    if proof['current_stage_adapter'].get('address_class_sideband'):
        variant('missing class flag', lambda p: p['current_stage_adapter'].update(address_class_sideband=False))
        variant('unknown reversible edge', lambda p: p['current_stage_adapter']['address_class_v9_edge'].update(edge_type='unproved'))
        variant('wrong complete class parent', lambda p: p['current_stage_adapter']['address_class_v9_edge']['rtl/TMS34020/TMS34020_MC.sv'].update(before_sha256='0' * 64))
        variant('lost hint reset coverage', lambda p: p['address_decoder_coverage'].update(async_resets=0))
        variant('lost hint EN0 holding', lambda p: p['address_class_coverage'].update(EN0=0))
        variant('wrong actual decoder', lambda p: p['current_stage_adapter']['address_class_decoder_scope']['current_expressions'].update(FG_DRAW_SEL="1'b0"))
        variant('unreviewed class helper', lambda p: p['current_stage_adapter']['address_class_v9_edge']['fixture_helper'].update(sha256='0' * 64))
    if proof['current_stage_adapter'].get('combined_ddr_scope'):
        variant('missing combined composition', lambda p: p['current_stage_adapter']['address_class_v9_edge'].pop('parallel_ddr_composition'))
        variant('wrong full DDR oracle', lambda p: p['current_stage_adapter']['combined_ddr_oracle'].update(git_raw_sha256='0' * 64))
        variant('missing compiled activated DDR', lambda p: p['sources'].pop(next(k for k in p['sources'] if '/compiled_inputs/' in k and k.endswith('/rtl/ddram.sv'))))
        variant('deactivated parallel mode', lambda p: p['current_stage_adapter']['combined_ddr_scope'].update(parameter='USE_PARALLEL_DIN=0'))
        variant('wrong raw memory phase', lambda p: p['current_stage_adapter']['combined_ddr_scope'].update(memory_phase='admitted CPU R'))
        variant('missing accepted raw owner wiring', lambda p: p['current_stage_adapter']['combined_ddr_scope'].update(controller_binding=''))
        for owner in ('sprite', 'foreground0', 'foreground1', 'cpu'):
            variant('lost accepted ' + owner, lambda p, owner=owner: p['combined_ddr_coverage'].update({owner: 0}))
        variant('lost held/cache views', lambda p: p['combined_ddr_coverage'].update(holds=0))
    if proof['current_stage_adapter'].get('vram_request_edge'):
        variant('missing typed request edge', lambda p: p['current_stage_adapter'].pop('vram_request_edge'))
        variant('wrong actual request function', lambda p: p['current_stage_adapter']['vram_request_scope'].update(candidate_request_function="4'b0"))
        variant('new ABA projection order', lambda p: p['current_stage_adapter']['vram_request_edge']['rtl/TMS34020/TMS34020_MC.sv']['projected_assignments'].reverse())
        variant('foreign request source hash', lambda p: p['current_stage_adapter']['vram_request_edge']['rtl/BT.sv'].update(actual_sha256='0' * 64))
        variant('unreviewed request helper', lambda p: p['current_stage_adapter']['vram_request_edge']['prepare_bt_vram_request.py'].update(sha256='0' * 64))
        variant('wrong full request oracle', lambda p: p['current_stage_adapter']['vram_request_full_v11_oracle'].update(immutable_v11_sha256='0' * 64))
        variant('missing compiled complete request oracle', lambda p: p['sources'].pop(next(k for k in p['sources'] if '/compiled_inputs/' in k and k.endswith('/TMS34020_MC_V11_REQUEST_ORACLE.sv'))))
        variant('added legacy RAS reset', lambda p: p['current_stage_adapter']['vram_request_edge'].update(legacy_ras_reset_added=True))
        variant('lost held-RAS reset request cases', lambda p: p['vram_request_probe_coverage'].update(reset_held_ras=0))
        variant('lost request EN0 coverage', lambda p: p['vram_request_coverage'].update(EN0=0))
        variant('untyped request counter', lambda p: p['vram_request_coverage'].update(pre=True))
        variant('new request bus force', lambda p: p['current_stage_adapter']['vram_request_scope'].update(new_bus_or_request_force_statements=['force VRAM_REQUEST=0']))
        variant('new undefined RAM mask', lambda p: p['current_stage_adapter']['vram_request_scope'].update(defined_undefined_ram_masks_changed=True))
        variant('missing old MC state', lambda p: p['current_stage_adapter']['vram_request_scope']['old_mc_state_names'].pop())
        variant('lost consuming RAS coverage', lambda p: p['vram_request_coverage'].update(MEM_post=0))
        def reorder_request(p):
            transforms = p['current_stage_adapter']['transforms']
            first = next(i for i, item in enumerate(transforms) if item[0] == ' output [3:0] ADDR_CLASS\n')
            transforms[first], transforms[first + 1] = transforms[first + 1], transforms[first]
        variant('wrong request fixture transform order', reorder_request)
    rejected = []
    for label, candidate in mutations:
        try:
            validate_current_stage(candidate, path, root, source_root)
        except (QualificationError, OSError, ValueError, KeyError, TypeError, AttributeError, AssertionError):
            rejected.append(label)
    check(len(rejected) == len(mutations), 'Strict validator accepted a negative control')
    return rejected


def read_negative_controls(proof, path, root):
    mutations = []
    def variant(label, edit):
        candidate = copy.deepcopy(proof)
        edit(candidate)
        mutations.append((label, candidate))
    variant('missing current RAM source', lambda p: p['sources'].pop(RAM))
    variant('wrong immutable parent', lambda p: p.update(oracle_commit='8f048ee518f3062506e80d5f5a64585450d062f5'))
    variant('different compiled input', lambda p: p['jobs']['ddram-cache']['compiled_inputs'][0].update(sha256='0' * 64))
    variant('lost read coverage', lambda p: p['jobs']['foreground-read']['coverage'].update(comparisons=0))
    variant('assertions not compiled', lambda p: p['jobs']['sprite-read']['commands'][0].remove('--assert'))
    variant('unexpected source on command', lambda p: p['jobs']['sprite-packet']['commands'][0].append('/mnt/d/uncompiled_other.sv'))
    variant('failed actual fixture', lambda p: p['jobs']['foreground-ddr'].update(run_exit_code=1))
    if proof.get('ddr_controller_edge'):
        variant('missing typed controller edge', lambda p: p.pop('ddr_controller_edge'))
        variant('wrong typed controller digest', lambda p: p['ddr_controller_edge'].update(current_controller_sha256='0' * 64))
    rejected = []
    for label, candidate in mutations:
        try:
            validate_read_suite(candidate, path, root)
        except (QualificationError, OSError, ValueError, KeyError, TypeError, AttributeError):
            rejected.append(label)
    check(len(rejected) == len(mutations), 'Strict read validator accepted a negative control')
    return rejected


def parallel_ddr_negative_controls(root):
    proof = json.loads(contained(root, PARALLEL_DDR_RECEIPT).read_text())
    cases = [
        ('failed parallel run', lambda p: p.update(run_exit_code=1)),
        ('untyped parallel compile result', lambda p: p.update(compile_exit_code=False)),
        ('wrong parallel oracle', lambda p: p.update(oracle_sha256='0' * 64)),
        ('wrong parallel candidate', lambda p: p['candidate_sources'].update({'rtl/ddram.sv': '0' * 64})),
        ('missing parallel compiled controller', lambda p: p['compiled_sources'].pop('ddram.sv')),
        ('disabled activated path', lambda p: p['fixture_transformations'][0].__setitem__(1, '    ddram candidate(')),
        ('wrong default/cache coverage', lambda p: p['coverage'].update(reads=0)),
        ('lost raw CPU owner', lambda p: p['parallel_coverage'].update(cpu=0)),
        ('missing owner-mask cases', lambda p: p.update(owner_mask_cases=0)),
        ('wrong actual BT producer', lambda p: p.update(actual_bt_source_slice='0' * 64)),
        ('unchecked simulator command', lambda p: p['commands'][0].remove('--assert'))]
    rejected = []
    for label, edit in cases:
        variant = copy.deepcopy(proof)
        edit(variant)
        try:
            validate_parallel_ddr_edge(root, variant)
        except (QualificationError, OSError, ValueError, KeyError, TypeError, AttributeError, AssertionError):
            rejected.append(label)
    check(len(rejected) == len(cases), 'Parallel DDR validator accepted a negative control')
    return rejected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--source-root', type=Path, help='Explicit frozen production overlay for stage qualification only.')
    parser.add_argument('--read-suite', type=Path)
    parser.add_argument('--stage', type=Path, action='append', default=[])
    parser.add_argument('--self-test', action='store_true')
    parser.add_argument('--out', type=Path)
    parser.add_argument('--quiet', action='store_true', help='Print a compact receipt summary after all strict checks.')
    args = parser.parse_args()
    root = args.root.resolve()
    check(args.read_suite or args.stage, 'Select actual current evidence')
    result = {'schema': 'bt-current-qualification-validation-v1', 'status': 'PASS', 'sources': {}, 'coverage': {},
              'scope': 'Supplemental directed source/body/consumer qualification only. Legacy checks unchanged; physical Intel, full native/raster and timing gates remain required.'}
    if args.read_suite:
        path = args.read_suite.resolve()
        proof = json.loads(path.read_text())
        read_coverage, helper_edge = validate_current_read_suite(proof, path, root)
        result['coverage']['read_storage'] = read_coverage
        if helper_edge:
            result['read_validator_helper_preservation_edge'] = helper_edge
            result['sources'][Path(helper_edge['retained_path']).relative_to(root).as_posix()] = helper_edge['executed_sha256']
            result['sources'][Path(helper_edge['provenance_path']).relative_to(root).as_posix()] = helper_edge['provenance_sha256']
        result['sources'].update(proof['sources'])
        for job in proof['jobs'].values():
            result['sources'].update(job['logs'])
            for item in job['compiled_inputs']:
                result['sources'][item['path']] = item['sha256']
        result['sources'][path.relative_to(root).as_posix()] = sha(path.read_bytes())
        if args.self_test:
            checker = retained_read_checker(proof, path, root)[0] if helper_edge else sys.modules[__name__]
            result.setdefault('negative_controls', {})['read_storage'] = checker.read_negative_controls(proof, path, root)
            if proof.get('ddr_controller_edge'):
                result['negative_controls']['parallel_ddr'] = checker.parallel_ddr_negative_controls(root)
    seen = set()
    for item in args.stage:
        path = item.resolve()
        proof = json.loads(path.read_text())
        outcome = validate_current_stage(proof, path, root, args.source_root)
        check(outcome['phase'] not in seen, 'Duplicate stage phase profile')
        seen.add(outcome['phase'])
        result['coverage']['stage_' + outcome['phase']] = outcome
        result['sources'].update(proof['sources'])
        result['sources'].update({name: record['sha256'] for name, record in proof['bound_production_inputs'].items()})
        result['sources'][path.relative_to(root).as_posix()] = sha(path.read_bytes())
        result['sources'][(path.parent / 'run.log').relative_to(root).as_posix()] = sha((path.parent / 'run.log').read_bytes())
        if args.self_test:
            result.setdefault('negative_controls', {})[outcome['phase']] = stage_negative_controls(proof, path, root, args.source_root)
    if args.stage:
        check(seen == {'production', 'alternating'}, 'Both actual and adversarial phase profiles are required')
    result['sources'][Path(__file__).resolve().relative_to(root).as_posix()] = sha(Path(__file__).read_bytes())
    if args.out:
        target = args.out.resolve()
        check(target.is_relative_to(root / 'build') or target.is_relative_to(root / 'tests/graphics/evidence'), 'Output must remain in evidence/workspace')
        check(not target.exists(), 'Do not overwrite evidence')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(result, indent=2) + '\n')
    if args.quiet:
        print(json.dumps({'status': result['status'], 'profiles': list(result['coverage']),
                          'negative_controls': {key: len(value) for key, value in result.get('negative_controls', {}).items()},
                          'out': str(args.out) if args.out else None}, sort_keys=True))
    else:
        print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except QualificationError as error:
        print('FAIL ' + str(error), file=sys.stderr)
        sys.exit(1)
