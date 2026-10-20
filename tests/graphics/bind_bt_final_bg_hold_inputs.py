"""Bind the selected v25 BG data identity edge to immutable v24 source/native proof."""
from __future__ import annotations
import argparse, copy, hashlib, importlib.util, json, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
SCHEMA='bt-v25-current-input-bg-hold-composition-v1'
STATUS='PASS_SCOPED_COMPOSITION'
PINS={
 'parent_helper':('tests/graphics/bind_bt_v24_native_replay.py','0e86b7318c3df8b141e4722726a3410cc7055091e5c22e2b670579aeb4b135b2'),
 'parent_native':('build/final_v24_native_input_qualification_r1/receipt.json','d1ba9783e02f06a4fb2f973c44a3a2b3341e2a1b59577058474c5ced846d885f'),
 'evidence_helper':('tests/graphics/bind_bt_final_bg_cpu_fg_inputs.py','cb4b37258d2ade627c25660fb722de87787f9df5975d4fae3804f98a251eef00'),
 'snapshot':('build/timing_closure_20261011/bg_hold_v25_private-snapshot.json','7799e521f7e02bae511dbd8fdf2637cac1c9daa311aa9f726f1ec97ca6243ddb'),
 'parent_snapshot':('build/timing_closure_20261011/mem_local_paths_v24_private-snapshot.json','014b565d404e7a345568df0453979fbcf0c76f114c0698f57b5ad2fa8582a28e'),
 'preparer':('tests/graphics/prepare_bt_bg_write_hold_lcell.py','152bc1ba0113aef3bddd54e695d2b0ef5cd0e69b091e8592217598e4e1187f0d'),
 'source_edge':('build/bg_write_hold_v24_v1/source-edge/manifest.json','7c9b256f9f5de10f28bb457ed88d6e9b6c9f14ccfeeb160a3fe50c5b14d63ed9'),
 'qualifier':('tests/graphics/qualify_bt_bg_write_hold_lcell_q17_time.py','3096ea7c350810030c26512567a43cd6f66a3d8324a09694c48d06364767bd10'),
 'hold_proof':('build/bg_write_hold_v24_v1/proof-r3/receipt.json','50180723fdcc9b501f740e0e40b77cc61c570986dc62a87069a0aff7affe94f1'),
 'hold_preparation':('build/bg_write_hold_v24_v1/proof-r3/preparation.json','dc2e4aa7ec28078f3db8a99bf4acf658c2114cca8efbb2eb9aca2fdbbd36baa3'),
 'declaration_projection':('build/bg_write_hold_v24_v1/q17-fixture-projection.json','ec2e2998f300155b1e1d493c9e27523963a3264a1a7249189f73958eec2ed327'),
 'timescale_projection':('build/bg_write_hold_v24_v1/q17-default-timescale-projection.json','3fd42a4f9c6ad0e5df47eb149faa5b70b6cb503b597a2cff3852e5ab57c9917e'),
 'artifact_recovery_helper':('build/ddr_din_local_flags_v20_v2/recover_exact_executables.py','f5079d1305822e75ccbed1cda554b3068153db5c929dbf1b913405b6bc2bb79b'),
 'artifact_recovery':('build/ddr_din_local_flags_v20_v2/executable-recovery-r1/receipt.json','eb4a3b19b8bdcbd045b766a487ed037d8ad8911084ece9e660d1f72ae4483c30'),
}
BG='rtl/bg_vram.sv'
OLD_SHA='748ba22e42d57d618ffce46800a7f66f023fe79b27a3186f9a04b9748af1273c'
NEW_SHA='a2323df5cb71ce3c9856a0f58720444fe95556917771615cad6f6a173d08b5ad'
COVERAGE={'full':{'original':[130738,130738,4096,16,4096,4],'scroll':[311914,16448,8192,64]},
 'actual_RAM_branch':[623828,66905,69],'raw':[589824,65536,524288,256,327835,392368],
 'pixel':[234241,4608,98304,131072,128],'cell':[140353,65536,65536,64,5120,1024]}
