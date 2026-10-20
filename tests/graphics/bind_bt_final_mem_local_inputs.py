"""Strict additive current v24 source/proof composition. No simulator is run."""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SCHEMA='bt-v24-current-input-memory-local-composition-v1'
STATUS='PASS_SCOPED_COMPOSITION'
PINS={
 'snapshot':('build/timing_closure_20261011/mem_local_paths_v24_private-snapshot.json','014b565d404e7a345568df0453979fbcf0c76f114c0698f57b5ad2fa8582a28e'),
 'parent_snapshot':('build/timing_closure_20261011/pixel_cpu_fg_v23_private-snapshot.json','627f642c9490ce2ffeb532313e33e750a1b67997b2d99a46f3a2cc564d6f6e67'),
 'parent_helper':('tests/graphics/bind_bt_v23_native_replay.py','f5fb29372587c8b5c75114da893cc078622076fc2da634d686031dc3825ecc2b'),
 'parent_receipt':('build/final_v23_native_input_qualification_r1/receipt.json','7a1a8becbe3f6e2fdd2027935824fb1288d4293ecc9eb31a52c12d37ae9588b6'),
 'evidence_helper':('tests/graphics/bind_bt_final_bg_cpu_fg_inputs.py','cb4b37258d2ade627c25660fb722de87787f9df5975d4fae3804f98a251eef00'),
 'composition':('build/timing_closure_20261011/v24_overlay_inputs/composition.json','ccb88c38617e56a9c06b4033746e295549e0f3cbb65749ebc4d204a66c3ceafd'),
 'bg_preparer':('tests/graphics/prepare_bt_bg_scroll_mem.py','a76c9c81b9bef8f226dbe7f8ebce78d0d6acd927ff126170c18b9ff1a4a7cb9e'),
 'bg_edge':('build/bg_scroll_mem_v23_v1/source-edge/manifest.json','eff9927b299461459701b9d248bd3b54910346ad60c8a2aef42674b2e873ae7c'),
 'bg_qualifier':('tests/graphics/qualify_bt_bg_scroll_mem.py','577d202b3aadc3bb2563b0562a5a94eed9a8349496a3626aeb06720476c83041'),
 'bg_proof':('build/bg_scroll_mem_v23_v1/proof-r2/receipt.json','0d19c3b65777402f600b4ef598e6a6cf57615b4acea80f01f48897f2cfd5af73'),
 'sprite_preparer':('tests/graphics/prepare_bt_sprite_data_v23.py','817f6d75714aba2a88649401dacab65f20d20c4790c84da2c3d16ec78a7931d6'),
 'sprite_edge':('build/sprite_data_local_v23_v1/source-edge/manifest.json','919de9d7c389dee904047e029221711ee5e6c86201c1ebfca590f990e5d99008'),
 'ddr_preparer':('tests/graphics/prepare_bt_ddr_busy_local.py','c995605c85c58951cfbe128f75f62367ccb5732bbfdbd14f0100a035a9426215'),
 'ddr_edge':('build/ddr_busy_local_v23_v1/manifest.json','65b4356c150a77b27e299b0682c5e811df359530a71a7c185d7dabfb9bd8f031'),
}
# Decisive fresh helper/receipt pins are populated only after their jobs close.
PROOFS={
 'sprite':dict(helper='tests/graphics/qualify_bt_sprite_data_v23.py',
   helper_sha256='3aa0d58d4bc4cd61f9fd68a55ce820ff3cc5148fc7a6eb62856ea34d0251b6e0',
   verifier='tests/graphics/verify_bt_sprite_data_v23.py',
   verifier_sha256='02fdeee68bc835f21f1f6dd396d049f5d04ea27244fdfef3f2c04419e4da705a',
   profiles={
    'vendor':('build/sprite_data_local_v23_v1/vendor-proof-r5/receipt.json',
      '62582631a47d50c95c1c6921c58732723614573b8156272701d30803029b4bc5'),
    'native-fg':('build/sprite_data_local_v23_v1/native-fg-proof-r2/receipt.json',
      '582bdea2b22b9a1d25ac0ec13d03eed885a28fc9290d31ffa427c180e13db32a'),
    'four-state-fg':('build/sprite_data_local_v23_v1/four-state-fg-proof-r1/receipt.json',
      '5c86d6f9b003fa49575070e840fb697539d64e650ae990af6b6e1d189a1527eb')}),
 'ddr':dict(helper='tests/graphics/qualify_bt_ddr_busy_local.py',
   helper_sha256='b6f498b8470b2f0e73534567e3947d2fb6788739f89ae93fa9507db7ba84e22f',
   receipt='build/ddr_busy_local_v23_v1/proof-r1/receipt.json',
   receipt_sha256='822e859fe6be763d501c35b75cbaeec6db406e82a3e5f59bf2034c15b78f6fbe'),
}
CHANGED=('rtl/BT.sv','rtl/bg_vram.sv','rtl/ddram.sv','rtl/fg_vram.sv','rtl/spr_vram.sv')

