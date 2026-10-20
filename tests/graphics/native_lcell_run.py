"""Native board replay with one byte-exact Intel LCELL simulation model.

The old native runner, fixture and RAM adapter remain immutable. An explicit
three-edit worker projection only freezes/hashes/links the additional model.
Its source overlay pins the selected RTL. The native board does not compile
the production emu top or its reset partition and does not qualify hardware.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[2]
PARENT=ROOT/'tests/graphics/native_run.py'
PARENT_SHA='3a81f2d5e5b37733bb3e7220bf81b301bc655c3dccb33c3ed795c0cab3f8f4e4'
MODEL=ROOT/'tests/graphics/intel_lcell_sim.v'
VENDOR=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA='c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'
LCELL_SHA='4012bc0467a7c3844315fd56d3c0d12d62fab6ef1050d55f06f617b47784eb0e'
RAM_SHA='039f6ead2da5edfeaa0bf4aeb45eb7795ccf3e57e6193ea3e7763a41ae2cdafc'
FIXTURE_SHA='725836f4dd1ffe937859dadfdf0a1085ff3fceb6a62ba96cf5dabb1346943e43'

def sha(data):
    return hashlib.sha256(data).hexdigest()

def shipped_model(vendor):
    assert sha(vendor)==VENDOR_SHA
    module=re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule',vendor,re.S)[0]
    assert sha(module)==LCELL_SHA
    license_header=b''.join(vendor.splitlines(keepends=True)[:15])
    return license_header+b'\n// Exact scalar LCELL body from the installed Quartus 17.0.2 Intel library.\n'+b'`timescale 1 ps / 1 ps\n'+module+b'\n'

def transform(parent):
    assert sha(parent)==PARENT_SHA, 'Frozen native runner required'
    newline=b'\r\n' if b'\r\n' in parent else b'\n'
    changes=[
        (b"for name in ('native_sim.sv','native.cpp','ram_models.sv'):",
         b"for name in ('native_sim.sv','native.cpp','ram_models.sv','intel_lcell_sim.v'):"),
        (b"    files += [target/'native_sim.sv']",
         b"    files += [target/'intel_lcell_sim.v',target/'native_sim.sv']"),
        (b"sources['tests/graphics/native_run.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()"+newline,
         b"sources['tests/graphics/native_run.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()"+newline+
         b"sources['tests/graphics/native_lcell_run.py']=LCELL_SHIM_SHA"+newline+
         b"sources['generated/native_lcell_worker.py']=LCELL_WORKER_SHA"+newline),
    ]
    worker=parent
    for old,new in changes:
        assert worker.count(old)==1
        worker=worker.replace(old,new,1)
    assert inverse(worker,changes)==parent
    return worker,changes

def inverse(worker,changes):
    for old,new in reversed(changes):
        assert worker.count(new)==1
        worker=worker.replace(new,old,1)
    return worker

def mixer_scope(top):
    text=top.decode().replace('\r\n','\n')
    begin=text.index('\twire DCLK = VCE_R;')
    end=text.index('\n\tend',begin)+len('\n\tend')
    ce=re.search(r'\.ce_pix\(([^\n]+)\)',text)[1].rstrip(',')
    return (text[begin:end]+'\nassign MIX_CE='+ce+';\n').encode()

def main():
    p=argparse.ArgumentParser(add_help=False)
    p.add_argument('--source-snapshot',type=Path,required=True)
    p.add_argument('--source-snapshot-sha256',required=True)
    p.add_argument('--qualification-output',type=Path,required=True)
    p.add_argument('--prepare-only',action='store_true')
    a,forwarded=p.parse_known_args()
    assert '--source-overlay' not in forwarded, 'The selected snapshot determines the complete RTL overlay'
    assert not a.qualification_output.exists(), 'Proof directory must be fresh'
    snapshot_raw=a.source_snapshot.read_bytes()
    assert sha(snapshot_raw)==a.source_snapshot_sha256
    selected=json.loads(snapshot_raw)
    assert len(selected['sources'])==144
    selected_root=Path(selected['project']).resolve().parent
    for name,wanted in selected['sources'].items():
        assert sha((selected_root/name).read_bytes())==wanted, ('Selected source changed',name)
    parent=PARENT.read_bytes()
    worker,changes=transform(parent)
    model=MODEL.read_bytes()
    vendor=VENDOR.read_bytes()
    assert model==shipped_model(vendor)
    assert sha((ROOT/'tests/graphics/ram_models.sv').read_bytes())==RAM_SHA
    fixture=(ROOT/'tests/graphics/native_sim.sv').read_bytes()
    # The actual current fixture is independently pinned by the retained native graph.
    assert sha(fixture)==FIXTURE_SHA, 'Frozen actual-reload native fixture changed'
    assert mixer_scope((selected_root/'Arcade-Battletoads.sv').read_bytes())==mixer_scope((ROOT/'Arcade-Battletoads.sv').read_bytes())
    overlay={}
    for name,wanted in selected['sources'].items():
        if not name.startswith('rtl/'):
            continue
        current=(ROOT/name).read_bytes()
        if sha(current)!=wanted:
            assert Path(name).suffix=='.sv', ('Unsupported native input difference',name)
            overlay[name]={'path':str((selected_root/name).resolve()),'sha256':wanted,'baseline_sha256':sha(current)}
    assert overlay, 'This selected private replay must have an explicit RTL overlay'
    a.qualification_output.mkdir(parents=True)
    worker_path=a.qualification_output/'native_lcell_worker.py'
    worker_path.write_bytes(worker)
    overlay_path=a.qualification_output/'source-overlay.json'
    overlay_path.write_text(json.dumps({'schema':1,'files':overlay},indent=2)+'\n')
    controls=[]
    def reject(name,operation):
        try:
            operation()
        except (AssertionError,ValueError):
            controls.append({'name':name,'rejected':True});return
        raise AssertionError('Negative control accepted: '+name)
    reject('changed frozen native parent',lambda:transform(parent+b'\n'))
    reject('model freeze omitted',lambda:inverse(worker.replace(b",'intel_lcell_sim.v'",b'',1),changes))
    reject('compiler model binding omitted',lambda:inverse(worker.replace(b"target/'intel_lcell_sim.v',",b'',1),changes))
    reject('worker source recorder omitted',lambda:inverse(worker.replace(b"sources['generated/native_lcell_worker.py']=LCELL_WORKER_SHA",b'',1),changes))
    reject('shipped vendor library changed',lambda:shipped_model(vendor+b'\n'))
    def model_identity(data):
        assert data==shipped_model(vendor)
    reject('model logic inverted',lambda:model_identity(model.replace(b'out = in',b'out = ~in',1)))
    preparation={'schema':'bt-native-lcell-link-preparation-v1','status':'PASS_STATIC_LINK_PROJECTION',
                 'selected_snapshot':str(a.source_snapshot.resolve()),'selected_snapshot_sha256':sha(snapshot_raw),
                 'full_selected_input_files':144,'selected_rtl_overlay':overlay,
                 'legacy_runner':str(PARENT),'legacy_runner_sha256':PARENT_SHA,
                 'shim':str(Path(__file__).resolve()),'shim_sha256':sha(Path(__file__).read_bytes()),
                 'actual_executed_worker':str(worker_path.resolve()),'actual_executed_worker_sha256':sha(worker),
                 'whole_worker_source_inverse_to_legacy_runner':True,
                 'model':str(MODEL),'model_sha256':sha(model),'vendor':str(VENDOR),'vendor_sha256':VENDOR_SHA,
                 'exact_vendor_scalar_body_sha256':LCELL_SHA,'model_direct_compiler_binding':True,
                 'ram_models_unchanged_sha256':RAM_SHA,'native_fixture_unchanged_sha256':sha(fixture),
                 'mixer_enable_slice_selected_equal_root':True,'mixer_enable_slice_sha256':sha(mixer_scope((ROOT/'Arcade-Battletoads.sv').read_bytes())),
                 'changes':[{'old':old.decode(),'new':new.decode()} for old,new in changes],
                 'negative_controls':controls,'legacy_assertions_and_runtime_unchanged':True,
                 'old_receipts_modified_or_retagged':False,'native_system_top_reset_partition_compiled':False,
                 'scope':'Explicit current selected RTL overlay into BT_NATIVE_SIM plus actual Intel scalar LCELL model. Native compiles the game board/CPUs/controller/graphics/audio and identical mixer slice; production emu/HPS/platform/top reset partition are not compiled. This is new native evidence, never a retag of old128 frames or an FPGA timing/hardware/MAME claim.'}
    (a.qualification_output/'preparation.json').write_text(json.dumps(preparation,indent=2)+'\n')
    if a.prepare_only:
        print(json.dumps({'status':preparation['status'],'preparation':str(a.qualification_output/'preparation.json'),'main_run_executed':False}));return
    namespace={'__file__':str(PARENT),'__name__':'__main__',
               'LCELL_SHIM_SHA':preparation['shim_sha256'],'LCELL_WORKER_SHA':sha(worker)}
    original_argv=sys.argv
    sys.argv=[str(PARENT),*forwarded,'--source-overlay',str(overlay_path.resolve())]
    sys.path.insert(0,str(PARENT.parent))
    code=0
    try:
        exec(compile(worker,str(worker_path),'exec'),namespace)
    except SystemExit as ex:
        code=ex.code or 0
    finally:
        sys.argv=original_argv
    target=Path(namespace['target'])
    native_receipt=ROOT/'tests/graphics/evidence/native'/target.name/'receipt.json'
    assert native_receipt.is_file(), ('Retained native compile/runtime failure',target,code)
    inner=json.loads(native_receipt.read_text())
    result={'schema':'bt-current-native-lcell-link-replay-v1','status':'PASS' if code==0 and inner.get('exit_code')==0 else 'FAIL',
            'preparation':str(a.qualification_output/'preparation.json'),
            'preparation_sha256':sha((a.qualification_output/'preparation.json').read_bytes()),
            'native_receipt':str(native_receipt),'native_receipt_sha256':sha(native_receipt.read_bytes()),
            'actual_worker_sha256':sha(worker_path.read_bytes()),'model_sha256':sha(model),
            'selected_snapshot_sha256':sha(snapshot_raw),'native_sim_top':'BT_NATIVE_SIM',
            'system_top_reset_partition_compiled':False,'old128frame_evidence_retagged':False,
            'hardware_timing_or_MAME_claim':False,'exit_code':code,'scope':preparation['scope']}
    (a.qualification_output/'receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    assert sha(PARENT.read_bytes())==PARENT_SHA and MODEL.read_bytes()==model
    assert sha((ROOT/'tests/graphics/ram_models.sv').read_bytes())==RAM_SHA and (ROOT/'tests/graphics/native_sim.sv').read_bytes()==fixture
    assert result['status']=='PASS', ('Retained fresh current native failure',result)
    print(json.dumps({'receipt':str(a.qualification_output/'receipt.json'),'sha256':sha((a.qualification_output/'receipt.json').read_bytes()),'status':result['status']}))

if __name__=='__main__':
    main()
