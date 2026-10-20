"""Strict source/command/log verifier for the fresh v23 sprite-data proof.

The caller pins the executed qualifier SHA explicitly.  This accepts no earlier
full-file receipt on a newer source, no inferred simulator success, and no path
normalization beyond the qualifier's two-key vendor-case preservation edge.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
QUALIFIER=ROOT/'tests/graphics/qualify_bt_sprite_data_v23.py'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def load_qualifier(expected):
 assert len(expected)==64 and sha(QUALIFIER.read_bytes())==expected
 spec=importlib.util.spec_from_file_location('strict_sprite_data_qualifier',QUALIFIER)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module

def expected_commands(q,output,profile):
 inputs=output/'inputs';tools=q.TOOLS;work=output/'work';pin=output/'pin_work'
 if profile=='vendor':
  result=[([str(tools/'vlib.exe'),str(work)],'vlib.log'),
   ([str(tools/'vlog.exe'),'-sv','-work',str(work),*[str(inputs/name) for name in ('spr_parent.sv','spr_candidate.sv','BT_mem.sv','sprite_local_q_vendor_tb.sv','sprite_read_equivalence_tb.sv','sprite_packet_tb.sv','sprite_data_v23_packet_tb.sv')],str(q.VENDOR)],'build.log'),
   ([str(tools/'vlib.exe'),str(pin)],'pin-vlib.log'),
   ([str(tools/'vlog.exe'),'-sv','-work',str(pin),*[str(inputs/name) for name in ('bank_parent.sv','bank_candidate.sv','sprite_bank_ram_pin_tb.sv')]],'pin-build.log')]
  for top,label,library in (('sprite_local_q_vendor_tb','vendor',work),('sprite_read_equivalence_tb','read',work),('sprite_packet_tb','packet',work),('sprite_data_v23_packet_tb','local-packet',work),('sprite_bank_ram_pin_tb','pin',pin)):
   result.append(([str(tools/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib',str(library),top,'-do','run -all; quit -code 0'],label+'.log'))
  return result
 if profile=='native-fg':
  runtime=q.load(q.OLD,'strict_native_sprite_runtime');result=[]
  for label,top,files in [('fg','item4_foreground_equivalence_tb',['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','intel_lcell.v','item4_foreground_equivalence_tb.sv']),('fg-ddr','foreground_ddr_tb',['fg_vram.sv','ddram.sv','bt_fg_ddr_clear.sv','ram_models.sv','intel_lcell.v','foreground_ddr_tb.sv'])]:
   target=output/label
   result.append((['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec','verilator','--binary','--assert','--timing','-j','4','--threads','1','--x-initial','unique','--x-assign','unique','--top-module',top,'--Mdir',runtime.wsl(target/'obj'),'-Wno-fatal',*files],label+'/build.log'))
   result.append((['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec',runtime.wsl(target/'obj'/('V'+top))],label+'/run.log'))
  return result
 assert profile=='four-state-fg'
 return [([str(tools/'vlib.exe'),str(work)],'vlib.log'),
  ([str(tools/'vlog.exe'),'-sv','-work',str(work),*[str(inputs/name) for name in ('fg_vram.sv','reference-fg_vram.sv','ram_models.sv','intel_lcell.v','item4_foreground_equivalence_tb.sv')]],'build.log'),
  ([str(tools/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib',str(work),'item4_foreground_equivalence_tb','-do','run -all; quit -code 0'],'run.log')]

def validate_receipt_data(q,output,meta,receipt):
 assert receipt['schema']=='bt-v23-sprite-data-proof-v1' and receipt['status']=='PASS' and receipt['failure'] is None
 assert receipt['profile']==meta['profile']
 for key in ('compiled_inputs','executed_helpers','candidate_files','oracle_files','source_manifest'):
  assert receipt[key]==meta[key],key
 assert receipt['preparation']==q.record(output/'preparation.json')
 assert receipt['original_assertions_preserved'] is True
 assert receipt['case_equality_exclusions']==0 and receipt['collision_masks_added']==0
 assert receipt['actual_Intel_vendor_RAM']==(meta['profile']=='vendor')
 assert receipt['mapped_replicas_or_timing_proven'] is False and receipt['rbf_generated'] is False
 commands=expected_commands(q,output,meta['profile']);assert len(receipt['commands'])==len(commands)
 for row,(argv,label) in zip(receipt['commands'],commands):
  assert row['command']==argv and row['exit_code']==0
  assert row['log']==q.record(output/label)
 runtime=q.load(q.OLD,'strict_sprite_log_parser')
 assert receipt['coverage']==q.coverage(output,meta['profile'],runtime)
 if meta['profile']=='vendor':
  edge=meta['fixture_edges']['vendor_fixture']['resolved_pin_scope']
  assert edge['vendor_byteena_a_net_kind']=='tri1 at frozen altera_mf.v:47724'
  assert edge['upstream_active_default_original_controls_compared'] is True and edge['literal_XZ_cases_retained'] is True
  assert meta['fixture_edges']['prior_q17_validation']['vendor_case_edge']['rejected_controls']==['different_file','different_bytes','different_path']
 return receipt['coverage']

def verify_proof(edge,receipt_path,qualifier_sha256,self_test=False):
 q=load_qualifier(qualifier_sha256);receipt_path=Path(receipt_path).resolve();output=receipt_path.parent
 meta=json.loads((output/'preparation.json').read_bytes());assert Path(meta['edge']).resolve()==Path(edge).resolve()
 assert meta['helpers'][str(QUALIFIER.resolve())]==qualifier_sha256
 assert meta['executed_helpers'][str(output/'executed-helpers'/QUALIFIER.name)]==qualifier_sha256
 q.verify_inputs(output,meta)
 receipt=json.loads(receipt_path.read_bytes());coverage=validate_receipt_data(q,output,meta,receipt)
 rejected=[]
 if self_test:
  mutations=[('status',lambda r:r.update(status='FAIL')),
   ('nonzero_exit',lambda r:r['commands'][0].update(exit_code=1)),
   ('command_argument',lambda r:r['commands'][0]['command'].append('--unexpected')),
   ('command_omitted',lambda r:r['commands'].pop()),
   ('compiled_source',lambda r:r['compiled_inputs'].update({next(iter(r['compiled_inputs'])):'0'*64})),
   ('oracle_source',lambda r:r['oracle_files'].clear()),
   ('log_hash',lambda r:r['commands'][-1]['log'].update(sha256='0'*64)),
   ('coverage',lambda r:r['coverage'].clear()),
   ('mask_waiver',lambda r:r.update(collision_masks_added=1)),
   ('case_exclusion',lambda r:r.update(case_equality_exclusions=1)),
   ('hardware_claim',lambda r:r.update(mapped_replicas_or_timing_proven=True)),
   ('helper_identity',lambda r:r['executed_helpers'].clear())]
  for label,mutate in mutations:
   changed=copy.deepcopy(receipt);mutate(changed)
   try:validate_receipt_data(q,output,meta,changed)
   except (AssertionError,KeyError):rejected.append(label)
   else:raise AssertionError((label,'bad evidence accepted'))
  assert len(rejected)==12
 return {'schema':'bt-v24-sprite-data-strict-proof-validation-v1','status':'PASS','profile':meta['profile'],
  'receipt':q.record(receipt_path),'preparation':q.record(output/'preparation.json'),
  'qualifier':q.record(QUALIFIER),'verifier':q.record(Path(__file__)),
  'source_manifest':meta['source_manifest'],'candidate_files':meta['candidate_files'],'oracle_files':meta['oracle_files'],
  'compiled_inputs':meta['compiled_inputs'],'executed_helpers':meta['executed_helpers'],
  'commands_and_logs':[{'argv':r['command'],'exit_code':r['exit_code'],'log':r['log']} for r in receipt['commands']],
  'coverage':coverage,'rejected_controls':rejected,'runtime_scope_only':True}

def main():
 p=argparse.ArgumentParser();p.add_argument('--edge',type=Path,required=True);p.add_argument('--receipt',type=Path,required=True)
 p.add_argument('--qualifier-sha256',required=True);p.add_argument('--self-test',action='store_true');p.add_argument('--output',type=Path)
 args=p.parse_args();result=verify_proof(args.edge,args.receipt,args.qualifier_sha256,args.self_test)
 if args.output:
  assert not args.output.exists();args.output.write_text(json.dumps(result,indent=2)+'\n')
 print(json.dumps({'status':result['status'],'profile':result['profile'],'coverage':result['coverage'],'rejected_controls':result['rejected_controls']},separators=(',',':')))
if __name__=='__main__':main()