def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
    if not value:raise AssertionError(message)
def normal(value):return json.loads(json.dumps(value))
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module);return module

def pinned(name,evidence):
    path,digest=PINS[name];return evidence.file(ROOT/path,digest)
def pinned_json(name,evidence):return json.loads(pinned(name,evidence))
def module(name,evidence):
    pinned(name,evidence);return load(ROOT/PINS[name][0],'v24_'+name)

def source_graph(current,before,bg,sprite,ddr,bg_meta,sprite_meta,ddr_meta):
    bg_edits=bg_meta['files']['rtl/BT.sv']['edits'];sprite_edits=sprite_meta['BT_connection_edits']
    parent=before['rtl/BT.sv'];candidate=current['rtl/BT.sv']
    left=bg.forward(sprite.forward(parent,sprite_edits),bg_edits)
    right=sprite.forward(bg.forward(parent,bg_edits),sprite_edits)
    require(left==right==candidate,'actual combined BT must equal both independent forward orders')
    require(bg.inverse(sprite.inverse(candidate,sprite_edits),bg_edits)==parent
            and sprite.inverse(bg.inverse(candidate,bg_edits),sprite_edits)==parent,
            'both full raw combined BT inverse orders must recover immutable v23')
    require(len(bg_edits)==8 and len(sprite_edits)==5,'all and only the declared BT binding edits required')
    graph={'rtl/BT.sv':dict(parent_sha256=sha(parent),candidate_sha256=sha(candidate),
          both_raw_forward_orders_identical=True,both_raw_inverse_orders_exact=True,bg_edits=8,sprite_edits=5)}
    relative='rtl/bg_vram.sv';record=bg_meta['files'][relative]
    require(bg.forward(before[relative],record['edits'])==current[relative]
            and bg.inverse(current[relative],record['edits'])==before[relative], 'full actual BG operand-stage inverse failed')
    graph[relative]=dict(parent_sha256=sha(before[relative]),candidate_sha256=sha(current[relative]),whole_raw_file_inverse=True)
    for relative in ('rtl/fg_vram.sv','rtl/spr_vram.sv'):
        record=sprite_meta['files'][relative]
        require(sprite.forward(before[relative],record['edits'])==current[relative]
                and sprite.inverse(current[relative],record['edits'])==before[relative], 'full actual sprite/FG raw inverse failed')
        graph[relative]=dict(parent_sha256=sha(before[relative]),candidate_sha256=sha(current[relative]),whole_raw_file_inverse=True)
    relative='rtl/ddram.sv';expected,edits=ddr.transform(before[relative])
    require(expected==current[relative] and edits==ddr_meta['edits']
            and ddr.reverse(current[relative],edits)==before[relative], 'full actual DDR busy-cone inverse failed')
    graph[relative]=dict(parent_sha256=sha(before[relative]),candidate_sha256=sha(current[relative]),whole_raw_file_inverse=True)
    return graph

