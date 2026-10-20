"""Strictly finalize retained minimal-FG runs; this never launches a simulator."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
PREPARED = ROOT / 'build/fg_serial_controls_v12_v2/full-pin-proof-v2'
EXECUTED_HELPER_SHA = '5660d1ce08e8ad68f306b82b73b15425d739afbac5925d1c436d46e3a85b0c15'
WORKER_SHA = '3be1c0ac9e6c750438d72937ce5e364c8864da99cfd5714de8cae8b02e354803'
DDR_MARKER = 'PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure'
sha = lambda data: hashlib.sha256(data).hexdigest()


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def check(data, expected):
    assert sha(data) == expected
    return data


def log_checks(text, fg):
    assert not re.search(r'\b(fatal|fail|error)\b', text, re.I)
    if not fg:
        assert DDR_MARKER in text
        return {'cold_clear_writes':196608,'masked_writes':128,'round_trip_bytes':512}
    markers = [
        'PASS item4 copy control corners: collect_cycles=106593 restart_collisions=8 abort_collisions=8 reset_collects=2;',
        'PASS item4 RMT/control corners: ram_cycles=13036 ddr_cycles=309223 ram_finish_restart=1 ddr_finish_restart=1 mode_changes=103 aborts=2 active_resets=202 history_falls=757 history_rises=757 hole_changes=920;',
        'PASS serial chunk complete pins/state: state_edges=1263909 bank_edge_checks=10111272 states=31 pin_fields=13;',
        'PASS foreground transaction equivalence: transactions=262 comparisons=107750',
    ]
    assert all(marker in text for marker in markers)
    return {'transactions':262,'original_transaction_comparisons':107750,'full_original_state_edges':1263909,
            'original_states':31,'bank_before_after_edge_checks':10111272,'RAM_fields_per_check':13,
            'copy_collect_cycles':106593,'restart_collisions':8,'abort_collisions':8,'reset_collects':2,
            'RMT_RAM_cycles':13036,'RMT_DDR_cycles':309223,'RMT_mode_changes':103,
            'RMT_aborts':2,'RMT_active_resets':202,'RAM_finish_restart':1,'DDR_finish_restart':1,
            'history_falls':757,'history_rises':757,'hole_changes':920}


def reject(label, action, controls):
    try:
        action()
    except AssertionError:
        controls.append({'name':label,'rejected':True})
        return
    raise AssertionError('Negative control accepted: '+label)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    output=args.output.resolve();output.relative_to(ROOT/'build')
    assert not output.exists(), 'Keep all executed/accepted receipts immutable'
    qualifier_path=ROOT/'tests/graphics/qualify_bt_fg_serial_controls.py'
    qualifier=load(qualifier_path,'fg_replay_qualifier')
    old=check((PREPARED/'helper-executed.py').read_bytes(),EXECUTED_HELPER_SHA)
    old_marker=b"assert 'PASS' in text and '196608' in text and '128512' in text"
    replacement=("assert '"+DDR_MARKER+"' in text").encode()
    assert old.count(old_marker)==1 and qualifier_path.read_bytes()==old.replace(old_marker,replacement,1)
    preparation_path=PREPARED/'preparation.json'
    preparation=json.loads(preparation_path.read_bytes())
    assert preparation['helper_sha256']==EXECUTED_HELPER_SHA
    assert preparation['worker_sha256']==WORKER_SHA and preparation['parent_sources']==qualifier.BOUND
    assert preparation['candidate_fg_sha256']==qualifier.FINAL_FG
    assert preparation['original_assertions_preserved'] and preparation['RAM_collision_masks_added']==0
    check((PREPARED/'worker.py').read_bytes(),WORKER_SHA)
    check(qualifier.CREATOR.read_bytes(),qualifier.CREATOR_SHA)
    assert re.fullmatch(r'fg-serial-controls-[0-9a-f]{32}',preparation['run_name'])
    retained=ROOT/'build'/preparation['run_name']
    executed_path=retained/'receipt.json';executed=json.loads(executed_path.read_bytes())
    assert executed['all_passed'] and [x['test'] for x in executed['results']]==['fg','fg-ddr']
    assert all(x['exit_code']==0 for x in executed['results'])
    assert executed['sources']['rtl/fg_vram.sv']==qualifier.FINAL_FG
    assert executed['sources']['baseline:rtl/fg_vram.sv']==qualifier.BOUND['rtl/fg_vram.sv']
    source_paths=preparation['source_paths']
    for name,expected in qualifier.BOUND.items():
        check(Path(source_paths[name]).read_bytes(),expected)
        check((PREPARED/'oracle'/name).read_bytes(),expected)
        check((PREPARED/'candidate'/name).read_bytes(),qualifier.FINAL_FG if name=='rtl/fg_vram.sv' else expected)
    candidate=check((qualifier.EDGE/'candidate/rtl/fg_vram.sv').read_bytes(),qualifier.FINAL_FG)
    preparer=load(ROOT/'tests/graphics/prepare_bt_fg_serial_controls.py','fg_replay_preparer')
    parent=Path(source_paths['rtl/fg_vram.sv']).read_bytes()
    generated,edits=preparer.transform(parent);assert generated==candidate
    preparer.verify_source(parent,candidate,edits)
    logs,coverage={},{}
    for record in executed['results']:
        for filename in ['build.log','run.log']:
            path=retained/record['test']/filename;data=path.read_bytes()
            logs[str(path)]=sha(data)
            if filename=='run.log':
                coverage[record['test']]=log_checks(data.decode(errors='replace'),record['test']=='fg')
    compiled={}
    fixture_dir=output.parent/(output.stem+'-compiled-inputs')
    assert not fixture_dir.exists();fixture_dir.mkdir(parents=True)
    for record in executed['results']:
        for name in record['command']:
            if not name.endswith('.sv'):
                continue
            path=Path(name);data=path.read_bytes()
            target=fixture_dir/path.name
            if target.exists():
                assert target.read_bytes()==data
            else:
                target.write_bytes(data)
            compiled[str(path)]={'sha256':sha(data),'retained_path':str(target)}
    assert any(name.endswith('item4_foreground_equivalence_tb.sv') for name in compiled)
    controls=[]
    fg_log=(retained/'fg/run.log').read_text()
    ddr_log=(retained/'fg-ddr/run.log').read_text()
    reject('false PASS with runtime failure',lambda:log_checks(fg_log+'\nFATAL regression',True),controls)
    reject('missing original transaction coverage',lambda:log_checks(fg_log.replace('transactions=262','transactions=261'),True),controls)
    reject('missing complete original state comparisons',lambda:log_checks(fg_log.replace('state_edges=1263909','state_edges=0'),True),controls)
    reject('reduced DDR round trip',lambda:log_checks(ddr_log.replace('512 round-trip','511 round-trip'),False),controls)
    reject('changed executable worker/assertions',lambda:check((PREPARED/'worker.py').read_bytes()+b'\n#altered',WORKER_SHA),controls)
    reject('changed behavioral RAM model',lambda:check(Path(source_paths['tests/graphics/ram_models.sv']).read_bytes()+b'\n',qualifier.BOUND['tests/graphics/ram_models.sv']),controls)
    reject('changed candidate RAM data/control pin',lambda:check(candidate.replace(b'SCSEL4[bank][3] ?',b'SCSEL4[bank][2] ?',1),qualifier.FINAL_FG),controls)
    receipt={'schema':'bt-fg-serial-controls-current-parent-full-pin-v2','status':'PASS','scope':
             'Strict fresh minimal-FG/current-parent replay validation; preserved executed compiler/simulator receipt. '
             'No simulator rerun, no Intel rerun, no mapped/timing/hardware claim.',
             'helper_sha256':sha(Path(__file__).read_bytes()),'preparation':str(preparation_path),
             'preparation_sha256':sha(preparation_path.read_bytes()),'executed_receipt':str(executed_path),
             'executed_receipt_sha256':sha(executed_path.read_bytes()),'parent_sources':qualifier.BOUND,
             'candidate_fg_sha256':qualifier.FINAL_FG,'source_paths':source_paths,'compiled_inputs':compiled,
             'retained_logs':logs,'coverage':coverage,'original_assertions_preserved':True,
             'case_equality_exclusions':0,'collision_masks_added':0,'source_stability_passed':True,
             'executed_creator_sha256':qualifier.CREATOR_SHA,'executed_worker_sha256':WORKER_SHA,
             'outer_helper_marker_only_edge':{'before_path':str(PREPARED/'helper-executed.py'),
                 'before_sha256':EXECUTED_HELPER_SHA,'after_path':str(qualifier_path),
                 'after_sha256':sha(qualifier_path.read_bytes()),'exact_only_edit':
                 'Validate actual 196608 cold writes / 128 masked writes / 512 bytes marker instead of concatenated historical-count typo.',
                 'generated_worker_candidates_fixtures_unchanged':True,'new_simulation_performed':False},
             'negative_controls':controls,'simulator_return_codes':[x['exit_code'] for x in executed['results']],
             'limitations':'Behavioral adapter run, including case equality, does not model Intel unspecified collision outputs. '
                           'Actual Intel data/X collision evidence applies only through a separate unchanged-physical-module/pin composition.'}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':'PASS','receipt':str(output),'sha256':sha(output.read_bytes()),'coverage':coverage,'negative_controls':len(controls)}))


if __name__=='__main__':
    main()
