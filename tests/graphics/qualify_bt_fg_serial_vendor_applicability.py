"""Compose strict unchanged Intel physical evidence onto the minimal FG edge."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT=Path(__file__).resolve().parents[2]
VENDOR=ROOT/'tests/graphics/evidence/vram-physical/vram-current-c37fbfc0d0cb409dae7e0692f8f4598f/receipt.json'
VENDOR_SHA='a5b9a3f59a05bba6faaf30cb5f833f6368e4754f0e1c8e7642bc558c1987e9d8'
V11=ROOT/'build/timing_closure_20261011/address_ddr_v11_physical_applicability.json'
V11_SHA='67696d57a1a03b17cabd6b5479f330eced907d47e618d649ebf72a823a86318f'
PARENT=ROOT/'build/timing_closure_20261011/vram_request_v12_private'
EDGE=ROOT/'build/fg_serial_controls_v12_v2'
CPU='rtl/TMS34020/TMS34020.sv';MC='rtl/TMS34020/TMS34020_MC.sv';FG='rtl/fg_vram.sv'
sha=lambda data:hashlib.sha256(data).hexdigest()


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def pinned(path,expected):
    data=path.read_bytes();assert sha(data)==expected,(str(path),'source/log fingerprint changed');return data


def lf(data):
    text=data.decode().replace('\r\n','\n');assert '\r' not in text;return text


def path(value):
    return Path(value.replace('\\\\','\\'))


def reject(label,action,controls):
    try:
        action()
    except AssertionError:
        controls.append({'name':label,'rejected':True});return
    raise AssertionError('Negative control accepted: '+label)


def same_digest(data,expected):
    assert sha(data)==expected


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--pin-receipt',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();current=args.source_root.resolve();output=args.output.resolve()
    current.relative_to(ROOT/'build');output.relative_to(ROOT/'build');assert not output.exists()
    snapshot_path=current.parent/(current.name+'-snapshot.json')
    snapshot=json.loads(snapshot_path.read_bytes())
    assert len(snapshot['sources'])==144
    for name,expected in snapshot['sources'].items():
        pinned(current/name,expected)
    parent_snapshot_path=PARENT.parent/(PARENT.name+'-snapshot.json')
    parent_snapshot=json.loads(parent_snapshot_path.read_bytes())
    changed={name for name in snapshot['sources'] if snapshot['sources'][name]!=parent_snapshot['sources'][name]}
    assert changed=={CPU,MC,FG},('Only declared header/FG edges allowed',changed)
    for name,expected in parent_snapshot['sources'].items():
        pinned(PARENT/name,expected)
    fg_preparer=load(ROOT/'tests/graphics/prepare_bt_fg_serial_controls.py','vendor_fg_preparer')
    original_fg=pinned(PARENT/FG,fg_preparer.BASE_SHA)
    new_fg,edits=fg_preparer.transform(original_fg)
    assert new_fg==(current/FG).read_bytes() and sha(new_fg)=='f3b4c19de2f64d018860a7c3480b0393f4ec9a6f39f004160c1a2c696f84750b'
    fg_preparer.verify_source(original_fg,new_fg,edits)
    decl=load(ROOT/'tests/graphics/prepare_bt_append_debug_ports.py','vendor_decl_preparer')
    for name in [CPU,MC]:
        fixed,_=decl.transform(name,(PARENT/name).read_bytes());assert fixed==(current/name).read_bytes()
    decl_path=ROOT/'build/v12_debug_ports_v1/compiler-proof/receipt.json'
    decl_receipt=json.loads(pinned(decl_path,'91e7e2487f4433b0a7923ebb0d0719324f97455b54371574244a538bbba92f7f'))
    assert decl_receipt['status']=='PASS' and decl_receipt['release_full_tokens_identical']
    assert decl_receipt['functional_bodies_raw_byte_identical']
    pin_path=args.pin_receipt.resolve();pin=json.loads(pin_path.read_bytes())
    assert pin['schema']=='bt-fg-serial-controls-current-parent-full-pin-v2' and pin['status']=='PASS'
    assert pin['candidate_fg_sha256']==sha(new_fg) and pin['parent_sources'][FG]==sha(original_fg)
    assert pin['case_equality_exclusions']==0 and pin['collision_masks_added']==0
    assert pin['original_assertions_preserved'] and pin['source_stability_passed']
    pin_helper=ROOT/'tests/graphics/verify_bt_fg_serial_control_replay.py';pinned(pin_helper,pin['helper_sha256'])
    for filename,expected in pin['retained_logs'].items():
        pinned(Path(filename),expected)
    for filename,record in pin['compiled_inputs'].items():
        pinned(Path(filename),record['sha256']);pinned(Path(record['retained_path']),record['sha256'])
    vendor=json.loads(pinned(VENDOR,VENDOR_SHA));v11=json.loads(pinned(V11,V11_SHA))
    assert vendor['exit_code']==0 and vendor['source_stability_passed']
    assert vendor['intel_model_equivalence_passed'] and not vendor['mapped_atoms_verified']
    assert v11['passed'] and not v11['new_vendor_simulation_performed']
    assert v11['strict_physical_data_x_z_comparison_exclusions']==0
    vendor_helper=load(ROOT/'tests/graphics/qualify_current_vram_vendor.py','vendor_module_extract')
    pinned(Path(vendor_helper.__file__),vendor['sources']['tests/graphics/qualify_current_vram_vendor.py'])
    # The vendor job compiled only these extracted RAM modules, not the full
    # controller. Regenerate its exact slices from the new input and compare.
    current_banked=vendor_helper.module(lf(new_fg),'BT_FG_BANKED_VRAM')
    old_banked=vendor_helper.module(lf(original_fg),'BT_FG_BANKED_VRAM')
    assert current_banked==old_banked
    bank_fixture=next(name for name in vendor['fixtures'] if name.endswith('/fg_banked.sv'))
    assert current_banked==lf(pinned(ROOT/bank_fixture,vendor['fixtures'][bank_fixture]))
    memory=pinned(current/'rtl/BT_mem.sv',vendor['sources']['rtl/BT_mem.sv'])
    current_memory='\n'.join(vendor_helper.module(lf(memory),name) for name in ['VRAM_MEM_64Kx8','VRAM_MEM_SLICE'])
    memory_fixture=next(name for name in vendor['fixtures'] if name.endswith('/memory.sv'))
    assert current_memory==lf(pinned(ROOT/memory_fixture,vendor['fixtures'][memory_fixture]))
    for name,expected in vendor['sources'].items():
        if name==FG:
            continue
        pinned((current if name.startswith('rtl/') else ROOT)/name,expected)
    for name,expected in vendor['fixtures'].items():
        pinned(ROOT/name,expected)
    for name,expected in vendor['external_sources'].items():
        pinned(path(name),expected)
    for name,filename in vendor['actual_source_paths'].items():
        pinned(path(filename),vendor['sources'][name])
    # The full original oracle files remain tied to the immutable Git object.
    git='D:/vibes/fpga/bin/git.EXE'
    git_oracles={}
    for name in [FG,'rtl/BT_mem.sv','rtl/bg_vram.sv','tests/vram_slice_tb.sv']:
        immutable=subprocess.check_output([git,'show',vendor['oracle_ref']+':'+name],cwd=ROOT)
        fixture=next(key for key in vendor['fixtures'] if key.endswith('/oracle/'+name))
        assert sha(immutable)==vendor['fixtures'][fixture]
        git_oracles[name]={'commit':vendor['oracle_ref'],'git_blob_sha256':sha(immutable),'retained_fixture':fixture}
    retained=v11['retained_vendor_receipt']['original_logs_rehashed']
    helper=load(ROOT/'tests/graphics/qualify_bt_address_class_v11.py','v11_strict_logs')
    pinned(Path(helper.__file__),v11['helper_sha256'])
    checked_logs=[]
    for result in vendor['results']:
        assert result['compile_exit_code']==0
        for expected in [result['compile_log_sha256']]:
            entry=next(record for record in retained if record['sha256']==expected)
            pinned(Path(entry['path']),expected);checked_logs.append(entry)
        for run in result['runs']:
            assert run['exit_code']==0 and run['passed']
            entry=next(record for record in retained if record['sha256']==run['log_sha256'])
            data=pinned(Path(entry['path']),entry['sha256'])
            helper.validate_log(data,entry['sha256'],run['markers']);checked_logs.append(entry)
    request_preparer=load(ROOT/'tests/graphics/prepare_bt_vram_request.py','vendor_request_edge')
    before_bt=pinned(request_preparer.BASE_ROOT/'rtl/BT.sv',request_preparer.BASE['rtl/BT.sv'])
    request_bt,_,_=request_preparer.transform('rtl/BT.sv',before_bt)
    assert request_bt==(current/'rtl/BT.sv').read_bytes()
    library=load(ROOT/'tests/graphics/qualify_bt_address_class_r2.py','vendor_ports')
    adapter=load(ROOT/'tests/graphics/bt_vram_request_fixture.py','vendor_instances')
    old_bt,new_bt=lf(before_bt),lf(request_bt);instances={}
    for kind,name in adapter.INSTANCES:
        old_pins=library.instance_ports(old_bt,kind,name)
        new_pins=library.instance_ports(new_bt,kind,name)
        # The strict existing parser accepts only unparameterized instances;
        # unchanged full physical module bytes therefore bind their geometry.
        assert re.search(r'\b'+kind+r'\s+'+name+r'\s*\(',old_bt)
        assert re.search(r'\b'+kind+r'\s+'+name+r'\s*\(',new_bt)
        assert set(old_pins)==set(new_pins)
        assert all(value==new_pins[key] for key,value in old_pins.items() if key!='RAS_N')
        instances[name]={'module':kind,'parameters':'No instance overrides; exact unchanged physical module defaults',
                         'all_non_RAS_pins':old_pins.copy(),
                         'old_RAS_N':old_pins['RAS_N'],'new_RAS_N':new_pins['RAS_N']}
        del instances[name]['all_non_RAS_pins']['RAS_N']
    assert len(instances)==6
    request_truth_path=ROOT/'build/vram_request_v11_v2/truth-proof-qualified.json'
    pinned(request_truth_path,'d30e614e5b920686e641beff1c73fdeff95084c337cbf470b74c9f6cf38a2a63')
    stage_paths=[('616b9707c5d34bf28314687ab3a720fb','b3666d07f4b016a0c9976451494f5d212b23258197cb0a4b47050d2394a0a28e'),
                 ('579b3ec9d47f435bac9aebfbcebcb5a7','62f0f72e28e6752261a16c1b0f806ef93db495ae73daa9ca1996e1235471fc43')]
    stages=[]
    for run_id,expected in stage_paths:
        stage_path=ROOT/'tests/graphics/evidence/ddr-be-bridge'/('ddr-be-bridge-'+run_id)/'receipt.json'
        data=pinned(stage_path,expected);stage=json.loads(data)
        assert stage['exit_code']==0
        stages.append({'path':str(stage_path),'sha256':expected,'scope':'Actual request producer/full original MC and all six RAS pins pre/post MEM edges; unchanged BT and header release-token composition.'})
    controls=[]
    bad_banked=current_banked.replace('SCSEL4[bank][3] ?','SCSEL4[bank][2] ?',1);assert bad_banked!=current_banked
    reject('changed physical serial data pin',lambda:same_digest(bad_banked.encode(),sha(current_banked.encode())),controls)
    bad_geometry,count=re.subn(rb'(parameter\s+(?:integer\s+)?ADDR_WIDTH\s*=\s*)16\b',rb'\g<1>15',memory,count=1)
    assert count==1 and bad_geometry!=memory
    reject('changed physical address geometry',lambda:same_digest(bad_geometry,vendor['sources']['rtl/BT_mem.sv']),controls)
    fixture_name=next(name for name in vendor['fixtures'] if name.endswith('/current_vram_vendor_tb.sv'))
    fixture=(ROOT/fixture_name).read_bytes()
    widened,count=re.subn(rb'(wire\s+\[63:0\]\s+canonical_sq_mask_now\s*=\s*).*?;',rb"\g<1>64'hffffffffffffffff;",fixture,count=1,flags=re.S);assert count==1
    reject('widened canonical collision predicate',lambda:same_digest(widened,vendor['fixtures'][fixture_name]),controls)
    entry=checked_logs[-1];data=Path(entry['path']).read_bytes()
    reject('changed retained Intel transcript',lambda:same_digest(data+b'\n',entry['sha256']),controls)
    reject('false PASS with fresh hash and failure',lambda:helper.validate_log(data+b'\nFAIL altered',sha(data+b'\nFAIL altered'),[]),controls)
    model_path,model_sha=next(iter(vendor['external_sources'].items()));model=path(model_path).read_bytes()
    reject('changed exact Intel model',lambda:same_digest(model+b'\n',model_sha),controls)
    assert all(control['rejected'] for control in controls)
    receipt={'schema':'bt-v13-minimal-fg-strict-physical-applicability-v1','status':'PASS','source_root':str(current),
             'snapshot':str(snapshot_path),'snapshot_sha256':sha(snapshot_path.read_bytes()),'all144_inputs_verified':True,
             'declared_source_delta_names':sorted(changed),'helper_sha256':sha(Path(__file__).read_bytes()),
             'fresh_FG_pin_receipt':{'path':str(pin_path),'sha256':sha(pin_path.read_bytes()),'coverage':pin['coverage']},
             'declaration_release_token_edge':{'path':str(decl_path),'sha256':sha(decl_path.read_bytes())},
             'retained_vendor_receipt':{'path':str(VENDOR),'sha256':VENDOR_SHA,'untouched':True},
             'retained_v11_physical_applicability':{'path':str(V11),'sha256':V11_SHA,'untouched':True},
             'actual_new_input_regenerates_identical_vendor_banked_module_LF_sha256':sha(current_banked.encode()),
             'actual_new_input_regenerates_identical_vendor_memory_modules_LF_sha256':sha(current_memory.encode()),
             'immutable_git_oracles':git_oracles,'all6instances_non_RAS_pins_and_geometry_identical':instances,
             'request_RAS_pin_equivalence':{'truth_receipt':str(request_truth_path),'truth_sha256':sha(request_truth_path.read_bytes()),'fresh_stage_receipts':stages},
             'original_Intel_logs_rehashed':checked_logs,'collision_contract':copy.deepcopy(vendor['canonical_comparison_contract']),
             'preserved_collision_contract_sha256':v11['collision_contract_sha256'],
             'collision_predicate_fixture_sha256':vendor['fixtures'][fixture_name],
             'strict_physical_data_x_z_comparison_exclusions':0,'new_canonical_collision_exclusions':0,
             'negative_controls':controls,'original_v11_negative_controls_preserved':v11['negative_controls'],
             'new_vendor_simulation_performed':False,'mapped_atoms_verified':False,'routed_timing_qualified':False,
             'mister_hardware_qualified':False,'global_validators_modified':False,
             'scope':'Explicit composition of unchanged actual vendor-compiled RAM/FG-banked module bytes, unchanged exact Intel models/fixtures/logs/collision contracts, fresh complete minimal-FG capture pins, and actual request-stage RAS equivalence. '
                     'Existing vendor receipts remain unchanged; this is applicability evidence, not a new Intel, whole-board native, routed timing, mapped or hardware result.'}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':'PASS','receipt':str(output),'sha256':sha(output.read_bytes()),'six_instances':len(instances),'negative_controls':len(controls),'vendor_rerun':False}))


if __name__=='__main__':
    main()