def source_controls(current,before,*args):
    checks=[]
    for relative in CHANGED:
        wrong=dict(current);raw=current[relative];wrong[relative]=bytes([raw[0]^1])+raw[1:]
        try:source_graph(wrong,before,*args)
        except (AssertionError,ValueError):checks.append(dict(name='unrelated raw edit '+relative,rejected=True))
        else:raise AssertionError('full-file source corruption was accepted')
    targets=[('rtl/BT.sv',b'.SCROLL_OFFSET(SCROLL1)',b'.SCROLL_OFFSET(SCROLL0)','wrong scroll bank'),
      ('rtl/bg_vram.sv',b'reg [15:0] base_m',b'bit [15:0] base_m','early unknown coercion'),
      ('rtl/bg_vram.sv',b'base_m <= SCROLL_BASE;',b'base_m <= A_M;','new address latency'),
      ('rtl/fg_vram.sv',b'CPU_SHIFT_SOURCE_D = SQ_D | (COPY_WORD & {64{COPY_WE}})',
          b'CPU_SHIFT_SOURCE_D = SQ_D ^ (COPY_WORD & {64{COPY_WE}})','wrong FG packet D'),
      ('rtl/spr_vram.sv',b'fg_packet_data_q <= FG_PACKET_D;',b'fg_packet_data_q <= CPU_SHIFT_DATA;','old-Q packet latency')]
    for relative,old,new,name in targets:
        require(old in current[relative],'source rejection anchor missing: '+name)
        wrong=dict(current);wrong[relative]=wrong[relative].replace(old,new,1)
        try:source_graph(wrong,before,*args)
        except (AssertionError,ValueError):checks.append(dict(name=name,rejected=True))
        else:raise AssertionError('semantic source corruption accepted: '+name)
    return checks

def bind_source(source_root):
    evidence_path=ROOT/PINS['evidence_helper'][0]
    require(sha(evidence_path.read_bytes())==PINS['evidence_helper'][1],'strict evidence helper changed')
    support=load(evidence_path,'v24_frozen_evidence_support');e=support.Evidence()
    e.file(evidence_path,PINS['evidence_helper'][1])
    snapshot=pinned_json('snapshot',e);previous=pinned_json('parent_snapshot',e)
    parent=pinned_json('parent_receipt',e);parent_helper=module('parent_helper',e)
    parent_validation=parent_helper.verify_composition_receipt(ROOT/PINS['parent_receipt'][0])
    e.ingest(parent['bound_evidence_files'])
    require(snapshot['parent_snapshot_sha256']==PINS['parent_snapshot'][1] and len(snapshot['sources'])==144
            and set(snapshot['sources'])==set(previous['sources']),'complete unchanged source inventory contract required')
    source_root=Path(source_root).resolve();current={};before={}
    for relative,digest in snapshot['sources'].items():
        current[relative]=e.file(source_root/relative,digest)
        before[relative]=e.file(Path(parent['source_root'])/relative,previous['sources'][relative])
    actual=[relative for relative in current if current[relative]!=before[relative]]
    require(set(actual)==set(CHANGED) and len(actual)==5,'all and only five actual source inputs may change')
    composition=pinned_json('composition',e)
    require(composition['schema']=='bt-v24-background-sprite-binding-composition-v1'
            and composition['status']=='PASS_SOURCE_COMPOSITION_ONLY'
            and composition['candidate_sha256']==sha(current['rtl/BT.sv'])
            and composition['parent_bt_sha256']==sha(before['rtl/BT.sv']), 'wrong independent combined-source freeze')
    bg=module('bg_preparer',e);bg_meta=pinned_json('bg_edge',e)
    sprite=module('sprite_preparer',e);sprite_meta=pinned_json('sprite_edge',e)
    ddr=module('ddr_preparer',e);ddr_meta=pinned_json('ddr_edge',e)
    bg_files,unused=bg.verify_edge((ROOT/PINS['bg_edge'][0]).parent)
    spr_parents,spr_files,unused=sprite.verify_edge((ROOT/PINS['sprite_edge'][0]).parent)
    ddr_source=ddr.verify_edge((ROOT/PINS['ddr_edge'][0]).parent)
    for relative,raw in bg_files.items():
        record=bg_meta['files'][relative];e.file(record['parent'],record['parent_sha256']);e.file(record['candidate'],record['candidate_sha256'])
        require(raw==current[relative] if relative!='rtl/BT.sv' else bg.inverse(raw,record['edits'])==before[relative],
                'standalone BG source must match its declared lift')
    for relative,raw in spr_files.items():
        record=sprite_meta['files'][relative];edge_root=(ROOT/PINS['sprite_edge'][0]).parent
        e.file(edge_root/'oracle'/relative,record['parent_sha256']);e.file(edge_root/'candidate'/relative,record['candidate_sha256'])
        require(raw==current[relative] and spr_parents[relative]==before[relative],'actual SPR/FG source must match qualified standalone')
    e.file((ROOT/PINS['sprite_edge'][0]).parent/'binding_parent/rtl/BT.sv',sprite_meta['BT_connection_parent_sha256'])
    e.file((ROOT/PINS['ddr_edge'][0]).parent/'candidate/rtl/ddram.sv',ddr_meta['candidate_sha256'])
    args=(bg,sprite,ddr,bg_meta,sprite_meta,ddr_meta)
    graph=source_graph(current,before,*args);controls=source_controls(current,before,*args)
    e.recheck()
    result=dict(schema=SCHEMA,status=STATUS,helper_sha256=sha(Path(__file__).read_bytes()),source_root=str(source_root),
      snapshot=str(ROOT/PINS['snapshot'][0]),snapshot_sha256=PINS['snapshot'][1],all144_source_inventory_entries_verified=True,
      only_changed_sources=list(CHANGED),unchanged_sources=139,raw_source_composition=graph,
      parent_v23_current_native_receipt=str(ROOT/PINS['parent_receipt'][0]),parent_v23_current_native_receipt_sha256=PINS['parent_receipt'][1],
      parent_validation=parent_validation,inherited_native_scope='Exact v23 BT_NATIVE_SIM replay remains v23; these five new source inputs require a separate fresh v24 replay.',
      immutable_git_oracles=parent['immutable_git_oracles'],new_source_corruption_controls=controls,
      case_equality_exclusions=0,collision_masks_added=0,new_compiler_or_simulator_run=False,new_whole_board_native_run=False,
      fresh_v24_native_replay=False,production_emu_HPS_top_reset_compiled=False,mapped_replication_proven=False,
      core_timing_accepted=False,timing_accepted=False,eligible_for_RBF=False,root_RTL_SDC_or_old_evidence_modified=False)
    return result,e