def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
 if not value:raise AssertionError(message)
def normal(value):return json.loads(json.dumps(value))
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec)
 spec.loader.exec_module(module);return module
def check_snapshot(selected,parent):
 require(set(selected['sources'])==set(parent['sources']) and len(selected['sources'])==144,'all144 inventory required')
 changed={p:h for p,h in selected['sources'].items() if h!=parent['sources'][p]}
 require(changed=={BG:NEW_SHA} and selected['changed_sources']==changed
         and selected['unchanged_source_count']==143,'exact one-BG-file source edge required')
 require(parent['sources'][BG]==OLD_SHA and selected['parent_snapshot_sha256']==PINS['parent_snapshot'][1],
         'wrong immutable v24 source parent')
 require(not any(selected[k] for k in ('timing_budgets_changed','framework_changed','original_settings_changed',
                                      'rbf_generation','production_sources_modified')),'source freeze broadened')
def check_source(preparer,old,new):
 require(sha(old)==OLD_SHA and sha(new)==NEW_SHA and preparer.transform(old)==new and preparer.reverse(new)==old,
         'exact whole BG source inverse required')
def check_proof(rec):
 require(rec['schema']=='bt-v25-bg-write-hold-lcell-qualification-v1'
         and rec['status']=='PASS_ACTUAL_BG_AND_SHIPPED_LCELL' and rec['failure'] is None,
         'actual complete BG and shipped primitive proof required')
 require(rec['edge_manifest_sha256']==PINS['source_edge'][1] and rec['helper_sha256']==PINS['qualifier'][1],
         'wrong source or actually executed qualifier')
 require(rec['coverage']==COVERAGE and len(rec['compiled_inputs'])==8,'complete original/new exact coverage required')
 require(rec['no_masks_or_exclusions'] is True and rec['mapped_or_timing_qualified'] is False,'functional proof scope changed')
 require(rec['source_and_fixture_projection']['original_assertions_and_stimulus_preserved'] is True
         and rec['source_and_fixture_projection']['collision_masks']==0
         and rec['source_and_fixture_projection']['case_equality_exclusions']==0,
         'original assertions or four-state contract weakened')
def fixture_projections(e,pinned):
 result=[]
 for role in ('declaration_projection','timescale_projection'):
  rec=pinned[role];before=e.record(rec['parent']);after=e.record(rec['candidate'])
  old=rec['old'].encode();new=rec['new'].encode()
  require(before.count(old)==1 and after.count(new)==1 and before.replace(old,new,1)==after
          and after.replace(new,old,1)==before,'exact compiler-only helper inverse changed')
  failed=json.loads(e.record(rec['original_failed_receipt']))
  require(failed['status']=='FAIL' and rec['whole_helper_byte_inverse'] is True,'old failed attempts must remain explicit')
  if role=='declaration_projection':
   require(rec['old']=='  wire [15:0] direct_data=raw,cell_data,stage_data;\n'
      and rec['new']=='  wire [15:0] direct_data,cell_data,stage_data;\n  assign direct_data=raw;\n'
      and rec['core_sources_or_original_assertions_changed'] is False
      and rec['new_core_edge_or_latency'] is False,'only four-state continuous test declaration may change')
  else:
   e.record(rec['prior_declaration_projection']);time_log=e.record(rec['original_complete_BG_time_log']).decode(errors='replace')
   require(rec['old']=="([str(SIM/'vlog.exe'),'-sv','-work','work']"
      and rec['new']=="([str(SIM/'vlog.exe'),'-sv','-timescale','1 ps / 1 ps','-work','work']"
      and rec['explicit_shipped_LCELL_timescale_changed'] is False
      and rec['default_timeunit']==rec['default_precision']=='1 ps'
      and rec['assertions_sources_and_stimulus_unchanged'] is True
      and rec['new_core_clock_edge_or_timing_exception'] is False
      and rec['original_complete_BG_finish_time_ps']==607378
      and re.search(r'Time:\s*607378\s*ps',time_log),'only original 1ps compiler default may be made explicit')
  result.append({'role':role,'parent':rec['parent'],'candidate':rec['candidate'],
      'failed_attempt_preserved':rec['original_failed_receipt'],'whole_helper_byte_inverse':True})
 return result
