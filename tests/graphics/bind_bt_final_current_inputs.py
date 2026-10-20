"""Strict current-input composition; never a timing, RBF or hardware gate.

The selected source inventory, each typed source edge, actual compiled slices,
immutable Git oracles and retained logs are bound separately. Original receipts
are not modified or relabeled as new runs. A new FG edge must be added explicitly
rather than accepted through a generic source or coverage-count exemption.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / 'tests'
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(Path(__file__).parent))
CPU = 'rtl/TMS34020/TMS34020.sv'
MC = 'rtl/TMS34020/TMS34020_MC.sv'
PKG = 'rtl/TMS34020/TMS34020_pkg.sv'
BT = 'rtl/BT.sv'
FG = 'rtl/fg_vram.sv'
TOP = 'Arcade-Battletoads.sv'
V9 = ROOT / 'build/timing_closure_20261011/integrated_v9_private'
V11 = ROOT / 'build/timing_closure_20261011/address_ddr_v11_private'
V12 = ROOT / 'build/timing_closure_20261011/vram_request_v12_private'
sha = lambda data: hashlib.sha256(data).hexdigest()
RECEIPTS = {
    'checker': ('build/final_cpu_checker_b537_v1/receipt.json', 'de0c8b89c8fd7725ec5daed3bb25f347a3b7adaaaae8938841f963a564684643'),
    'shift': ('build/final_cpu_checker_b537_v1/shift_composition/receipt.json', '11269a455b0ee7c9c0ef17d0a9d90f1d9c9841ba29c3fe67d72add222da8a20d'),
    'palette': ('build/final_cpu_checker_b537_v1/palette_proof/receipt.json', 'c339fffe4ad44da4b06d11679a310c18a46bb310ffaa796d417d1d17325ac684'),
    'fields': ('tests/graphics/evidence/io-phase/io-cpu_fields-current-cef789c96b8b4b13b88c3c939940f170/receipt.json', '6444e030a9fca7822cd2a738c16865020132ee24daeb59808566bb0fef397ed7'),
    'opcodes': ('tests/graphics/evidence/io-phase/io-cpu_opcodes-e6fc35b4091644198c4a6b07d9643521/receipt.json', '69d3438865dcaf55cc8c42db81281aa367a730de22a698a2744663ae465d757d'),
    'pause': ('build/pause_nvram_b537_v2/phase_proof/receipt.json', '12a2c6304e0e92ccda306d0a57671def4b320b8986e25c5e01d8a94eab2c8c36'),
    'nvram': ('build/pause_nvram_b537_v2/nvram_proof/receipt.json', 'f925a11a730eee8f68d6fe2df713e40e1adee6cbd031168ac81d75f83b9f81eb'),
    'reads': ('build/current_read_storage_b537_v6/receipt.json', '50e8e34f7054b9f4d0e0cea3abff8b539f705480820970b238c463f392749764'),
    'stage': ('build/timing_closure_20261011/v12-current-stage-validation-r1.json', '4433af9b7b81178d62394e460d5b32e8293627a10660447759391f9c03917281'),
    'abi': ('build/v12_debug_ports_v1/applicability-v13-r1.json', '81e24b0a39943705ebb68d4d11d16518c4c075689af3b808dec1dca216caacab'),
    'fg_pins': ('build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2.json', 'b69b35a83a218444197b7ac7a7629d9e3a71d82c3ffa0d53309b0ffd4fa8d91a'),
    'physical': ('build/fg_serial_controls_v12_v2/vendor-applicability-v13.json', '84976ae407f2b9e216df012363b7ce0625269982bd4caf66709d71b1c2f3592d'),
    'ddr': ('build/ddr_parallel_sources_v9_v2/proof/receipt.json', '7963e66ef8a36f8748fb10f02e21fab545d13483848ae360841a971d9ad9d5a5'),
}


def lf(data):
    text = data.decode().replace('\r\n', '\n')
    assert '\r' not in text, 'Only LF/CRLF normalization is allowed'
    return text


def native(value):
    if value.startswith('/mnt/') and len(value) > 7 and value[6] == '/':
        value = value[5].upper() + ':/' + value[7:]
    return Path(value.replace('\\\\', '\\'))


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Evidence:
    def __init__(self):
        self.files = {}
        self.oracles = {}
        self.logs = {}

    def file(self, path, expected=None):
        path = native(str(path)).resolve()
        data = path.read_bytes()
        digest = sha(data)
        assert expected is None or digest == expected, ('Fingerprint changed', str(path), expected, digest)
        assert str(path) not in self.files or self.files[str(path)] == digest, 'Input changed during verification'
        self.files[str(path)] = digest
        return data

    def receipt(self, key):
        name, digest = RECEIPTS[key]
        return json.loads(self.file(ROOT / name, digest))

    def git(self, commit, name, expected):
        data = subprocess.check_output(['D:/vibes/fpga/bin/git.EXE', 'show', commit + ':' + name], cwd=ROOT)
        assert sha(data) == expected, ('Immutable Git provenance differs', commit, name)
        self.oracles[commit + ':' + name] = expected
        return data

    def log(self, path, marker, coverage=None):
        data = self.file(path)
        text = data.decode(errors='replace')
        assert marker in text, ('Retained PASS absent', str(path), marker)
        assert not re.search(r'%Error|Assertion failed|\b(?:FAIL|FATAL|Aborting)\b', text), ('Failure in retained log', str(path))
        if coverage is not None:
            match = re.search(re.escape(marker) + r'\s+(\{[^\n]+\})', text)
            assert match and json.loads(match[1]) == coverage, ('Retained coverage differs', str(path))
        self.logs[str(native(str(path)).resolve())] = sha(data)
        return data

    def copied_compiled_input(self, temporary, expected_data, retained):
        """Keep original temporary locations honest when their copies survive.

        A deleted temporary workspace is not recreated. The immutable executed
        helper/receipt and exact retained tested-input bytes establish the copy
        or declared module-name-only transform, separately from a live recheck.
        """
        temporary = native(str(temporary))
        if temporary.is_file():
            assert self.file(temporary) == expected_data
        return {'original_temporary_path': str(temporary),
                'temporary_input_currently_available': temporary.is_file(),
                'expected_executed_input_sha256': sha(expected_data),
                'retained_tested_input_or_original': str(retained),
                'scope': 'Exact retained executed-source fingerprint/copy or pinned module-name transform; deleted temporary input is not recreated or claimed rechecked.'}


def snapshot(evidence, directory):
    manifest_path = directory.parent / (directory.name + '-snapshot.json')
    data = json.loads(evidence.file(manifest_path))
    assert len(data['sources']) == 144
    for name, digest in data['sources'].items():
        evidence.file(directory / name, digest)
    return data, manifest_path


def source_edges(e, current, inventory):
    class_helper = load(ROOT / 'tests/graphics/prepare_bt_address_class.py', 'final_class_edge')
    e.file(Path(class_helper.__file__), 'd433e7536bd74fdc305c4f0196358d46416275df42318f54b0be9fe81142595d')
    request = load(ROOT / 'tests/graphics/prepare_bt_vram_request.py', 'final_request_edge')
    e.file(Path(request.__file__), 'ab16e532b42d05cdef638b4b5926cad50d23ee788b38db532594b3695884e5cb')
    header = load(ROOT / 'tests/graphics/prepare_bt_append_debug_ports.py', 'final_header_edge')
    e.file(Path(header.__file__), 'e3024de4ce955ea7a820ceb7347c6b7aa7e1c73b7115bfabc758e7ee46e15d11')
    graph = {}
    for name in (CPU, MC):
        old = e.file(V9 / name, class_helper.BASE[name])
        classes = class_helper.address_class_transform(name, old)
        assert classes == e.file(V11 / name, request.BASE[name])
        requested, edits, assignments = request.transform(name, classes)
        assert requested == e.file(V12 / name, header.BASE[name])
        corrected, header_edits = header.transform(name, requested)
        assert corrected == e.file(current / name, inventory['sources'][name])
        inverse = lf(corrected)
        for edit in reversed(header_edits):
            assert inverse.count(edit['after']) == 1
            inverse = inverse.replace(edit['after'], edit['before'], 1)
        assert inverse == lf(requested)
        for edit in reversed(edits):
            assert edit['after'] in inverse
            inverse = inverse.replace(edit['after'], edit['before'], 1)
        assert inverse == lf(classes)
        graph[name] = {'v9_sha256': sha(old), 'v11_class_sha256': sha(classes),
                       'v12_request_sha256': sha(requested), 'selected_header_sha256': sha(corrected),
                       'exact_request_inverse': True, 'exact_header_inverse': True,
                       'projected_original_assignments': assignments,
                       'scope': 'Exact guarded same-edge class/request edges followed by declaration-only release token identity; original DEBUG ports restored.'}
    before_bt = e.file(V11 / BT, request.BASE[BT])
    requested_bt, edits, _ = request.transform(BT, before_bt)
    assert requested_bt == e.file(current / BT, inventory['sources'][BT])
    inverse = lf(requested_bt)
    for edit in reversed(edits):
        assert edit['after'] in inverse
        inverse = inverse.replace(edit['after'], edit['before'], 1)
    assert inverse == lf(before_bt)
    graph[BT] = {'v11_sha256': sha(before_bt), 'selected_sha256': sha(requested_bt),
                 'exact_request_inverse': True, 'parallel_DDR_owner_and_data_source_preserved': True}
    return graph


def cpu_checker(e, current):
    proof = e.receipt('checker')
    assert proof['status'] == 'PASS' and proof['synthesis_source_identical']
    helper = load(ROOT / 'tests/graphics/prepare_bt_cpu_return_checker.py', 'final_return_checker')
    e.file(Path(helper.__file__), proof['helper_sha256'])
    old = e.file(native(proof['base_root']) / CPU, proof['base_sources'][CPU])
    before = e.file(native(proof['candidate_root']) / CPU, proof['sources'][CPU])
    assert helper.no_simulation(old.decode()) == helper.no_simulation(before.decode())
    assert sha(helper.no_simulation(old.decode()).encode()) == proof['synthesis_source_sha256']
    marker = 'if (RST_N && EN && CE_R) assert (MC_DIN === MC_DIN_F)'
    assert lf(e.file(current / CPU)).count(marker) == lf(before).count(marker) == 1
    assert len(proof['enable_cases']) == 8 and proof['checker_values_and_failure_unchanged']
    return {'receipt': RECEIPTS['checker'], 'checker_macro': proof['checker_exclusion'],
            'functional_body_preservation': proof['synthesis_source_sha256'],
            'original_checker_values_and_failure_retained': True, 'scope': proof['scope']}


def shift_slices(e, current):
    proof = e.receipt('shift')
    assert proof['status'] == 'PASS' and proof['compiled_inputs_byte_identical']
    parent_path = native(proof['immutable_parent_receipt'])
    parent = json.loads(e.file(parent_path, proof['immutable_parent_receipt_sha256']))
    assert parent['build_exit_code'] == parent['run_exit_code'] == 0
    original = e.git(proof['oracle_commit'], CPU, proof['oracle_cpu_sha256'])
    package = e.git(proof['oracle_commit'], PKG, proof['oracle_pkg_sha256'])
    runner_path = TESTS / 'run_bt_cpu_shift_flags.py'
    runner = e.file(runner_path, proof['runner_sha256'])
    e.file(ROOT / 'tests/graphics/verify_bt_cpu_shift_composition.py', proof['composition_helper_sha256'])
    e.file(TESTS / 'bt_sv_bool_proof.py', parent['symbolic_interpreter_sha256'])
    e.file(TESTS / 'bt_cpu_shift_flags_tb.sv', parent['testbench_sha256'])
    e.file(TESTS / 'bt_cpu_line_gz_tb.sv', parent['base_line_testbench_sha256'])
    e.file(parent_path.parent / 'TMS34020.sv', proof['proved_parent_cpu_sha256'])
    assert e.file(parent_path.parent / 'TMS34020_oracle.sv') == original
    assert e.file(parent_path.parent / 'TMS34020_pkg.sv') == package
    tree = ast.parse(runner.decode())
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('function', 'slices')]
    generation = [node for node in tree.body if 129 <= node.lineno <= 162]
    assert len(definitions) == 2 and len(generation) == 7
    namespace = {'re': re, 'source': lf(original), 'candidate': lf(e.file(current / CPU))}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(runner_path), 'exec'), namespace)
    function = namespace['function']
    namespace.update(new_carry=function(namespace['candidate'], 'BtCarryShifter'),
                     new_ovf=function(namespace['candidate'], 'BtShiftLeftOvf'))
    exec(compile(ast.Module(body=generation, type_ignores=[]), str(runner_path), 'exec'), namespace)
    slices = '\n'.join(namespace['modules']).encode()
    assert sha(slices) == proof['actual_slices_sha256']
    assert slices == e.file(parent_path.parent / 'actual_slices.sv', proof['actual_slices_sha256'])
    assert slices == e.file(ROOT / 'build/final_cpu_checker_b537_v1/shift_composition/actual_slices.sv', proof['actual_slices_sha256'])
    log = e.log(parent_path.parent / 'run.log', 'PASS line predicate combin=')
    coverage = proof['retained_compiled_pass_coverage']
    patterns = [(r'PASS line predicate combin=(\d+) phase=(\d+) zero_sign=(\d+)',
                 ('alu_combinational_comparisons', 'pixel_phase_cycles', 'zero_sign_witnesses')),
                (r'PASS shift functions comparisons=(\d+) all16codes/all32amounts/all66basispatterns', ('direct_function_comparisons',)),
                (r'PASS actual operand/status phases=(\d+) reset=(\d+) en_hold=(\d+) ce_hold=(\d+) stalls=(\d+) actions=(\d+) overflow_writes=(\d+) all8statusclasses',
                 ('actual_operand_status_cycles', 'status_resets', 'status_enable_holds', 'status_ce_holds', 'status_stalls', 'status_actions', 'overflow_flag_writes'))]
    for pattern, names in patterns:
        match = re.search(pattern, log.decode())
        assert match and all(coverage[name] == int(value) for name, value in zip(names, match.groups()))
    assert proof['fresh_universal_function_proof'] == parent['universal_function_proof']
    assert proof['fresh_universal_function_proof']['all_miter_bits_identically_zero']
    return {'receipt': RECEIPTS['shift'], 'current_compiled_slices_identical_sha256': sha(slices),
            'preserved_universal_proof': proof['fresh_universal_function_proof'], 'retained_actual_ALU_operand_status_coverage': coverage,
            'new_simulator_run': False}, slices


def palette_slice(e, current):
    proof = e.receipt('palette')
    assert proof['status'] == 'PASS' and proof['returncode'] == 0
    assert proof['guards'] == 'RST_N/CE_R; unchanged absence of EN guard'
    runner = load(TESTS / 'run_bt_palette_early.py', 'final_palette_runner')
    e.file(Path(runner.__file__), proof['runner_sha256'])
    old = e.git(proof['oracle_commit'], BT, proof['oracle_BT_sha256'])
    old_cpu = e.git(proof['oracle_commit'], CPU, proof['oracle_CPU_sha256'])
    actual_bt, actual_cpu = lf(e.file(current / BT)), lf(e.file(current / CPU))
    assert runner.palette_body(actual_bt) == runner.palette_body(lf(old))
    assert runner.mux_body(actual_bt) == runner.mux_body(lf(old))
    assert runner.late_body(actual_bt, 'LDI_CACHE_LATE') == runner.late_body(lf(old), 'LDI_CACHE_LATE')
    for text in (lf(old_cpu), actual_cpu):
        begin = text.index('\twire [31:0] MC_RETURN_WORD =')
        end = text.index('\t// The same word', begin)
        if text == lf(old_cpu):
            old_return = text[begin:end]
        else:
            assert text[begin:end] == old_return
    slices = (runner.wrapper('palette_old', lf(old)) + runner.wrapper('palette_new', actual_bt, True)).encode()
    folder = ROOT / 'build/final_cpu_checker_b537_v1/palette_proof'
    assert slices == e.file(folder / 'palette_slices.sv', proof['compiled_slice_sha256'])
    e.file(TESTS / 'bt_palette_early_tb.sv', proof['testbench_sha256'])
    e.file(folder / 'bt_palette_early_tb.sv', proof['testbench_sha256'])
    e.log(folder / 'run.log', 'PASS palette_early', proof['coverage'])
    return {'receipt': RECEIPTS['palette'], 'current_compiled_slice_identical_sha256': sha(slices),
            'guard_RST_and_CE_R_without_EN_preserved': True, 'coverage': proof['coverage'], 'new_simulator_run': False}, slices


def fields(e, current):
    proof = e.receipt('fields')
    assert proof['build_exit_code'] == proof['run_exit_code'] == proof['exit_code'] == 0
    assert proof['coverage'] == {'byte_enables': 2048, 'extensions': 33280}
    helper = load(ROOT / 'tests/graphics/qualify_bt_current_fields.py', 'final_field_extract')
    e.file(Path(helper.__file__), proof['sources']['tests/graphics/qualify_bt_current_fields.py'])
    declarations = []
    identities = {}
    for reference in proof['references']:
        old = e.git(reference['commit'], reference['path'], reference['blob_sha256'])
        ref_body = helper.extract(old.decode(), reference['function'])
        body = helper.extract(lf(e.file(current / reference['path'])), reference['function'])
        assert sha(ref_body.encode()) == reference['reference_function_sha256']
        assert sha(body.encode()) == reference['current_function_sha256']
        for prefix, text in (('candidate', body), ('reference', ref_body)):
            declarations.append(re.sub(r'\b' + reference['function'] + r'\b', prefix + '_' + reference['function'], text))
        identities[reference['function']] = {'current_function_sha256': sha(body.encode()), 'immutable_reference': reference}
    include = '\n\n'.join(declarations).encode()
    folder = ROOT / RECEIPTS['fields'][0]
    folder = folder.parent
    assert include == e.file(folder / 'field_functions.svh', proof['generated_include_sha256'])
    temporary = e.copied_compiled_input(native(proof['snapshot']) / 'field_functions.svh', include, folder / 'field_functions.svh')
    e.file(ROOT / 'tests/cpu_field_timing_tb.sv', proof['sources']['tests/cpu_field_timing_tb.sv'])
    e.file(folder / 'cpu_field_timing_tb.sv', proof['sources']['tests/cpu_field_timing_tb.sv'])
    e.file(folder / 'build.log')
    e.log(folder / 'run.log', 'PASS CPU field timing helpers: byte_enables=2048 extensions=33280')
    return {'receipt': RECEIPTS['fields'], 'exact_actual_function_identities': identities,
            'regenerated_compiled_include_sha256': sha(include), 'coverage': proof['coverage'],
            'retained_tested_input_edge': temporary,
            'scope': 'Actual current FastDataWriteBE and Ext functions only; full MC states/bus/phase ownership use separate consuming-stage proof.'}, include


def opcodes(e, current):
    proof = e.receipt('opcodes')
    assert proof['compile_exit_code'] == proof['run_exit_code'] == proof['exit_code'] == 0
    assert all(proof[key] is True for key in ('current_generated_decoder_and_helpers_exact',
               'later_operand_select_transform_exact_and_reversible', 'registered_and_combinational_decode_compared_to_immutable', 'original_decoder_scope_preserved'))
    generator_path = ROOT / 'tests/graphics/predecode_opcode.py'
    generator = load(generator_path, 'final_opcode_generator')
    e.file(generator_path, proof['sources']['tests/graphics/predecode_opcode.py'])
    helper_path = ROOT / 'tests/graphics/qualify_bt_current_opcode.py'
    helper_bytes = e.file(helper_path, proof['sources']['tests/graphics/qualify_bt_current_opcode.py'])
    oracle = e.git(proof['oracle_commit'], 'rtl/TMS34020/TMS34020_ID.sv', proof['oracle_original_sha256'])
    generated, predicates, rs_predicates, cases, labels = generator.full_opcode_classes(oracle.decode())
    helpers = generator.package_helper(predicates, rs_predicates) + generator.rf_address_helper(oracle.decode())
    tree = ast.parse(helper_bytes.decode())
    transform_node = [node for node in tree.body if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'decoder_transforms' for t in node.targets)]
    assert len(transform_node) == 1
    transforms = ast.literal_eval(transform_node[0].value)
    assert [list(pair) for pair in transforms] == proof['decoder_transforms']
    expected = generated
    for before, after in transforms:
        assert expected.count(before) == 1
        expected = expected.replace(before, after, 1)
    actual = lf(e.file(current / 'rtl/TMS34020/TMS34020_ID.sv', proof['sources']['rtl/TMS34020/TMS34020_ID.sv']))
    assert actual == expected
    inverse = actual
    for before, after in reversed(transforms):
        assert inverse.count(after) == 1
        inverse = inverse.replace(after, before, 1)
    assert inverse == generated
    assert helpers.strip() in lf(e.file(current / PKG, proof['sources']['rtl/TMS34020/TMS34020_PKG.sv']))
    cpu = lf(e.file(current / CPU))
    assertions = ('assert (IC_MATCHES == DecodeICMatches(IC))',
                  'assert (IC_RF_ADDR == DecodeICRFAddress(IC,STATE,0) && IC_RF_ADDR_POS == DecodeICRFAddress(IC,STATE,1))',
                  'assert (IC_RS_STATIC == DecodeICRS(IC))', 'assert (OPSEL == OPSEL_COMB)')
    assert all(statement in cpu for statement in assertions)
    for name, record in proof['bound_input_paths'].items():
        e.file(native(record['path']), record['sha256'])
        if name.startswith('rtl/') and name != CPU:
            e.file(current / name, record['sha256'])
    folder = (ROOT / RECEIPTS['opcodes'][0]).parent
    assert e.file(folder / 'TMS34020_ID_IMMUTABLE.sv', proof['oracle_original_sha256']) == oracle
    assert e.file(folder / 'generated_helpers.svh') == helpers.encode()
    bench = lf(e.file(ROOT / 'tests/cpu_opcode_equivalence_tb.sv', proof['sources']['tests/cpu_opcode_equivalence_tb.sv']))
    namespace = {'bench_original': bench}
    fixture_nodes = [node for node in tree.body if 119 <= node.lineno <= 135]
    assert len(fixture_nodes) == 7
    exec(compile(ast.Module(body=fixture_nodes, type_ignores=[]), str(helper_path), 'exec'), namespace)
    expected_bench = namespace['bench'].encode()
    assert expected_bench == e.file(folder / 'cpu_opcode_equivalence_current_tb.sv')
    target = native(proof['snapshot'])
    assert oracle.count(b'module TMS34020_ID') == 1
    temporary = {
        'immutable_reference_name_transform': e.copied_compiled_input(target / 'TMS34020_ID_REFERENCE.sv',
            oracle.replace(b'module TMS34020_ID', b'module TMS34020_ID_REFERENCE', 1), folder / 'TMS34020_ID_IMMUTABLE.sv'),
        'adapted_testbench_copy': e.copied_compiled_input(target / 'cpu_opcode_equivalence_tb.sv', expected_bench, folder / 'cpu_opcode_equivalence_current_tb.sv')}
    decoder_bytes = e.file(native(proof['bound_input_paths']['rtl/TMS34020/TMS34020_ID.sv']['path']), proof['sources']['rtl/TMS34020/TMS34020_ID.sv'])
    temporary['current_decoder_copy'] = e.copied_compiled_input(target / 'TMS34020_ID.sv', decoder_bytes,
            proof['bound_input_paths']['rtl/TMS34020/TMS34020_ID.sv']['path'])
    e.file(folder / 'build.log')
    e.log(folder / 'run.log', 'PASS opcode predecode: all 65536 opcodes, 32 states, 3 condition profiles, 6291456 complete-control comparisons')
    return {'receipt': RECEIPTS['opcodes'], 'actual_generated_decoder_sha256': sha(actual.encode()),
            'actual_generated_helpers_sha256': sha(helpers.encode()), 'adapted_fixture_sha256': sha(expected_bench),
            'retained_tested_input_edges': temporary,
            'shipping_identity_assertions_preserved': list(assertions), 'coverage': proof['coverage'], 'scope': proof['scope']}, actual.encode()


def pause_nvram(e, current):
    pause, nvram = e.receipt('pause'), e.receipt('nvram')
    assert pause['status'] == nvram['status'] == 'PASS' and pause['returncode'] == nvram['returncode'] == 0
    phase = load(TESTS / 'run_bt_pause_bridge.py', 'run_bt_pause_bridge')
    sys.modules['run_bt_pause_bridge'] = phase
    helper = load(TESTS / 'run_bt_pause_nvram.py', 'final_nvram_generator')
    e.file(Path(phase.__file__), pause['runner_sha256'])
    e.file(Path(helper.__file__), nvram['runner_sha256'])
    top = lf(e.file(current / TOP))
    common = phase.board_slice(top)
    old_top = e.git(pause['oracle_commit'], TOP, pause['oracle_top_sha256'])
    old_nvram = e.git(nvram['oracle_commit'], 'rtl/bt_nvram.sv', nvram['oracle_nvram_sha256'])
    bridge = e.file(current / 'rtl/bt_pause_bridge.sv', pause['candidate_bridge_sha256'])
    clock = e.file(current / 'rtl/bt_clock_enables.sv', pause['unchanged_clock_generator_sha256'])
    assert lf(bridge) == phase.MODULE
    assert clock == e.git(pause['oracle_commit'], 'rtl/bt_clock_enables.sv', pause['unchanged_clock_generator_sha256'])
    assert lf(e.file(current / 'rtl/bt_nvram.sv', nvram['candidate_nvram_sha256'])) == phase.expected_nvram(lf(old_nvram))
    assert helper.nvram_slice(top) == helper.nvram_slice(phase.expected_top(lf(old_top)))
    e.file(current / 'files.qip', pause['candidate_qip_sha256'])
    pause_board = ('''module pause_board(input wire clk_sys, reset,
input wire [31:0] joy0,joy1,joy2,input wire OSD_STATUS,nvram_pause,
output wire gated_f,gated_r,vce);
''' + common + '''assign gated_f=CE_F_CPU;
assign gated_r=CE_R_CPU;
assign vce=VCE_R;
endmodule
''').encode()
    phase_folder = ROOT / 'build/pause_nvram_b537_v2/phase_proof'
    assert pause_board == e.file(phase_folder / 'board_slice.sv', pause['compiled_board_slice_sha256'])
    e.file(TESTS / 'bt_pause_bridge_tb.sv', pause['testbench_sha256'])
    e.file(phase_folder / 'bt_pause_bridge_tb.sv', pause['testbench_sha256'])
    e.log(phase_folder / 'run.log', 'PASS pause_bridge', pause['coverage'])
    new_board = ('module nvram_phase_board(\n' + helper.PORTS + ');\n' + common + helper.nvram_slice(top) + '''
assign gated_f=CE_F_CPU;assign gated_r=CE_R_CPU;assign vce=VCE_R;
endmodule
''')
    old_instance = helper.nvram_slice(lf(old_top)).replace('bt_nvram nvram (', 'bt_nvram_old nvram (')
    old_board = ('module nvram_phase_board_old(\n' + helper.PORTS + ');\n' + common + old_instance + '''
assign gated_f=CE_F_CPU;assign gated_r=CE_R_CPU;assign vce=VCE_R;
endmodule
''')
    inputs = {'board_slices.sv': (new_board + old_board).encode(),
              'bt_nvram.sv': e.file(current / 'rtl/bt_nvram.sv'),
              'bt_nvram_old.sv': lf(old_nvram).replace('module bt_nvram(', 'module bt_nvram_old(', 1).encode(),
              'bt_pause_bridge.sv': bridge, 'bt_clock_enables.sv': clock,
              'bt_pause_nvram_tb.sv': e.file(TESTS / 'bt_pause_nvram_tb.sv')}
    folder = ROOT / 'build/pause_nvram_b537_v2/nvram_proof'
    assert set(inputs) == set(nvram['compiled_inputs'])
    for name, data in inputs.items():
        assert data == e.file(folder / name, nvram['compiled_inputs'][name])
    e.log(folder / 'run.log', 'PASS pause_nvram', nvram['coverage'])
    return {'pause_receipt': RECEIPTS['pause'], 'nvram_receipt': RECEIPTS['nvram'],
            'current_board_pause_and_nvram_compiled_slices_identical': True,
            'unchanged_clock_generator_full_sha256': sha(clock),
            'pause_coverage': pause['coverage'], 'nvram_coverage': nvram['coverage'],
            'scope': 'Exact current board phase bridge/NVRAM integration slices, complete controller and original losing-final-R regression; unrelated new top DDR outputs require their separate edge.'}, inputs['board_slices.sv']


def accepted_graph(e, current, inventory):
    abi = e.receipt('abi')
    assert abi['status'] == 'PASS_HEADER_APPLICABILITY'
    assert abi['full_source_count'] == 144 and abi['unchanged_sources'] == 141
    assert abi['target_snapshot']['sha256'] == sha(e.file(current.parent / (current.name + '-snapshot.json')))
    e.file(native(abi['helper']['path']), abi['helper']['sha256'])
    for record in abi['retained_inputs'].values():
        e.file(native(record['path']), record['sha256'])
    # Re-run the already-qualified read-only ABI/stage/native binder into a
    # separate output. No compiler or simulator is invoked by this helper.
    independent = ROOT / 'build/v12_debug_ports_v1/applicability-v13-r2-independent.json'
    stability = json.loads(e.file(independent, '4ded4d25eb3f62bc402839ac5fc70634682e442dcb2b49d149cbd08d693bcb80'))
    assert stability['status'] == abi['status'] and stability['target_snapshot'] == abi['target_snapshot']
    stage = e.receipt('stage')
    assert stage['status'] == 'PASS'
    for name, digest in stage['sources'].items():
        e.file((V12 if name in inventory['sources'] else ROOT) / name, digest)
    reads = e.receipt('reads')
    assert reads['status'] == 'PASS'
    assert set(reads['jobs']) == {'ddram-cache', 'sprite-packet', 'sprite-read', 'foreground-read', 'foreground-ddr'}
    pin, physical = e.receipt('fg_pins'), e.receipt('physical')
    assert pin['status'] == physical['status'] == 'PASS'
    assert pin['candidate_fg_sha256'] == inventory['sources'][FG]
    assert pin['case_equality_exclusions'] == pin['collision_masks_added'] == 0
    assert physical['snapshot_sha256'] == abi['target_snapshot']['sha256']
    assert physical['strict_physical_data_x_z_comparison_exclusions'] == 0
    assert not physical['new_vendor_simulation_performed'] and not physical['mapped_atoms_verified']
    for path, digest in pin['retained_logs'].items():
        e.file(native(path), digest)
    for path, record in pin['compiled_inputs'].items():
        e.file(native(path), record['sha256']); e.file(native(record['retained_path']), record['sha256'])
    for record in physical['original_Intel_logs_rehashed']:
        e.file(native(record['path']), record['sha256'])
    ddr = e.receipt('ddr')
    assert ddr['status'] == 'PASS' and ddr['parent_body_identical_lf']
    assert ddr['compile_exit_code'] == ddr['run_exit_code'] == 0
    assert ddr['owner_mask_cases'] == 60 and ddr['exact_fixture_restoration']
    for name, digest in ddr['helper_sources'].items():
        e.file(ROOT / name, digest)
    assert inventory['sources']['rtl/ddram.sv'] == ddr['candidate_sources']['rtl/ddram.sv']
    assert inventory['sources'][TOP] == ddr['candidate_sources'][TOP]
    parallel = load(ROOT / 'tests/graphics/prepare_bt_parallel_ddr_write.py', 'final_parallel_edge')
    assert parallel.PARALLEL in lf(e.file(current / BT))
    assert parallel.PARALLEL in lf(e.file(native(ddr['candidate_dir']) / BT, ddr['candidate_sources'][BT]))
    e.git(ddr['oracle_commit'], ddr['oracle_git_file'], ddr['oracle_sha256'])
    proof_folder = (ROOT / RECEIPTS['ddr'][0]).parent
    compiled = {}
    def command_inputs(value):
        if isinstance(value, list):
            for item in value:
                command_inputs(item)
        elif isinstance(value, str) and value.endswith('.sv'):
            candidate = native(value)
            if candidate.name in ddr['compiled_sources']:
                e.file(candidate, ddr['compiled_sources'][candidate.name])
                compiled[candidate.name] = str(candidate)
    command_inputs(ddr['commands'])
    assert set(compiled) == set(ddr['compiled_sources']), 'Bind all actual DDR compiled controller/source/fixture bytes'
    compile_logs = [name for name in ('build.log', 'compile.log') if (proof_folder / name).is_file()]
    assert len(compile_logs) == 1
    e.file(proof_folder / compile_logs[0], ddr['compile_log_sha256'])
    e.file(proof_folder / 'run.log', ddr['run_log_sha256'])
    return {'ABI_stage_native_header_only': {'receipt': RECEIPTS['abi'], 'original_receipts_untouched': True,
            'new_FG_whole_board_execution_inferred': False},
            'MC_bus_request_and_consuming_MEM_stages': {'receipt': RECEIPTS['stage'], 'coverage': stage['coverage'], 'negative_controls': stage['negative_controls']},
            'read_storage': {'receipt': RECEIPTS['reads'], 'FG_changed_source_edge': RECEIPTS['fg_pins'],
            'FG_full_state_and_actual_pins_coverage': pin['coverage'], 'other_four_jobs_inputs_unchanged': True},
            'physical_VRAM_and_BG': {'receipt': RECEIPTS['physical'], 'strict_physical_data_x_z_exclusions': 0,
            'collision_contract_sha256': physical['preserved_collision_contract_sha256'],
            'all_six_top_instance_bindings': physical['all6instances_non_RAS_pins_and_geometry_identical'],
            'new_vendor_run': False, 'mapped_atoms_verified': False},
            'parallel_DDR': {'receipt': RECEIPTS['ddr'], 'raw_four_owner_source_slice_preserved': True,
            'actual_controller_sha256': ddr['candidate_sources']['rtl/ddram.sv'], 'new_simulator_run': False}}


def reject(label, action, controls):
    try:
        action()
    except AssertionError:
        controls.append({'name': label, 'rejected': True})
    else:
        raise AssertionError('Negative control accepted: ' + label)


def same(data, digest):
    assert sha(data) == digest


def verify_retained_receipt(path):
    result = json.loads(path.read_bytes())
    assert result['schema'] == 'bt-current-input-functional-composition-v1' and result['status'] == 'PASS_SCOPED_COMPOSITION'
    assert result['helper_sha256'] == sha(Path(__file__).read_bytes())
    for name, expected in result['bound_evidence_files'].items():
        assert sha(native(name).read_bytes()) == expected, ('Retained evidence changed', name)
    for key, expected in result['immutable_git_oracles'].items():
        commit, name = key.split(':', 1)
        assert sha(subprocess.check_output(['D:/vibes/fpga/bin/git.EXE', 'show', commit + ':' + name], cwd=ROOT)) == expected
    assert all(item['rejected'] for item in result['negative_controls'])
    print(json.dumps({'status': result['status'], 'verified_evidence_files': len(result['bound_evidence_files']), 'receipt': str(path)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-receipt', type=Path)
    args = parser.parse_args()
    if args.verify_receipt:
        verify_retained_receipt(args.verify_receipt.resolve()); return
    assert args.source_root and args.output
    current, output = args.source_root.resolve(), args.output.resolve()
    current.relative_to(ROOT / 'build'); output.relative_to(ROOT / 'build'); assert not output.exists()
    e = Evidence()
    inventory, inventory_path = snapshot(e, current)
    parent, parent_path = snapshot(e, V12)
    changes = {name for name in inventory['sources'] if inventory['sources'][name] != parent['sources'][name]}
    assert changes == {CPU, MC, FG}, 'Unrecognized source edge; add and prove an explicit typed branch'
    graph = source_edges(e, current, inventory)
    checker = cpu_checker(e, current)
    shift, shift_data = shift_slices(e, current)
    palette, palette_data = palette_slice(e, current)
    field, field_data = fields(e, current)
    opcode, opcode_data = opcodes(e, current)
    pause, pause_data = pause_nvram(e, current)
    composed = accepted_graph(e, current, inventory)
    controls = []
    for label, data in [('changed actual ALU/shift/status compiled slice', shift_data),
                        ('changed palette guard or mux slice', palette_data),
                        ('changed current field function include', field_data),
                        ('changed generated opcode decoder', opcode_data),
                        ('changed board pause/NVRAM capture slice', pause_data)]:
        reject(label, lambda data=data: same(data + b'\n', sha(data)), controls)
    reject('changed declared MC/source edge', lambda: same(e.file(current / MC) + b'\n', inventory['sources'][MC]), controls)
    reject('changed RAM geometry/source', lambda: same(e.file(current / 'rtl/BT_mem.sv') + b'\n', inventory['sources']['rtl/BT_mem.sv']), controls)
    first_log = next(iter(e.logs)); original_log = e.file(native(first_log))
    reject('changed retained transcript', lambda: same(original_log + b'\n', e.logs[first_log]), controls)
    reject('false PASS with a fresh hash plus FAIL', lambda: assert_log_failure(original_log + b'\nFAIL altered'), controls)
    assert len(controls) == 9
    for path, expected in list(e.files.items()):
        assert sha(native(path).read_bytes()) == expected, ('Source changed while composing', path)
    result = {'schema': 'bt-current-input-functional-composition-v1', 'status': 'PASS_SCOPED_COMPOSITION',
              'source_root': str(current), 'snapshot': str(inventory_path), 'snapshot_sha256': sha(inventory_path.read_bytes()),
              'parent_snapshot': str(parent_path), 'all144_inputs_bound': True, 'declared_changes': sorted(changes),
              'helper_sha256': sha(Path(__file__).read_bytes()), 'source_graph': graph,
              'CPU_return_checker': checker, 'CPU_ALU_shift_operand_status': shift, 'palette_E_predictor': palette,
              'CPU_field_functions': field, 'CPU_opcode_decoder': opcode, 'board_pause_NVRAM': pause,
              'composed_proofs': composed, 'bound_evidence_files': e.files, 'immutable_git_oracles': e.oracles,
              'retained_logs_rehashed': e.logs, 'negative_controls': controls,
              'legacy_verify_timing_modified': False, 'legacy_missing_or_stale_evidence_overridden': False,
              'new_simulator_or_Quartus_run': False, 'new_whole_board_native_run': False,
              'routed_timing_accepted': False, 'mapped_atoms_verified': False, 'mister_hardware_qualified': False,
              'eligible_for_RBF': False,
              'scope': 'Exact current-input applicability of named accepted functional/component proofs via typed same-edge and declaration edges. Original receipts stay immutable. The v12 full-native execution remains an explicitly retained parent; changed FG gets its separate fresh full-pin proof. All-corner pad/clock timing, final mapped/resource warnings, mandatory unlisted legacy gates and hardware qualification remain independent requirements.'}
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'receipt': str(output), 'sha256': sha(output.read_bytes()),
                      'all144_inputs': True, 'bound_files': len(e.files), 'oracle_blobs': len(e.oracles),
                      'negative_controls': len(controls), 'eligible_for_RBF': False}))


def assert_log_failure(data):
    assert not re.search(rb'\b(?:FAIL|FATAL|Aborting)\b', data)


if __name__ == '__main__':
    main()
