"""Strict additive v22 -> v23 source/proof composition, without simulations."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
BUILD=ROOT/'build'
SCHEMA='bt-v23-current-input-bg-cpu-foreground-composition-v1'
STATUS='PASS_SCOPED_COMPOSITION'
PINS={
 'snapshot':('build/timing_closure_20261011/pixel_cpu_fg_v23_private-snapshot.json','627f642c9490ce2ffeb532313e33e750a1b67997b2d99a46f3a2cc564d6f6e67'),
 'parent_snapshot':('build/timing_closure_20261011/q17_local_paths_v22_private-snapshot.json','339bf281bad4f0235b0effb5b1b468a9ac6854421634aaec8d489bcc93520aed'),
 'parent_helper':('tests/graphics/bind_bt_final_local_path_inputs.py','dc9afeda406af59888e359758eefb8fcb0cbae6ea2495701cd764a8fa9528e59'),
 'parent_receipt':('build/final_v22_current_input_qualification_r1/receipt.json','4f48189efdab4e0daacce817def75901f02ccc7d92011d04e8028ddcd2fbbc95'),
 'parent_native':('build/native_lcell_link_v22_v1/qualified-128-r1/receipt.json','9d0dcd907838171d1ece06d91c831342cb9271387d781a453abd56c96ed21c20'),
 'parent_native_creator':('build/native_lcell_link_v22_v1/qualify_128.py','cf96e10c1c22d806de9a186b4036b1174ffd5a5f3fab5fa60f6aea7372a05e9c'),
 'bg_edge':('build/bg_pixel_predicates_v22_v1/source-edge-r2/manifest.json','f419ccbc4948b1c1291530139c6a19dcca86fbd0e8df72043dda6166eb21e4f1'),
 'bg_preparer':('tests/graphics/prepare_bt_bg_pixel_predicates.py','7e6a30d68bce8271e45cc68bbfec4314f57ef91ac1eaf3430216ae191346cf4d'),
 'bg_qualifier':('tests/graphics/qualify_bt_bg_pixel_predicates.py','fe020fa70b2a7ff2ec586d0990fe1c388b0b3123d3bf6d377928ed8fe7216305'),
 'bg_proof':('build/bg_pixel_predicates_v22_v1/proof-r2/receipt.json','89b5703b84005df70c6cddb3a192078be9e2745a7919cc29f8ae34bbc81ed19c'),
 'bg_algebra_helper':('tests/graphics/prove_bt_bg_predicate_algebra.py','eb84cd02ada8a0b86b866921fee4e1315cf702acbdbe1935c6abb2f902f5cbf3'),
 'bg_algebra_proof':('build/bg_pixel_predicates_v22_v1/algebra-proof-r1/receipt.json','db5e4ee7c704295d98bf318a7c982fb5d2769fb731dd7c4e27ffc039290f9ee5'),
 'cpu_edge':('build/cpu_zero_flags_v22_v1/manifest.json','e802eb33ac0c518317723ba83e8ccdb7f7c8a17528e02c34259b20ec34da5abd'),
 'cpu_preparer':('tests/graphics/prepare_bt_cpu_zero_flags.py','e2fe780d89aec27b7ffdfc2f81ddaa41d29e2649416c9a34cee13d2b02034d8b'),
 'cpu_qualifier':('tests/graphics/qualify_bt_cpu_zero_flags.py','5cbd5b265d9c03e022699642906cfbfa0766c06d5112630ca3cd1e56c3240cca'),
 'cpu_proof':('build/cpu_zero_flags_v22_v1/proof-r1/receipt.json','d9f9d3c2b18d1a656937bc29d34fd47e85391ef5c6b10a126fccbff0ea99551b'),
 'fg_edge':('build/fg_remote_factor_v22_v1/source-edge/manifest.json','c738899089523d46ab8f84643901523ade17af382b4fc66f78db03ece4c1d12a'),
 'fg_preparer':('tests/graphics/prepare_bt_fg_remote_v22.py','22c16d0a471085613d8d166363c9ff39fff744ca81ca3b3d335cf828a9bfef28'),
 'fg_qualifier':('tests/graphics/qualify_bt_fg_remote_v22.py','e8d2ed46c52611ab899269572d8b38f19ccf95881356227853d3e2e78d244496'),
 'fg_aggregate':('build/fg_remote_factor_v22_v1/qualification.json','db419773fe3fc02d8fc751b59f1556a452147b38a9d58b30483ba2b836acadb5'),
 'fg_audit_helper':('build/fg_remote_factor_v22_v1/finalize_remote_v22.py','eec9eedcfb43a80dd9c2f6fcbf1a6e7066bc4509a5f5edf780dd679cb7a4a539'),
}
CHANGED=('rtl/BT.sv','rtl/bg_vram.sv','rtl/TMS34020/TMS34020.sv','rtl/fg_vram.sv')

def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
    if not value:raise AssertionError(message)
def normal(value):return json.loads(json.dumps(value))
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module

class Evidence:
    def __init__(self):self.files={}
    def file(self,path,digest=None):
        path=Path(path)
        require(not path.is_symlink(),'symlink evidence is not accepted')
        path=path.resolve();data=path.read_bytes();actual=sha(data)
        if digest is not None:require(actual==digest,f'changed retained artifact: {path}')
        key=str(path);require(key not in self.files or self.files[key]==actual,'conflicting evidence digest')
        self.files[key]=actual;return data
    def json(self,path,digest=None):return json.loads(self.file(path,digest))
    def record(self,record):
        data=self.file(record['path'],record['sha256'])
        if 'bytes' in record:require(len(data)==record['bytes'],'changed artifact size')
        return data
    def ingest(self,ledger):
        require(isinstance(ledger,dict),'explicit digest ledger required')
        for path,digest in ledger.items():self.file(path,digest)
    def tree(self,value):
        if isinstance(value,dict):
            if isinstance(value.get('path'),str) and isinstance(value.get('sha256'),str):self.record(value)
            for child in value.values():
                if isinstance(child,(dict,list)):self.tree(child)
        elif isinstance(value,list):
            for child in value:self.tree(child)
    def recheck(self):
        for path,digest in tuple(self.files.items()):require(sha(Path(path).read_bytes())==digest,'evidence changed during qualification')

def pin(name,evidence):
    path,digest=PINS[name];return evidence.file(ROOT/path,digest)
def pinned_json(name,evidence):return json.loads(pin(name,evidence))
def module(name,evidence):
    pin(name,evidence);return load(ROOT/PINS[name][0],'v23_'+name)

def render_fg(meta,q,evidence):
    """Reproduce the executed remote-factor inputs in memory, no runner invoked."""
    old=q.load(q.OLD,'v23_frozen_fg_control_runtime')
    evidence.file(q.OLD,q.OLD_SHA)
    edge=evidence.json(meta['edge']['path'],meta['edge']['sha256'])
    parent=evidence.record(edge['oracle']);candidate=evidence.record(edge['candidate'])
    result={}
    for relative in ('rtl/BT_mem.sv','rtl/ddram.sv','rtl/bt_fg_ddr_clear.sv'):
        record=meta['parent_sources'][relative];result[Path(relative).name]=evidence.record(record)
    for relative in ('tests/graphics/ram_models.sv','tests/foreground_ddr_tb.sv'):
        record=meta['parent_sources'][relative];result[Path(relative).name]=evidence.record(record)
    result['fg_vram.sv']=candidate
    reference=parent.decode('latin1');names=re.findall(r'^module\s+(\w+)',reference,re.M)
    for name in sorted(names,key=len,reverse=True):
        reference=re.sub(r'\b'+re.escape(name)+r'\b',name+'_REFERENCE',reference)
    require(names==meta['namespace_modules'],'reference namespace adapter changed')
    result['reference-fg_vram.sv']=reference.encode('latin1')
    vendor=evidence.file(old.VENDOR,old.VENDOR_SHA)
    primitive=re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule',vendor,re.S)[0]
    require(sha(primitive)==old.PRIMITIVE_SHA,'Intel primitive body changed')
    result['intel_lcell.v']=b'`timescale 1ps/1ps\n'+primitive+b'\n'
    original=evidence.file(old.TB,old.TB_SHA)
    text=old.canonical(original).decode('latin1');extra=q.additions()
    require(meta['assertion_additions']==extra,'actual full-fixture assertions changed')
    text=text.replace('  initial begin\n',extra+'  initial begin\n',1)
    marker='    $display("PASS serial chunk complete pins/state:'
    report='    $display("PASS FG v22 remote control: checks=%0d",fg_v22_remote_checks);\n'
    if meta['profile']=='four-state':
        report+='    assert(fg_remote_v22_fourstate_tb.done) else $fatal(1,"FG remote exhaustive proof unfinished");\n'
    require(text.count(marker)==1 and report==meta['report_addition'],'fixture report adapter changed')
    text=text.replace(marker,report+marker,1)
    require(text.replace(extra,'',1).replace(report,'',1)==old.canonical(original).decode('latin1'),
            'original full-pin assertions and stimulus must remain exact')
    result['item4_foreground_equivalence_tb.sv']=text.encode('latin1')
    fragment,hashes=q.make_fragment(parent,candidate)
    require(hashes==meta['fragment_hashes'],'actual remote source fragment changed')
    result['fg_remote_v22_fourstate_tb.sv']=fragment
    adapters={}
    if meta['profile']=='four-state':
        evidence.file(old.ORDER,old.ORDER_SHA)
        order=old.load(old.ORDER,old.ORDER_SHA,'v23_retained_decl_order')
        for name in ('fg_vram.sv','reference-fg_vram.sv'):
            raw=result[name];canonical=old.canonical(raw)
            result[name],detail=order.declaration_order(canonical,old.ORDER_NAMES)
            adapters[name]={'raw_sha256':sha(raw),'canonical_sha256':sha(canonical),
                            'newline_edge':'CRLF to LF',**detail}
        name='item4_foreground_equivalence_tb.sv'
        result[name],adapters[name]=order.declaration_order(result[name],('DRAW_ADDR',))
    require(normal(adapters)==meta['declaration_order_adapters'],'declaration-only adapter changed')
    actual={Path(path).name:(path,digest) for path,digest in meta['compiled_inputs'].items()}
    require(set(result)==set(actual),'complete actual compiler source inventory required')
    for name,data in result.items():
        path,digest=actual[name];require(sha(data)==digest and evidence.file(path,digest)==data,
                                      f'FG actual compiler input is not regenerated: {name}')
    for path,digest in meta['executed_helpers'].items():
        evidence.file(path,digest)
    return {name:sha(data) for name,data in result.items()}

def bind_fg(evidence):
    q=module('fg_qualifier',evidence);audit=module('fg_audit_helper',evidence)
    aggregate=pinned_json('fg_aggregate',evidence);evidence.tree(aggregate)
    require(aggregate['schema']=='bt-v22-fg-remote-aggregate-qualification-v1' and aggregate['status']=='PASS',
            'actual FG aggregate qualification required')
    require(aggregate['compiled_bytes_regenerated_equal'] and aggregate['collision_masks_added']==0
            and aggregate['case_equality_exclusions']==0 and not aggregate['intel_ram_or_timing_or_hardware_claim'],
            'FG scope/exclusions changed')
    proofs=[]
    for record in aggregate['proofs']:
        rp=Path(record['receipt']['path']);proof=json.loads(evidence.record(record['receipt']))
        meta=json.loads(evidence.record(record['preparation']))
        evidence.tree(proof);evidence.tree(meta)
        evidence.ingest(meta['compiled_inputs']);evidence.ingest(meta['executed_helpers'])
        coverage=audit.reparse(proof,rp,meta,q)
        require(coverage==record['parsed_coverage'],'FG independently reparsed counts changed')
        regenerated=render_fg(meta,q,evidence)
        proofs.append(dict(profile=meta['profile'],receipt=str(rp),sha256=record['receipt']['sha256'],
                           coverage=coverage,regenerated_actual_compiled_inputs=regenerated))
    require({p['profile'] for p in proofs}=={'native','four-state'},'both actual FG profiles required')
    return dict(actual_profiles=proofs,default_off_fixture_abi_scope=aggregate['suite_data_abi_scope'],
                control_identity_independent_of_data_ABI=True,new_mapped_or_native_claim=False)

def check_native_claim(rec):
    require(rec['schema']=='bt-current-v22-native128-lcell-raster-qualification-v1'
            and rec['status']=='PASS_ACTUAL_NATIVE128_AND_24_RASTERS','actual v22 native qualification required')
    require(rec['selected_snapshot_sha256']==PINS['parent_snapshot'][1]
            and rec['functional_composition_sha256']==PINS['parent_receipt'][1],'parent native source proof changed')
    require(rec['requested_frames']==128 and rec['actual_native_exit_code']==0
            and rec['actual_complete_cycles']==172308065 and rec['actual_DDR_commands']==2878478
            and rec['actual_logged_phase_frames_checked']==[1,128],'actual parent native counts changed')
    require(rec['actual_last_frame_DDR_phase']=={
      'frame':128,'captures':2573046,'cpu':279286,'sprite':0,'fg0':1146880,'fg1':1146880,
      'launch_age_checks':2573046,'ext_reloads':53513164,'fs_reloads':660076,'ba_reloads':1014,
      'buf_reloads':660076,'min_ext':5,'min_fs':5,'min_ba':5,'min_buf':3,
      'probe_checks':171038303,'conservative_false':2486591},'actual final native phase changed')
    require(rec['compiler_top']=='BT_NATIVE_SIM' and rec['compiled_primitive_input_count']==1
            and rec['actual_compiled_physical_input_files']==31
            and rec['selected_full144_source_inventory_checked'] is True
            and rec['unchanged_per_capture_assertions_enabled_throughout_128_frames'] is True,'actual native compiler scope changed')
    require(rec['native_system_top_reset_partition_compiled'] is False
            and rec['mapped_timing_RBF_hardware_MAME_claim'] is False
            and rec['old_native128_receipts_or_rasters_modified'] is False,'native scope improperly broadened')
    require(rec['failures']==[] and rec['comparison_count']==24 and len(rec['actual_byte_comparisons'])==24,
            'all24 actual raster comparisons required')
    require(len(rec['retained_inputs_logs_and_executable'])==47,'all47 retained actual native artifacts required')

def bind_native(evidence):
    rec=pinned_json('parent_native',evidence);check_native_claim(rec)
    evidence.ingest(rec['retained_inputs_logs_and_executable'])
    evidence.file(rec['selected_snapshot'],rec['selected_snapshot_sha256'])
    evidence.file(rec['functional_composition'],rec['functional_composition_sha256'])
    actual=evidence.json(rec['native_receipt'],rec['native_receipt_sha256'])
    evidence.file(rec['previous_comparison_receipt'],rec['previous_comparison_receipt_sha256'])
    pin('parent_native_creator',evidence)
    rows=[];keys=[]
    for row in rec['actual_byte_comparisons']:
        require(row['byte_equal'] is True,'native raster comparison failed')
        data=[evidence.file(row[key+'_path'],row[key+'_sha256']) for key in ('reference','previous_native','current')]
        require(data[0]==data[1]==data[2] and len(data[2])==row['bytes'],'actual raw raster bytes changed')
        keys.append((row['kind'],row['name']));rows.append(dict(kind=row['kind'],name=row['name'],sha256=sha(data[2])))
    require(len(set(keys))==24,'native raster names duplicated')
    logs=[]
    for path in rec['retained_inputs_logs_and_executable']:
        if Path(path).suffix=='.log':
            text=Path(path).read_text(errors='replace')
            if 'NATIVE_COMPLETE frames=' in text:logs.append(text)
    require(len(logs)==1,'exact single retained actual native run log required')
    require(re.findall(r'NATIVE_COMPLETE frames=(\d+) cycles=(\d+) DDR_commands=(\d+)',logs[0])
            ==[('128','172308065','2878478')],'raw native completion count changed')
    require(not re.search(r'(?im)\b(?:fatal|assertion failed|FAIL(?:ED)?)\b',logs[0]),'actual native log failed')
    return dict(receipt=str(ROOT/PINS['parent_native'][0]),sha256=PINS['parent_native'][1],
                raw_rasters=rows,actual_compiled_input_files=31,actual_frames=128,
                reported_phase_frames=[1,128],assertions_active_throughout_128=True,
                production_top_reset_partition_compiled=False,fresh_v23_native_claim=False)

def source_edges(current,parent,evidence):
    bg=module('bg_preparer',evidence);bg_meta=pinned_json('bg_edge',evidence)
    bg_files,_=bg.verify_edge(ROOT/PINS['bg_edge'][0].rsplit('/',1)[0])
    cpu=module('cpu_preparer',evidence);cpu_meta=pinned_json('cpu_edge',evidence)
    cpu.verify_edge(Path(cpu_meta['candidate_directory']))
    fg=module('fg_preparer',evidence);fg_meta=pinned_json('fg_edge',evidence)
    result={}
    for relative in CHANGED:
        before=parent[relative];after=current[relative]
        if relative in bg_files:
            old,new,edits=bg_files[relative]
            require(before==old and after==new and bg.inverse(after,edits)==before
                    and bg.forward(before,edits)==after,'BG full raw source inverse failed')
        elif relative=='rtl/TMS34020/TMS34020.sv':
            require(cpu.reverse(after)==before and cpu.transform(before)==after,'CPU full raw source inverse failed')
            require(sha(after)==cpu_meta['candidate_sha256'],'CPU candidate changed')
        else:
            require(fg.reverse(after,fg_meta['edits'])==before
                    and fg.forward(before,fg_meta['edits'])==after,'FG full raw source inverse failed')
            fg.source_proof(before,after,fg_meta['edits'])
            require(sha(after)==fg_meta['candidate']['sha256'],'FG candidate changed')
        result[relative]=dict(parent_sha256=sha(before),candidate_sha256=sha(after),whole_file_raw_inverse=True)
    return result

def source_controls(current,parent,evidence):
    controls=[]
    for relative in CHANGED:
        bad=dict(current);bad[relative]=bad[relative]+b'\n'
        try:source_edges(bad,parent,evidence)
        except AssertionError:controls.append(relative+':unrelated-byte-change')
        else:raise AssertionError('changed source was accepted')
    for relative,before,after,name in (
        ('rtl/bg_vram.sv',b'SQ_NZ <= SERIAL_NZ_D;',b'SQ_NZ <= SQ;','old-SQ-extra-edge'),
        ('rtl/bg_vram.sv',b'SQ_HIGH <= SERIAL_BYTE_D[7];',b'SQ_HIGH <= SERIAL_BYTE_D[0];','wrong-high-bit'),
        ('rtl/BT.sv',b'BG1_PIX_NZ = BG1_SQ_NZ[0];',b'BG1_PIX_NZ = BG1_SQ_NZ[1];','wrong-bank-predicate'),
        ('rtl/BT.sv',b'bit BG0_PIX_NZ, BG1_PIX_NZ, BG1_PIX_HIGH;',b'bit BG0_PIX_NZ, BG1_PIX_NZ, BG1_PIX_HIGH;\n\t\tBG0_PIX_NZ=0;','new-predicate-reset-or-hold')):
        require(current[relative].count(before)==1,'mutation target must be exact')
        bad=dict(current);bad[relative]=bad[relative].replace(before,after,1)
        try:source_edges(bad,parent,evidence)
        except AssertionError:controls.append(name)
        else:raise AssertionError('wrong predicate source was accepted')
    return controls

def bind_current(source_root):
    source_root=Path(source_root).resolve();e=Evidence()
    snapshot=pinned_json('snapshot',e);previous=pinned_json('parent_snapshot',e)
    old=module('parent_helper',e);parent=pinned_json('parent_receipt',e)
    parent_validation=old.verify_composition_receipt(ROOT/PINS['parent_receipt'][0])
    e.ingest(parent['bound_evidence_files'])
    require(snapshot['parent_snapshot_sha256']==PINS['parent_snapshot'][1]
            and set(snapshot['sources'])==set(previous['sources']) and len(snapshot['sources'])==144,
            'exact selected144 source inventory required')
    current={};before={}
    for relative,digest in snapshot['sources'].items():
        current[relative]=e.file(source_root/relative,digest)
        before[relative]=e.file(Path(parent['source_root'])/relative,previous['sources'][relative])
    changed=tuple(relative for relative in snapshot['sources'] if current[relative]!=before[relative])
    require(set(changed)==set(CHANGED) and len(changed)==4,'all and only four v23 sources may change')
    edges=source_edges(current,before,e)
    bg_q=module('bg_qualifier',e);bg=pinned_json('bg_proof',e);e.ingest(bg['retained_files'])
    bg_validation=bg_q.verify_composition_receipt(ROOT/PINS['bg_proof'][0])
    algebra_q=module('bg_algebra_helper',e);algebra=pinned_json('bg_algebra_proof',e);e.ingest(algebra['retained_files'])
    algebra_validation=algebra_q.verify_composition_receipt(ROOT/PINS['bg_algebra_proof'][0])
    cpu_q=module('cpu_qualifier',e);cpu=pinned_json('cpu_proof',e);e.ingest(cpu['bound_evidence_files'])
    cpu_validation=cpu_q.verify_composition_receipt(ROOT/PINS['cpu_proof'][0])
    fg_validation=bind_fg(e);native=bind_native(e)
    result=dict(schema=SCHEMA,status=STATUS,helper_sha256=sha(Path(__file__).read_bytes()),source_root=str(source_root),
                snapshot=str(ROOT/PINS['snapshot'][0]),snapshot_sha256=PINS['snapshot'][1],
                all144_source_inventory_entries_verified=True,only_changed_sources=list(CHANGED),unchanged_sources=140,
                parent_v22_receipt=str(ROOT/PINS['parent_receipt'][0]),parent_v22_receipt_sha256=PINS['parent_receipt'][1],
                parent_validation=parent_validation,raw_source_composition=edges,
                scoped_proofs=dict(bg=bg_validation,bg_arbitrary_four_state_induction=algebra_validation,
                                   cpu=cpu_validation,fg=fg_validation),actual_parent_v22_native128=native,
                new_source_corruption_controls=source_controls(current,before,e),
                immutable_git_oracles=parent['immutable_git_oracles'],case_equality_exclusions=0,collision_masks_added=0,
                new_compiler_or_simulator_run=False,new_whole_board_native_run=False,
                mapped_replication_proven=False,core_timing_accepted=False,timing_accepted=False,eligible_for_RBF=False,
                root_RTL_SDC_or_old_evidence_modified=False,
                limits=['New BG proof compiles complete old/current BG with unchanged qualified RAM adapter; RAM storage body is unchanged.',
                        'Per-bank bit predicates hold in the original SYS selection branches; no new SYS byte stage or clock latency.',
                        'FG full-pin fixture retains default-off bank ABI; universal remote control equality is independent of data values.',
                        'Actual v22 native128 and24 rasters are inherited only within their compiler scope; fresh v23 replay is separate.',
                        'Production top/HPS/physical mapped topology and all-corner timing/pad gates remain separate.'])
    return result,e

def verify_claim(result,expected):
    require(normal(result)==normal(expected),'changed current-source receipt/claims')

def claim_controls(expected):
    controls=[]
    for key,value in (('unchanged_sources',141),('snapshot_sha256','0'*64),('new_whole_board_native_run',True),
                      ('timing_accepted',True),('eligible_for_RBF',True),('collision_masks_added',1)):
        bad=copy.deepcopy(expected);bad[key]=value
        try:verify_claim(bad,expected)
        except AssertionError:controls.append(key)
        else:raise AssertionError('wrong proof claim was accepted')
    return controls

def verify_composition_receipt(path):
    path=Path(path).resolve();result=json.loads(path.read_bytes())
    require(result['schema']==SCHEMA and result['status']==STATUS,'wrong v23 receipt schema/status')
    require(result['helper_sha256']==sha(Path(__file__).read_bytes()),'executed source binder changed')
    expected,evidence=bind_current(result['source_root'])
    evidence.record(result['executed_helper']);expected['executed_helper']=result['executed_helper']
    expected['new_claim_corruption_controls']=claim_controls(expected)
    expected['bound_evidence_files']=dict(evidence.files)
    verify_claim(result,expected);evidence.recheck()
    return dict(status=STATUS,receipt=str(path),receipt_sha256=sha(path.read_bytes()),sources=144,unchanged_sources=140,
                verified_evidence_files=len(evidence.files),verified_immutable_git_oracles=len(result['immutable_git_oracles']),
                source_corruption_controls=8,claim_corruption_controls=6,
                actual_parent_v22_native_frames=128,fresh_v23_native_or_timing_claim=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();require(not out.exists(),'exclusive new receipt output required')
    result,evidence=bind_current(args.source_root)
    out.mkdir(parents=True);helper=out/Path(__file__).name;helper.write_bytes(Path(__file__).read_bytes())
    result['executed_helper']=dict(path=str(helper),sha256=sha(helper.read_bytes()),bytes=helper.stat().st_size)
    evidence.record(result['executed_helper'])
    result['new_claim_corruption_controls']=claim_controls(result);result['bound_evidence_files']=dict(evidence.files)
    target=out/'receipt.json';target.write_text(json.dumps(normal(result),indent=2)+'\n')
    validated=verify_composition_receipt(target)
    (out/'verification.json').write_text(json.dumps(validated,indent=2)+'\n');print(json.dumps(validated))

if __name__=='__main__':main()