def rejection_controls(selected,parent,preparer,old,new,proof):
 result=[]
 def rejects(name,fn):
  try:fn()
  except (AssertionError,KeyError,ValueError):result.append({'name':name,'rejected':True})
  else:raise AssertionError('corruption accepted: '+name)
 for name,edit in [
  ('foreign BG source',lambda r:r['sources'].__setitem__(BG,'0'*64)),
  ('missing inventory source',lambda r:r['sources'].pop('Arcade-Battletoads.qsf')),
  ('foreign QSF bytes',lambda r:r['sources'].__setitem__('Arcade-Battletoads.qsf','0'*64)),
  ('new core timing budget',lambda r:r.__setitem__('timing_budgets_changed',True)),
  ('false unchanged count',lambda r:r.__setitem__('unchanged_source_count',144)),
  ('wrong immutable parent',lambda r:r.__setitem__('parent_snapshot_sha256','0'*64))]:
  bad=copy.deepcopy(selected);edit(bad);rejects(name,lambda b=bad:check_snapshot(b,parent))
 for name,bad in [
   ('removed actual data LCELL',new.replace(b'\tlcell write_data_hold_delay',b'\twire write_data_hold_delay',1)),
   ('wrong delayed data bit',new.replace(b'.in(WRITE_DATA[15])',b'.in(WRITE_DATA[14])',1)),
   ('new data pipeline',new+b'\r\nreg inserted_delay;\r\n'),
   ('unrelated original body edit',new.replace(b'\tbit [15:0]   WRITE_DATA;',b'\tbit [15:0]   WRITE_DATA_CHANGED;',1))]:
  require(bad!=new,'mutation anchor absent');rejects(name,lambda b=bad:check_source(preparer,old,b))
 for key,value,name in [
  ('status','FAIL','accepted failed primitive proof'),
  ('helper_sha256','0'*64,'foreign executed helper'),
  ('no_masks_or_exclusions',False,'new collision or X exclusion'),
  ('mapped_or_timing_qualified',True,'false mapped/timing claim'),
  ('coverage',dict(COVERAGE,actual_RAM_branch=[1,1,1]),'truncated full actual RAM branch coverage'),
  ('compiled_inputs',{},'omitted compiler input')]:
  bad=copy.deepcopy(proof);bad[key]=value;rejects(name,lambda b=bad:check_proof(b))
 return result