def bind_current(source_root):
    result,e=bind_source(source_root)
    require(set(PROOFS)=={'sprite','ddr'},'both decisive fresh SPR and DDR proof pins must be supplied')
    bg_module=module('bg_qualifier',e);bg=pinned_json('bg_proof',e);e.ingest(bg['retained_files'])
    result['scoped_proofs']={'bg':bg_module.verify_composition_receipt(ROOT/PINS['bg_proof'][0])}
    for name,record in PROOFS.items():
        if name=='sprite':
            result['scoped_proofs'][name]=bind_sprite(record,e)
            continue
        helper=ROOT/record['helper'];receipt=ROOT/record['receipt']
        e.file(helper,record['helper_sha256']);raw=e.json(receipt,record['receipt_sha256'])
        q=load(helper,'v24_actual_'+name);validation=q.verify_composition_receipt(receipt)
        result['scoped_proofs'][name]=validation
        e.tree(raw)
        for key in ('retained_files','bound_evidence_files','retained_inputs_logs_and_executable'):
            if key in raw:e.ingest(raw[key])
        if isinstance(validation,dict) and 'bound_evidence_files' in validation:e.ingest(validation['bound_evidence_files'])
        if name=='ddr':result['scoped_proofs']['ddr_actual_command_and_input_binding']=bind_ddr(raw,receipt,q,e)
    e.recheck();return result,e

