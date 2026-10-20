"""Fresh native/4-state replay of the guarded v18 FG setup candidate.

The retained original 31-state/all-bank/full-pin fixture is immutable. Its
original assertions and workload are kept, with extra predicate identities.
The RAM model is the unmodified current behavioral model, not Intel storage.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]
BASE = ROOT/'build/timing_closure_20261011/reset_partition_v18_private'
TB = ROOT/'build/fg_serial_controls_v12_v2/full-pin-proof-v2-final-r2-compiled-inputs/item4_foreground_equivalence_tb.sv'
TB_SHA = 'af689824790f60bcce1b309cae68071e91fb693281da99a9c672e9e8978bc9aa'
BOUND = {'rtl/fg_vram.sv':'15ca6106299cebaa05e7651b340c4c908b692385af89a75498bf0d60674cf6ae',
    'rtl/BT_mem.sv':'903aeedc272fd64409ebae8b8624befe82bc1f073d1545310dbeb070afaf6393',
    'rtl/ddram.sv':'ea8b8738afeca05c2dc214cb9a30c946ddb9d3010900ada185d0e180f6987dc9',
    'rtl/bt_fg_ddr_clear.sv':'bb811a37ed3e084eb291e2f1a4f24218aa69dad859223c248261860fd5a6f9d1',
    'tests/graphics/ram_models.sv':'039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc',
    'tests/foreground_ddr_tb.sv':'fd723e62a48b285c8872526720cbf18b30b82e80f908986ce1addef70a21ea3c'}
SHA = lambda data: hashlib.sha256(data).hexdigest()


def load_preparer():
    path = ROOT/'tests/graphics/prepare_bt_fg_setup_q17.py'
    spec = importlib.util.spec_from_file_location('bt_fg_setup_preparer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked(path: Path, expected: str) -> bytes:
    raw = path.read_bytes()
    assert SHA(raw) == expected, ('Frozen source changed', str(path), SHA(raw))
    return raw


def run(command: list[str], cwd: Path, log: Path):
    with log.open('w') as target:
        result = subprocess.run(command, cwd=cwd, stdout=target, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return {'command':command, 'exit_code':result.returncode, 'log':str(log), 'log_sha256':SHA(log.read_bytes())}


def wsl(path: Path) -> str:
    value = path.resolve().as_posix()
    assert value[1] == ':', 'Explicit Windows drive path required'
    return '/mnt/'+value[0].lower()+value[2:]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edge', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profile', choices=('native','four-state'), required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT/'build')
    assert not output.exists(), 'Retain all existing PASS and FAIL evidence'
    edge = args.edge.resolve()
    manifest = json.loads((edge/'manifest.json').read_text())
    preparer = load_preparer()
    assert manifest['helper_sha256'] == SHA(Path(preparer.__file__).read_bytes())
    parent = checked(Path(manifest['parent_path']), BOUND['rtl/fg_vram.sv'])
    candidate = checked(Path(manifest['candidate_path']), manifest['candidate_sha256'])
    preparer.verify_source(parent,candidate,manifest['edits'])
    originals, source_paths = {}, {}
    for name, expected in BOUND.items():
        path = (ROOT if name.startswith('tests/') else BASE)/name
        originals[name] = checked(path, expected)
        source_paths[name] = str(path)
    original_tb = checked(TB, TB_SHA)
    output.mkdir(parents=True)
    inputs = output/'inputs'
    inputs.mkdir()
    for name,data in originals.items():
        (inputs/Path(name).name).write_bytes(candidate if name=='rtl/fg_vram.sv' else data)
    reference = parent.decode()
    modules = re.findall(r'^module\s+(\w+)',reference,re.M)
    for module in sorted(modules,key=len,reverse=True):
        reference = re.sub(r'\b'+re.escape(module)+r'\b',module+'_REFERENCE',reference)
    (inputs/'reference-fg_vram.sv').write_bytes(reference.encode())
    tb = original_tb.decode().replace('\r\n','\n')
    extra = '''
  integer setup_predicate_checks=0;
  always @(negedge CLK) begin
    #0.1;
    if(RST_N) begin
      setup_predicate_checks++;
      assert(candidate.COPY_READ_REQUEST_M === {8{!reference.RAS_N_M && !reference.OE_N_M && reference.WE_N_M && reference.TRANSFER_M}})
        else $fatal(1,"same-edge current read decode differs");
      assert(candidate.RDY_COPY_COLLECT === (reference.COPY_STATE==3'd3) &&
             candidate.HOLE_POS_END_RAM_B === {3{reference.SREG_POS==9'h1f8}} &&
             candidate.HOLE_POS_END_DDR_B === {3{reference.SREG_POS==9'h1fe}})
        else $fatal(1,"same-edge state/position decode differs");
      assert(candidate.RDY_LOCAL_UNALIGNED_NEXT === reference.RDY_NEXT_UNALIGNED_EXEC &&
             candidate.RDY_LOCAL_COPY_WE === reference.RDY_NEXT_COPY_WE)
        else $fatal(1,"ready Boolean priority differs");
      assert(candidate.serial_copy_address[0].next_addr === reference.HOLE_NEXT_ADDR &&
             candidate.serial_copy_address[1].next_addr === reference.HOLE_NEXT_ADDR &&
             candidate.serial_copy_address[2].next_addr === reference.HOLE_NEXT_ADDR &&
             candidate.serial_copy_address[3].next_addr === reference.HOLE_NEXT_ADDR)
        else $fatal(1,"local current-copy address priority differs");
    end
  end
'''
    anchor = '  initial begin\n'
    assert tb.count(anchor) >= 1
    tb = tb.replace(anchor,extra+anchor,1)
    marker = '    $display("PASS serial chunk complete pins/state:'
    assert tb.count(marker) == 1
    tb = tb.replace(marker,'    $display("PASS FG setup same-edge predicates: checks=%0d",setup_predicate_checks);\n'+marker,1)
    (inputs/'item4_foreground_equivalence_tb.sv').write_text(tb,newline='\n')
    # Prove that the retained fixture, including all old assertions, is exactly
    # reconstructed by removing only this declared addition.
    inverse = tb.replace(extra,'',1).replace('    $display("PASS FG setup same-edge predicates: checks=%0d",setup_predicate_checks);\n','',1)
    assert inverse == original_tb.decode().replace('\r\n','\n')
    metadata = {'schema':'bt-fg-setup-v18-replay-inputs-v1','profile':args.profile,
        'manifest':str(edge/'manifest.json'),'manifest_sha256':SHA((edge/'manifest.json').read_bytes()),
        'helper_path':str(Path(__file__).resolve()),'helper_sha256':SHA(Path(__file__).read_bytes()),
        'parent_sources':BOUND,'source_paths':source_paths,'candidate_sha256':SHA(candidate),
        'original_tb_path':str(TB),'original_tb_sha256':TB_SHA,'oracle_namespace_modules':modules,
        'compiled_inputs':{str(p):SHA(p.read_bytes()) for p in inputs.iterdir()},
        'original_assertion_workload_inverse':True,'new_assertions':extra,
        'case_equality_exclusions':0,'collision_masks_added':0,'intel_primitive_claim':False,
        'new_register_bits':15,'timing_or_hardware_claim':False}
    (output/'preparation.json').write_text(json.dumps(metadata,indent=2)+'\n')
    records=[]
    if args.profile == 'native':
        checks=[('fg','item4_foreground_equivalence_tb',['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','item4_foreground_equivalence_tb.sv']),
                ('fg-ddr','foreground_ddr_tb',['fg_vram.sv','ddram.sv','bt_fg_ddr_clear.sv','ram_models.sv','foreground_ddr_tb.sv'])]
        for label,top,files in checks:
            target=output/label;target.mkdir()
            # Explicit Ubuntu WSL; no extensionless ELF is launched by Windows.
            command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec','verilator',
                '--binary','--assert','--timing','-j','4','--threads','1','--x-initial','unique','--x-assign','unique',
                '--top-module',top,'--Mdir',wsl(target/'obj'),'-Wno-fatal',*files]
            record=run(command,inputs,target/'build.log');records.append(record)
            if record['exit_code']:break
            record=run(['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec',
                wsl(target/'obj'/('V'+top))],inputs,target/'run.log');records.append(record)
            if record['exit_code']:break
    else:
        # Four-state canonical RAM replay of the identical complete fixture;
        # simulator primitive/packing/collision applicability remains separate.
        tool=Path('D:/q17/modelsim_ase/win32aloem')
        work=output/'work'
        records.append(run([str(tool/'vlib.exe'),str(work)],output,output/'vlib.log'))
        if records[-1]['exit_code']==0:
            records.append(run([str(tool/'vlog.exe'),'-sv','-work',str(work),*[str(inputs/name) for name in
                ['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','item4_foreground_equivalence_tb.sv']]],
                output,output/'build.log'))
        if records[-1]['exit_code']==0:
            records.append(run([str(tool/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib',str(work),
                'item4_foreground_equivalence_tb','-do','run -all; quit -code 0'],output,output/'run.log'))
    passed=all(record['exit_code']==0 for record in records)
    run_log=output/('fg/run.log' if args.profile=='native' else 'run.log')
    coverage={}
    if passed and run_log.exists():
        text=run_log.read_text(errors='replace')
        match=re.search(r'PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)',text)
        pred=re.search(r'PASS FG setup same-edge predicates: checks=(\d+)',text)
        passed=bool(match and pred and not re.search(r'\b(fatal|fail(?:ed)?|error)\b',text,re.I))
        if passed:
            coverage={'states':31,'ram_banks':4,'ram_pin_fields':13,'state_edges':int(match[1]),
                'bank_edge_checks':int(match[2]),'same_edge_predicate_checks':int(pred[1]),
                'comparison':'case equality before/after every RAM edge','reset_restart_abort_workload':True}
            assert coverage['state_edges']>100000 and coverage['same_edge_predicate_checks']>100000
            assert 'restart_collisions=8 abort_collisions=8 reset_collects=2' in text
            assert 'PASS item4 RMT/control corners:' in text
        if passed and args.profile=='native':
            ddr=(output/'fg-ddr/run.log').read_text(errors='replace')
            marker='PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure'
            passed=marker in ddr and not re.search(r'\b(fatal|fail(?:ed)?|error)\b',ddr,re.I)
            coverage.update(cold_clear_writes=196608,masked_writes=128,copy_bytes=512)
    for name,path in source_paths.items():checked(Path(path),BOUND[name])
    checked(Path(manifest['candidate_path']),manifest['candidate_sha256'])
    for path,expected in metadata['compiled_inputs'].items():checked(Path(path),expected)
    receipt={'schema':'bt-fg-setup-v18-current-parent-replay-v1','status':'PASS' if passed else 'FAIL',
        'profile':args.profile,'preparation':str(output/'preparation.json'),
        'preparation_sha256':SHA((output/'preparation.json').read_bytes()),'records':records,
        'coverage':coverage,'original_assertions_preserved':True,'case_equality_exclusions':0,
        'collision_masks_added':0,'intel_primitive_claim':False,'mapped_or_timing_claim':False}
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'receipt':str(output/'receipt.json'),'sha256':SHA((output/'receipt.json').read_bytes()),
        'status':receipt['status'],'coverage':coverage},separators=(',',':')))
    raise SystemExit(0 if passed else 1)


if __name__ == '__main__':
    main()