def bind_current(source_root=None):
 support_path=ROOT/PINS['evidence_helper'][0]
 require(sha(support_path.read_bytes())==PINS['evidence_helper'][1],'frozen evidence implementation changed')
 e=load(support_path,'v25_hold_frozen_evidence').Evidence()
 pinned={}
 for key,(path,digest) in PINS.items():
  data=e.file(ROOT/path,digest)
  if Path(path).suffix=='.json':pinned[key]=json.loads(data)
 recovery=pinned['artifact_recovery']
 require(recovery['status']=='PASS_EXACT_BINARY_RECOVERY_NO_EXECUTION'
         and recovery['schema']=='bt-ddr-flags-exact-executable-recovery-v1'
         and recovery['old_receipt_sha256']=='60d49e56e363d8b5f130215b4022653a6b40fb9699a8eaff451b6ae296093d80'
         and recovery['old_compiler_inputs_all14_unchanged'] is True
         and recovery['same_verilator_version_text'] is True
         and recovery['historical_simulation_retagged'] is False
         and recovery['new_simulator_execution'] is False
         and recovery['old_receipts_sources_logs_modified'] is False,
         'exact recovered artifacts cannot become new historical execution evidence')
 recovery_helper=load(ROOT/PINS['artifact_recovery_helper'][0],'v25_exact_historical_artifact_recovery')
 require(recovery_helper.verify_receipt(ROOT/PINS['artifact_recovery'][0])==recovery,
         'exact recovery receipt verification changed')
 e.ingest(recovery['retained_artifacts']);e.ingest(recovery['original_logs'])
 parent_helper=load(ROOT/PINS['parent_helper'][0],'v25_frozen_v24_native')
 parent_validation=parent_helper.verify_composition_receipt(ROOT/PINS['parent_native'][0])
 parent_receipt=pinned['parent_native'];e.ingest(parent_receipt['bound_evidence_files'])
 selected=pinned['snapshot'];parent=pinned['parent_snapshot'];check_snapshot(selected,parent)
 if source_root is None:source_root=Path(selected['project']).parent
 source_root=Path(source_root).resolve()
 source_bytes={p:e.file(source_root/p,h) for p,h in selected['sources'].items()}
 parent_root=Path(parent['project']).parent
 parent_bytes={p:e.file(parent_root/p,h) for p,h in parent['sources'].items()}
 require(all(source_bytes[p]==parent_bytes[p] for p in selected['sources'] if p!=BG),'all143 original bytes must hold')
 p=load(ROOT/PINS['preparer'][0],'v25_frozen_hold_source')
 edge=Path(ROOT/PINS['source_edge'][0]).parent
 old,new,manifest=p.verify_edge(edge);check_source(p,old,new)
 require(old==parent_bytes[BG] and new==source_bytes[BG],'actual selected BG not the proved source edge')
 e.file(edge/'oracle'/BG,OLD_SHA);e.file(edge/'candidate'/BG,NEW_SHA)
 require(manifest['changed_source_files']==[BG] and manifest['new_registers']==0
         and manifest['capture_cycle_changed'] is False and manifest['reset_changed'] is False
         and manifest['raw_write_packet_other_consumers_unchanged'] is True and manifest['qsf_sdc_clock_changes']==0,
         'identity branch must preserve all clocks, registers and constraints')
 for path,digest in selected['source_preparation_evidence'].items():e.file(path,digest)
 adapters=fixture_projections(e,pinned)
 q=load(ROOT/PINS['qualifier'][0],'v25_frozen_actual_hold_qualifier')
 proof=pinned['hold_proof'];check_proof(proof)
 proof_validation=q.verify_composition_receipt(ROOT/PINS['hold_proof'][0])
 inputs,actual_manifest,detail=q.generated_inputs(edge)
 require(actual_manifest==manifest and normal(detail)==pinned['hold_preparation']['source_and_fixture_projection'],
         'regenerated actual compiler proof changed')
 e.ingest(proof['retained_files'])
 for name,row in proof['compiled_inputs'].items():
  raw=e.record(row);require(raw==inputs[name],'actual whole compiler input changed: '+name)
 for command in proof['commands']:
  for key in ('log','executable'):
   if isinstance(command.get(key),dict):e.record(command[key])
 require(proof_validation['coverage']==COVERAGE and len(proof_validation['rejected_controls'])==12,
         'actual proof reparse or all negative controls changed')
 controls=rejection_controls(selected,parent,p,old,new,proof)
 e.recheck()
 return dict(schema=SCHEMA,status=STATUS,helper_sha256=sha(Path(__file__).read_bytes()),
  source_root=str(source_root),snapshot=str(ROOT/PINS['snapshot'][0]),snapshot_sha256=PINS['snapshot'][1],
  all144_source_inventory_entries_verified=True,source_inventory=selected['sources'],
  inherited_current_native=str(ROOT/PINS['parent_native'][0]),inherited_current_native_sha256=PINS['parent_native'][1],
  inherited_current_native_validation=parent_validation,inherited_native_scope='Actual v24 game-board run; this new BG source is qualified by the separate current component proof.',
  current_BG_hold_source_edge=str(ROOT/PINS['source_edge'][0]),current_BG_hold_source_edge_sha256=PINS['source_edge'][1],
  source_inverse={'changed_sources':[BG],'unchanged_source_count':143,'parent_sha256':OLD_SHA,'candidate_sha256':NEW_SHA,
                  'full_file_byte_inverse':True,'all143_other_raw_bytes_identical':True},
  actual_BG_hold_proof=str(ROOT/PINS['hold_proof'][0]),actual_BG_hold_proof_sha256=PINS['hold_proof'][1],
  actual_BG_hold_validation=proof_validation,actual_compiled_inputs=8,actual_coverage=COVERAGE,
  test_compiler_only_edges=adapters,binding_corruption_controls=controls,
  immutable_git_oracles=parent_receipt['immutable_git_oracles'],
  exact_historical_artifact_recovery=str(ROOT/PINS['artifact_recovery'][0]),
  exact_historical_artifact_recovery_sha256=PINS['artifact_recovery'][1],
  artifact_recovery_scope='Compile-only recovery of the exact two old ELF byte strings; no new or retagged historical run.',
  functional_equivalence_current_source_graph=True,current_v25_native_replay_completed=False,
  new_whole_board_native_run=False,production_emu_HPS_top_reset_compiled=False,
  old_proofs_or_rasters_modified=False,case_equality_exclusions=0,collision_masks_added=0,
  mapped_cell_retention_qualified=False,core_timing_accepted=False,timing_accepted=False,eligible_for_RBF=False,
  limits=['Current source component proofs compose with actual v24 native replay; fresh v25 replay remains separate.',
          'Fitted cell retention, all-corner timing, physical I/O and release packaging are separate gates.']),e