def bind_sprite(record,e):
    """Regenerate each actual profile; bind every argv, log and fixture."""
    e.file(ROOT/record['helper'],record['helper_sha256'])
    e.file(ROOT/record['verifier'],record['verifier_sha256'])
    q=load(ROOT/record['helper'],'v24_frozen_sprite_qualifier')
    v=load(ROOT/record['verifier'],'v24_frozen_sprite_strict_verifier')
    require(set(record['profiles'])=={'vendor','native-fg','four-state-fg'},
            'all actual vendor and full foreground profiles required')
    profiles={}
    for profile,(relative,digest) in record['profiles'].items():
        path=ROOT/relative;raw=e.json(path,digest);base=path.parent
        meta=e.json(base/'preparation.json',raw['preparation']['sha256'])
        validation=v.verify_proof((ROOT/PINS['sprite_edge'][0]).parent,path,
                                  record['helper_sha256'],self_test=True)
        require(validation['status']=='PASS' and validation['profile']==profile
                and len(validation['rejected_controls'])==12,
                'fresh actual sprite/foreground proof or controls changed')
        require(raw['candidate_files']=={
            'rtl/spr_vram.sv':'a2283ef824e15f137390607ccae1f96253a2e64779126c14a697c689e4edac6d',
            'rtl/fg_vram.sv':'cf292fe331ec0a2efd75743a09fe57835760160f5e7db07a5dc457aa0cae45f6'},
            'proof must compile the exact current sprite and foreground')
        e.tree(meta);e.tree(raw);e.tree(validation)
        for group in ('helpers','executed_helpers','compiled_inputs'):
            e.ingest(meta[group])
        for row in raw['commands']:e.record(row['log'])
        if profile=='native-fg':
            for label,top in [('fg','item4_foreground_equivalence_tb'),('fg-ddr','foreground_ddr_tb')]:
                executable=base/label/'obj'/('V'+top)
                require(e.file(executable)[:4]==b'\x7fELF','retained foreground executable must be Linux ELF')
        if profile=='vendor':e.file(q.VENDOR,q.VENDOR_SHA)
        profiles[profile]=validation
    return dict(profiles=profiles,all_original_assertions_and_stimulus_preserved=True,
                regenerated_complete_compiler_inputs_and_ordered_argv=True,
                actual_log_coverage_reparsed=True,fresh_rejected_controls=36,
                new_native128_or_mapped_timing_claim=False)

def bind_ddr(rec,path,q,e):
    """The busy proof uses relative digest ledgers and named log/ELF records."""
    base=path.parent
    require(rec['helper_sha256']==PROOFS['ddr']['helper_sha256']
            and rec['preparer_sha256']==PINS['ddr_preparer'][1], 'actual DDR executed helpers changed')
    for relative,digest in rec['compiled_inputs'].items():
        require(not Path(relative).is_absolute() and '..' not in Path(relative).parts,'foreign DDR compiled input')
        e.file(base/relative,digest)
    for relative,digest in [('executed_qualifier.py',rec['helper_sha256']),('executed_preparer.py',rec['preparer_sha256']),
                           ('parent_raw.sv',rec['parent_sha256']),('candidate_raw.sv',rec['candidate_sha256'])]:
        e.file(base/relative,digest)
    require(set(rec['jobs'])=={'activated','foreground','fourstate'},'all actual DDR jobs required')
    for family,job in rec['jobs'].items():
        require(job['compile']['exit_code']==job['run']['exit_code']==0,'actual DDR job failed')
        for phase in ('compile','run'):
            record=job[phase];e.file(record['log'],record['log_sha256'])
            require(record['command'][:6]==['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec'],
                    'actual Linux DDR tools must use the explicit Ubuntu interpreter')
        command=job['compile']['command']
        if family in ('activated','foreground'):
            require('--assert' in command and '--timing' in command
                    and '-DSYNTHESIS' not in command,'actual native DDR assertions changed')
        e.file(job['executable'],job['executable_sha256'])
    for record in rec['tool_versions'].values():
        if isinstance(record,dict) and 'log' in record:e.file(record['log'],record['log_sha256'])
    coverage=q.coverage(base)
    require(coverage==rec['coverage'] and coverage['four_state_read_cases']==32768
            and coverage['four_state_io_cases']==262144 and coverage['output_or_collision_masks']==0,
            'actual DDR source-derived log coverage changed')
    for key in ('parent_actual_parallel_receipt','parent_current_read_receipt','parent_actual_native128_receipt'):
        e.file(rec[key],rec[key+'_sha256'])
    return dict(actual_compiled_sources=len(rec['compiled_inputs']),coverage=coverage,
                actual_job_assertions_enabled=True,explicit_Ubuntu_ELF_routing=True,no_new_native128_or_timing_claim=True)

