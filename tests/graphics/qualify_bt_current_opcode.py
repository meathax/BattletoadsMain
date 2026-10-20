"""Renew exhaustive decode coverage using the exact retained original ID hash.

The deleted whole-core temporary snapshot is unnecessary for this decode-only
scope. All compiled package/types/helpers and generated decoder are current.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import uuid
import re
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root', type=Path, help='Explicit production-source overlay; all actual input paths and hashes are retained.')
args = parser.parse_args()

ROOT = Path(__file__).resolve().parents[2]
ID = 'rtl/TMS34020/TMS34020_ID.sv'
PKG = 'rtl/TMS34020/TMS34020_PKG.sv'
CPU = 'rtl/TMS34020/TMS34020.sv'
SDC = 'rtl/bt_cpu_phase.sdc'
GENERATOR = 'tests/graphics/predecode_opcode.py'
TB = 'tests/cpu_opcode_equivalence_tb.sv'
COMMIT = 'e5dbd1dd4ffa93a3a6cef36523a543d750334fea'
ORIGINAL_ID_SHA = '19d78ea1d1a72a8fe735caf0a25a67d7cc76b83e14dc9d2e6e15b220c3bfec4f'
sha = lambda data: hashlib.sha256(data).hexdigest()
source_root = args.source_root.resolve() if args.source_root else ROOT
bound_inputs = {}
canonical_text_hashes = {}


def current_bytes(name):
    path = ROOT / name
    if name.startswith('rtl/') and (source_root / name).is_file():
        path = source_root / name
    data = path.read_bytes()
    entry = {'path': str(path.resolve()), 'sha256': sha(data)}
    assert name not in bound_inputs or bound_inputs[name] == entry, 'An input changed during qualification: ' + name
    bound_inputs[name] = entry
    return data


def current_text(name):
    # Git and Windows snapshots can use either LF or CRLF. Compilation still
    # uses the exact raw bytes recorded above; this guard permits only that
    # explicit line-ending conversion, and rejects bare carriage returns.
    raw = current_bytes(name).decode()
    normalized = raw.replace('\r\n', '\n')
    assert '\r' not in normalized, 'Unexpected source line ending: ' + name
    canonical_text_hashes[name] = sha(normalized.encode())
    return normalized


oracle = subprocess.check_output(['git', 'show', COMMIT + ':' + ID], cwd=ROOT)
assert sha(oracle) == ORIGINAL_ID_SHA, 'Original whole decoder differs from retained receipt hash'
spec = importlib.util.spec_from_file_location('qualified_predecode_opcode', ROOT / GENERATOR)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)
generated, predicates, rs_predicates, cases, labels = generator.full_opcode_classes(oracle.decode())
helper = generator.package_helper(predicates, rs_predicates) + generator.rf_address_helper(oracle.decode())
decoder_transforms = [
    ('module TMS34020_ID\n', "module TMS34020_ID\n #(parameter bit OPSEL_REG = 1'b0)\n"),
    ('\tinput ICRFAddress_t IC_RF_ADDR_POS,\n', '\tinput ICRFAddress_t IC_RF_ADDR_POS,\n\tinput OpSel_t OPSEL,\n'),
    ('\toutput DecInstr_t  DECI\n', '''\toutput DecInstr_t  DECI,
\t// DECI.MC.AT before the PIX_WE gate on the bitmap-write microcycle: the READ
\t// decision does not depend on PIX_WE (only MA_WRITE becomes MA_NONE).
\toutput MemAccess_t DECI_AT_PRE,
\t// Operand-select fields as decoded combinationally from (IC,STATE).
\toutput OpSel_t OPSEL_COMB
'''),
    ("CLASS_DECI[52].MC = '{MAS_RA, MDS_PIX, PIX_WE ? MA_WRITE : MA_NONE, MT_PIX};",
     "CLASS_DECI[52].MC = '{MAS_RA, MDS_PIX, MA_WRITE, MT_PIX};"),
    ('\t\tDECI = BASE_DECI ^ CLASS_DELTA;\n', '''\t\tDECI = BASE_DECI ^ CLASS_DELTA;
\t\tDECI_AT_PRE = DECI.MC.AT;
\t\tOPSEL_COMB = {DECI.AIA,DECI.AIB,DECI.SHC,DECI.F,DECI.MC.AS,DECI.MC.DS};
\t\t// Registered predecode of the same (IC,STATE)-only fields.
\t\tif (OPSEL_REG) {DECI.AIA,DECI.AIB,DECI.SHC,DECI.F,DECI.MC.AS,DECI.MC.DS} = OPSEL;
\t\t// Class 52 state 18 (PATS_B pixel write) writes only when PIX_WE.
\t\tif (IC_MATCHES[52] && STATE_OH[18] && !PIX_WE) DECI.MC.AT = MA_NONE;
'''),
]
expected = generated
for before, after in decoder_transforms:
    assert expected.count(before) == 1, repr(before)
    expected = expected.replace(before, after, 1)
assert current_text(ID) == expected, 'Current decoder differs from the exact generated and operand-select transformations'
restored = expected
for before, after in reversed(decoder_transforms):
    assert restored.count(after) == 1, repr(after)
    restored = restored.replace(after, before, 1)
assert restored == generated, 'Decoder transformation guard is not reversible'
assert helper.strip() in current_text(PKG), 'Current static decode helper or RF-address function differs'
cpu = current_text(CPU)
for identity in (
    'assert (IC_MATCHES == DecodeICMatches(IC))',
    'assert (IC_RF_ADDR == DecodeICRFAddress(IC,STATE,0) && IC_RF_ADDR_POS == DecodeICRFAddress(IC,STATE,1))',
    'assert (IC_RS_STATIC == DecodeICRS(IC))',
    'assert (OPSEL == OPSEL_COMB)',
):
    assert identity in cpu, 'A separately exercised shipping CPU identity assertion is missing'
target = Path('R:/Verilator/BT') / ('io-cpu_opcodes-' + uuid.uuid4().hex)
target.mkdir(parents=True, exist_ok=False)
retained = ROOT / 'tests/graphics/evidence/io-phase' / target.name
retained.mkdir(parents=True, exist_ok=False)
sources = {}
files = []
for name in (PKG, ID):
    data = current_bytes(name)
    sources[name] = sha(data)
    path = target / Path(name).name
    path.write_bytes(data)
    files.append(str(path))
bench_original = (ROOT / TB).read_text()
bench = bench_original.replace('DecInstr_t candidate, reference;', '''DecInstr_t candidate, reference, registered_candidate;
  OpSel_t reference_opsel, combinational_opsel, registered_opsel;
  MemAccess_t access_pre, registered_access_pre, reference_access_pre;
  assign reference_opsel={reference.AIA,reference.AIB,reference.SHC,reference.F,reference.MC.AS,reference.MC.DS};
  assign reference_access_pre=(flags[52] && STATE_OH[18]) ? MA_WRITE : reference.MC.AT;''', 1)
base_instance = next(line for line in bench.splitlines() if 'TMS34020_ID dut(' in line)
new_instance = base_instance.replace('.DECI(candidate)', ".OPSEL('0),.OPSEL_COMB(combinational_opsel),.DECI_AT_PRE(access_pre),.DECI(candidate)")
registered_instance = base_instance.replace('TMS34020_ID dut(', "TMS34020_ID #(.OPSEL_REG(1'b1)) registered_dut(").replace('.DECI(candidate)', '.OPSEL(reference_opsel),.OPSEL_COMB(registered_opsel),.DECI_AT_PRE(registered_access_pre),.DECI(registered_candidate)')
bench = bench.replace(base_instance, new_instance + '\n' + registered_instance, 1)
bench = bench.replace('          checks++;', '''          assert(registered_candidate === reference)
            else $fatal(1,"Registered opcode decode mismatch IC=%h state=%0d profile=%0d candidate=%h reference=%h",IC,STATE,profile,registered_candidate,reference);
          assert(combinational_opsel === reference_opsel && registered_opsel === reference_opsel)
            else $fatal(1,"Operand-select decode differs from immutable decoder IC=%h state=%0d profile=%0d",IC,STATE,profile);
          assert(access_pre === reference_access_pre && registered_access_pre === reference_access_pre)
            else $fatal(1,"Pre-PIX_WE access decode differs from original truth IC=%h state=%0d profile=%0d",IC,STATE,profile);
          checks++;''', 1)
assert bench.count('assert(candidate === reference)') == bench_original.count('assert(candidate === reference)') == 1
bench_file = target / Path(TB).name
bench_file.write_bytes(bench.encode())
files.append(str(bench_file))
sources[TB] = sha((ROOT / TB).read_bytes())
retained_bench = retained / 'cpu_opcode_equivalence_current_tb.sv'
retained_bench.write_bytes(bench.encode())
sources[retained_bench.relative_to(ROOT).as_posix()] = sha(bench.encode())
for name in (CPU, SDC, GENERATOR, 'tests/graphics/qualify_bt_current_opcode.py'):
    sources[name] = sha(current_bytes(name))
oracle_file = retained / 'TMS34020_ID_IMMUTABLE.sv'
oracle_file.write_bytes(oracle)
compiled_oracle = target / 'TMS34020_ID_REFERENCE.sv'
compiled_oracle.write_bytes(oracle.replace(b'module TMS34020_ID', b'module TMS34020_ID_REFERENCE', 1))
assert oracle.count(b'module TMS34020_ID') == 1
files.append(str(compiled_oracle))
sources[oracle_file.relative_to(ROOT).as_posix()] = sha(oracle)
helper_file = retained / 'generated_helpers.svh'
helper_file.write_bytes(helper.encode())
sources[helper_file.relative_to(ROOT).as_posix()] = sha(helper_file.read_bytes())
command = ['D:/vibes/fpga/bin/verilator.exe', '--binary', '--assert', '--timing', '-j', '4',
           '--threads', '1', '--top-module', 'cpu_opcode_equivalence_tb', '--Mdir', str(target / 'obj'),
           '-Wno-fatal', '-MAKEFLAGS',
           'CXX=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe LINK=D:/vibes/fpga/toolchains/msys64/ucrt64/bin/g++.exe',
           '-CFLAGS', '-DVL_TIME_CONTEXT -std=c++17',
           '-LDFLAGS', '-static-libstdc++ -static-libgcc', *files]
environment = dict(os.environ, MISTER_DIFF_HEADLESS='1', VERILATOR_PROJECT='BT',
                   VERILATOR_WORKSPACE=str(target), VERILATOR_RAM_WORKSPACE=str(target))
flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
with (target / 'build.log').open('w') as log:
    build = subprocess.run(command, cwd=target, env=environment, stdout=log,
                           stderr=subprocess.STDOUT, creationflags=flags)
run_command = [str(target / 'obj/Vcpu_opcode_equivalence_tb.exe')]
run_code = None
if build.returncode == 0:
    with (target / 'run.log').open('w') as log:
        run = subprocess.run(run_command, cwd=target, env=environment, stdout=log,
                             stderr=subprocess.STDOUT, creationflags=flags)
    run_code = run.returncode
log_path = target / ('run.log' if run_code is not None else 'build.log')
output = log_path.read_text(errors='replace')
passed = build.returncode == 0 and run_code == 0 and \
    'PASS opcode predecode: all 65536 opcodes, 32 states, 3 condition profiles, 6291456 complete-control comparisons' in output
assert all(sha(current_bytes(name)) == digest for name, digest in sources.items()), \
    'Current or retained input changed during qualification'
receipt = {
    'schema': 'bt-current-immutable-opcode-v1', 'snapshot': str(target), 'sources': sources,
    'production_source_overlay': str(source_root), 'bound_input_paths': bound_inputs,
    'text_guard_normalization': 'LF/CRLF only; actual raw compiled source hashes retained.',
    'canonical_lf_text_hashes': canonical_text_hashes,
    'command': command, 'run_command': run_command, 'compile_exit_code': build.returncode,
    'run_exit_code': run_code, 'exit_code': 0 if passed else (build.returncode or run_code or 1),
    'oracle_commit': COMMIT, 'oracle_original_sha256': ORIGINAL_ID_SHA,
    'current_generated_decoder_and_helpers_exact': True,
    'later_operand_select_transform_exact_and_reversible': True,
    'registered_and_combinational_decode_compared_to_immutable': True,
    'decoder_transforms': decoder_transforms,
    'original_decoder_scope_preserved': True,
    'generated_classes': {'cases': cases, 'labels': labels, 'predicates': len(predicates)},
    'coverage': {'opcodes': 65536, 'states': 32, 'condition_profiles': 3, 'profiles_checked': 6291456, 'complete_control_comparisons': 12582912, 'operand_select_comparisons': 12582912, 'pre_pixel_write_access_comparisons': 12582912} if passed else {},
    'scope': 'Complete immutable/current instruction decoder, both OPSEL_REG settings, current static helpers, and pre-PIX_WE access truth across every opcode/state/condition profile. The registered decoder receives immutable reference operand fields; actual shipping CPU register capture/phase ownership requires the separately source-bound native replay and its unchanged OPSEL identity assertion. No whole-package history or physical RAM qualification claimed.',
}
(retained / 'receipt.json').write_text(json.dumps(receipt, indent=2))
for name in ('build.log', 'run.log'):
    if (target / name).exists():
        shutil.copyfile(target / name, retained / name)
print(output[-2200:])
print('receipt=' + str(retained / 'receipt.json'))
sys.exit(receipt['exit_code'])