def verify_composition_receipt(path):
 path=Path(path).resolve();actual=json.loads(path.read_bytes())
 require(actual['schema']==SCHEMA and actual['status']==STATUS,'wrong current-source schema/status')
 expected,e=bind_current(actual['source_root']);e.record(actual['executed_helper'])
 require(e.file(actual['executed_helper']['path'])==Path(__file__).read_bytes(),'executed binder changed')
 expected['executed_helper']=actual['executed_helper'];expected['bound_evidence_files']=dict(e.files)
 require(normal(actual)==normal(expected),'source composition or evidence claims changed')
 e.recheck()
 return {'schema':SCHEMA,'status':STATUS,'receipt':str(path),'receipt_sha256':sha(path.read_bytes()),
    'sources':144,'changed_sources':1,'unchanged_sources':143,'verified_evidence_files':len(e.files),
    'verified_immutable_git_oracles':len(actual['immutable_git_oracles']),
    'binding_corruption_controls':len(actual['binding_corruption_controls']),
    'actual_hold_corruption_controls':12,'current_v25_native_replay_completed':False,'timing_accepted':False}
def main():
 parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--source-root',type=Path);args=parser.parse_args()
 output=args.output.resolve();require(not output.exists(),'exclusive new evidence output required')
 result,e=bind_current(args.source_root);output.mkdir(parents=True)
 helper=output/Path(__file__).name;helper.write_bytes(Path(__file__).read_bytes())
 result['executed_helper']={'path':str(helper),'sha256':sha(e.file(helper)),'bytes':helper.stat().st_size}
 result['bound_evidence_files']=dict(e.files);path=output/'receipt.json'
 path.write_text(json.dumps(normal(result),indent=2)+'\n')
 validation=verify_composition_receipt(path)
 (output/'verification.json').write_text(json.dumps(validation,indent=2)+'\n');print(json.dumps(validation))
if __name__=='__main__':main()