def evidence_controls(e):
    tests=[]
    for name in ('snapshot','bg_proof'):
        path,digest=PINS[name]
        try:e.file(ROOT/path,'0'*64)
        except AssertionError:tests.append(dict(name='wrong required digest '+name,rejected=True))
        else:raise AssertionError('altered required evidence digest accepted')
    try:e.file(ROOT/'build/__v24_required_evidence_omission_negative__/absent.json','0'*64)
    except FileNotFoundError:tests.append(dict(name='absent required evidence',rejected=True))
    else:raise AssertionError('absent required evidence accepted')
    try:e.record(dict(path=str(ROOT/PINS['bg_proof'][0]),sha256=PINS['bg_proof'][1],bytes=0))
    except AssertionError:tests.append(dict(name='truncated required evidence',rejected=True))
    else:raise AssertionError('truncated required evidence accepted')
    return tests

def claim_controls(expected):
    results=[]
    for key,value in [('fresh_v24_native_replay',True),('timing_accepted',True),('eligible_for_RBF',True),
                      ('mapped_replication_proven',True),('unchanged_sources',140),('collision_masks_added',1)]:
        wrong=copy.deepcopy(expected);wrong[key]=value
        try:require(normal(wrong)==normal(expected),'changed qualified composition claim')
        except AssertionError:results.append(dict(name=key,rejected=True))
        else:raise AssertionError('scope/receipt corruption accepted')
    return results

def verify_composition_receipt(path):
    path=Path(path).resolve();actual=json.loads(path.read_bytes())
    require(actual['schema']==SCHEMA and actual['status']==STATUS,'wrong v24 composition receipt')
    expected,e=bind_current(actual['source_root']);e.record(actual['executed_helper'])
    require(e.file(actual['executed_helper']['path'])==Path(__file__).read_bytes(),'executed new source binder changed')
    expected['executed_helper']=actual['executed_helper'];expected['new_claim_corruption_controls']=claim_controls(expected)
    expected['new_evidence_corruption_controls']=evidence_controls(e)
    expected['bound_evidence_files']=dict(e.files)
    require(normal(actual)==normal(expected),'changed v24 composition/evidence/claims');e.recheck()
    return dict(status=STATUS,receipt=str(path),receipt_sha256=sha(path.read_bytes()),sources=144,unchanged_sources=139,
      verified_evidence_files=len(e.files),verified_immutable_git_oracles=len(actual['immutable_git_oracles']),
      source_corruption_controls=10,claim_corruption_controls=6,evidence_corruption_controls=4,fresh_v24_native_or_timing_claim=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--source-root',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);parser.add_argument('--source-only',action='store_true');args=parser.parse_args()
    out=args.output.resolve();require(not out.exists(),'exclusive new evidence output required')
    result,e=(bind_source if args.source_only else bind_current)(args.source_root)
    if args.source_only:result['schema']='bt-v24-memory-local-source-preparation-v1';result['status']='SOURCE_ONLY_FUNCTIONAL_PROOFS_PENDING'
    out.mkdir(parents=True);helper=out/Path(__file__).name;helper.write_bytes(Path(__file__).read_bytes())
    result['executed_helper']=dict(path=str(helper),sha256=sha(e.file(helper)),bytes=helper.stat().st_size)
    result['new_claim_corruption_controls']=claim_controls(result);result['new_evidence_corruption_controls']=evidence_controls(e)
    result['bound_evidence_files']=dict(e.files)
    target=out/'receipt.json';target.write_text(json.dumps(normal(result),indent=2)+'\n')
    if args.source_only:print(json.dumps(dict(status=result['status'],receipt=str(target),sha256=sha(target.read_bytes()),sources=144,changed=5)));return
    validated=verify_composition_receipt(target);(out/'verification.json').write_text(json.dumps(validated,indent=2)+'\n');print(json.dumps(validated))
if __name__=='__main__':main()
