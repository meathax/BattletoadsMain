#!/usr/bin/env python3
"""Bind parallel DDR sources and actual reload ages in an isolated native fixture."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import uuid

ROOT=Path(__file__).resolve().parents[2]
NATIVE='b32b7159eccf9f7db4ddf3b906eb9e31d08c5e3c015cada146eda7be233b2a03'
NATIVE_LF='7af25464eaace2c2c2750a9d19e46e24e1cc891fefa69b4ee7e67c3993c53663'
ORACLE='b53726397822b9dbebb02d36411294056fd08649'
E4_NATIVE='e4a771a80eb9dd7fca7893bf5a03e8c93ac8b16a89f2e7e9327d9683748dbc31'
E4_DIR=ROOT/'build/ddr_parallel_sources_v9_v2/native_adapter_v2'
V3_NATIVE='687b71058e5e85c657fd320a8edba48928b21e84128261868b9225281e1e051b'
V3_DIR=ROOT/'build/ddr_parallel_sources_v9_v2/native_adapter_v3_r1'
V4_NATIVE='295782cac0f9c362e45736347b6c9dc8d857a8731455736a1838b02f5731ad5a'
MONITOR='''    // BT_PARALLEL_NATIVE_PHASE_BEGIN
    // Exact launch predicates include identical-value reloads. Independent
    // NBA probes attached to every actual private-copy MC assignment verify
    // these predicates against the unchanged original control branches. A
    // coincident MEM capture samples pre-NBA Q and therefore its prior launch;
    // the next MEM edge sees the new source launch, even for identical values.
    realtime parallel_last_mem_edge=0,parallel_mem_period=0;
    realtime parallel_ext_launch=0,parallel_fs_launch=0,parallel_ba_launch=0,parallel_buf_launch=0;
    longint unsigned parallel_ext_reloads=0,parallel_fs_reloads=0,parallel_ba_reloads=0,parallel_buf_reloads=0;
    longint unsigned parallel_capture_checks=0,parallel_cpu_captures=0,parallel_sprite_captures=0;
    longint unsigned parallel_fg0_captures=0,parallel_fg1_captures=0,parallel_launch_age_checks=0;
    longint unsigned parallel_min_ext_age='1,parallel_min_fs_age='1,parallel_min_ba_age='1,parallel_min_buf_age='1;
    logic[31:0] parallel_captured_word=0;
    logic[3:0] parallel_captured_owner=0;
    bit parallel_captured_valid=0;
    string parallel_last_ext_event,parallel_last_fs_event,parallel_last_ba_event,parallel_last_buf_event;
    realtime parallel_last_any_f=0;
    logic parallel_last_any_f_state=0;
    logic[3:0] parallel_last_any_f_probes=0;
    longint unsigned parallel_conservative_false_count=0;
    logic[3:0] parallel_expected_probes=0;
    bit parallel_probe_valid=0;
    longint unsigned parallel_probe_checks=0;
    wire parallel_f_idle=core.CPU.MC.RST_N && core.CPU.MC.EN && ce_f && !core.CPU.MC.MC_STATE;
    wire parallel_r_idle=core.CPU.MC.RST_N && core.CPU.MC.EN && ce_r && !core.CPU.MC.MC_STATE;
    wire parallel_buf_load=parallel_r_idle &&
        ((core.CPU.MC.MC_READ_PEND && core.CPU.MC.RMW) || core.CPU.MC.MC_WRITE_PEND);
    wire parallel_ba_load=parallel_f_idle && !core.CPU.MC.MC_READ_EXT && core.CPU.MC.MC_WRITE_EXT;
    wire parallel_fs_load=parallel_f_idle && !core.CPU.MC.MC_READ_EXT && !core.CPU.MC.MC_WRITE_EXT &&
        !core.CPU.MC.SCRREF_PEND && !core.CPU.MC.READ && core.CPU.MC.WRITE && !core.CPU.MC.CACHE;
    always @(posedge CLK or negedge core.CPU.MC.RST_N) begin
        parallel_expected_probes<={(!core.CPU.MC.RST_N || parallel_f_idle),
            (!core.CPU.MC.RST_N || parallel_fs_load),parallel_ba_load,
            (!core.CPU.MC.RST_N || parallel_buf_load)};
        parallel_probe_valid<=1;
        if(!core.CPU.MC.RST_N) begin
            parallel_ext_launch<=$realtime;parallel_fs_launch<=$realtime;
            parallel_buf_launch<=$realtime;
        end else begin
            if(core.CPU.MC.EN && ce_f)begin
                parallel_last_any_f<=$realtime;parallel_last_any_f_state<=core.CPU.MC.MC_STATE;
                parallel_last_any_f_probes<={parallel_f_idle,parallel_fs_load,parallel_ba_load,parallel_buf_load};
            end
            if(parallel_f_idle)begin parallel_ext_launch<=$realtime;parallel_ext_reloads++;
                parallel_last_ext_event<=$sformatf("EXT t=%0t state=%b old=%b rdext=%b wrext=%b",$time,
                    core.CPU.MC.MC_STATE,core.CPU.MC.MC_EXT_WORD,core.CPU.MC.MC_READ_EXT,core.CPU.MC.MC_WRITE_EXT);
            end
            if(parallel_fs_load)begin parallel_fs_launch<=$realtime;parallel_fs_reloads++;
                parallel_last_fs_event<=$sformatf("FS t=%0t old=%h new=%h",$time,core.CPU.MC.DOUT_FS,core.CPU.MC.FS);end
            if(parallel_ba_load)begin parallel_ba_launch<=$realtime;parallel_ba_reloads++;
                parallel_last_ba_event<=$sformatf("BA t=%0t old=%h new=%h",$time,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DBUS_A[4:0]);end
            if(parallel_buf_load)begin parallel_buf_launch<=$realtime;parallel_buf_reloads++;
                parallel_last_buf_event<=$sformatf("BUF t=%0t old=%h new=%h state=%b readpend=%b writepend=%b rmw=%b",$time,
                    core.CPU.MC.DOUT_BUF,core.CPU.MC.DOUT,core.CPU.MC.MC_STATE,core.CPU.MC.MC_READ_PEND,
                    core.CPU.MC.MC_WRITE_PEND,core.CPU.MC.RMW);end
        end
    end
    always @(negedge CLK)if(parallel_probe_valid)begin
        assert({core.CPU.MC.bt_probe_ext,core.CPU.MC.bt_probe_fs,core.CPU.MC.bt_probe_ba,core.CPU.MC.bt_probe_buf}
               ===parallel_expected_probes)else $fatal(1,"Exact MC launch predicates differ from actual assignment probes");
        parallel_probe_checks++;
    end
    always @(posedge CLK2X) begin
        if(parallel_last_mem_edge!=0)parallel_mem_period<=$realtime-parallel_last_mem_edge;
        parallel_last_mem_edge<=$realtime;
        if(!reset_cpu && !RESET && memory.write_prepend && ce_r)begin
            assert(parallel_mem_period>0 && $onehot(edata_select))
                else $fatal(1,"Parallel DDR acceptance owner/clock contract missing");
            // Check every raw capture, including inactive CPU data. DATA_OLD
            // keeps its original ordinary single-cycle path and is not added.
            if($realtime-parallel_last_any_f<2*parallel_mem_period)begin
                parallel_conservative_false_count++;
                if(parallel_conservative_false_count<=8)begin
                    $display("DDR_CONSERVATIVE_FALSE t=%0t owner=%h word=%h rawCPU=%h current_state=%b lastF=%0f lastF_state=%b actualFloads=%b exact_ages=%0f/%0f/%0f/%0f period=%0f ext=%b fs=%h ba=%h buf=%h pend=%b%b%b",
                        $time,edata_select,edata,edata_candidates[3],core.CPU.MC.MC_STATE,
                        parallel_last_any_f,parallel_last_any_f_state,parallel_last_any_f_probes,
                        $realtime-parallel_ext_launch,$realtime-parallel_fs_launch,
                        $realtime-parallel_ba_launch,$realtime-parallel_buf_launch,parallel_mem_period,
                        core.CPU.MC.MC_EXT_WORD,core.CPU.MC.DOUT_FS,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DOUT_BUF,
                        core.CPU.MC.MC_READ_PEND,core.CPU.MC.MC_WRITE_PEND,core.CPU.MC.MC_WRITE_PEND2);
                    $display("DDR_CONSERVATIVE_LAST %s | %s | %s | %s",parallel_last_ext_event,
                        parallel_last_fs_event,parallel_last_ba_event,parallel_last_buf_event);
                end
            end
            if($realtime-parallel_ext_launch<2*parallel_mem_period ||
               $realtime-parallel_fs_launch<2*parallel_mem_period ||
               $realtime-parallel_ba_launch<2*parallel_mem_period ||
               $realtime-parallel_buf_launch<2*parallel_mem_period)begin
                $display("DDR_PARALLEL_EVENT t=%0t owner=%h word=%h rawCPU=%h state=%b F=%b R=%b age=%0f/%0f/%0f/%0f period=%0f ext=%b fs=%h ba=%h buf=%h loads=%b%b%b%b pend=%b%b%b",
                    $time,edata_select,edata,edata_candidates[3],core.CPU.MC.MC_STATE,ce_f,ce_r,
                    $realtime-parallel_ext_launch,$realtime-parallel_fs_launch,$realtime-parallel_ba_launch,
                    $realtime-parallel_buf_launch,parallel_mem_period,core.CPU.MC.MC_EXT_WORD,
                    core.CPU.MC.DOUT_FS,core.CPU.MC.DOUT_BA_OLD,core.CPU.MC.DOUT_BUF,
                    parallel_f_idle,parallel_fs_load,parallel_ba_load,parallel_buf_load,
                    core.CPU.MC.MC_READ_PEND,core.CPU.MC.MC_WRITE_PEND,core.CPU.MC.MC_WRITE_PEND2);
                $display("DDR_PARALLEL_PREVIOUS %s | %s | %s | %s",parallel_last_ext_event,
                    parallel_last_fs_event,parallel_last_ba_event,parallel_last_buf_event);
            end
            assert($realtime-parallel_ext_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR MC_EXT_WORD exact reload age too short");
            assert($realtime-parallel_fs_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR DOUT_FS exact reload age too short");
            assert($realtime-parallel_ba_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR DOUT_BA_OLD exact reload age too short");
            assert($realtime-parallel_buf_launch>=2*parallel_mem_period)
                else $fatal(1,"Parallel DDR DOUT_BUF reload age too short");
            parallel_launch_age_checks++;
            if(($realtime-parallel_ext_launch)/parallel_mem_period<parallel_min_ext_age)
                parallel_min_ext_age=$rtoi(($realtime-parallel_ext_launch)/parallel_mem_period);
            if(($realtime-parallel_fs_launch)/parallel_mem_period<parallel_min_fs_age)
                parallel_min_fs_age=$rtoi(($realtime-parallel_fs_launch)/parallel_mem_period);
            if(($realtime-parallel_ba_launch)/parallel_mem_period<parallel_min_ba_age)
                parallel_min_ba_age=$rtoi(($realtime-parallel_ba_launch)/parallel_mem_period);
            if(($realtime-parallel_buf_launch)/parallel_mem_period<parallel_min_buf_age)
                parallel_min_buf_age=$rtoi(($realtime-parallel_buf_launch)/parallel_mem_period);
            parallel_captured_word<=edata;parallel_captured_owner<=edata_select;parallel_captured_valid<=1;
            parallel_capture_checks++;
            if(edata_select[0])parallel_sprite_captures++;
            if(edata_select[1])parallel_fg0_captures++;
            if(edata_select[2])parallel_fg1_captures++;
            if(edata_select[3])parallel_cpu_captures++;
        end
    end
    always @(negedge CLK2X)if(parallel_captured_valid)begin
        assert(memory.parallel_write_capture.cache_owner===parallel_captured_owner &&
               memory.parallel_write_capture.beat_owner===parallel_captured_owner &&
               memory.write_data===parallel_captured_word && memory.write_data_o===parallel_captured_word)
            else $fatal(1,"Parallel DDR selected/held captured source differs from legacy EDATA");
    end
    // BT_PARALLEL_NATIVE_PHASE_END
'''
REPORT='''            $display("DDR_PARALLEL_PHASE frame=%0d captures=%0d cpu=%0d sprite=%0d fg0=%0d fg1=%0d launch_age_checks=%0d ext_reloads=%0d fs_reloads=%0d ba_reloads=%0d buf_reloads=%0d min_ext=%0d min_fs=%0d min_ba=%0d min_buf=%0d probe_checks=%0d conservative_false=%0d",
                phase_report_frames,parallel_capture_checks,parallel_cpu_captures,parallel_sprite_captures,
                parallel_fg0_captures,parallel_fg1_captures,parallel_launch_age_checks,
                parallel_ext_reloads,parallel_fs_reloads,parallel_ba_reloads,parallel_buf_reloads,
                parallel_min_ext_age,parallel_min_fs_age,parallel_min_ba_age,parallel_min_buf_age,
                parallel_probe_checks,parallel_conservative_false_count);
'''

def sha(raw):return hashlib.sha256(raw).hexdigest()

def prepare(source,output,core):
    oracle=subprocess.check_output(['D:/vibes/fpga/bin/git.EXE','-C',str(ROOT),
                                    'show',ORACLE+':tests/graphics/native_sim.sv'])
    assert sha(oracle)==NATIVE_LF,'Immutable native Git oracle changed'
    assert b'\r' not in oracle
    raw=oracle.replace(b'\n',b'\r\n')
    assert sha(raw)==NATIVE,'Original declared CRLF reconstruction differs'
    assert not output.exists() and output.is_relative_to(ROOT/'build')
    body=raw.decode().replace('\r\n','\n');original=body
    edits=[]
    def change(before,after):
        nonlocal body
        assert body.count(before)==1,'Native adapter anchor changed'
        body=body.replace(before,after,1);edits.append({'before':before,'after':after})
    header_end=body.index(');')+2
    change(body[:header_end],body[:header_end]+'\n    timeunit 1ps; timeprecision 1ps;')
    change('    wire [3:0] ewe;', '    wire [3:0][31:0] edata_candidates;\n    wire [3:0] edata_select;\n    wire [3:0] ewe;')
    change('.EADDR_CANDIDATES(eaddr_candidates),.EADDR_SELECT(eaddr_select),',
           '.EADDR_CANDIDATES(eaddr_candidates),.EADDR_SELECT(eaddr_select),\n        .EDATA_CANDIDATES(edata_candidates),.EDATA_SELECT(edata_select),')
    change('.USE_PREDECODED_MISS(1)) memory', '.USE_PREDECODED_MISS(1),.USE_PARALLEL_DIN(1)) memory')
    change('.din(edata),.rd(', '.din(edata),.parallel_din(edata_candidates),.parallel_din_sel(edata_select),.rd(')
    change('    // DBUS_BE loads in the CE_R after each launch (TMS34020_MC.sv);',
           MONITOR+'\n    // DBUS_BE loads in the CE_R after each launch (TMS34020_MC.sv);')
    original_guard='        if(phase_report_frames%128==0)\n'
    new_report_scope='        if(phase_report_frames==1 || phase_report_frames%128==0)begin\n'+REPORT+'        end\n'
    change(original_guard+'            $display("DDR_PHASE frame=',
           new_report_scope+original_guard+'            $display("DDR_PHASE frame=')
    reverse=body
    for edit in reversed(edits):
        assert reverse.count(edit['after'])==1;reverse=reverse.replace(edit['after'],edit['before'],1)
    assert reverse==original
    old_age=original[original.index('    // DBUS_BE loads'):original.index('    bit bus_phase_valid')]
    new_age=body[body.index('    // DBUS_BE loads'):body.index('    bit bus_phase_valid')]
    assert old_age==new_age
    e4_path=E4_DIR/'candidate/tests/graphics/native_sim.sv'
    e4_raw=e4_path.read_bytes();assert sha(e4_raw)==E4_NATIVE
    e4_receipt_path=E4_DIR/'receipt.json'
    e4_receipt=json.loads(e4_receipt_path.read_text())
    assert e4_receipt['status']=='PASS' and e4_receipt['native_candidate_sha256']==E4_NATIVE
    e4_body=e4_raw.decode().replace('\r\n','\n');e4_reverse=e4_body
    for edit in reversed(e4_receipt['edits']):
        assert e4_reverse.count(edit['after'])==1
        e4_reverse=e4_reverse.replace(edit['after'],edit['before'],1)
    assert e4_reverse==original,'Frozen e4 adapter does not reverse to immutable oracle'
    def replace_marked(text,begin,end,replacement):
        assert text.count(begin)==1 and text.count(end)==1
        start=text.index(begin);stop=text.index(end,start)+len(end)
        return text[:start]+replacement+text[stop:]
    begin='    // BT_PARALLEL_NATIVE_PHASE_BEGIN'
    end='    // BT_PARALLEL_NATIVE_PHASE_END\n'
    patched=replace_marked(e4_body,begin,end,MONITOR)
    old_report=e4_body[e4_body.index('            $display("DDR_PARALLEL_PHASE'):e4_body.index('            $display("DDR_PHASE frame=')]
    assert patched.count(original_guard+old_report)==1
    patched=patched.replace(original_guard+old_report,new_report_scope+original_guard,1)
    assert patched==body,'e4-to-v3 edge changes more than the marked monitor/report'
    final_raw=body.replace('\n','\r\n').encode()
    input_raw=source.read_bytes()
    assert sha(input_raw) in (NATIVE,E4_NATIVE,V3_NATIVE,V4_NATIVE,sha(final_raw)),'Unrecognized native input bytes'
    mc=(core/'rtl/TMS34020/TMS34020_MC.sv').read_text()
    anchors=['if (EN)', 'if (CE_F)', 'if (CE_R)', 'MC_EXT_WORD <= 0;',
             'end else if (MC_WRITE_EXT) begin', 'DOUT_BA_OLD <= DBUS_A[4:0];',
             'end else if (WRITE && !CACHE) begin', 'DOUT_FS <= FS;',
             'if ((MC_READ_PEND && RMW) || MC_WRITE_PEND) begin', 'DOUT_BUF <= DOUT;']
    assert all(anchor in mc for anchor in anchors),'Actual MC launch body changed'
    output.mkdir(parents=True)
    candidate=output/'candidate/tests/graphics/native_sim.sv';candidate.parent.mkdir(parents=True)
    candidate.write_bytes(final_raw)
    (output/'immutable_native_lf.sv').write_bytes(oracle)
    assert old_age.replace('\n','\r\n').encode() in candidate.read_bytes()
    sources={name:sha((core/name).read_bytes()) for name in
        ('rtl/BT.sv','rtl/ddram.sv','rtl/TMS34020/TMS34020_MC.sv','rtl/TMS34020/TMS34020.sv','Arcade-Battletoads.sv')}
    from bt_native_mc_scope import validate_runtime_edge
    runtime_edge=validate_runtime_edge(ROOT)
    sources.update({name:sha((ROOT/name).read_bytes()) for name in
        ('tests/graphics/native_run.py','tests/graphics/bt_native_mc_scope.py')})
    receipt={'schema':'bt-parallel-native-adapter-v2','status':'PASS','native_original_sha256':NATIVE,
        'immutable_oracle':ORACLE,'immutable_oracle_path':'tests/graphics/native_sim.sv','immutable_oracle_sha256_lf':NATIVE_LF,
        'input_native_sha256':sha(input_raw),
        'e4_preservation_edge':{'candidate_path':str(e4_path),'candidate_sha256':E4_NATIVE,
            'receipt_path':str(e4_receipt_path),'receipt_sha256':sha(e4_receipt_path.read_bytes()),
            'original_reversal_verified':True,'only_marked_monitor_and_report_changed':True},
        'v3_preservation_edge':{'candidate_path':str(V3_DIR/'candidate/tests/graphics/native_sim.sv'),
            'candidate_sha256':V3_NATIVE,'failed_native_receipt':'tests/graphics/evidence/native/native-99573d602afa428f80f4dd18d4a84468/receipt.json'},
        'v4_prefix_proof':{'native_candidate_sha256':V4_NATIVE,
            'receipt':'tests/graphics/evidence/native/native-ca5aabadd691442c8711a6748ffb9148/receipt.json',
            'scope':'Exact-reload one-frame run passed; v5 additionally records old conservative false positives and restores the original report guard.'},
        'native_candidate_sha256':sha(candidate.read_bytes()),'source_root':str(core),
        'core_sources':sources,'adapter_sha256':sha(Path(__file__).read_bytes()),
        'newline_transform':'Explicit CRLF to LF text processing, restored CRLF bytes; exact reversible original body.',
        'old_all_owner_age_block_sha256_lf':sha(old_age.encode()),'old_all_owner_age_block_unchanged':True,
        'actual_mc_load_anchors':anchors,'edits':edits,
        'f_metadata_launch_scope':'Exact MC.RST_N && MC.EN && CE_F && !MC_STATE for MC_EXT_WORD; exact mutually exclusive extended-write/normal-write priority for DOUT_BA_OLD/DOUT_FS. Source scan has no MC_EXT_WORD case-1 writes.',
        'r_buffer_launch_scope':'Exact MC.RST_N && MC.EN && CE_R && !MC_STATE && ((MC_READ_PEND && RMW) || MC_WRITE_PEND).',
        'native_runtime_edge':runtime_edge,
        'scope':'Fixture preparation and exact old age-body preservation only. Fresh actual-core native run must satisfy all reload/acceptance assertions and compare the same input-journal reference rasters.',
        'minimum_reload_age_memory_cycles':2,'age_guard':'Every !reset_cpu && !RESET && memory.write_prepend && ce_r; all owners.',
        'data_old_exception':'None: existing DATA_OLD single-cycle exclusion and tracker preserved verbatim.'}
    assert original_guard+'            $display("DDR_PHASE frame=' in body
    receipt['original_phase_report_guard_preserved']=True
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'candidate':str(candidate),'hash':receipt['native_candidate_sha256'],'receipt':str(output/'receipt.json')}))
    return candidate

def compile_only(candidate,failed_receipt_path,core,output):
    """Check full actual source hierarchy using a preserved failed native snapshot."""
    previous=json.loads(failed_receipt_path.read_text())
    assert previous['exit_code']!=0
    for name,expected in previous['sources'].items():
        actual=sha((core/Path(name)).read_bytes())
        if name.replace('\\','/')=='tests/graphics/native_sim.sv':
            assert actual in (E4_NATIVE,V3_NATIVE,V4_NATIVE,sha(candidate.read_bytes()))
        elif name.replace('\\','/')=='tests/graphics/native_run.py':
            baseline=ROOT/'build/ddr_parallel_sources_v9_v2/native_runtime_scope_v1/original_native_run.py'
            assert sha(baseline.read_bytes())==expected
        else:
            assert actual==expected,'Failed snapshot production input changed: '+name
    snapshot=Path(previous['snapshot'])
    target=Path('R:/Verilator/BT')/('native-parallel-compile-only-'+uuid.uuid4().hex)
    target.mkdir(parents=True)
    shutil.copytree(snapshot/'rtl',target/'rtl')
    for name in ('t80_native.v','ram_models.sv','mixer_enable.svh'):
        shutil.copyfile(snapshot/name,target/name)
    shutil.copyfile(candidate,target/'native_sim.sv')
    from bt_native_mc_scope import expose_launch_scope
    mc=target/'rtl/TMS34020/TMS34020_MC.sv'
    exposed,scope=expose_launch_scope(mc.read_text());mc.write_text(exposed)
    (output/'mc_launch_scope.json').write_text(json.dumps(scope,indent=2)+'\n')
    old_command=next(command for command in reversed(previous['commands']) if '--cc' in command)
    assert '--cc' in old_command and '--build' in old_command
    command=[old_command[0],'--lint-only','--Mdir',str(target/'obj')];skip=False
    for arg in old_command[1:]:
        if skip:skip=False;continue
        if arg in ('--cc','--exe','--build'):continue
        if arg in ('-MAKEFLAGS','-CFLAGS','-LDFLAGS','--Mdir','-j'):
            skip=True;continue
        if arg.endswith('native.cpp'):continue
        command.append(arg.replace(str(snapshot),str(target)))
    compiled={str(path.relative_to(target)):sha(path.read_bytes()) for path in target.rglob('*') if path.is_file()}
    log=target/'compile.log'
    with log.open('w') as stream:
        result=subprocess.run(command,cwd=target,stdout=stream,stderr=subprocess.STDOUT,
                              env=dict(os.environ,MISTER_DIFF_HEADLESS='1',VERILATOR_PROJECT='BT',
                                       VERILATOR_WORKSPACE=str(target),VERILATOR_RAM_WORKSPACE=str(target)),
                              creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    receipt={'schema':'bt-parallel-native-compile-only-v1','status':'PASS' if result.returncode==0 else 'FAIL',
        'exit_code':result.returncode,'command':command,'compiled_sources':compiled,
        'native_candidate_sha256':sha(candidate.read_bytes()),'core_sources_verified_against_failed_receipt':True,
        'failed_receipt_path':str(failed_receipt_path),'failed_receipt_sha256':sha(failed_receipt_path.read_bytes()),
        'log_path':str(log),'log_sha256':sha(log.read_bytes()),
        'scope':'Full native RTL parse/elaboration with actual converted T80 and retained private runtime adaptations; no simulation or hardware qualification.'}
    (output/'compile_receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    shutil.copyfile(log,output/'compile.log')
    assert result.returncode==0,log.read_text(errors='replace')[-5000:]
    return receipt

def parse_phase_report(report):
    pattern=r'DDR_PARALLEL_PHASE frame=(\d+) captures=(\d+) cpu=(\d+) sprite=(\d+) fg0=(\d+) fg1=(\d+) launch_age_checks=(\d+) ext_reloads=(\d+) fs_reloads=(\d+) ba_reloads=(\d+) buf_reloads=(\d+) min_ext=(\d+) min_fs=(\d+) min_ba=(\d+) min_buf=(\d+) probe_checks=(\d+) conservative_false=(\d+)'
    rows=re.findall(pattern,report)
    assert rows,'No activated parallel native phase evidence'
    values=list(map(int,rows[-1]));names=['frame','captures','cpu','sprite','fg0','fg1','launch_age_checks',
        'ext_reloads','fs_reloads','ba_reloads','buf_reloads','min_ext','min_fs','min_ba','min_buf','probe_checks','conservative_false']
    result=dict(zip(names,values))
    assert result['captures']==result['launch_age_checks']==sum(result[name] for name in ('cpu','sprite','fg0','fg1'))
    assert result['captures']>0 and all(result[name]>=2 for name in ('min_ext','min_fs','min_ba','min_buf'))
    assert all(result[name]>0 for name in ('ext_reloads','buf_reloads','probe_checks'))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,default=ROOT/'tests/graphics/native_sim.sv')
    parser.add_argument('--core',type=Path,default=ROOT)
    parser.add_argument('--out',type=Path,default=ROOT/'build/ddr_parallel_sources_v9_v2/native_adapter_exact_v5')
    parser.add_argument('--compile-receipt',type=Path)
    parser.add_argument('--update-root',action='store_true')
    args=parser.parse_args();core=args.core.resolve();output=args.out.resolve()
    candidate=prepare(args.input.resolve(),output,core)
    if args.compile_receipt:compile_only(candidate,args.compile_receipt.resolve(),core,output)
    if args.update_root:
        assert args.compile_receipt,'Compile-only PASS is required before updating the ROOT fixture'
        target=ROOT/'tests/graphics/native_sim.sv'
        original=target.read_bytes();assert sha(original) in (E4_NATIVE,V3_NATIVE,V4_NATIVE),'ROOT fixture is no longer a frozen predecessor'
        target.write_bytes(candidate.read_bytes())
        (output/'root_update.json').write_text(json.dumps({'before_sha256':sha(original),
            'after_sha256':sha(target.read_bytes()),'only_test_fixture_updated':True},indent=2)+'\n')
        print('root_ready='+sha(target.read_bytes()))
