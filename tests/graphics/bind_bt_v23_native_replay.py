"""Bind the immutable v23 source proofs to its actual 128-frame native replay.

This verifier performs no compilation or simulation.  Its compiler projection
is deliberately limited to BT_NATIVE_SIM; the production emu/HPS and pad timing
are separate obligations.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path, PureWindowsPath

ROOT=Path(__file__).resolve().parents[2]
SCHEMA='bt-v23-current-input-native-replay-composition-v1'
STATUS='PASS_SCOPED_COMPOSITION'
RUN='native-7fb37e39f9704977b316c9aa38db2148'
PINS={
 'source_helper':('tests/graphics/bind_bt_final_bg_cpu_fg_inputs.py','cb4b37258d2ade627c25660fb722de87787f9df5975d4fae3804f98a251eef00'),
 'source':('build/final_v23_current_input_qualification_r1/receipt.json','dcb5047a888cbc6846fa7630426cf9458f8743a8bb9a5dd4140c6b9007ed1648'),
 'replay':('build/native_lcell_link_v23_v1/qualified-128-r1/receipt.json','a1bbf28570b895f6e15ccad5f25854ea436014590887ee2528fcf8fee50e43e1'),
 'creator':('build/native_lcell_link_v23_v1/qualify_128.py','e79d34d4b41902600e573d4619ea179d22e1f88de8fd78e5f2ac3a9b5c36e135'),
 'creator_projection':('build/native_lcell_link_v23_v1/qualifier-static-projection.json','2d3d2bebc86b1b6351d1ba14b980f49c2e88197c074f271d30118400abaf9aac'),
 'preparation':('build/native_lcell_link_v23_v1/proof-128-r1/preparation.json','79e737e07c130e46fc98e7191e61d2a51694095f84d9c70bb52e9d362b8ad0b3'),
 'parent_replay':('build/native_lcell_link_v22_v1/qualified-128-r1/receipt.json','9d0dcd907838171d1ece06d91c831342cb9271387d781a453abd56c96ed21c20'),
}
SNAPSHOT_SHA='627f642c9490ce2ffeb532313e33e750a1b67997b2d99a46f3a2cc564d6f6e67'
JOURNAL_SHA='cb8fa1afa6e4f446eb7921921689b8b5b2f246c1530122bae0b2e89612ad708b'
PHASE=dict(frame=128,captures=2573046,cpu=279286,sprite=0,fg0=1146880,fg1=1146880,
 launch_age_checks=2573046,ext_reloads=53513164,fs_reloads=660076,ba_reloads=1014,
 buf_reloads=660076,min_ext=5,min_fs=5,min_ba=5,min_buf=3,probe_checks=171038303,conservative_false=2486591)
OVERLAY={'rtl/BT.sv','rtl/bg_vram.sv','rtl/fg_vram.sv','rtl/spr_vram.sv','rtl/ddram.sv',
         'rtl/TMS34020/TMS34020.sv','rtl/TMS34020/TMS34020_MC.sv'}

def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
    if not value:raise AssertionError(message)
def normal(value):return json.loads(json.dumps(value))
def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m);return m
def canonical(data):return data.decode().replace('\r\n','\n').replace('\r','\n')
def windows_text(text):return text.replace('\n','\r\n').encode()

def claim(rec):
    require(rec['schema']=='bt-current-v23-native128-lcell-raster-qualification-v1'
            and rec['status']=='PASS_ACTUAL_NATIVE128_AND_24_RASTERS','actual v23 replay required')
    require(rec['selected_snapshot_sha256']==SNAPSHOT_SHA
            and rec['functional_composition_sha256']==PINS['source'][1],'replay source identity changed')
    require(rec['requested_frames']==128 and rec['actual_native_exit_code']==0
            and rec['actual_complete_cycles']==172308065 and rec['actual_DDR_commands']==2878478
            and rec['actual_logged_phase_frames_checked']==[1,128]
            and rec['actual_last_frame_DDR_phase']==PHASE,'actual replay/phase counts changed')
    require(rec['compiler_top']=='BT_NATIVE_SIM' and rec['compiled_primitive_input_count']==1
            and rec['actual_compiled_physical_input_files']==31
            and rec['actual_compiled_BG_input_count']==1
            and rec['actual_compiled_BG_input_sha256']=='b0080afc9ae4a5cc110058150f5cc710085e3394be20604524bfe443602ecd17'
            and PureWindowsPath(rec['actual_compiled_BG_input']).parts[-2:]==('rtl','bg_vram.sv'),
            'complete actual compiler/BG binding required')
    require(rec['actual_input_journal_sha256']==JOURNAL_SHA
            and rec['selected_full144_source_inventory_checked'] is True
            and rec['unchanged_per_capture_assertions_enabled_throughout_128_frames'] is True,'native assertion/source contract changed')
    require(rec['native_system_top_reset_partition_compiled'] is False
            and rec['mapped_timing_RBF_hardware_MAME_claim'] is False
            and rec['old_native128_receipts_or_rasters_modified'] is False,'native scope broadened')
    require(rec['failures']==[] and rec['comparison_count']==24 and len(rec['actual_byte_comparisons'])==24
            and len(rec['retained_inputs_logs_and_executable'])==47,'complete actual replay evidence required')
    require(len(rec['negative_controls'])==7 and all(c['rejected'] for c in rec['negative_controls']),
            'actual replay rejection controls changed')

def compiler_inputs(native):
    target=PureWindowsPath(native['snapshot']);commands=native['commands']
    require(len(commands)==4,'exact native command history required')
    source=[]
    for index in (0,2):
        for value in commands[index]:
            path=PureWindowsPath(value)
            if path.suffix.lower() in ('.vhd','.sv','.v','.cpp'):
                try:relative=path.relative_to(target).as_posix()
                except ValueError:raise AssertionError('foreign actual compiler source')
                source.append(relative)
    require(len(source)==31 and len(set(source))==31,'all31 unique actual compiler inputs required')
    return source

def no_comments(data):
    """Ignore comments alone; quoted Verilog bytes remain exact."""
    text=canonical(data)
    return re.sub(r'"(?:\\.|[^"\\])*"|/\*.*?\*/|//[^\n]*',
                  lambda m:m[0] if m[0].startswith('"') else '',text,flags=re.S)

def parse_log(text):
    require(not re.search(r'(?im)\b(?:fatal|assertion failed|FAIL(?:ED)?)\b',text),'actual native assertion failed')
    require(re.findall(r'NATIVE_COMPLETE frames=(\d+) cycles=(\d+) DDR_commands=(\d+)',text)
            ==[('128','172308065','2878478')],'actual native completion log changed')
    rows=[]
    for line in text.splitlines():
        if line.startswith('DDR_PARALLEL_PHASE '):
            rows.append({key:int(value) for key,value in re.findall(r'(\w+)=(\d+)',line)})
    require([row['frame'] for row in rows]==[1,128] and rows[-1]==PHASE,'actual phase log changed')
    require(all(row['captures']==row['launch_age_checks'] and min(row['min_ext'],row['min_fs'],row['min_ba'])>=5
                and row['min_buf']>=3 for row in rows),'physical capture phase minima failed')
    return rows

def bind_actual():
    e_helper=ROOT/PINS['source_helper'][0]
    require(sha(e_helper.read_bytes())==PINS['source_helper'][1],'frozen source binder changed')
    b=load(e_helper,'v23_replay_frozen_source');e=b.Evidence()
    pinned={key:e.json(ROOT/path,digest) for key,(path,digest) in PINS.items() if key not in ('source_helper','creator')}
    e.file(e_helper,PINS['source_helper'][1]);e.file(ROOT/PINS['creator'][0],PINS['creator'][1])
    src=pinned['source'];source_verification=b.verify_composition_receipt(ROOT/PINS['source'][0])
    e.ingest(src['bound_evidence_files'])
    selected=e.json(src['snapshot'],SNAPSHOT_SHA);source_root=Path(src['source_root'])
    rec=pinned['replay'];claim(rec);e.ingest(rec['retained_inputs_logs_and_executable'])
    native=e.json(rec['native_receipt'],rec['native_receipt_sha256'])
    require(Path(native['snapshot']).name==RUN and native['exit_code']==0 and native['requested_frames']==128,
            'wrong actual native execution')
    parent=pinned['parent_replay'];parent_native=e.json(parent['native_receipt'],parent['native_receipt_sha256'])
    old_target=parent_native['snapshot'];target=native['snapshot']
    # Every option and source position is inherited verbatim; only the run root changes.
    expected_commands=[[value.replace(old_target,target) for value in command] for command in parent_native['commands']]
    require(native['commands']==expected_commands,'native compiler/assertions/runtime changed')
    require(native['adaptations']==parent_native['adaptations'] and native['rom_sha256']==parent_native['rom_sha256'],
            'native ROM/preprocessing model changed')
    files=compiler_inputs(native);require(files==compiler_inputs(parent_native),'native compiler projection changed')
    prep=pinned['preparation'];require(prep['selected_snapshot_sha256']==SNAPSHOT_SHA
           and prep['full_selected_input_files']==144 and set(prep['selected_rtl_overlay'])==OVERLAY,
           'full selected/overlay native projection changed')
    require(prep['legacy_assertions_and_runtime_unchanged'] is True
           and prep['native_system_top_reset_partition_compiled'] is False
           and prep['old_receipts_modified_or_retagged'] is False,'native preparation scope changed')
    for relative,record in prep['selected_rtl_overlay'].items():
        require(record['sha256']==selected['sources'][relative] and Path(record['path']).resolve()==(source_root/relative).resolve(),
                'wrong selected native overlay')
        e.file(record['path'],record['sha256'])
    compiled=Path(ROOT/PINS['replay'][0]).parent/'compiled-inputs'
    old_compiled=Path(ROOT/PINS['parent_replay'][0]).parent/'compiled-inputs'
    ledger=rec['retained_inputs_logs_and_executable']
    def retained(relative):
        path=compiled/relative;require(str(path) in ledger,'unlisted actual compiled artifact')
        return e.file(path,ledger[str(path)])
    shim=e.file(ROOT/'tests/graphics/native_lcell_run.py',rec['executed_shim_sha256'])
    shim_module=load(ROOT/'tests/graphics/native_lcell_run.py','v23_replay_frozen_shim')
    worker=retained('native_lcell_worker.py');legacy=e.file(prep['legacy_runner'],prep['legacy_runner_sha256'])
    changes=[(item['old'].encode(),item['new'].encode()) for item in prep['changes']]
    require(sha(worker)==rec['actual_worker_sha256'] and shim_module.inverse(worker,changes)==legacy,
            'native executed worker inverse changed')
    require(retained('native_lcell_run.py')==shim,'executed native shim changed')
    vendor=e.file(prep['vendor'],rec['shipped_vendor_sha256'])
    model=retained('intel_lcell_sim.v');actual_model=shim_module.shipped_model(vendor)
    require(model==actual_model and shim_module.LCELL_SHA==rec['exact_scalar_body_sha256']
            and sha(model)==rec['exact_model_sha256'],'actual shipped LCELL compiler model changed')
    scope_path=ROOT/'tests/graphics/bt_native_mc_scope.py'
    recorded_sources={PureWindowsPath(key).as_posix():value for key,value in native['sources'].items()}
    e.file(scope_path,recorded_sources['tests/graphics/bt_native_mc_scope.py'])
    mc_scope=load(scope_path,'v23_replay_frozen_mc_scope')
    edges={}
    for relative in files:
        actual=retained(relative);edge='raw selected-source byte identity'
        if relative.startswith('rtl/'):
            require(relative in selected['sources'],'actual native RTL outside selected source inventory')
            source=e.file(source_root/relative,selected['sources'][relative])
            require(recorded_sources[relative]==sha(source),'canonical native pre-adapter source hash changed')
            expected=source
            if relative=='rtl/BT.sv':
                text=canonical(source);require(text.count('rtl/bsmt2000.mif')==1,'DSP filename adapter changed')
                expected=windows_text(text.replace('rtl/bsmt2000.mif','rtl/bsmt2000.hex'))
                edge='literal DSP image filename replacement; universal-read and Windows write newlines'
            elif relative=='rtl/TMS34020/TMS34020_MC.sv':
                text=canonical(source);old='\t\tbit         READ_LATCH;';anchor='\tbit          FETCH_LATCH;'
                require(text.count(old)==text.count(anchor)==1,'MC visibility declaration anchors changed')
                text=text.replace(old,'').replace(anchor,anchor+'\n\tbit          READ_LATCH;')
                text,detail=mc_scope.expose_launch_scope(text)
                require(detail==json.loads(retained('mc_launch_scope.json')),'actual MC launch visibility edge changed')
                expected=windows_text(text);edge='exact declaration-only native MC visibility edge and Windows newlines'
            elif relative in ('rtl/T80/T80.vhd','rtl/T80/T80pa.vhd'):
                text=re.sub(r'(:\s*)work\.(T80\w*)',r'\1entity work.\2',canonical(source))
                expected=windows_text(text.replace('ioq and x"7"','ioq and "000000111"'))
                edge='literal VHDL entity binding and width spelling; Windows newlines'
            require(actual==expected,'actual compiler source cannot be reconstructed: '+relative)
        elif relative=='t80_native.v':
            old_ledger=parent['retained_inputs_logs_and_executable'];old_path=old_compiled/relative
            old=e.file(old_path,old_ledger[str(old_path)])
            require(no_comments(actual)==no_comments(old),'actual GHDL generated controller changed outside comments')
            edge='same exact five VHDL inputs/GHDL argv and generated non-comment bytes'
        else:
            origin=ROOT/'tests/graphics'/relative
            if relative!='intel_lcell_sim.v':require(actual==e.file(origin,recorded_sources['tests/graphics/'+relative]),
                                                          'actual native helper input changed: '+relative)
            edge='actual helper byte identity' if relative!='intel_lcell_sim.v' else 'exact shipped Intel scalar primitive model'
        edges[relative]=dict(actual_compiler_path=str(PureWindowsPath(target)/relative),retained_path=str(compiled/relative),
                             compiled_sha256=sha(actual),typed_edge=edge)
    require(retained('obj/VBT_NATIVE_SIM.exe')[:2]==b'MZ','actual runtime must be a native PE executable')
    require(native['input_journal']['sha256']==JOURNAL_SHA and sha(retained('canonical-native/inputs.txt'))==JOURNAL_SHA,
            'actual runtime input journal changed')
    overlay=json.loads(retained('source_overlay.json'))
    require(overlay['files']==prep['selected_rtl_overlay'],'actual compiler overlay recorder changed')
    mixer=shim_module.mixer_scope(e.file(source_root/'Arcade-Battletoads.sv',selected['sources']['Arcade-Battletoads.sv']))
    require(sha(mixer)==prep['mixer_enable_slice_sha256'] and retained('mixer_enable.svh')==windows_text(mixer.decode()),
            'exact compiled mixer slice changed')
    phases=parse_log(retained('canonical-native/run.log').decode(errors='replace'))
    e.file(rec['previous_comparison_receipt'],rec['previous_comparison_receipt_sha256'])
    wanted={(row['kind'],row['name']) for row in parent['actual_byte_comparisons']};seen=set();rows=[]
    for row in rec['actual_byte_comparisons']:
        key=(row['kind'],row['name']);require(key not in seen and key in wanted and row['byte_equal'] is True,
                                             'missing/duplicate/foreign actual raster')
        seen.add(key);data=[e.file(row[k+'_path'],row[k+'_sha256']) for k in ('reference','previous_native','current')]
        require(data[0]==data[1]==data[2] and len(data[2])==row['bytes'],'actual raw raster bytes differ')
        require(Path(row['current_path']).parts[-3]==RUN,'raster belongs to a different native execution')
        rows.append(dict(kind=row['kind'],name=row['name'],bytes=row['bytes'],sha256=sha(data[2])))
    require(seen==wanted and len(rows)==24,'all24 exact raw reference/current rasters required')
    e.recheck()
    result=dict(schema=SCHEMA,status=STATUS,helper_sha256=sha(Path(__file__).read_bytes()),source_root=src['source_root'],
      snapshot=src['snapshot'],snapshot_sha256=SNAPSHOT_SHA,all144_source_inventory_entries_verified=True,
      functional_composition=str(ROOT/PINS['source'][0]),functional_composition_sha256=PINS['source'][1],
      functional_validation=source_verification,actual_replay=str(ROOT/PINS['replay'][0]),actual_replay_sha256=PINS['replay'][1],
      actual_native_id=RUN,actual_compiler_input_projection=edges,actual_compiled_input_files=31,
      actual_selected_overlays=sorted(OVERLAY),actual_raw_rasters=rows,actual_frames=128,actual_cycles=172308065,
      actual_DDR_commands=2878478,actual_phase_rows=phases,actual_journal_sha256=JOURNAL_SHA,
      immutable_git_oracles=src['immutable_git_oracles'],actual_BT_NATIVE_SIM_replay=True,
      production_emu_HPS_top_reset_compiled=False,new_whole_board_native_run=False,
      core_timing_accepted=False,timing_accepted=False,eligible_for_RBF=False,mapped_replication_proven=False,
      old_proofs_or_rasters_modified=False,case_equality_exclusions=0,collision_masks_added=0,
      limits=['Actual native compiler covers the game board, CPUs, memory controller, graphics, audio and exact mixer slice.',
              'Production emu/HPS/top reset, fitted RAM placement, physical I/O, timing, hardware and MAME qualification remain separate.'])
    return result,e

def controls(rec,native):
    result=[]
    for key,value,name in [('actual_compiled_BG_input_count',0,'missing BG compiler input'),
       ('actual_compiled_BG_input_sha256','0'*64,'foreign BG source'),('functional_composition_sha256','0'*64,'foreign source proof'),
       ('actual_input_journal_sha256','0'*64,'changed journal'),('actual_complete_cycles',1,'truncated actual replay'),
       ('actual_last_frame_DDR_phase',dict(PHASE,min_buf=1),'invalid capture age'),
       ('native_system_top_reset_partition_compiled',True,'false whole-board claim')]:
        bad=copy.deepcopy(rec);bad[key]=value
        try:claim(bad)
        except AssertionError:result.append(dict(name=name,rejected=True))
        else:raise AssertionError('native claim corruption was accepted: '+name)
    for change,name in [(lambda r:r['commands'][2].remove('--assert'),'disabled native assertions'),
                        (lambda r:r['commands'][2].append(r['commands'][2][-2]),'duplicate compiler input')]:
        bad=copy.deepcopy(native);change(bad)
        try:
            compiler_inputs(bad)
            require('--assert' in bad['commands'][2],'actual assertions required')
        except AssertionError:result.append(dict(name=name,rejected=True))
        else:raise AssertionError('compiler corruption was accepted: '+name)
    return result

def expected_receipt():
    result,e=bind_actual();rec=json.loads(e.file(ROOT/PINS['replay'][0],PINS['replay'][1]))
    native=json.loads(e.file(rec['native_receipt'],rec['native_receipt_sha256']))
    result['native_corruption_controls']=controls(rec,native);return result,e

def verify_composition_receipt(path):
    path=Path(path).resolve();actual=json.loads(path.read_bytes())
    require(actual['schema']==SCHEMA and actual['status']==STATUS,'wrong current-native composition schema/status')
    expected,e=expected_receipt();e.record(actual['executed_helper']);expected['executed_helper']=actual['executed_helper']
    require(e.file(actual['executed_helper']['path'])==Path(__file__).read_bytes(),'executed replay binder changed')
    expected['bound_evidence_files']=dict(e.files)
    require(normal(actual)==normal(expected),'changed strict native composition receipt/claims')
    e.recheck()
    return dict(status=STATUS,receipt=str(path),receipt_sha256=sha(path.read_bytes()),sources=144,
      actual_compiler_inputs=31,actual_frames=128,actual_raw_rasters=24,verified_evidence_files=len(e.files),
      verified_immutable_git_oracles=len(actual['immutable_git_oracles']),native_negative_controls=9,
      production_emu_HPS_top_reset_compiled=False,timing_accepted=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    output=args.output.resolve();require(not output.exists(),'exclusive new evidence output required')
    result,e=expected_receipt();output.mkdir(parents=True)
    helper=output/Path(__file__).name;helper.write_bytes(Path(__file__).read_bytes())
    result['executed_helper']=dict(path=str(helper),sha256=sha(e.file(helper)),bytes=helper.stat().st_size)
    result['bound_evidence_files']=dict(e.files);path=output/'receipt.json'
    path.write_text(json.dumps(normal(result),indent=2)+'\n')
    verification=verify_composition_receipt(path)
    (output/'verification.json').write_text(json.dumps(verification,indent=2)+'\n');print(json.dumps(verification))
if __name__=='__main__':main()
