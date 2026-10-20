"""Bind the immutable-8f shift proof to the exact final CPU's compiled slices.

The original full-file receipt stays immutable. This separate receipt proves
byte identity of every compiled slice and fixture, and repeats the universal
actual-function proof. It does not claim equivalence of untested CPU bodies.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / 'tests'
sys.path.insert(0, str(TESTS))
from bt_sv_bool_proof import prove

REF = '8f048ee518f3062506e80d5f5a64585450d062f5'
CPU = 'rtl/TMS34020/TMS34020.sv'
PKG = 'rtl/TMS34020/TMS34020_pkg.sv'
GIT = 'D:/vibes/fpga/bin/git.EXE'
PINS = {
    'runner': 'd210db8dc759119d5b2a259527c1eb1d8b1ffe9f1b38f3b65c95aa386c8fa469',
    'interpreter': '2647264099e67c8b1f7fe03aedf8653b2455451b63919a9808baa69fe495fcbb',
    'candidate': 'b559dd361d02705cc19088d9b09389b1f978645b7c7f3cb8cb761877226de1a9',
    'proved_candidate': 'df7637012a98e0b571a4616af640c706df9ec01fb389f00b3242c7b6e5114219',
    'oracle_cpu': '1fe4b85021385afaa73498cf5ead192758ec5a310389d2b85717f2dd2349aa32',
    'oracle_pkg': '02dad572b549dbcfabb59c68ecdea1306c311505d9994b49b010d116394811e0',
    'slices': 'd2739349f590b50173b4591f5e510444f143a456add31771ae6828dc60d0da7b',
}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def norm(data):
    return data.decode().replace('\r\n', '\n')


def blob(path):
    result = subprocess.run([GIT, '-C', str(ROOT), 'show', REF + ':' + path], capture_output=True)
    assert result.returncode == 0, result.stderr.decode(errors='replace')
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, default=ROOT / 'build/final_cpu_checker_b537_v1/candidate' / CPU)
    parser.add_argument('--proof', type=Path, default=ROOT / 'build/cpu_shift_flags_promoted_v1')
    parser.add_argument('--out', type=Path, default=ROOT / 'build/final_cpu_checker_b537_v1/shift_composition')
    args = parser.parse_args()
    candidate = args.candidate.resolve().read_bytes()
    assert sha(candidate) == PINS['candidate'], 'final CPU changed'
    oracle_cpu, oracle_pkg = blob(CPU), blob(PKG)
    assert sha(oracle_cpu) == PINS['oracle_cpu'] and sha(oracle_pkg) == PINS['oracle_pkg']
    assert norm((ROOT / PKG).read_bytes()) == norm(oracle_pkg), 'live package changed'
    proof = args.proof.resolve()
    old_receipt_path = proof / 'receipt.json'
    old_receipt_data = old_receipt_path.read_bytes()
    previous = json.loads(old_receipt_data)
    assert previous['oracle_commit'] == REF
    assert previous['candidate_sha256'] == PINS['proved_candidate']
    assert sha((proof / 'TMS34020.sv').read_bytes()) == PINS['proved_candidate']
    assert (proof / 'TMS34020_oracle.sv').read_bytes() == oracle_cpu
    assert (proof / 'TMS34020_pkg.sv').read_bytes() == oracle_pkg
    assert previous['build_exit_code'] == previous['run_exit_code'] == 0
    old_slices = (proof / 'actual_slices.sv').read_bytes()
    assert sha(old_slices) == previous['actual_slices_sha256'] == PINS['slices']
    runner_path = TESTS / 'run_bt_cpu_shift_flags.py'
    runner = runner_path.read_bytes()
    assert sha(runner) == previous['runner_sha256'] == PINS['runner']
    interpreter = (TESTS / 'bt_sv_bool_proof.py').read_bytes()
    assert sha(interpreter) == previous['symbolic_interpreter_sha256'] == PINS['interpreter']
    assert sha((TESTS / 'bt_cpu_shift_flags_tb.sv').read_bytes()) == previous['testbench_sha256']
    assert sha((TESTS / 'bt_cpu_line_gz_tb.sv').read_bytes()) == previous['base_line_testbench_sha256']

    # Reuse the exact, pinned extraction and module-generation AST, without
    # executing its CLI, writes, candidate validator, simulator, or receipt code.
    tree = ast.parse(runner.decode())
    definitions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in ('function', 'slices')]
    assert len(definitions) == 2
    generation = [node for node in tree.body if 129 <= node.lineno <= 162]
    assert len(generation) == 7, 'pinned generator boundaries changed'
    namespace = {'re': re, 'source': norm(oracle_cpu), 'candidate': norm(candidate)}
    exec(compile(ast.Module(body=definitions, type_ignores=[]), str(runner_path), 'exec'), namespace)
    function = namespace['function']
    old_carry = function(norm(oracle_pkg), 'CarryShifter')
    old_ovf = function(norm(oracle_pkg), 'ShiftLeftOvf')
    new_carry = function(norm(candidate), 'BtCarryShifter')
    new_ovf = function(norm(candidate), 'BtShiftLeftOvf')
    namespace.update(new_carry=new_carry, new_ovf=new_ovf)
    exec(compile(ast.Module(body=generation, type_ignores=[]), str(runner_path), 'exec'), namespace)
    regenerated = '\n'.join(namespace['modules']).encode()
    assert regenerated == old_slices, 'a compiled function/ALU/pixel/operand/status slice changed'
    universal = prove(old_carry, new_carry, old_ovf, new_ovf)
    assert universal == previous['universal_function_proof']

    run_log = (proof / 'run.log').read_text(errors='replace')
    line = re.search(r'PASS line predicate combin=(\d+) phase=(\d+) zero_sign=(\d+)', run_log)
    fun = re.search(r'PASS shift functions comparisons=(\d+) all16codes/all32amounts/all66basispatterns', run_log)
    phase = re.search(r'PASS actual operand/status phases=(\d+) reset=(\d+) en_hold=(\d+) ce_hold=(\d+) stalls=(\d+) actions=(\d+) overflow_writes=(\d+) all8statusclasses', run_log)
    assert line and fun and phase, 'retained compiled PASS evidence missing'
    counts = dict(zip(('alu_combinational_comparisons', 'pixel_phase_cycles', 'zero_sign_witnesses'), map(int, line.groups())))
    counts['direct_function_comparisons'] = int(fun[1])
    counts.update(dict(zip(('actual_operand_status_cycles', 'status_resets', 'status_enable_holds', 'status_ce_holds', 'status_stalls', 'status_actions', 'overflow_flag_writes'), map(int, phase.groups()))))
    assert all(counts[key] == previous['pass_coverage'][key] for key in counts)
    assert all(value > 0 for value in counts.values())
    out = args.out.resolve()
    assert out.is_relative_to((ROOT / 'build').resolve()) and not out.exists()
    out.mkdir(parents=True)
    (out / 'actual_slices.sv').write_bytes(regenerated)
    receipt = {
        'schema': 'bt-cpu-shift-slice-composition-v1', 'status': 'PASS',
        'candidate_path': str(args.candidate.resolve()), 'candidate_sha256': sha(candidate),
        'oracle_commit': REF, 'oracle_cpu_sha256': sha(oracle_cpu), 'oracle_pkg_sha256': sha(oracle_pkg),
        'immutable_parent_receipt': str(old_receipt_path), 'immutable_parent_receipt_sha256': sha(old_receipt_data),
        'proved_parent_cpu_sha256': PINS['proved_candidate'],
        'actual_slices_sha256': sha(regenerated), 'compiled_inputs_byte_identical': True,
        'fresh_universal_function_proof': universal, 'retained_compiled_pass_coverage': counts,
        'runner_sha256': sha(runner), 'composition_helper_sha256': sha(Path(__file__).read_bytes()),
        'scope': 'Same exact function/ALU/pixel/operand/status compiled slices and fixtures as immutable-8f proof. Original receipt is unchanged; no new compiled simulation claimed. Palette/interface and full CPU behavior require their separate fresh proofs.'}
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')
    assert old_receipt_path.read_bytes() == old_receipt_data, 'original receipt changed'
    print(json.dumps({'receipt': str(out / 'receipt.json'), 'status': 'PASS', 'candidate_sha256': sha(candidate),
                      'actual_slices_sha256': sha(regenerated), 'coverage': counts}, sort_keys=True))


if __name__ == '__main__':
    main()
