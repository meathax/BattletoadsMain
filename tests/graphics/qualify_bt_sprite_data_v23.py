"""Frozen v23 source-bound vendor sprite and complete foreground regressions.

Three profiles are run sequentially by the caller.  Each retains its actual
inputs/commands/logs; no earlier full-file receipt is relabelled.  The actual
Intel profile preserves all reviewed Q17 sprite fixtures and adds independent
row-pin and original-edge packet checks.  FG profiles preserve the full
31-state/all-bank-pin workload and the unchanged shipping DDR workload.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[2]
PREPARER=ROOT/'tests/graphics/prepare_bt_sprite_data_v23.py'
PREPARER_SHA='817f6d75714aba2a88649401dacab65f20d20c4790c84da2c3d16ec78a7931d6'
OLD=ROOT/'tests/graphics/qualify_bt_fg_v20_controls.py'
OLD_SHA='dcb52aecb244fb56d3bf45d6fed2937b117d1d384c50ae8490389bff5e4e2006'
SPR_OLD=ROOT/'tests/graphics/qualify_bt_sprite_bank_mirrors.py'
SPR_OLD_SHA='bb993daa409d0de4347d23342e407c3d38078f11e808e45f4f1001da7355d077'
Q17=ROOT/'tests/graphics/qualify_bt_sprite_bank_mirrors_q17.py'
Q17_SHA='17d16cf5b93254e693b457ddd4887d2c4d8ea7aa550cc6c88c9fa02dd8844019'
PRIOR=ROOT/'build/sprite_bank_mirrors_v20_v2/proof-r1'
PRIOR_RECEIPT_SHA='3e57a6119e87a94152b1875785fc754dd924a39a44da6d4208ee25a8b6503ed7'
Q17_SIDECAR_SHA='592cea92366ee665ed318ed70582bd70ef8fe2c8219dc38a3ab2d906358a400e'
PACKET=ROOT/'tests/graphics/bt_sprite_data_v23_packet_tb.sv'
TOOLS=Path('D:/q17/modelsim_ase/win32aloem')
VENDOR=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v')
VENDOR_SHA='c2f3f75264468c5ef594c5864fa81b550d113f40e3027c700c6153106d247213'


def sha(raw):return hashlib.sha256(raw).hexdigest()
def record(path):return {'path':str(Path(path).resolve()),'sha256':sha(Path(path).read_bytes()),'bytes':Path(path).stat().st_size}
def checked(path,expected):
 raw=Path(path).read_bytes();assert sha(raw)==expected,(str(path),'digest changed');return raw
def load(path,name):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
def once(text,old,new):
 assert text.count(old)==1,('fixture anchor changed',old);return text.replace(old,new,1)
def canonical(raw):return raw.replace(b'\r\n',b'\n')
def namespace_sprite(raw,suffix):
 text=canonical(raw).decode('latin1')
 for name in ('SPR_VRAM','BT_SPR_POST_NONZERO_MIRROR'):
  text=re.sub(r'\b'+name+r'\b',name+suffix,text)
 return text.encode('latin1')


def vendor_fixture(raw):
 text=canonical(raw).decode('latin1')
 replacements=[('BT_SPR_POST_NONZERO_MIRROR_V20','BT_SPR_POST_NONZERO_MIRROR_P'),
               ('BT_SPR_POST_NONZERO_MIRROR_BANKS','BT_SPR_POST_NONZERO_MIRROR_C')]
 for old,new in replacements:text=text.replace(old,new)
 text=once(text,'BT_SPR_POST_NONZERO_MIRROR_C #(10,1,1) active(',
                'BT_SPR_POST_NONZERO_MIRROR_C #(10,1,1,1) active(')
 # Eight independently specified expected bit permutations. These are not
 # imported from the producer implementation/function used in the source proof.
 patterns=((1,2,3,4,5,6,0),(2,3,4,5,6,0,1),(3,4,5,6,0,1,2),(4,5,6,0,1,2,3),
           (5,6,0,1,2,3,4),(6,0,1,2,3,4,5),(6,5,4,3,2,1,0),(1,0,2,3,4,5,6))
 checks=[' integer permutation_pin_checks=0;']
 for variant,p in enumerate(patterns):
  hierarchy='active.registered_foreground_banks.foregrounds[%d].banks[%d].mirror'%(variant//4,variant%4)
  # Intel byteena_a is tri1: literal Z resolves to 1 at BOTH unchanged
  # leaf interfaces.  Compare resolved pins, retaining every X/Z case.
  # Address inputs are ordinary nets, and their unchanged 9:3 indices
  # are reindexed by the independent bijection specified above.
  w='{'+','.join('original.raw_mirror.WADDR[%d]'%(p[bit]+3) for bit in reversed(range(7)))+'}'
  r='{'+','.join('original.raw_mirror.RADDR[%d]'%(p[bit]+3) for bit in reversed(range(7)))+'}'
  checks.append(' always @(posedge clk or negedge clk)begin\n  #0.1;assert({%s.WADDR,%s.RADDR,%s.DATA,%s.WREN,%s.CLK,%s.ACLR}==={%s,%s,original.raw_mirror.DATA,original.raw_mirror.WREN,original.raw_mirror.CLK,1\'b0})else $fatal(1,"permuted mirror resolved pins changed bank%d");\n  assert({active.WADDR,active.RADDR,active.DATA,active.WREN,active.CLK,active.ACLR}==={original.WADDR,original.RADDR,original.DATA,original.WREN,original.CLK,original.ACLR} && {default_off.WADDR,default_off.RADDR,default_off.DATA,default_off.WREN,default_off.CLK,default_off.ACLR}==={original.WADDR,original.RADDR,original.DATA,original.WREN,original.CLK,original.ACLR})else $fatal(1,"upstream literal control resolution changed");permutation_pin_checks++;\n end'%(hierarchy,hierarchy,hierarchy,hierarchy,hierarchy,hierarchy,w,r,variant))
 additions='\n'.join(checks)+'\n'
 text=once(text,' initial begin\n',additions+' initial begin\n')
 report='  $display("SPRITE_V23_PERMUTATION_PINS_PASS checks=%0d banks=8",permutation_pin_checks);\n'
 text=once(text,'  $finish;',report+'  $finish;')
 # Removing only namespace/activation/additions recovers every prior assertion
 # and stimulus byte (after the declared LF canonicalization).
 inverse=text.replace(additions,'',1).replace(report,'',1)
 inverse=once(inverse,'BT_SPR_POST_NONZERO_MIRROR_C #(10,1,1,1) active(',
                       'BT_SPR_POST_NONZERO_MIRROR_C #(10,1,1) active(')
 for old,new in reversed(replacements):inverse=inverse.replace(new,old)
 assert inverse.encode('latin1')==canonical(raw)
 return text.encode('latin1'),{'additions':additions,'report':report,'namespace':replacements,'full_fixture_inverse':True,
  'resolved_pin_scope':{'address_expected_from':'original.raw_mirror.WADDR/RADDR, independently permuted 9:3 indices',
                       'other_expected_from':'original.raw_mirror.DATA/WREN/CLK; original hard mirror ACLR=0',
                       'vendor_byteena_a_net_kind':'tri1 at frozen altera_mf.v:47724',
                       'upstream_active_default_original_controls_compared':True,'literal_XZ_cases_retained':True}}


def stock_sprite_fixture(raw,profile):
 text=canonical(raw).decode('latin1')
 replacements=[('SPR_VRAM_V20','SPR_VRAM_P'),('SPR_VRAM_BANKS','SPR_VRAM_C')]
 for old,new in replacements:text=text.replace(old,new)
 old='.REGISTERED_FG_BANK_Q(1))'
 assert text.count(old)==1
 # Stock tests retain the legacy external packet word. They activate only the
 # row permutation; the additional full module bench activates local packet D.
 text=once(text,old,'.REGISTERED_FG_BANK_Q(1),.FG_BANK_ADDR_PERMUTE(1))')
 inverse=once(text,'.REGISTERED_FG_BANK_Q(1),.FG_BANK_ADDR_PERMUTE(1))',old)
 for before,after in reversed(replacements):inverse=inverse.replace(after,before)
 assert inverse.encode('latin1')==canonical(raw)
 return text.encode('latin1'),{'namespace':replacements,'only_activation':'FG_BANK_ADDR_PERMUTE(1)','full_fixture_inverse':True,'profile':profile}


def fg_fixture(raw):
 text=canonical(raw).decode('latin1')
 additions='''
  integer fg_v23_packet_d_checks=0;
  always @(posedge CLK or negedge CLK) begin
    #0.1;
    assert(candidate.CPU_SHIFT_SOURCE_D === (reference.SQ_D | (reference.COPY_WORD & {64{reference.COPY_WE}})))
      else $fatal(1,"foreground packet raw D differs");
    assert({candidate.CPU_SHIFT_DATA_Q,candidate.CPU_SHIFT_WA_Q,candidate.CPU_SHIFT_WE_Q} ===
           {reference.CPU_SHIFT_DATA_Q,reference.CPU_SHIFT_WA_Q,reference.CPU_SHIFT_WE_Q})
      else $fatal(1,"original foreground packet stages changed");
    fg_v23_packet_d_checks=fg_v23_packet_d_checks+1;
  end
'''
 text=once(text,'  initial begin\n',additions+'  initial begin\n') if text.count('  initial begin\n')==1 else text.replace('  initial begin\n',additions+'  initial begin\n',1)
 marker='    $display("PASS serial chunk complete pins/state:'
 report='    $display("PASS FG v23 packet D: checks=%0d",fg_v23_packet_d_checks);\n'
 text=once(text,marker,report+marker)
 assert text.replace(additions,'',1).replace(report,'',1).encode('latin1')==canonical(raw)
 return text.encode('latin1'),{'additions':additions,'report':report,'full_fixture_inverse':True}


def vendor_case_projection(actual,expected):
 """Only the two observed spellings of this exact Intel vendor file qualify."""
 aliases=('D:\\Q17\\quartus\\eda\\sim_lib\\altera_mf.v',
          'D:\\q17\\quartus\\eda\\sim_lib\\altera_mf.v')
 left,right=map(Path,aliases)
 assert left.samefile(right)
 checked(left,VENDOR_SHA);checked(right,VENDOR_SHA)
 assert set(actual)-set(expected)<=set(aliases) and set(expected)-set(actual)<=set(aliases)
 assert all(actual[key]==expected[key] for key in actual.keys() & expected.keys())
 projected=dict(actual)
 for old in set(actual)-set(expected):
  destinations=set(expected)-set(actual);assert len(destinations)==1
  new=next(iter(destinations));assert old in aliases and new in aliases
  assert Path(old).samefile(Path(new)) and actual[old]==expected[new]==VENDOR_SHA
  projected[new]=projected.pop(old)
 assert projected==expected
 return projected


def validate_q17_parent():
 # Repeat the unchanged sidecar's complete original source/input/log/coverage
 # validation, with one separately typed vendor-ledger spelling projection.
 q17=load(Q17,'sprite_data_q17_evidence')
 sidecar_path=PRIOR/'q17-declaration-qualification.json'
 sidecar=json.loads(checked(sidecar_path,Q17_SIDECAR_SHA))
 assert sidecar['schema']=='bt-v20-sprite-bank-mirror-q17-declaration-qualification-v1'
 assert sidecar['status']=='PASS_FRESH_VENDOR_CONSUMERS_AND_PINS'
 assert sidecar['adapter_sha256']==Q17_SHA
 source=q17.load(q17.PREPARER,'strict_q17_source',sidecar['source_adapter_sha256'])
 parents,candidates,manifest=source.verify_edge(Path(sidecar['edge']))
 assert sidecar['edge_sha256']==sha((Path(sidecar['edge'])/'manifest.json').read_bytes())
 assert sidecar['candidate_sources']=={rel:sha(raw) for rel,raw in candidates.items()}
 verifier=q17.load(q17.VERIFIER,'unchanged_v1_sprite_data_verifier',q17.VERIFIER_SHA)
 assert verifier.PREPARER==q17.OLD_PREPARER
 verifier.PREPARER=q17.PREPARER  # Same one declared source callback as old Q17 adapter.
 validated=verifier.verify_proof(sidecar['edge'],sidecar['worker_receipt'])
 expected=sidecar['validated_evidence']
 assert set(validated)==set(expected)
 projected=dict(validated)
 projected['bound_evidence_files']=vendor_case_projection(validated['bound_evidence_files'],expected['bound_evidence_files'])
 assert projected==expected  # Every non-vendor key/value stays exactly equal.
 assert sidecar['worker_sha256']==q17.WORKER_SHA==SPR_OLD_SHA
 assert sidecar['verifier_sha256']==q17.VERIFIER_SHA
 assert sidecar['source_adapter_sha256']==sha(q17.PREPARER.read_bytes())
 assert sidecar['new_v1_receipt_retagged'] is False
 rejected=[]
 base={'D:\\q17\\quartus\\eda\\sim_lib\\altera_mf.v':VENDOR_SHA}
 for label,wrong in [('different_file',{'D:\\q17\\quartus\\eda\\sim_lib\\220model.v':VENDOR_SHA}),
                     ('different_bytes',{'D:\\Q17\\quartus\\eda\\sim_lib\\altera_mf.v':'0'*64}),
                     ('different_path',{'D:\\q17\\quartus\\eda\\sim_lib\\..\\sim_lib\\altera_mf.v':VENDOR_SHA})]:
  try:vendor_case_projection(wrong,base)
  except AssertionError:rejected.append(label)
  else:raise AssertionError((label,'vendor alias control accepted'))
 assert rejected==['different_file','different_bytes','different_path']
 return {'status':'PASS_UNCHANGED_PARENT_PROOF_WITH_TWO_KEY_VENDOR_CASE_EDGE',
         'sidecar':record(sidecar_path),'validated_evidence':projected,
         'vendor_case_edge':{'aliases':list(base)+['D:\\Q17\\quartus\\eda\\sim_lib\\altera_mf.v'],
                            'Path_samefile':True,'both_raw_sha256':VENDOR_SHA,
                            'scope':'Only these two exact dictionary keys; no global path normalization or existence exception.',
                            'rejected_controls':rejected}}


def make_inputs(edge,profile):
 checked(PREPARER,PREPARER_SHA);checked(OLD,OLD_SHA)
 prep=load(PREPARER,'sprite_data_source_preparer');runtime=load(OLD,'sprite_data_fg_runtime')
 parents,candidates,manifest=prep.verify_edge(edge)
 snapshot=json.loads(checked(prep.SNAPSHOT,prep.SNAPSHOT_SHA))
 sources={};inputs={};helpers=[PREPARER,OLD,Path(__file__).resolve()];details={}
 for name in ('rtl/BT_mem.sv','rtl/ddram.sv','rtl/bt_fg_ddr_clear.sv'):
  path=prep.PARENT/name;raw=checked(path,snapshot['sources'][name]);sources[name]=record(path);inputs[path.name]=raw
 if profile=='vendor':
  checked(SPR_OLD,SPR_OLD_SHA);checked(Q17,Q17_SHA);checked(VENDOR,VENDOR_SHA)
  checked(PRIOR/'receipt.json',PRIOR_RECEIPT_SHA)
  checked(PRIOR/'q17-declaration-qualification.json',Q17_SIDECAR_SHA)
  details['prior_q17_validation']=validate_q17_parent()
  prior=json.loads((PRIOR/'preparation.json').read_bytes())
  fixture_data={}
  for name in ('sprite_local_q_vendor_tb.sv','sprite_read_equivalence_tb.sv','sprite_packet_tb.sv','sprite_bank_ram_pin_tb.sv'):
   path=PRIOR/'compiled'/name;fixture_data[name]=checked(path,prior['compiled_sources'][str(path.resolve())]);sources[name]=record(path)
  inputs={'spr_parent.sv':namespace_sprite(parents['rtl/spr_vram.sv'],'_P'),
          'spr_candidate.sv':namespace_sprite(candidates['rtl/spr_vram.sv'],'_C'),
          'BT_mem.sv':inputs['BT_mem.sv'],'sprite_data_v23_packet_tb.sv':PACKET.read_bytes()}
  inputs['sprite_local_q_vendor_tb.sv'],details['vendor_fixture']=vendor_fixture(fixture_data['sprite_local_q_vendor_tb.sv'])
  for name,label in (('sprite_read_equivalence_tb.sv','read'),('sprite_packet_tb.sv','packet')):
   inputs[name],details[name]=stock_sprite_fixture(fixture_data[name],label)
  worker=load(SPR_OLD,'sprite_data_bank_module')
  inputs['bank_parent.sv']=worker.bank_module(parents['rtl/fg_vram.sv'],'_V20')
  inputs['bank_candidate.sv']=worker.bank_module(candidates['rtl/fg_vram.sv'],'_BANKS')
  inputs['sprite_bank_ram_pin_tb.sv']=fixture_data['sprite_bank_ram_pin_tb.sv']
  helpers += [SPR_OLD,Q17,PACKET,ROOT/'tests/graphics/verify_bt_sprite_bank_mirror_proof.py']
 else:
  inputs['fg_vram.sv']=candidates['rtl/fg_vram.sv']
  reference=parents['rtl/fg_vram.sv'].decode('latin1')
  modules=re.findall(r'^module\s+(\w+)',reference,re.M)
  for module in sorted(modules,key=len,reverse=True):reference=re.sub(r'\b'+re.escape(module)+r'\b',module+'_REFERENCE',reference)
  inputs['reference-fg_vram.sv']=reference.encode('latin1');details['namespace_modules']=modules
  for name in ('tests/graphics/ram_models.sv','tests/foreground_ddr_tb.sv'):
   path=ROOT/name;inputs[path.name]=checked(path,runtime.BOUND[name]);sources[name]=record(path)
  vendor=checked(runtime.VENDOR,runtime.VENDOR_SHA)
  primitive=re.search(rb'(?m)^module lcell \(in, out\);\r?\n.*?^endmodule',vendor,re.S)[0]
  assert sha(primitive)==runtime.PRIMITIVE_SHA
  inputs['intel_lcell.v']=b'`timescale 1ps/1ps\n'+primitive+b'\n'
  tb=checked(runtime.TB,runtime.TB_SHA);inputs['item4_foreground_equivalence_tb.sv'],details['fg_fixture']=fg_fixture(tb);sources['original_fg_fixture']=record(runtime.TB)
  if profile=='four-state-fg':
   order=runtime.load(runtime.ORDER,runtime.ORDER_SHA,'sprite_data_fg_decl_order')
   adapters={}
   for name in ('fg_vram.sv','reference-fg_vram.sv'):
    raw=inputs[name];adapted,detail=order.declaration_order(canonical(raw),runtime.ORDER_NAMES)
    adapters[name]={'raw_sha256':sha(raw),'canonical_sha256':sha(canonical(raw)),**detail};inputs[name]=adapted
   raw=inputs['item4_foreground_equivalence_tb.sv'];adapted,detail=order.declaration_order(raw,('DRAW_ADDR',))
   adapters['item4_foreground_equivalence_tb.sv']=detail;inputs['item4_foreground_equivalence_tb.sv']=adapted
   details['declaration_order_adapters']=adapters;helpers.append(runtime.ORDER)
 return inputs,helpers,{'source_manifest':record(edge/'manifest.json'),'parent_sources':sources,'fixture_edges':details,
  'oracle_files':{rel:sha(data) for rel,data in parents.items()},'candidate_files':{rel:sha(data) for rel,data in candidates.items()},
  'source_proof':manifest['source_proof'],'snapshot':record(prep.SNAPSHOT)}


def prepare(edge,output,profile):
 assert not output.exists() and output.is_relative_to(ROOT/'build')
 inputs,helpers,binding=make_inputs(edge,profile)
 target=output/'inputs';target.mkdir(parents=True);frozen=output/'executed-helpers';frozen.mkdir()
 for name,raw in inputs.items():(target/name).write_bytes(raw)
 for path in helpers:(frozen/path.name).write_bytes(path.read_bytes())
 meta={'schema':'bt-v23-sprite-data-proof-inputs-v1','profile':profile,'edge':str(edge),**binding,
  'helpers':{str(path):sha(path.read_bytes()) for path in helpers},
  'executed_helpers':{str(path):sha(path.read_bytes()) for path in frozen.iterdir()},
  'compiled_inputs':{str(target/name):sha(raw) for name,raw in inputs.items()},
  'original_assertions_preserved':True,'case_equality_exclusions':0,'collision_masks_added':0,
  'actual_Intel_vendor_RAM':profile=='vendor','physical_retention_or_timing_claim':False}
 (output/'preparation.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
 verify_inputs(output,meta)
 return meta


def verify_inputs(output,meta):
 assert meta['schema']=='bt-v23-sprite-data-proof-inputs-v1'
 for key in ('helpers','executed_helpers','compiled_inputs'):
  for path,digest in meta[key].items():checked(path,digest)
 inputs,helpers,binding=make_inputs(Path(meta['edge']),meta['profile'])
 assert {str(output/'inputs'/name):sha(raw) for name,raw in inputs.items()}==meta['compiled_inputs']
 for key,value in binding.items():
  # JSON has one sequence type: namespace edit tuples are serialized as lists.
  assert json.loads(json.dumps(meta[key]))==json.loads(json.dumps(value)),(key,'regeneration changed')
 return True


def coverage(output,profile,runtime):
 if profile=='vendor':
  logs={name:(output/(name+'.log')).read_text(errors='replace') for name in ('vendor','read','packet','local-packet','pin')}
  assert all(not runtime.failure_text(text) for text in logs.values())
  m=re.search(r'SPRITE_LOCAL_VENDOR_PASS pre=(\d+) post=(\d+) old_data=(\d+) mask_cases=(\d+) collisions=(\d+) offedge=(\d+) unknown=(\d+)',logs['vendor']);assert m
  values=list(map(int,m.groups()));assert values[2:6]==[128,32768,16384,16] and values[6]>0
  banks=re.search(r'SPRITE_REGISTERED_BANKS checks=(\d+) mirrors=8 literal_control_cases=(\d+)',logs['vendor']);assert banks and int(banks[2])==50
  pins=re.search(r'SPRITE_V23_PERMUTATION_PINS_PASS checks=(\d+) banks=8',logs['vendor']);assert pins and int(pins[1])>500000
  local=re.search(r'SPRITE_V23_LOCAL_PACKET_PASS checks=(\d+) resets=(\d+) loads=(\d+) owner0=(\d+) owner1=(\d+) xz=(\d+)',logs['local-packet']);assert local
  local_counts=list(map(int,local.groups()));assert local_counts[0]>=8192 and local_counts[1]>=30 and local_counts[2]>2000 and local_counts[3]>1000 and local_counts[4]>1000 and local_counts[5]==512
  pin=re.search(r'SPRITE_BANK_PIN_PASS cases=(\d+) pre=(\d+) post=(\d+) banks=4 pins=12',logs['pin']);assert pin and int(pin[1])==2048
  assert 'PASS' in logs['read'] and 'PASS' in logs['packet']
  return {'vendor_original_counts':values,'registered_bank_checks':int(banks[1]),'literal_XZ_control_cases':50,
          'actual_RAM_permutation_pin_checks':int(pins[1]),'local_packet_counts':local_counts,
          'bank_selector_cases':2048,'bank_pre_pin_checks':int(pin[2]),'bank_post_pin_checks':int(pin[3]),
          'preserved_sprite_read_and_packet_logs':{k:record(output/(k+'.log')) for k in ('read','packet')}}
 path=output/('fg/run.log' if profile=='native-fg' else 'run.log');text=path.read_text(errors='replace')
 assert not runtime.failure_text(text)
 state=re.search(r'PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)',text)
 raw=re.search(r'PASS FG v23 packet D: checks=(\d+)',text);assert state and raw
 assert tuple(map(int,state.groups()))==(1263909,10111272) and int(raw[1])>1260000
 result={'complete_state_edges':1263909,'all_bank_pin_checks':10111272,'packet_D_identity_checks':int(raw[1]),'states':31,'banks':4,'RAM_pin_fields':13}
 if profile=='native-fg':
  text=(output/'fg-ddr/run.log').read_text(errors='replace')
  assert not runtime.failure_text(text) and 'PASS shipping DDR controller: 196608 cold-clear writes during reset, 128 masked writes, 512 round-trip copy bytes, cache reads and command backpressure' in text
  result.update(cold_clear_writes=196608,masked_writes=128,copy_bytes=512)
 return result


def simulate(output,meta):
 runtime=load(OLD,'sprite_data_actual_runtime');inputs=output/'inputs';runs=[];profile=meta['profile']
 if profile=='vendor':
  work=output/'work';pin=output/'pin_work'
  jobs=[([str(TOOLS/'vlib.exe'),str(work)],'vlib.log'),
   ([str(TOOLS/'vlog.exe'),'-sv','-work',str(work),*[str(inputs/name) for name in ('spr_parent.sv','spr_candidate.sv','BT_mem.sv','sprite_local_q_vendor_tb.sv','sprite_read_equivalence_tb.sv','sprite_packet_tb.sv','sprite_data_v23_packet_tb.sv')],str(VENDOR)],'build.log'),
   ([str(TOOLS/'vlib.exe'),str(pin)],'pin-vlib.log'),
   ([str(TOOLS/'vlog.exe'),'-sv','-work',str(pin),*[str(inputs/name) for name in ('bank_parent.sv','bank_candidate.sv','sprite_bank_ram_pin_tb.sv')]],'pin-build.log')]
  for top,label,library in (('sprite_local_q_vendor_tb','vendor',work),('sprite_read_equivalence_tb','read',work),('sprite_packet_tb','packet',work),('sprite_data_v23_packet_tb','local-packet',work),('sprite_bank_ram_pin_tb','pin',pin)):
   jobs.append(([str(TOOLS/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib',str(library),top,'-do','run -all; quit -code 0'],label+'.log'))
  for command,log in jobs:
   runs.append(runtime.run(command,output,output/log))
   if runs[-1]['exit_code']:break
 elif profile=='native-fg':
  for label,top,files in [('fg','item4_foreground_equivalence_tb',['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','intel_lcell.v','item4_foreground_equivalence_tb.sv']),('fg-ddr','foreground_ddr_tb',['fg_vram.sv','ddram.sv','bt_fg_ddr_clear.sv','ram_models.sv','intel_lcell.v','foreground_ddr_tb.sv'])]:
   target=output/label;target.mkdir()
   command=['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec','verilator','--binary','--assert','--timing','-j','4','--threads','1','--x-initial','unique','--x-assign','unique','--top-module',top,'--Mdir',runtime.wsl(target/'obj'),'-Wno-fatal',*files]
   runs.append(runtime.run(command,inputs,target/'build.log'))
   if runs[-1]['exit_code']:break
   runs.append(runtime.run(['C:/Windows/System32/wsl.exe','-d','Ubuntu','--cd',str(inputs),'--exec',runtime.wsl(target/'obj'/('V'+top))],inputs,target/'run.log'))
   if runs[-1]['exit_code']:break
 else:
  work=output/'work';jobs=[([str(TOOLS/'vlib.exe'),str(work)],'vlib.log'),
   ([str(TOOLS/'vlog.exe'),'-sv','-work',str(work),*[str(inputs/name) for name in ('fg_vram.sv','reference-fg_vram.sv','ram_models.sv','intel_lcell.v','item4_foreground_equivalence_tb.sv')]],'build.log'),
   ([str(TOOLS/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','-lib',str(work),'item4_foreground_equivalence_tb','-do','run -all; quit -code 0'],'run.log')]
  for command,log in jobs:
   runs.append(runtime.run(command,output,output/log))
   if runs[-1]['exit_code']:break
 passed=bool(runs) and all(row['exit_code']==0 for row in runs);counts={};error=None
 if passed:
  try:counts=coverage(output,profile,runtime)
  except (AssertionError,OSError) as exc:passed=False;error=repr(exc)
 verify_inputs(output,meta)
 receipt={'schema':'bt-v23-sprite-data-proof-v1','status':'PASS' if passed else 'FAIL','profile':profile,
  'preparation':record(output/'preparation.json'),'commands':runs,'coverage':counts,'failure':error,
  'candidate_files':meta['candidate_files'],'oracle_files':meta['oracle_files'],'source_manifest':meta['source_manifest'],
  'compiled_inputs':meta['compiled_inputs'],'executed_helpers':meta['executed_helpers'],
  'original_assertions_preserved':True,'case_equality_exclusions':0,'collision_masks_added':0,
  'actual_Intel_vendor_RAM':profile=='vendor','mapped_replicas_or_timing_proven':False,'rbf_generated':False}
 (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
 print(json.dumps({'status':receipt['status'],'receipt':record(output/'receipt.json'),'coverage':counts,'failure':error},separators=(',',':')))
 assert passed,'Original assertions or strict coverage failed'


def verify_proof(output):
 output=Path(output).resolve();meta=json.loads((output/'preparation.json').read_bytes());verify_inputs(output,meta)
 receipt=json.loads((output/'receipt.json').read_bytes());assert receipt['status']=='PASS'
 assert receipt['preparation']==record(output/'preparation.json')
 assert receipt['compiled_inputs']==meta['compiled_inputs'] and receipt['candidate_files']==meta['candidate_files']
 for row in receipt['commands']:
  assert row['exit_code']==0;checked(row['log']['path'],row['log']['sha256'])
 counts=coverage(output,meta['profile'],load(OLD,'sprite_data_reparse'))
 assert receipt['coverage']==counts
 return {'receipt':record(output/'receipt.json'),'coverage':counts,'compiled_inputs':meta['compiled_inputs'],
         'source_manifest':meta['source_manifest'],'typed_scope':meta['profile']}


def main():
 parser=argparse.ArgumentParser();parser.add_argument('--edge',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
 parser.add_argument('--profile',choices=('vendor','native-fg','four-state-fg'),required=True)
 parser.add_argument('--prepare-only',action='store_true');parser.add_argument('--resume',action='store_true');parser.add_argument('--verify-only',action='store_true')
 args=parser.parse_args();output=args.output.resolve();assert output.is_relative_to(ROOT/'build')
 if args.verify_only:print(json.dumps(verify_proof(output),separators=(',',':')));return
 if args.resume:
  meta=json.loads((output/'preparation.json').read_bytes());assert meta['profile']==args.profile;verify_inputs(output,meta)
 else:meta=prepare(args.edge.resolve(),output,args.profile)
 if args.prepare_only:print(json.dumps({'status':'PREPARED','preparation':record(output/'preparation.json')},separators=(',',':')))
 else:simulate(output,meta)


if __name__=='__main__':main()
