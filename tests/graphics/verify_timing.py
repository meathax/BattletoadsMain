"""Fail closed before RBF assembly: every corner and source must be verified."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import re
import sys

def native_raster_verified(receipt, comparison, root):
    """Bind both successful runs, journals, inventories and actual raster bytes."""
    try:
        proof=json.loads(comparison.read_text())
        if proof.get('exit_code')!=0 or proof.get('failures')!=[]:
            return False
        folders=[root/'tests/graphics/evidence/native'/Path(proof[key]).name
                 for key in ('reference','candidate')]
        if folders[0]==folders[1] or folders[1]!=receipt.parent:
            return False
        records=proof.get('run_receipts',[])
        if len(records)!=2:
            return False
        runs=[]
        for folder,record in zip(folders,records):
            path=folder/'receipt.json'
            if Path(record['path']).resolve()!=path.resolve() or record['sha256']!=sha(path):
                return False
            run=json.loads(path.read_text())
            if run.get('exit_code')!=0 or run.get('requested_frames',0)<128:
                return False
            journal=run['input_journal']['sha256']
            if journal!=proof['input_journal_sha256'] or sha(folder/'inputs.txt')!=journal:
                return False
            runs.append(run)
        if not runs[0].get('rom_sha256') or runs[0]['rom_sha256']!=runs[1].get('rom_sha256'):
            return False
        inventories=[]
        for folder in folders:
            inventory=set()
            for kind in ('frames','frames-pre'):
                names={path.name for path in (folder/kind).glob('*.ppm')}
                if not names:
                    return False
                inventory.update((kind,name) for name in names)
            inventories.append(inventory)
        items=proof.get('comparisons',[])
        keys={(item['kind'],item['name']) for item in items}
        if len(items)<24 or len(keys)!=len(items) or keys!=inventories[0] or keys!=inventories[1]:
            return False
        for item in items:
            before=sha(folders[0]/item['kind']/item['name'])
            after=sha(folders[1]/item['kind']/item['name'])
            if (item.get('equal') is not True or before!=after or
                    item.get('reference_sha256')!=before or item.get('candidate_sha256')!=after):
                return False
        return True
    except (OSError,ValueError,KeyError,TypeError):
        return False

def source_bound_run_verified(proof, needed, root, flags, production_aliases=None):
    """Require successful processes and bind every declared input, including fixtures."""
    try:
        if any(type(proof.get(key)) is not int or proof[key] != 0
               for key in ('compile_exit_code','run_exit_code','exit_code')):
            return False
        if any(proof.get(key) is not True for key in ('testbench_passed',)+tuple(flags)):
            return False
        raw=proof['sources']
        if not isinstance(raw,dict) or not raw:
            return False
        sources={name.replace('\\','/'):digest for name,digest in raw.items()}
        if len(sources)!=len(raw) or any(name not in sources for name in needed):
            return False
        workspace=root.resolve()
        for name,digest in sources.items():
            if not isinstance(digest,str) or re.fullmatch('[0-9a-f]{64}',digest) is None:
                return False
            path=(workspace/(production_aliases or {}).get(name,name)).resolve()
            path.relative_to(workspace)
            if not path.is_file() or sha(path)!=digest:
                return False
        return True
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        return False


def retained_inputs_bound(proof, prefix, names):
    """Require each compiled fixture explicitly, from one retained experiment."""
    sources={name.replace('\\','/'):digest for name,digest in proof.get('sources',{}).items()}
    selected=[]
    for basename in names:
        matches=[name for name in sources if name.startswith(prefix) and
                 name.rsplit('/',1)[-1]==basename]
        if len(matches)!=1:
            return False
        selected.extend(matches)
    return len({name.rsplit('/',1)[0] for name in selected})==1


def selector_coverage_verified(proof):
    coverage=proof.get('coverage',{})
    needed=('captures','cache','en0','palette_late','extended','rmw','pause_live',
            'pause_ack','pause_resume_f','pause_resume_r','scan','screens',
            'draw_overlap','draw_mem','draw_ddr','draw_handoff','partner','copy_busy',
            'copy_handoff','address_checks','read_checks','en0_before_ready','prepared_resume_r')
    if not isinstance(coverage,dict) or any(type(coverage.get(name)) is not int or
            coverage[name]<=0 for name in needed):
        return False
    if (coverage['captures']<=100 or coverage['cache']<60 or coverage['pause_ack']<3 or
            coverage['read_checks']<60 or coverage['address_checks']!=coverage['cache']):
        return False
    for name,length in (('selector_counts',8),('fg_bank_counts',8),('bg_page_counts',2)):
        counts=coverage.get(name)
        if not isinstance(counts,list) or len(counts)!=length or any(
                type(value) is not int or value<=0 for value in counts):
            return False
    return True


def ddr_split_bridge_verified(proof,needed,root,production_pairs=None,block_files=None):
    """Require the real MC comparison, cache oracle, and defined producer handoff."""
    try:
        if not (source_bound_run_verified(proof,needed,root,
                ('selector_capture_equivalence_passed','cache_placement_and_contents_passed',
                 'cache_word_stage_checked_passed','qa_collision_exclusion_passed',
                 'mc_word_equivalence_passed','ddr_split_equivalence_passed',
                  'postmux_owner_equivalence_passed')) and selector_coverage_verified(proof)):
            return False
        coverage=proof['coverage']
        minima={'nvram_late_updates':1,'qa_fg_collision_checks':1,'qa_bg_collision_checks':1,
                'cache_mem_writes':1,'cache_late_writes':1,'cache_nvram_writes':1,
                'mc_cycle_checks':88000,'mc_read_checks':5900,'mc_ext_reads':1900,
                'mc_write_checks':11900,'mc_held_reads':5900,'mc_late_reads':2,
                'mc_field_cases':2048,'mc_read_en0':2,'mc_io_late':2,
                'queued_draw_reads':2,'queued_draw_sameword_writes':4,
                'queued_draw_busy_cycles':2,'queued_draw_handoffs':2,
                 **{name:1 for name in ('mc_ddr_reads','mc_full_reads','mc_byte_reads','mc_ram_reads',
                    'cache_ddr_writes','cache_full_writes','cache_byte_writes','cache_ram_writes',
                    'postmux_fg_owner_checks','postmux_bg_owner_checks')}}
        if any(type(coverage.get(key)) is not int or coverage[key]<minimum
               for key,minimum in minima.items()):
            return False
        if (coverage['cache_mem_writes']+coverage['cache_late_writes']!=coverage['cache'] or
                coverage['mc_held_reads']+coverage['mc_late_reads']!=coverage['mc_read_checks'] or
                coverage['mc_ddr_reads']!=coverage['mc_full_reads']+coverage['mc_byte_reads'] or
                coverage['mc_held_reads']!=coverage['mc_ddr_reads']+coverage['mc_ram_reads'] or
                coverage['cache_ddr_writes']!=coverage['cache_full_writes']+coverage['cache_byte_writes'] or
                coverage['cache_mem_writes']!=coverage['cache_ddr_writes']+coverage['cache_ram_writes']):
            return False
        sources=proof['sources']
        for live,private in (production_pairs if production_pairs is not None else (('rtl/BT.sv','build/resource_audit/ddr_return_split/BT.sv'),
                ('rtl/TMS34020/TMS34020.sv','build/resource_audit/ddr_return_split/TMS34020.sv'),
                ('rtl/TMS34020/TMS34020_MC.sv','build/resource_audit/pause_mc_candidate.sv'),
                ('rtl/TMS34020/TMS34020_CACHE.sv',
                 'build/resource_audit/ddr_return_split/TMS34020_CACHE.sv'),
                ('rtl/fg_vram.sv','build/post_mux_qa_experiment/rtl/fg_production.sv'),
                ('rtl/bg_vram.sv','build/post_mux_qa_experiment/rtl/bg_production.sv'))):
            if sources[live]!=sources[private]:
                return False
        block=(root/'build/resource_audit/ddr_return_split/MC_MEM_RETURN_STAGE.svh').read_bytes()
        return (bool(block.strip()) and b'MC_OLD_MEM_WORD' in block and b'MC_OLD_MEM_SELECTED' in block and
                all(block in (root/name).read_bytes() for name in (block_files if block_files is not None else
                ('rtl/TMS34020/TMS34020.sv','build/resource_audit/ddr_return_split/TMS34020.sv',
                  'build/resource_audit/ddr_split_bridge_tb.sv'))) and
                b'CACHE_OLD_MEM_WORD' in (root/'rtl/TMS34020/TMS34020_CACHE.sv').read_bytes())
    except (KeyError,TypeError,ValueError,OSError):
        return False


def qa_output_registers_verified(proof,root,production_aliases=None):
    """Bind the actual QA1 atoms, collision tests, and all retained inputs."""
    try:
        qa=root/'build/qa_reg_experiment'
        if not (proof.get('schema')=='bt-private-qa-reg-experiment-v1' and
                type(proof.get('exit_code')) is int and proof['exit_code']==0 and
                proof.get('hardware_equivalence_passed') is True and
                type(proof.get('primitive_process_exit_code')) is int and
                proof['primitive_process_exit_code']==0):
            return False
        sources=proof.get('sources',{})
        fixture_root=proof.get('fixture_root','build/qa_reg_experiment')
        if fixture_root not in ('build/qa_reg_experiment','build/qa_reg_experiment/current_6148'):
            return False
        fixture=root/fixture_root
        needed={'rtl/BT_mem.sv','rtl/fg_vram.sv','rtl/bg_vram.sv','tests/graphics/ram_models.sv'}
        needed.update(p.relative_to(root).as_posix() for p in fixture.rglob('*')
                      if p.is_file() and p.suffix in ('.sv','.py','.qsf','.qpf','.vo') and
                      (fixture!=qa or p.relative_to(qa).parts[0]!='current_6148'))
        vendor='D:/q17/quartus/eda/sim_lib/altera_mf.v'
        needed.add(vendor)
        if not needed.issubset(sources):return False
        for name,digest in sources.items():
            path=(root/(production_aliases or {}).get(name,name)).resolve()
            if (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or
                    (not path.is_relative_to(root.resolve()) and path!=Path(vendor).resolve()) or
                    not path.is_file() or sha(path)!=digest):
                return False
        for key in ('transaction_status','serial_status'):
            status=proof.get(key,{})
            if not (type(status.get('exit_code')) is int and status['exit_code']==0 and
                    status.get('passed') is True and status.get('phase')=='complete'):
                return False
        def number(text,key):
            match=re.search(r'\b'+key+r'=(\d+)',text)
            return int(match[1]) if match else 0
        transaction=proof.get('transaction_pass','')
        serial=proof.get('serial_pass','')
        if not (transaction.startswith('PASS QA_REG actual FG/BG transactions') and
                number(transaction,'captures')>=840 and number(transaction,'rmw')>=160 and
                number(transaction,'draw_waits')>=20 and number(transaction,'copies')>=3 and
                serial.startswith('PASS FG bank-local serial selection every-clock') and
                number(serial,'cycles')>=20192 and number(serial,'mixed_collisions')>=4000):
            return False
        cases=proof.get('primitive_cases',[])
        if (len(cases)!=6 or {(int(c['address_width']),int(c['sq_reg'])) for c in cases}!=
                {(width,sq) for width in (12,14,16) for sq in (0,1)}):
            return False
        for case in cases:
            if not (int(case['cycles'])>=50000 and int(case['qa0_checks'])>30000 and
                    int(case['qa1_checks'])>30000 and int(case['extra_mem_latency_checks'])>20000 and
                    int(case['mixed_port_collisions'])>=12000 and case['byte_masks']=='f'):
                return False
        probes=proof.get('probe_status',[])
        if len(probes)!=2 or {p.get('observed_byte_lane') for p in probes}!={0,1}:return False
        for probe in probes:
            after=probe.get('port_a_output_clocks',[])
            before=probe.get('before_port_a_output_clocks',[])
            atoms=probe.get('port_a_atom_inventory',[])
            if not (type(probe.get('exit_code')) is int and probe['exit_code']==0 and
                    probe.get('passed') is True and probe.get('phase')=='complete' and
                    len(after)==23 and set(after)<= {'clock0','clock1'} and
                    len(before)==23 and set(before)=={'none'} and
                    len(atoms)==46 and len(set(atoms))==46):
                return False
        markers=proof.get('physical_pass_markers',[])
        physical=[m for m in markers if m.startswith('# PASS QA primitive AW=14 SQ=1')]
        if not (len(physical)==2 and all(number(m,'cycles')>=28192 and
                number(m,'delay')>=9000 and number(m,'serial')>=28190 and
                number(m,'mixed_writes')>=5000 and 'masks=f' in m for m in physical) and
                all(any('LANE'+str(lane)+' matched latency/collisions' in m for m in markers)
                    for lane in (0,1))):
            return False
        evidence=proof.get('evidence',{})
        required_logs={'primitive.log','primitive_compile.log','transactions.log',
                       'transactions_compile.log','serial.log','serial_compile.log'}
        required_logs.update('probe_lane'+str(lane)+'/'+name for lane in (0,1)
                             for name in ('map.log','eda.log','vlog.log','proof.log'))
        if fixture!=qa:
            required_logs={fixture.relative_to(qa).as_posix()+'/'+name for name in required_logs}
        if not required_logs.issubset(evidence):return False
        for name,digest in evidence.items():
            path=(qa/name).resolve()
            if not (path.is_relative_to(qa.resolve()) and path.is_file() and
                    isinstance(digest,str) and re.fullmatch(r'[0-9a-f]{64}',digest) and
                    sha(path)==digest):
                return False
        return True
    except (KeyError,TypeError,ValueError,OSError):
        return False


def fg_serial_write_segment_verified(proof,root,production_aliases=None):
    """Bind the current write-only cone and its unchanged historical QA proof."""
    try:
        folder=root/'build/fg_serial_wren_experiment'
        vendor='D:/q17/quartus/eda/sim_lib/altera_mf.v'
        if not (proof.get('schema')=='bt-fg-serial-write-segment-v1' and
                type(proof.get('exit_code')) is int and proof['exit_code']==0 and
                proof.get('hardware_equivalence_passed') is True and
                proof.get('output_latency_preserved') is True and
                proof.get('expected_m10k_per_fg_bank')==14 and
                proof.get('qualified_address_width')==14 and
                proof.get('qualified_qa_reg')==1 and proof.get('qualified_sq_reg')==1):
            return False
        aliases={'rtl/BT_mem.sv':'build/fg_serial_wren_experiment/before_exact_BT_mem.sv',
                 'rtl/fg_vram.sv':'build/fg_serial_wren_experiment/before_exact_fg_vram.sv',
                 'rtl/bg_vram.sv':'build/fg_serial_wren_experiment/before_exact_bg_vram.sv',
                 'tests/graphics/ram_models.sv':
                     'build/fg_serial_wren_experiment/before_exact_ram_models.sv'}
        prior_name='build/qa_reg_experiment/prior_qa_receipt.json'
        needed=set(aliases)|set(aliases.values())|{vendor,prior_name,
                'build/fg_serial_wren_experiment/production_snapshot.json'}
        needed.update(p.relative_to(root).as_posix() for p in folder.rglob('*')
                      if p.is_file() and p.suffix in ('.sv','.py','.qsf','.qpf','.vo'))
        raw=proof['sources']
        sources={name.replace('\\','/'):digest for name,digest in raw.items()}
        if len(sources)!=len(raw) or not needed.issubset(sources):
            return False
        for name,digest in sources.items():
            path=(root/(production_aliases or {}).get(name,name)).resolve()
            if (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or
                    (not path.is_relative_to(root.resolve()) and path!=Path(vendor).resolve()) or
                    not path.is_file() or sha(path)!=digest):
                return False
        prior=proof['previous_qa_receipt']
        if (prior.get('path')!=prior_name or prior.get('sha256')!=sha(root/prior_name) or
                sources[prior_name]!=prior['sha256']):
            return False
        previous=json.loads((root/prior_name).read_text())
        original=proof['original_production_sources']
        if set(original)!=set(aliases) or any(original[name]!=sources[alias] or
                original[name]!=previous.get('sources',{}).get(name)
                for name,alias in aliases.items()):
            return False
        if not qa_output_registers_verified(previous,root,aliases):
            return False
        def completed(status):
            return (type(status.get('exit_code')) is int and status['exit_code']==0 and
                    status.get('passed') is True and status.get('phase')=='complete')
        def number(marker,key):
            match=re.search(r'\b'+key+r'=(\d+)',marker)
            return int(match[1]) if match else 0
        helper=proof['helper_status']
        if not completed(helper):return False
        if not any(marker.startswith('PASS FG explicit serial write segments every-clock') and
                number(marker,'cycles')>=20192 and number(marker,'definedQ')>=20000 and
                number(marker,'definedSQ')>=19000 and number(marker,'mixed_collisions')>=4000 and
                number(marker,'prefetch_changes')>=6000 and 'masks=0000000f' in marker
                for marker in helper.get('pass_markers',[])):
            return False
        if any(sources.get(name.replace('\\','/'))!=digest
               for name,digest in helper.get('sources',{}).items()):
            return False
        probes=proof['probe_status']
        if len(probes)!=2 or {p.get('observed_byte_lane') for p in probes}!={0,1}:
            return False
        evidence={name.replace('\\','/'):digest for name,digest in proof['evidence'].items()}
        required_logs={'build/fg_serial_wren_experiment/'+name
                       for name in ('equivalence.log','compile.log')}
        for probe in probes:
            lane=probe['observed_byte_lane']
            if not completed(probe):return False
            after=probe.get('candidate_atoms',[]); before=probe.get('before_atoms',[])
            if (len(after)!=23 or len(before)!=23 or
                    any(len(atom)!=2 or atom[1] not in ('clock0','clock1') for atom in after+before) or
                    len({atom[0] for atom in after+before})!=46):
                return False
            if not any(marker.startswith('# PASS FG explicit serial write synthesized Intel-atom LANE'+str(lane)) and
                    number(marker,'cycles')>=32192 and number(marker,'definedQ')>=25000 and
                    number(marker,'definedSQ')>=21000 and number(marker,'mixed')>=6000 and
                    number(marker,'independent_write_address')>=7505 and 'masks=0000000f' in marker
                    for marker in probe.get('pass_markers',[])):
                return False
            required_logs.update('build/fg_serial_wren_experiment/probe_lane'+str(lane)+'/'+name
                                 for name in ('map.log','eda.log','vlog.log','proof.log'))
            if any(evidence.get(name.replace('\\','/'))!=digest
                   for name,digest in probe.get('logs',{}).items()):
                return False
        if not required_logs.issubset(evidence):return False
        for name,digest in evidence.items():
            path=(root/name).resolve()
            if (not path.is_relative_to(folder.resolve()) or not path.is_file() or
                    not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or
                    sha(path)!=digest):
                return False
        structural=proof['structural_status']
        if not (type(structural.get('exit_code')) is int and structural['exit_code']==0 and
                structural.get('passed') is True and structural.get('mapped_write_cone_verified') is True):
            return False
        lanes=structural.get('lanes',[])
        if len(lanes)!=2 or {lane.get('lane') for lane in lanes}!={0,1}:return False
        write_leaves={'SADDR_W[12]~input_o','SADDR_W[13]~input_o','SWREN~input_o'}
        old_extra={'SADDR_R[12]~input_o','SADDR_R[13]~input_o','WRITE_SELECT~input_o'}
        for lane in lanes:
            netlist='build/fg_serial_wren_experiment/probe_lane'+str(lane['lane'])+'/simulation/modelsim/probe.vo'
            if not (lane.get('candidate_unique_write_enables')==5 and
                    set(lane.get('candidate_leaves',[]))==write_leaves and
                    write_leaves|old_extra<=set(lane.get('before_leaves',[])) and
                    lane.get('candidate_read_address_in_write_cone') is False and
                    lane.get('before_read_address_in_write_cone') is True and
                    lane.get('netlist_sha256')==sources[netlist]):
                return False
        return True
    except (KeyError,TypeError,ValueError,OSError,AttributeError):
        return False


def completed_hardware_status(status):
    return (isinstance(status,dict) and type(status.get('exit_code')) is int and
            status['exit_code']==0 and status.get('passed') is True and status.get('phase')=='complete')

def marker_number(marker,key):
    match=re.search(r'\b'+re.escape(key)+r'=(\d+)',marker)
    return int(match[1]) if match else 0

def postmux_qa_verified(proof,root,production_aliases=None):
    """Bind unchanged QA/serial qualifications to every shipping post-mux geometry."""
    try:
        prefix='build/post_mux_qa_experiment/'
        folder=root/prefix
        canonical={'rtl/BT_mem.sv','rtl/fg_vram.sv','rtl/bg_vram.sv','tests/graphics/ram_models.sv'}
        if not (proof.get('schema')=='bt-post-final-mux-qa-v1' and
                proof.get('fixture_root')==prefix.rstrip('/') and
                type(proof.get('exit_code')) is int and proof['exit_code']==0 and
                proof.get('hardware_equivalence_passed') is True and
                proof.get('current_production_matches_candidate') is True):return False
        raw=proof['sources'];sources={n.replace('\\','/'):v for n,v in raw.items()}
        required=canonical|{prefix+'rtl/fg_production.sv',prefix+'rtl/bg_production.sv',
                prefix+'before_exact_QA_receipt.json',prefix+'before_exact_serial_receipt.json'}
        required.update(p.relative_to(root).as_posix() for p in folder.rglob('*')
                        if p.is_file() and p.suffix in ('.sv','.py','.qsf','.qpf','.vo'))
        if len(sources)!=len(raw) or not required.issubset(sources):return False
        vendor=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v').resolve()
        for name,digest in sources.items():
            path=(root/(production_aliases or {}).get(name,name)).resolve()
            if (not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest) or
                    (not path.is_relative_to(root.resolve()) and path!=vendor) or
                    not path.is_file() or sha(path)!=digest):return False
        after=proof['candidate_production_sources'];before=proof['before_production_sources']
        aliases=proof['canonical_before_copies']
        if set(after)!=canonical or set(before)!=canonical or set(aliases)!=canonical:return False
        for name in canonical:
            expected=prefix+'before_exact_'+{'rtl/BT_mem.sv':'BT_mem.sv','rtl/fg_vram.sv':'fg_vram.sv',
                    'rtl/bg_vram.sv':'bg_vram.sv','tests/graphics/ram_models.sv':'ram_models.sv'}[name]
            if aliases[name]!=expected or sources[name]!=after[name] or sources.get(expected)!=before[name]:return False
        for live,private in [('rtl/fg_vram.sv',prefix+'rtl/fg_production.sv'),
                             ('rtl/bg_vram.sv',prefix+'rtl/bg_production.sv')]:
            if sources[live]!=sources[private]:return False
        previous={}
        for kind in ('qa','serial'):
            pointer=proof['previous_'+kind+'_receipt'];name=prefix+'before_exact_'+('QA' if kind=='qa' else 'serial')+'_receipt.json'
            if pointer.get('path')!=name or pointer.get('sha256')!=sources.get(name):return False
            previous[kind]=json.loads((root/name).read_text())
            if any(previous[kind].get('sources',{}).get(n)!=before[n] for n in canonical):return False
        if not qa_output_registers_verified(previous['qa'],root,aliases):return False
        if not fg_serial_write_segment_verified(previous['serial'],root,aliases):return False
        evidence={n.replace('\\','/'):v for n,v in proof['evidence'].items()}
        for name,digest in evidence.items():
            path=(root/name).resolve()
            if (not path.is_relative_to(folder.resolve()) or not re.fullmatch('[0-9a-f]{64}',digest) or
                    not path.is_file() or sha(path)!=digest):return False
        expected_logs={prefix+n for n in ('transactions.log','serial_bridge.log')}
        cases=proof['intel_model_cases']
        if len(cases)!=6 or {(c.get('AW'),c.get('SQ'))for c in cases}!={(a,q)for a in (12,14,16)for q in (0,1)}:return False
        for case in cases:
            if not completed_hardware_status(case) or not any('PASS QA primitive ' in m and
                    marker_number(m,'cycles')>=8500 and marker_number(m,'delay')>0 and
                    marker_number(m,'mixed_writes')>0 and 'masks=f' in m for m in case['pass_markers']):return False
            expected_logs.add(prefix+'model_'+str(case['AW'])+'_'+str(case['SQ'])+'.log')
        if not completed_hardware_status(proof['transaction_status']) or not any(
                'PASS QA_REG actual FG/BG transactions' in m and marker_number(m,'captures')>=840 and
                marker_number(m,'writes')>=672 and marker_number(m,'rmw')>=160 and
                marker_number(m,'pauses')>=764 and marker_number(m,'readiness')>=31960 and
                'banks=0000000f' in m and 'masks=0000000f' in m for m in proof['transaction_pass_markers']):return False
        if not any('PASS postmux every-clock' in m and marker_number(m,'checks')>=31984
                   for m in proof['transaction_pass_markers']):return False
        if not completed_hardware_status(proof['serial_bridge_status']) or not any(
                'PASS postmux default-QA0 serial archive bridge' in m and marker_number(m,'cycles')>=20192 and
                marker_number(m,'definedQ')>=20000 and marker_number(m,'definedSQ')>=19000 and
                marker_number(m,'mixed_collisions')>=4000 and marker_number(m,'prefetch_changes')>=6000 and
                'masks=0000000f' in m for m in proof['serial_bridge_pass_markers']):return False
        leaf=proof['fg_leaf_physical_cases']
        if len(leaf)!=2 or {c.get('byte_lane') for c in leaf}!={0,1}:return False
        for case in leaf:
            if not completed_hardware_status(case) or case.get('AW')!=14 or case.get('rbf_assembly') is not False:return False
            if len(case['before_atom_modes'])!=23 or len(case['after_atom_modes'])!=23:return False
            if any(a[1] not in ('clock0','clock1') for a in case['before_atom_modes']) or any(a[1]!='none' for a in case['after_atom_modes']):return False
            if not any('PASS QA primitive AW=14 SQ=1' in m and marker_number(m,'cycles')>=20000 and
                    marker_number(m,'mixed_writes')>=3000 and 'masks=f' in m for m in case['pass_markers']):return False
            directory=prefix+'physical_14_'+str(case['byte_lane'])+'_3/'
            expected_logs.update(directory+n for n in ('map.log','eda.log','vlog.log','proof.log'))
        bg=proof['bg_shipping_physical_cases'];fg=proof['fg_final_bank_physical_cases']
        bg_bits={0,1,2,3,4,5,7,8,9,10,11,12,13,15};fg_bits={0,5,7}
        if len(bg)!=14 or {c.get('bit')for c in bg}!=bg_bits or len(fg)!=3 or {c.get('bit')for c in fg}!=fg_bits:return False
        descriptor_names=set()
        for kind,cases in [('bg',bg),('bank',fg)]:
            for case in cases:
                if (not completed_hardware_status(case) or case.get('rbf_assembly') is not False or
                        case.get('map_geometry_preserved') is not True or
                        type(case.get('retained_atom_count'))is not int or case['retained_atom_count']<=0):return False
                if kind=='bg' and (case.get('address_width')!=16 or case.get('sq_reg')!=0):return False
                if not any('PASS ' in m and marker_number(m,'cycles')>=40000 and 'masks=f' in m for m in case['pass_markers']):return False
                directory=prefix+kind+'_full_geometry_'+str(case['bit'])+'/'
                descriptor_names.add(directory+'partition.vo.json')
                expected_logs.update(directory+n for n in ('vlog.log','proof.log'))
        descriptors=proof['geometry_descriptors']
        if set(descriptors)!=descriptor_names:return False
        for name,digest in descriptors.items():
            if sources.get(name)!=digest:return False
            descriptor=json.loads((root/name).read_text())
            if any(descriptor.get(k)is not True for k in ('map_geometry_preserved','retained_logic_byte_exact','complete_clock_enable_address_data_cones')):return False
            if descriptor.get('full_atom_count')!=368 or descriptor.get('retained_logic_objects',0)<=0:return False
            count=descriptor['retained_atom_count']
            if (type(count)is not int or count<=0 or len(descriptor['kept_atoms'])!=count or
                    count+len(descriptor['removed_atoms'])!=368):return False
            for k in ('source','partition'):
                path=Path(descriptor[k]).resolve();relative=path.relative_to(root.resolve()).as_posix()
                if sources.get(relative)!=descriptor[k+'_sha256'] or sha(path)!=descriptor[k+'_sha256']:return False
        maps=proof['full_geometry_maps']
        if set(maps)!={'fg','bg'}:return False
        for kind,data in maps.items():
            if (not completed_hardware_status(data) or data.get('rbf_assembly')is not False or
                    data.get('all_data_lanes_retained_during_map')is not True):return False
            before_atoms=data['before_atom_modes'];after_atoms=data['after_atom_modes'];ffs=data['final_output_ff_names']
            if (len(before_atoms)!=184 or len(after_atoms)!=184 or
                    len({a[0] for a in before_atoms})!=184 or len({a[0]for a in after_atoms})!=184 or
                    any(a[1]not in ('clock0','clock1')for a in before_atoms) or any(a[1]!='none'for a in after_atoms) or
                    len(ffs)!=16 or len(set(ffs))!=16 or
                    {int(re.search(r'\[(\d+)\]$',n)[1])for n in ffs}!=set(range(16))):return False
            directory=prefix+('bg_full_map/' if kind=='bg' else 'bank_full_map/')
            expected_logs.update(directory+n for n in ('map.log','eda.log'))
        return expected_logs<=set(evidence)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError):return False

def ddr_be_bridge_verified(proof,needed,root):
    """Use real MC/cache consumers and the exact retained current byte-enable wiring."""
    try:
        if not (ddr_split_bridge_verified(proof,needed,root,production_pairs=(),block_files=(
                'rtl/TMS34020/TMS34020.sv','build/resource_audit/ddr_be_bridge_tb.sv')) and
                proof.get('scalar_write_mirror_equivalence_passed') is True):return False
        coverage=proof['coverage']
        if (type(coverage.get('scalar_mirror_checks'))is not int or
                type(coverage.get('scalar_write_checks'))is not int or
                coverage['scalar_mirror_checks']!=coverage['mc_cycle_checks'] or
                coverage['scalar_write_checks']!=coverage['mc_write_checks']):return False
        sources=proof['sources'];prefix='tests/graphics/evidence/ddr-be-bridge/ddr-be-bridge-'
        compiled=[n for n in sources if n.startswith(prefix) and '/compiled_inputs/' in n]
        if len(compiled)!=12 or len({n.split('/compiled_inputs/')[0]for n in compiled})!=1:return False
        pairs=('rtl/TMS34020/TMS34020_pkg.sv','rtl/TMS34020/TMS34020_MC.sv',
                'rtl/TMS34020/TMS34020_CACHE.sv','rtl/TMS34020_mem.sv',
                'rtl/bg_vram.sv','rtl/fg_vram.sv','rtl/spr_vram.sv','rtl/sprite_blitter.sv',
                'tests/graphics/ram_models.sv','rtl/BT.sv','build/resource_audit/ddr_be_bridge_tb.sv',
                'build/resource_audit/qualify_ddr_be_bridge.py')
        for canonical in pairs:
            matches=[n for n in compiled if n.endswith('/'+canonical)]
            if len(matches)!=1:return False
            expected=(root/canonical).read_bytes();actual=(root/matches[0]).read_bytes()
            if canonical.endswith('/TMS34020_MC.sv'):
                # The only permitted compiler adapter exposes READ_LATCH to the oracle.
                original=(root/canonical).read_text();compiled_text=(root/matches[0]).read_text()
                declaration='\t\tbit         READ_LATCH;'
                event='\talways @(posedge CLK or negedge RST_N) begin'
                if original.count(declaration)!=1:return False
                adapted=original.replace(declaration,'',1).replace(event,'\tbit READ_LATCH;\n'+event,1)
                if compiled_text!=adapted:return False
            elif actual!=expected:return False
        command=' '.join(map(str,proof.get('command',[])))
        return '--assert' in command and 'MISTER_CPU_PHASE_CHECK' in command and 'SYNTHESIS' not in command
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False


def mc_write_mirrors_verified(proof,root,production_aliases=None):
    try:
        folder='build/resource_audit/mc_be_mirror_experiment/'
        needed=('rtl/TMS34020/TMS34020_MC.sv','rtl/TMS34020/TMS34020.sv',
                'tests/graphics/graphics_sim.sv',folder+'TMS34020_MC.sv',folder+'TMS34020.sv',
                folder+'graphics_stub.sv',folder+'publish_receipt.py')
        if not (proof.get('schema')=='bt-mc-scalar-write-mirror-v1' and
                source_bound_run_verified(proof,needed,root,('normal_cycle_equivalence_passed',
                    'all_cycle_scalar_equivalence_passed'),production_aliases) and
                proof.get('mc_production_bytes_compiled')is True and
                proof.get('cpu_scalar_equations_checked')is True and
                type(proof.get('masked_cas_truth_cases'))is int and proof['masked_cas_truth_cases']==128):return False
        if len(proof['sources'])!=18:return False
        pointer=proof['original_receipt'];name=pointer['path']
        if not re.fullmatch(r'tests/graphics/evidence/mc-be-mirror/mc-be-mirror-[0-9a-f]{32}/receipt.json',name):return False
        original=root/name
        if sha(original)!=pointer['sha256']:return False
        raw=json.loads(original.read_text())
        if not source_bound_run_verified(raw,tuple(raw['sources']),root,
                ('normal_cycle_equivalence_passed','all_cycle_scalar_equivalence_passed'),production_aliases):return False
        if not retained_inputs_bound(raw,'tests/graphics/evidence/mc-be-mirror/mc-be-mirror-',
                ('TMS34020_pkg.sv','bt_clock_enables.sv','TMS34020_MC.sv','baseline.sv','tms_memory_tb.sv')):return False
        for live,private in ((needed[0],folder+'TMS34020_MC.sv'),(needed[1],folder+'TMS34020.sv'),
                             (needed[2],folder+'graphics_stub.sv')):
            if (root/(production_aliases or {}).get(live,live)).read_bytes()!=(root/private).read_bytes():return False
        compiled=[n for n in raw['sources']if n.startswith('tests/graphics/evidence/mc-be-mirror/')and n.endswith('/TMS34020_MC.sv')]
        return len(compiled)==1 and (root/compiled[0]).read_text().split()==(root/needed[0]).read_text().split()
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False


def ddr_request_verified(proof,receipt,root,kind):
    """Bind actual compiler inputs, including generated benches retained on the RAM workspace."""
    try:
        prefix='ddr-request-predecode-' if kind=='controller' else 'ddr-boundary-'
        flag='cycle_equivalence_passed' if kind=='controller' else 'boundary_equivalence_passed'
        if any(type(proof.get(k))is not int or proof[k]!=0 for k in ('compile_exit_code','run_exit_code','exit_code')):return False
        if proof.get(flag)is not True or proof.get('production_inputs_compiled')is not True:return False
        snapshot=Path(proof['snapshot']).resolve()
        if not re.fullmatch(prefix+r'[0-9a-f]{32}',snapshot.name) or snapshot.parent!=Path('R:/Verilator/BT').resolve():return False
        sources=proof['sources'];virtual='compiled_'+('ddram_cache_tb.sv'if kind=='controller'else'ddr_boundary_tb.sv')
        needed={'rtl/BT.sv','Arcade-Battletoads.sv','rtl/ddram.sv',virtual,
                'build/resource_audit/qualify_ddr_request_'+('predecode'if kind=='controller'else'boundary')+'.py'}
        if kind=='controller':needed|={'tests/ddram_cache_tb.sv',
                'build/resource_audit/prepare_ddr_request_predecode.py',
                'build/resource_audit/ddr-request-predecode/reference_ddram.sv'}
        if not needed.issubset(sources):return False
        for name,digest in sources.items():
            path=snapshot/virtual.removeprefix('compiled_')if name==virtual else root/name
            if name!=virtual and not path.resolve().is_relative_to(root.resolve()):return False
            if not re.fullmatch('[0-9a-f]{64}',digest) or not path.is_file()or sha(path)!=digest:return False
        command=list(map(str,proof['command']))
        if '--assert'not in command or any('SYNTHESIS'in c for c in command):return False
        compiled=[Path(c).resolve()for c in command if c.endswith('.sv')]
        expected=[snapshot/virtual.removeprefix('compiled_')]
        if kind=='controller':expected=[snapshot/'rtl/ddram.sv',
                snapshot/'build/resource_audit/ddr-request-predecode/reference_ddram.sv']+expected
        if set(compiled)!={p.resolve()for p in expected}:return False
        if kind=='controller':
            if (snapshot/'rtl/ddram.sv').read_bytes()!=(root/'rtl/ddram.sv').read_bytes():return False
            reference=(root/'build/resource_audit/ddr-request-predecode/reference_ddram.sv').read_bytes()
            actual=expected[1].read_bytes()
            name=re.search(rb'\bmodule\s+(\w+)',actual)[1]
            if re.sub(rb'(\bmodule\s+)\w+',lambda m:m[1]+name,reference,count=1)!=actual:return False
        log=(receipt.parent/'run.log').read_text(errors='replace')
        return ('PASS'in log and (all(str(n)in log for n in (3080,2176))if kind=='controller'
                else all(str(n)in log for n in (1048576,10240))))
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError):return False


def fg_bank_write_predecode_verified(proof,root,production_aliases=None):
    """Verify current bank strobes and the immutable post-mux/QA/serial qualification ancestry."""
    try:
        prefix='build/fg_porta_wren_experiment/';folder=root/prefix
        canonical={'rtl/fg_vram.sv','rtl/bg_vram.sv','rtl/BT_mem.sv','tests/graphics/ram_models.sv'}
        if not (proof.get('schema')=='bt-fg-bank-write-predecode-v1' and
                proof.get('fixture_root')==prefix.rstrip('/')and
                type(proof.get('exit_code'))is int and proof['exit_code']==0 and
                all(proof.get(k)is True for k in ('hardware_equivalence_passed','production_promoted','transformation_verified'))):return False
        sources=proof['sources'];aliases=proof['canonical_before_copies'];before=proof['before_sources']
        if set(aliases)!=canonical or set(before)!=canonical or not canonical.issubset(sources):return False
        required={p.relative_to(root).as_posix()for p in folder.rglob('*')if p.is_file()and p.suffix in ('.sv','.py','.qsf','.qpf','.vo')}
        if not required.issubset(sources):return False
        vendor=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v').resolve()
        for name,digest in sources.items():
            path=(root/(production_aliases or {}).get(name,name)).resolve()
            if (not re.fullmatch('[0-9a-f]{64}',digest)or(not path.is_relative_to(root.resolve())and path!=vendor)
                    or not path.is_file()or sha(path)!=digest):return False
        if proof['candidate_fg_sha256']!=sources['rtl/fg_vram.sv']:return False
        for live in canonical:
            if aliases[live]!=prefix+'before/'+live or sources.get(aliases[live])!=before[live]:return False
        pointer=proof['previous_postmux_receipt'];name=prefix+'before_exact_postmux_receipt.json'
        if pointer.get('path')!=name or pointer.get('sha256')!=sha(root/name):return False
        ancestor=json.loads((root/name).read_text())
        if any(ancestor.get('sources',{}).get(n)!=before[n]for n in canonical):return False
        if not postmux_qa_verified(ancestor,root,aliases):return False
        evidence=proof['evidence']
        for name,digest in evidence.items():
            path=(root/name).resolve()
            if not path.is_relative_to(folder.resolve())or not path.is_file()or sha(path)!=digest:return False
        if not completed_hardware_status(proof['transaction_status']):return False
        markers=proof['transaction_pass_markers']
        if not any('PASS postmux every-clock'in m and marker_number(m,'checks')>=31984 for m in markers):return False
        if not any(all(marker_number(m,k)>=n for k,n in {'captures':840,'writes':672,'rmw':160,'pauses':764,'readiness':31960}.items())
                and 'banks=0000000f'in m and 'masks=0000000f'in m for m in markers):return False
        if not any(marker_number(m,'cycles')>=116384 and marker_number(m,'checks')>=931076 for m in proof['ingress_pass_markers']):return False
        geom=proof['full_geometry_map']
        if not(completed_hardware_status(geom)and geom.get('rbf_assembly')is False and
                geom.get('all_data_lanes_retained_during_map')is True):return False
        for key in ('before_atom_modes','after_atom_modes'):
            atoms=geom[key]
            if len(atoms)!=184 or len({a[0]for a in atoms})!=184 or any(a[1]!='none'for a in atoms):return False
        if len(geom['final_output_ff_names'])!=32 or len(set(geom['final_output_ff_names']))!=32:return False
        cones=proof['mapped_write_cones']
        if (cones['before_bank']['max_logic_levels']!=2 or cones['after_bank']['max_logic_levels']!=1 or
                any(cones[k]['qualified_targets']!=184 for k in ('before_bank','after_bank'))):return False
        cases=proof['physical_cases']
        if len(cases)!=3 or {c['bit']for c in cases}!={0,5,7}:return False
        for case in cases:
            if not(completed_hardware_status(case)and case.get('rbf_assembly')is False and case.get('map_geometry_preserved')is True):return False
            if not any(all(marker_number(m,k)>=n for k,n in {'cycles':45792,'mixed':3000,'serial':45790,'writes':41768}.items())
                    and 'masks=f'in m and 'banks=f'in m for m in case['pass_markers']):return False
            if not any(marker_number(m,'draw')>=6000 and marker_number(m,'overlaps')>=4000 for m in case['pass_markers']):return False
        return bool(evidence)
    except (OSError,ValueError,KeyError,TypeError,AttributeError,IndexError):return False


def bound_hash_map(proof,key,root,aliases=None,vendor=False):
    try:
        raw=proof[key];entries={n.replace('\\','/'):d for n,d in raw.items()}
        if not entries or len(entries)!=len(raw):return False
        allowed=Path('D:/q17/quartus/eda/sim_lib/altera_mf.v').resolve()
        for name,digest in entries.items():
            path=(root/(aliases or {}).get(name,name)).resolve()
            if (not isinstance(digest,str)or not re.fullmatch('[0-9a-f]{64}',digest)or
                    (not path.is_relative_to(root.resolve())and not(vendor and path==allowed))or
                    not path.is_file()or sha(path)!=digest):return False
        return True
    except(OSError,ValueError,KeyError,TypeError,AttributeError):return False


def cpu_flat_rf_verified(proof,root):
    try:
        prefix='build/resource_audit/rf_flat_write_experiment/'
        if not (proof.get('schema')=='bt-cpu-flat-rf-write-v1'and type(proof.get('exit_code'))is int and proof['exit_code']==0 and
                all(proof.get(k)is True for k in ('testbench_passed','write_word_equivalence_passed','transformation_verified',
                    'output_latency_preserved','production_promoted'))and bound_hash_map(proof,'sources',root)and
                bound_hash_map(proof,'evidence',root)):return False
        sources=proof['sources'];needed={'rtl/TMS34020/TMS34020.sv','rtl/TMS34020/TMS34020_pkg.sv'}|{
                prefix+n for n in ('TMS34020.sv','before/TMS34020.sv','select.svh','result.svh','write_flat.sv',
                'rf_flat_write_tb.sv','prepare.py','qualify.py','publish_receipt.py','qualified_receipt.json')}
        if (not needed.issubset(sources)or sources['rtl/TMS34020/TMS34020.sv']!=sources[prefix+'TMS34020.sv']or
                proof['candidate_sha256']!=sources[prefix+'TMS34020.sv']):return False
        baseline=proof['before_source'];pointer=proof['qualified_receipt']
        if baseline.get('path')!=prefix+'before/TMS34020.sv'or baseline.get('sha256')!=sources[baseline['path']]:return False
        if pointer.get('path')!=prefix+'qualified_receipt.json'or pointer.get('sha256')!=sources[pointer['path']]:return False
        raw=json.loads((root/pointer['path']).read_text())
        if not(bound_hash_map(raw,'sources',root,{'rtl/TMS34020/TMS34020.sv':baseline['path']})and
                type(raw.get('exit_code'))is int and raw['exit_code']==0 and raw.get('testbench_passed')is True and
                raw.get('candidate_eligible')is True and raw.get('checks')==231072 and proof.get('checks')==231072):return False
        if proof['metrics']!=raw['metrics']:return False
        metrics=proof['metrics']
        if (metrics['before']['source_to_write_max_luts']!=9 or metrics['candidate']['source_to_write_max_luts']!=7 or
                metrics['before']['flip_flops']!=metrics['candidate']['flip_flops']or
                any(metrics[k]['qualified_write_bits']<30 for k in ('before','candidate'))):return False
        for kind in ('before','candidate'):
            if not all(prefix+kind+'/'+n in sources for n in ('probe.sv','probe.qpf','probe.qsf','simulation/modelsim/probe.vo')):return False
        select=(root/(prefix+'select.svh')).read_text();result=(root/(prefix+'result.svh')).read_text()
        guard='\t// synopsys translate_off\n\talways @(posedge CLK) if (RST_N && EN && CE_R && (RF_WA_WE || RF_WB_WE))\n\t\tassert (RF_WRITE_D === (RF_WA_WE ? RF_WA_D : RF_WB_D))\n\t\t\telse $fatal(1,"RF flat write source changed actual memory payload");\n\t// synopsys translate_on\n'
        original=(root/baseline['path']).read_text()
        if original.count('.WA_D(RF_WA_D)')!=1 or original.count('.WB_D(RF_WB_D)')!=1:return False
        expected=original.replace('.WA_D(RF_WA_D)','.WA_D(RF_WRITE_D)',1).replace('.WB_D(RF_WB_D)','.WB_D(RF_WRITE_D)',1)
        expected=expected.replace('\t//Registers bank',select+guard+'\n\t//Registers bank',1)
        anchor='\t\tendcase \n\tend\n\t\n\t//DIV unit'
        if expected.count(anchor)!=1:return False
        expected=expected.replace(anchor,'\t\tendcase\n'+result+'\tend\n\t\n\t//DIV unit',1)
        return expected==(root/'rtl/TMS34020/TMS34020.sv').read_text()and 'PASS RF flat write source checks=231072'in (root/(prefix+'run.log')).read_text()
    except(OSError,ValueError,KeyError,TypeError,AttributeError):return False


def fg_same_edge_ready_verified(proof,root,production_aliases=None):
    try:
        prefix='build/fg_ready_next_experiment/final_1d31/';qualified='build/fg_ready_next_experiment/v2/'
        canonical={'rtl/fg_vram.sv','rtl/bg_vram.sv','rtl/BT_mem.sv','tests/graphics/ram_models.sv'}
        if len(proof.get('sources',{}))!=44:return False
        if not (proof.get('schema')=='bt-fg-same-edge-ready-transform-v1'and proof.get('fixture_root')==prefix.rstrip('/')and
                proof.get('qualified_fixture_root')==qualified.rstrip('/')and type(proof.get('exit_code'))is int and proof['exit_code']==0 and
                all(proof.get(k)is True for k in ('hardware_equivalence_passed','transformation_verified','production_promoted',
                    'original_main_state_and_ram_blocks_unchanged','all_fg_outputs_retained_during_map'))and
                proof.get('clock_latency_change')==0 and proof.get('rbf_assembly')is False and
                bound_hash_map(proof,'sources',root,production_aliases,vendor=True)and bound_hash_map(proof,'evidence',root)):return False
        sources=proof['sources'];aliases=proof['canonical_before_copies'];before=proof['before_sources']
        if set(aliases)!=canonical or set(before)!=canonical:return False
        for name in canonical:
            if aliases[name]!=prefix+'before/'+name or sources.get(aliases[name])!=before[name]:return False
        if (sources.get('rtl/fg_vram.sv')!=proof['candidate_sha256']or sources.get(qualified+'rtl/fg_production.sv')!=proof['candidate_sha256']or
                before['rtl/fg_vram.sv']!=proof['production_before_sha256']):return False
        needed=canonical|{prefix+'finalize.py'}|{p.relative_to(root).as_posix()for p in (root/qualified).rglob('*')
                if p.is_file()and p.suffix in ('.sv','.py','.qsf','.qpf','.vo')}
        if not needed.issubset(sources):return False
        pointers={}
        for kind,file in (('bank_predecode','before_bank_predecode_receipt.json'),('ready','before_ready_receipt.json')):
            pointer=proof['previous_'+kind+'_receipt'];name=prefix+file
            if pointer.get('path')!=name or pointer.get('sha256')!=sha(root/name):return False
            pointers[kind]=json.loads((root/name).read_text())
        if not fg_bank_write_predecode_verified(pointers['bank_predecode'],root,aliases):return False
        old=pointers['ready']
        if not(old.get('schema')=='bt-fg-same-edge-next-ready-v1'and type(old.get('exit_code'))is int and old['exit_code']==0 and
                old.get('hardware_equivalence_passed')is True and bound_hash_map(old,'sources',root,aliases,vendor=True)and
                old.get('candidate_sha256')==proof['candidate_sha256']):return False
        if any(proof.get(k)!=old.get(k)for k in ('statuses','pass_markers','mapped_cones')):return False
        statuses=proof['statuses']
        if set(statuses)!={'transactions','full_map','physical'}or any(not completed_hardware_status(s)for s in statuses.values()):return False
        if not(statuses['full_map'].get('all_fg_output_ports_retained_during_map')is True and statuses['full_map'].get('rbf_assembly')is False and
                statuses['physical'].get('complete_observed_cones_preserved')is True and statuses['physical'].get('rbf_assembly')is False):return False
        markers=proof['pass_markers']
        if not any(marker_number(m,'captures')>=840 and marker_number(m,'writes')>=672 and marker_number(m,'rmw')>=160 and
                marker_number(m,'pauses')>=764 and marker_number(m,'readiness')>=31960 for m in markers):return False
        if not any(marker_number(m,'journal_cycles')>=32007 and marker_number(m,'checks')>=96028 and
                marker_number(m,'async_resets')>=6 for m in statuses['physical']['pass_markers']):return False
        cones=proof['mapped_cones'];predictors=cones['predictor_registers']
        if (cones['ready']['before_fg']['mrt_exec_to_ready_lut_levels']!=3 or
                cones['ready']['after_fg']['mrt_exec_to_ready_lut_levels']!=-1 or len(predictors)!=1):return False
        ff=next(iter(predictors.values()))
        return ff['d']['max_lut_levels']<=3 and ff['q_fanout']>0 and sources.get(cones['full_map_source'].replace('\\','/'))is not None
    except(OSError,ValueError,KeyError,TypeError,AttributeError):return False


def sprite_same_edge_ready_verified(proof,root,production_aliases=None):
    """Qualify the closed Intel control cone and independent full-output RAM proof."""
    try:
        flags=('hardware_equivalence_passed','full_output_equivalence_passed',
               'same_edge_completion_equivalence_passed','mapped_control_equivalence_passed',
               'sequential_dependency_closure_passed','sprite_packet_passed','sprite_read_passed',
               'mapped_board_ready_composition_passed','generator_transformation_replayed',
               'unchanged_main_memory_and_data_processes_passed')
        if any(proof.get(k)is not True for k in flags)or any(type(proof.get(k))is not int or proof[k]!=0
                for k in ('compile_exit_code','run_exit_code','exit_code')):return False
        sources=proof['sources']
        needed={'rtl/spr_vram.sv','rtl/BT_mem.sv','build/spr_ready_experiment/spr_reference.sv',
                'build/spr_ready_experiment/spr_candidate.sv','build/resource_audit/spr_ready_tb.sv',
                'build/resource_audit/prepare_spr_ready.py','build/resource_audit/normalize_spr_ready.py',
                'build/resource_audit/qualify_spr_ready_control.py','tests/sprite_packet_tb.sv',
                'tests/sprite_read_equivalence_tb.sv'}
        if len(sources)<52 or not needed<=set(sources):return False
        vendors={('d:/q17/quartus/eda/sim_lib/'+n)for n in
                 ('altera_mf.v','altera_primitives.v','cyclonev_atoms.v')}
        for name,digest in sources.items():
            path=(root/(production_aliases or {}).get(name,name)).resolve()
            if str(path).replace('\\','/').lower()not in vendors:path.relative_to(root.resolve())
            if not re.fullmatch('[0-9a-f]{64}',digest)or sha(path)!=digest:return False
        baseline=root/'build/spr_ready_experiment/spr_reference.sv'
        candidate=root/'build/spr_ready_experiment/spr_candidate.sv'
        if (sha(baseline)!=proof['original_sha256']or sha(candidate)!=proof['candidate_sha256']or
                candidate.read_bytes()!=(root/(production_aliases or {}).get('rtl/spr_vram.sv','rtl/spr_vram.sv')).read_bytes()or
                proof['ancestor_aliases']!={'rtl/spr_vram.sv':str(baseline.relative_to(root)).replace('\\','/')}):return False
        # Reconstruct the ready-only transformation, preserving every original data process.
        tree=ast.parse((root/'build/resource_audit/prepare_spr_ready.py').read_text())
        blocks=[ast.literal_eval(n.value)for n in tree.body if isinstance(n,ast.Assign)and
                any(isinstance(t,ast.Name)and t.id=='block'for t in n.targets)]
        if len(blocks)!=1:return False
        expected=baseline.read_text()
        replacements=(('\tinput          ESTE\n','\tinput          ESTE,\n\toutput         COMPLETE_RDY,\n\toutput         PACKET_IDLE\n'),
                      ('\t\tbit        RAS_N_OLD;',''),
                      ('\tassign RDY = ~(MRT_EXEC | RMT_EXEC | (|SR_WE));',blocks[0]))
        for before,after in replacements:
            if expected.count(before)!=1:return False
            expected=expected.replace(before,after)
        anchor='\talways @(posedge CLK or negedge RST_N) begin'
        if expected.count(anchor)!=4:return False
        expected=expected.replace(anchor,'\tbit RAS_N_OLD;\n'+anchor,1)
        if expected!=candidate.read_text():return False
        closure=proof['closure']
        if (closure.get('sequential_dependency_closure_passed')is not True or
                closure.get('literal_instances_and_defparams_preserved')is not True or
                closure.get('internal_state_substitution')is not False or
                closure.get('unknown_count')!=0 or closure.get('unresolved_count')!=0 or
                (closure.get('atom_count'),closure.get('ff_count'),closure.get('lut_count'))!=(78,18,31)):return False
        if not {'LRDY_BEFORE','LRDY_AFTER','COMPLETE_RDY','PACKET_IDLE'}<=set(closure['target_outputs']):return False
        closure_paths=[root/n for n in sources if n.endswith('/closure.json')]
        if len(closure_paths)!=1:return False
        stored=json.loads(closure_paths[0].read_text())
        if any(stored.get(k)!=v for k,v in closure.items()if k!='sequential_dependency_closure_passed'):return False
        control_path=Path(proof['mapped_control_receipt']);control_path.resolve().relative_to(root.resolve())
        if str(control_path.relative_to(root)).replace('\\','/')not in sources:return False
        control=json.loads(control_path.read_text())
        for category,labels in (('generic_steps',('all_outputs_compile','all_outputs_run','packet_compile',
                'packet_run','read_compile','read_run','map','eda')),('mapped_steps',('vlib','vlog','intel_control'))):
            if set(proof[category])!=set(labels):return False
            for label in labels:
                status=proof[category][label]
                if type(status.get('exit_code'))is not int or status['exit_code']!=0 or status.get('passed')is not True:return False
                log=Path(proof['generic_log_bindings'][label])if category=='generic_steps'else control_path.parent/(label+'.log')
                log.resolve().relative_to(root.resolve())
                if str(log.relative_to(root)).replace('\\','/')not in sources:return False
                contents=log.read_text(errors='replace')
                if re.search(r'\bFATAL\b|\*\* Error:|\bFAIL\b',contents):return False
                if status.get('required_marker')and status['required_marker']not in contents:return False
        for kind,minimum,defined_minimum in (('generic',110766,23703444),('mapped_control',110738,442952)):
            c=proof['coverage'][kind]
            if c.get('comparisons',0)<minimum or c.get('defined_bits',0)<defined_minimum:return False
            if any(type(c.get(k))is not int or c[k]<n for k,n in
                    (('packet_checks',512),('raw_busy_checks',512),('command_reads',10),('command_writes',8),
                     ('read_beats',1280),('write_beats',1024),('async_resets',50))):return False
        return (proof.get('full_mapped_attempt_qualifies')is False and
                control.get('exit_code')==0 and control.get('sequential_dependency_closure_passed')is True)
    except(OSError,ValueError,KeyError,TypeError,AttributeError,SyntaxError):return False


def bt_sprite_ready_verified(proof,root,production_aliases=None):
    """Bind the literal board composition to the qualified sprite outputs."""
    try:
        prefix='build/resource_audit/bt-sprite-ready/'
        if (proof.get('schema')!='bt-sprite-ready-board-compose-v1'or proof.get('equivalence_passed')is not True or
                proof.get('requires_exact_SPR_predicate_preservation_receipt')is not True or proof.get('checks')!=8192 or
                any(type(proof.get(k))is not int or proof[k]!=0 for k in ('compile_exit_code','run_exit_code','exit_code'))):return False
        snapshot=Path(proof['snapshot'])
        if not re.fullmatch(r'R:/Verilator/BT/bt-sprite-ready-[0-9a-f]{32}',str(snapshot).replace('\\','/')):return False
        for name,digest in proof['sources'].items():
            path=snapshot/'ready_compose_tb.sv'if name=='compiled_ready_compose_tb.sv'else(root/name)
            if name!='compiled_ready_compose_tb.sv':path.resolve().relative_to(root.resolve())
            if sha(path)!=digest:return False
        if set(proof['sources'])!={'build/resource_audit/prepare_bt_sprite_ready.py',prefix+'reference_BT.sv',
                prefix+'BT.sv','build/spr_ready_experiment/spr_candidate.sv','compiled_ready_compose_tb.sv'}:return False
        if ('--assert'not in proof['command']or str(snapshot/'ready_compose_tb.sv')not in proof['command']):return False
        baseline=(root/(prefix+'reference_BT.sv')).read_text()
        replacements=(('\twire CPU_SHIFT_BUSY;','\twire CPU_SHIFT_BUSY;\n\twire SPR_CPU_SHIFT_WE = FG0_COPY_WE | FG1_COPY_WE;\n\twire SPR_COMPLETE_RDY, SPR_PACKET_IDLE;'),
                      ('.CPU_SHIFT_WE(FG0_COPY_WE | FG1_COPY_WE)', '.CPU_SHIFT_WE(SPR_CPU_SHIFT_WE)'),
                      ('\t\t.RDY(SPR_RDY),','\t\t.RDY(SPR_RDY),\n\t\t.COMPLETE_RDY(SPR_COMPLETE_RDY), .PACKET_IDLE(SPR_PACKET_IDLE),'),
                      ('LRDY_SELECT_VALID && !(SPR_BUSY || CPU_SHIFT_BUSY ||','LRDY_SELECT_VALID && !(SPR_BUSY || SPR_CPU_SHIFT_WE ||'),
                      ('(LRDY_USE_ERDY && !ERDY) || (LRDY_USE_SPR && !SPR_RDY));',
                       '(LRDY_USE_ERDY && !ERDY) ||\n\t              (LRDY_USE_SPR ? !SPR_COMPLETE_RDY : !SPR_PACKET_IDLE));'))
        for before,after in replacements:
            if baseline.count(before)!=1:return False
            baseline=baseline.replace(before,after)
        candidate=root/(prefix+'BT.sv')
        return (baseline==candidate.read_text()and candidate.read_bytes()==(root/(production_aliases or {}).get('rtl/BT.sv','rtl/BT.sv')).read_bytes()and
                sha(candidate)==proof['candidate_BT_sha256']and
                sha(root/(prefix+'reference_BT.sv'))==proof['baseline_BT_sha256']and
                sha(root/(production_aliases or {}).get('rtl/spr_vram.sv','rtl/spr_vram.sv'))==proof['SPR_candidate_sha256'])
    except(OSError,ValueError,KeyError,TypeError,AttributeError):return False


def ddr_selector_profile_verified(proof,root,aliases,candidate_alias=None):
    """Verify an attribute-only selector change, including the actual mapped FF ENAs."""
    try:
        if (proof.get('schema')!='bt-ddr-selector-clock-enable-profile-v1'or type(proof.get('exit_code'))is not int or
                proof['exit_code']!=0 or any(proof.get(k)is not True for k in
                ('normalized_rtl_byte_exact','selector_ena_vcc_verified','no_new_clock_or_latency','requires_fresh_routed_timing'))or
                proof.get('selector_ff_count')!=16 or not bound_hash_map(proof,'sources',root,aliases)):return False
        if set(proof['sources'])!={'rtl/ddram.sv','build/resource_audit/prepare_ddr_no_enable.py',
                'build/resource_audit/ddr-no-enable/ddram.sv'}:return False
        original=(root/aliases['rtl/ddram.sv']).read_bytes();candidate_path=root/(candidate_alias or 'rtl/ddram.sv');candidate=candidate_path.read_bytes()
        before=b'(* keep = "true" *) reg [15:0] read_return_sel'
        after=b'(* keep = "true", altera_attribute = "-name AUTO_CLOCK_ENABLE_RECOGNITION OFF" *) reg [15:0] read_return_sel'
        if (candidate.count(after)!=1 or candidate.replace(after,before)!=original or
                sha(candidate_path)!=proof['candidate_sha256']or
                sha(root/aliases['rtl/ddram.sv'])!=proof['baseline_sha256']or
                candidate!=(root/'build/resource_audit/ddr-no-enable/ddram.sv').read_bytes()):return False
        receipt=root/proof['map_receipt'];receipt.resolve().relative_to(root.resolve())
        if sha(receipt)!=proof['map_receipt_sha256']or sha(receipt.with_name('metadata_cones.json'))!=proof['metadata_cones_sha256']:return False
        mapped=json.loads(receipt.read_text());cones=json.loads(receipt.with_name('metadata_cones.json').read_text())
        if type(mapped.get('exit_code'))is not int or mapped['exit_code']!=0 or not bound_hash_map(mapped,'sources',root,aliases):return False
        for kind,digest in (('production',proof['baseline_sha256']),('no_enable',proof['candidate_sha256'])):
            item=mapped['mapping'][kind];folder=receipt.parent/kind
            if (item['exit_codes']!=[0,0]or item['ddram_sha256']!=digest or sha(folder/'ddram.sv')!=digest or
                    sha(folder/'probe.sv')!=item['wrapper_sha256']or sha(root/item['netlist'])!=item['netlist_sha256']):return False
            if cones['variants'][kind]['unknown_in_target_cones']or cones['variants'][kind]['target_summary']['read_return_sel']['max_depth']!=3:return False
        selected=[];text=(root/mapped['mapping']['no_enable']['netlist']).read_text()
        for m in re.finditer(r'\bdffeas\s+(\\\S+|\w+)\s*\((.*?)\);',text,re.S):
            if not m[1].strip().lstrip('\\').startswith('dut|read_return_sel['):continue
            ports={p[1]:p[2].strip()for p in re.finditer(r'\.(\w+)\s*\(([^)]*)\)',m[2])}
            if ports.get('ena','vcc')!='vcc':return False
            selected.append(m[1])
        return len(selected)==16 and proof['mapped_selector_depth_before']==3 and proof['mapped_selector_depth_after']==3
    except(OSError,ValueError,KeyError,TypeError,AttributeError):return False


def clock_predicate_verified(proof,receipt,root):
    needed=('rtl/bt_clock_enables.sv','build/resource_audit/ddr_return_split/bt_clock_enables.sv',
            'build/resource_audit/ddr_return_split/clock_reference.sv',
            'build/resource_audit/ddr_return_split/clock_predicate_tb.sv',
            'build/resource_audit/ddr_return_split/qualify_clock_predicate.py',
            'build/resource_audit/ddr_return_split/prepare.py',
            'build/resource_audit/ddr_return_split/before/rtl/bt_clock_enables.sv')
    try:
        if not source_bound_run_verified(proof,needed,root,('clock_waveform_equivalence_passed',)):return False
        if proof['sources'][needed[0]]!=proof['sources'][needed[1]]:return False
        if not any(m.startswith('PASS exact registered CPU phase predicates') and
                all(marker_number(m,k)>=v for k,v in {'cycles':25000,'checks':50000,'resets':500,
                    'pauses':6000,'F':9000,'R':9000,'V':2500}.items())for m in proof['pass_markers']):return False
        evidence=proof['evidence']
        return set(evidence)=={'compile.log','run.log'} and all(sha(receipt.parent/n)==v for n,v in evidence.items())
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False

def cache_split_verified(proof,needed,root):
    try:
        if not source_bound_run_verified(proof,needed,root,('functional_miter_passed',
                'normal_controller_equivalence_passed','hardware_equivalence_passed',
                'word_stage_equivalence_passed','ddr_split_equivalence_passed')):return False
        if any(type(v)is not int or v<=1000 for v in proof['word_stage_coverage'].values()):return False
        counts=proof['ddr_split_coverage']
        if set(counts)!={'ram_writes','ddr_full_writes','ddr_byte_writes'} or any(type(v)is not int or v<=1000 for v in counts.values()):return False
        sources=proof['sources']
        if (proof['candidate_cache_sha256']!=sources['rtl/TMS34020/TMS34020_CACHE.sv'] or
                proof['candidate_memory_sha256']!=sources['rtl/TMS34020_mem.sv'] or
                proof['generator_sha256']!=sources['build/resource_audit/cache_packing_ddr_split.py']):return False
        fixtures=('cache_packing_tb.sv','cache_storage_physical_tb.sv','TMS34020_CACHE_REF.sv',
                  'cache_ram_ref.sv','vendor_ref.sv','vendor_candidate.sv','normal_cache_ref.sv',
                  'normal_ram_ref.sv','normal_cache_tb.sv','TMS34020_CACHE.sv','TMS34020_mem.sv','TMS34020_pkg.sv')
        if not retained_inputs_bound(proof,'build/resource_audit/cache-packing/cache-packing-ddr-split-',fixtures):return False
        evidence=proof['evidence'];expected={'functional-build.log','functional-run.log',
                'normal-controller-build.log','normal-controller-run.log','physical-build.log','physical-run.log'}
        if {n.rsplit('/',1)[-1]for n in evidence}!=expected or len(evidence)!=6:return False
        for name,digest in evidence.items():
            path=(root/name).resolve()
            if not path.is_relative_to((root/'build/resource_audit/cache-packing').resolve()) or sha(path)!=digest:return False
        original=proof['retained_original_receipt']
        return original in sources and sha(root/original)==sources[original]
    except (OSError,ValueError,KeyError,TypeError,AttributeError):return False

def held_capture_reports_verified(snapshot,corners):
    try:
        rows=list(csv.DictReader((snapshot/'timing_audit/held_capture_endpoints.tsv').open(),delimiter='\t'))
        groups=('mc_ram','mc_ddr','cache_ram','cache_ddr')
        if len(rows)!=8 or {r['corner']for r in rows}!=corners:return False
        for row in rows:
            for group in groups:
                if not re.fullmatch('[1-9][0-9]*',row[group+'_nodes']):return False
                tag=re.sub(r'[^A-Za-z0-9_.-]','_',row['corner'])
                text=(snapshot/'timing_audit'/(tag+'_'+group+'_capture.rpt')).read_text(errors='replace')
                summary=re.search(r'Found (\d+) setup paths .*?Worst case slack is\s+(-?[\d.]+)',text)
                relationships=re.findall(r'Setup Relationship\s*;\s*(-?[\d.]+)',text)
                if (summary is None or int(summary[1])!=1 or float(summary[2])<0 or
                        len(relationships)!=1 or abs(float(relationships[0])-6.25)>0.0005):return False
        return True
    except (OSError,ValueError,KeyError,TypeError):return False


"""Private source-bound same-edge HOLE_RD promotion gate; no RTL writes."""

def fg_hole_address_promotion_verified(proof,root,production_aliases=None):
    try:
        prefix='build/fg_ready_next_experiment/final_hole_a5/'
        canonical={'rtl/fg_vram.sv','rtl/bg_vram.sv','rtl/BT_mem.sv','tests/graphics/ram_models.sv'}
        if not (proof.get('schema')=='bt-fg-same-edge-hole-address-bit5-promotion-v1'and
                proof.get('fixture_root')==prefix.rstrip('/')and
                proof.get('qualified_fixture_root')=='build/fg_ready_next_experiment/hole_a5'and
                proof.get('hole_read_qualified_fixture_root')=='build/fg_ready_next_experiment/hole_rd_only'and
                proof.get('cleanup_qualified_fixture_root')=='build/fg_ready_next_experiment/clean'and
                type(proof.get('exit_code'))is int and proof['exit_code']==0 and
                all(proof.get(k)is True for k in ('hardware_equivalence_passed','production_promoted',
                    'original_main_and_ram_blocks_unchanged','hole_sel_combinational_unchanged','same_edge_no_added_latency'))and
                proof.get('rbf_assembly')is False and len(proof.get('sources',{}))==211 and
                bound_hash_map(proof,'sources',root,production_aliases,vendor=True)):return False
        sources=proof['sources'];before=proof['canonical_before_sources'];aliases=proof['canonical_before_copies']
        if set(before)!=canonical or set(aliases)!=canonical:return False
        for name in canonical:
            if aliases[name]!=prefix+'before/'+name or sources.get(aliases[name])!=before[name]:return False
        if sources.get('rtl/fg_vram.sv')!=proof['candidate_fg_sha256']:return False
        for name in canonical-{'rtl/fg_vram.sv'}:
            if sources.get(name)!=before[name]:return False
        roles={};role_aliases={}
        for role,kind in (('ready','ready_transform'),('cleanup','cleanup'),('hole','hole_read'),('address','address_bit'),('strict_hole_fgddr','hole_strict_foreground_ddr'),('strict_fgddr','strict_foreground_ddr')):
            pointer=proof['previous_'+kind+'_receipt']
            expected=prefix+'prior_'+kind+'_receipt.json'
            if pointer!=expected or proof['previous_'+kind+'_receipt_sha256']!=sha(root/pointer):return False
            raw=json.loads((root/pointer).read_text());roles[role]=raw
            resolved=proof['qualified_source_sets'][role]
            if set(resolved)!=set(raw['sources']):return False
            role_aliases[role]={}
            for name,binding in resolved.items():
                if not (binding.get('sha256')==raw['sources'][name]and sources.get(binding['path'])==binding['sha256']and
                        sha(root/binding['path'])==binding['sha256']):return False
                role_aliases[role][name]=binding['path']
            if not bound_hash_map(raw,'sources',root,role_aliases[role],vendor=True):return False
            if type(raw.get('exit_code'))is not int or raw['exit_code']!=0:return False
        ready,cleanup,hole,address,strict_old,strict=(roles[k]for k in ('ready','cleanup','hole','address','strict_hole_fgddr','strict_fgddr'))
        if not fg_same_edge_ready_verified(ready,root,role_aliases['ready']):return False
        if (ready['candidate_sha256']!=before['rtl/fg_vram.sv']or
                cleanup['production_before_sha256']!=before['rtl/fg_vram.sv']or
                cleanup['candidate_sha256']!=proof['cleanup_candidate_fg_sha256']or
                hole['candidate_fg_sha256']!=proof['intermediate_hole_read_fg_sha256']or
                address['candidate_fg_sha256']!=proof['candidate_fg_sha256']or
                address['baseline_hole_read_fg_sha256']!=hole['candidate_fg_sha256']):return False
        if any(raw.get('hardware_equivalence_passed')is not True for raw in (cleanup,hole,address)):return False
        for previous,expected_sha in [(strict_old,proof['intermediate_hole_read_fg_sha256']),(strict,proof['candidate_fg_sha256'])]:
            previous_command=previous['command']
            if not (previous['sources'].get('rtl/fg_vram.sv')==expected_sha and
                    all(flag in previous_command for flag in ('--binary','--assert','--top-module','foreground_ddr_tb'))and
                    not any(flag in previous_command for flag in ('-Wno-fatal','-Wno-LATCH'))):return False
        command=strict['command']
        if not (strict['sources'].get('rtl/fg_vram.sv')==proof['candidate_fg_sha256']and
                all(flag in command for flag in ('--binary','--assert','--top-module','foreground_ddr_tb'))and
                not any(flag in command for flag in ('-Wno-fatal','-Wno-LATCH'))):return False
        if proof['status']!={key:address['statuses'][key]for key in proof['status']}or proof['mapped_cones']!=address['mapped_cones']:return False
        if any(not completed_hardware_status(s)for s in proof['status'].values()):return False
        if not (type(proof.get('all_production_fg_outputs_retained_during_map'))is int and
                proof['all_production_fg_outputs_retained_during_map']>=13 and
                proof.get('original_control_state_bits')==48 and
                proof.get('mapped_hole_rd_checks',0)>=546065 and
                proof.get('hole_rd_high_checks',0)>=17115 and proof.get('hole_rd_low_checks',0)>=528950):return False
        if not (proof.get('all_address_bits_compared')==18 and proof.get('only_address_bit5_registered')is True and
                proof.get('mapped_all_address_bits_checks',0)>=546065 and
                proof.get('hole_a_bit5_high_checks',0)>=227883 and proof.get('hole_a_bit5_low_checks',0)>=318182):return False
        for key in ['mapped_all_address_bits_checks','hole_a_bit5_high_checks','hole_a_bit5_low_checks','address_cones','copy_addr_n_invariant']:
            if proof.get(key)!=address.get(key):return False
        cones=proof['address_cones']
        if cones.get('original_address_bit5_max_lut_levels')!=1 or cones.get('predicted_address_bit5_max_lut_levels')!=0:return False
        registers=cones.get('predictor_registers',{})
        if len(registers)!=1:return False
        for name,data in registers.items():
            if '|HOLE_A5_FF' not in name or data['summary']['d']['max_lut_levels']>3:return False
            if data['specific_launch_cones']['COPY_ADDR_N[5]']['max_lut_levels']>2:return False
        if proof['pass_markers']!=address['pass_markers']:return False
        markers=proof['pass_markers']
        if not any('PASS same-edge HOLE_A18 Intel FF atoms'in m and marker_number(m,'checks')>=546065 and
                marker_number(m,'bit5_high')>=227883 and marker_number(m,'bit5_low')>=318182 for m in markers):return False
        if not any(marker_number(m,'captures')>=840 and marker_number(m,'writes')>=672 and marker_number(m,'rmw')>=160 and
                marker_number(m,'pauses')>=764 and marker_number(m,'readiness')>=31960 for m in markers):return False
        if not any(marker_number(m,'state_bits')>=48 and marker_number(m,'checks')>=546065 for m in markers):return False
        if not any(marker_number(m,'journal_cycles')>=182007 and marker_number(m,'checks')>=546065 and
                marker_number(m,'async_resets')>=43 for m in markers):return False
        candidate=root/(production_aliases or {}).get('rtl/fg_vram.sv','rtl/fg_vram.sv')
        if proof['candidate_copy']not in sources or candidate.read_bytes()!=(root/proof['candidate_copy']).read_bytes():return False
        transforms=proof['pure_transforms']
        if transforms!=prefix+'transforms.py'or sources.get(transforms)!=proof['pure_transforms_sha256']:return False
        tree=ast.parse((root/transforms).read_text())
        nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom,ast.Assign,ast.FunctionDef))]
        if len(nodes)!=len(tree.body):return False
        env={};exec(compile(ast.Module(body=nodes,type_ignores=[]),'qualified-pure-fg-hold-transform','exec'),env)
        before_text=(root/aliases['rtl/fg_vram.sv']).read_text()
        clean=env['clean'](before_text);intermediate=env['transform'](clean);after=env['hole_a5_transform'](intermediate)
        if clean!=(root/proof['cleanup_candidate_copy']).read_text()or after!=candidate.read_text():return False
        intermediate_copy=proof['intermediate_hole_read_candidate_copy']
        if sources.get(intermediate_copy)!=proof['intermediate_hole_read_fg_sha256']or intermediate!=(root/intermediate_copy).read_text():return False
        if env['main_block'](clean)!=env['main_block'](intermediate):return False
        if proof['copy_addr_n_invariant']!='Reset ADDR=0,N=1; start ADDR=A,N=A+1; collect increments both by1 modulo2^18':return False
        if env['main_block'](before_text)!=env['main_block'](after):return False
        return 'assign HOLE_SEL = READ_DDR || RMT_DDR;'in after and all(
            data.get('d',{}).get('max_lut_levels',999)<=3 and data.get('q_fanout',0)>0
            for data in proof['mapped_cones']['predictor_registers'].values())
    except(OSError,ValueError,KeyError,TypeError,AttributeError,SyntaxError,AssertionError):return False


"""Private guarded lane-selector transform and original inference-profile chain."""

def ddr_lane_replicas_verified(proof,root,profile_aliases,controller_aliases=None,production_aliases=None):
    try:
        prefix='build/resource_audit/ddr-return-lanes-v2/'
        final=prefix+'final/'
        if not (proof.get('schema')=='bt-ddr-return-lanes-v1'and type(proof.get('exit_code'))is int and proof['exit_code']==0 and
                len(proof.get('sources',{}))==29 and all(proof.get(k)is True for k in
                ('source_reconstruction_byte_exact','selector_ena_vcc_verified','existing_clock_verified','no_new_clock_or_latency',
                 'requires_fresh_routed_timing','production_promoted'))and proof.get('output_line_endings')=='CRLF'and
                bound_hash_map(proof,'sources',root,production_aliases)):return False
        sources=proof['sources']
        candidate=root/(production_aliases or {}).get('rtl/ddram.sv','rtl/ddram.sv')
        if (sources.get('rtl/ddram.sv')!=proof['candidate_sha256']or
                proof['before_source']!=final+'before_ddram.sv'or sha(root/proof['before_source'])!=proof['baseline_sha256']or
                candidate.read_bytes()!=(root/(prefix+'ddram.sv')).read_bytes()):return False
        previous=proof['before_selector_profile_receipt']
        if previous!=final+'before_selector_profile_receipt.json'or sha(root/previous)!=proof['before_selector_profile_receipt_sha256']:return False
        profile=json.loads((root/previous).read_text())
        if profile['candidate_sha256']!=proof['baseline_sha256']or not ddr_selector_profile_verified(
                profile,root,profile_aliases,proof['before_source']):return False
        generator=root/(final+'prepare_ddr_return_lanes.py')
        fragment=generator.read_text().split("original='\\n'.join",1)
        if len(fragment)!=2:return False
        fragment="original='\\n'.join"+fragment[1].split('for name,data in',1)[0]
        env={'old':(root/proof['before_source']).read_text()}
        exec(compile(fragment,str(generator),'exec'),env)
        if env['new'].replace('\n','\r\n').encode()!=candidate.read_bytes():return False
        for field,before,after in (('selector_ff_count',16,64),('selector_fanout',33,9),('mapped_output_depth',3,3)):
            if proof.get(field+'_before')!=before or proof.get(field+'_after')!=after:return False
        if proof.get('additional_logic_ff')!=48 or proof.get('mapped_combinational_delta')!=87:return False
        mapped=json.loads((root/proof['map_receipt']).read_text())
        analysis=json.loads((root/proof['map_analysis']).read_text())
        if not (type(mapped.get('exit_code'))is int and mapped['exit_code']==0 and
                type(analysis.get('exit_code'))is int and analysis['exit_code']==0 and analysis.get('no_new_clock_or_enable')is True and
                bound_hash_map(mapped,'sources',root,{'rtl/ddram.sv':proof['before_source']})):return False
        if analysis.get('map_receipt_sha256')!=sha(root/proof['map_receipt']):return False
        parsed={}
        for kind,count,source in (('baseline',16,root/proof['before_source']),('lanes',64,candidate)):
            item=mapped['mapping'][kind];folder=(root/proof['map_receipt']).parent/kind
            if len(item['commands'])!=2 or any(type(c.get('exit_code'))is not int or c['exit_code']!=0 for c in item['commands']):return False
            if not ('quartus_map'in item['commands'][0]['argv']and 'quartus_eda'in item['commands'][1]['argv']):return False
            if ((folder/'ddram.sv').read_text()!=source.read_text()or sha(folder/'probe.sv')!=item['wrapper_sha256']or
                    sha(root/item['netlist'])!=item['netlist_sha256']):return False
            text=(root/item['netlist']).read_text();selected={};references={}
            for m in re.finditer(r'\bdffeas\s+(\\\S+|\w+)\s*\((.*?)\);',text,re.S):
                if 'read_return_sel'not in m[1].strip().lstrip('\\'):continue
                p={x[1]:x[2].strip()for x in re.finditer(r'\.(\w+)\s*\(([^)]*)\)',m[2])}
                if p.get('ena','vcc')!='vcc':return False
                selected[m[1].strip().lstrip('\\')]=p
            if len(selected)!=count or len({p['clk']for p in selected.values()})!=1:return False
            parsed[kind]=selected
            actual=analysis['variants'][kind]
            if (actual['selector_count']!=count or actual['selector_ena_vcc']is not True or actual['selector_clock_count']!=1 or
                    actual['selector_to_dout_maximum_lut_depth']!=3 or actual['selector_max_lut_fanout']!=(33 if kind=='baseline'else 9)):return False
            if set(actual['selector_cells'])!=set(selected):return False
        if {p['clk']for p in parsed['baseline'].values()}!={p['clk']for p in parsed['lanes'].values()}:return False
        controller=json.loads((root/proof['all_cycle_controller_receipt']).read_text())
        snapshot=Path(controller['snapshot'])
        expected_snapshot='ddr-request-predecode-'+(root/proof['all_cycle_controller_receipt']).parent.name.removeprefix('ddr-request-predecode-')
        if snapshot.parent!=Path('R:/Verilator/BT')or snapshot.name!=expected_snapshot:return False
        virtual='compiled_ddram_cache_tb.sv';compiled_tb=snapshot/'ddram_cache_tb.sv'
        if sha(compiled_tb)!=controller['sources'][virtual]or str(compiled_tb)not in controller['command']:return False
        for name in (prefix+'ddram.sv','build/resource_audit/ddr-request-predecode/reference_ddram.sv'):
            compiled=snapshot/name
            expected=(root/name).read_text()
            if name.endswith('/reference_ddram.sv'):
                if expected.count('module ddram')!=1:return False
                expected=expected.replace('module ddram','module ddram_baseline',1)
            if compiled.read_text()!=expected or str(compiled)not in controller['command']:return False
        declared=dict(controller);declared['sources']={k:v for k,v in controller['sources'].items()if k!=virtual}
        if not (all(type(controller.get(k))is int and controller[k]==0 for k in ('compile_exit_code','run_exit_code','exit_code'))and
                controller.get('cycle_equivalence_passed')is True and bound_hash_map(declared,'sources',root,controller_aliases)and
                controller['sources'].get(prefix+'ddram.sv')==proof['candidate_sha256']and '--assert'in controller['command']):return False
        log=(root/proof['all_cycle_controller_receipt']).with_name('run.log').read_text()
        return ('PASS DDR cache pipeline:'in log and '3080 masked/burst/I/O writes'in log and '2176 checked reads'in log and
                '176 DDR read commands'in log and not any(token in log for token in ('Fatal','%Error','Assertion failed')))
    except(OSError,ValueError,KeyError,TypeError,AttributeError,SyntaxError,AssertionError):return False


"""Strict source-closed SPR_NZ_SPR nonzero preservation predicate for gate integration.

source_hashes must be the gate's authoritative snapshot input hashes. A private
prospective test may supply qualified candidate hashes, but that is explicitly
not release qualification. This helper never changes a file or waives timing.
"""
from pathlib import Path
import hashlib,json,re
SPR_NZ_FLAGS=('hardware_equivalence_passed','full_output_equivalence_passed','nibble_valid_equivalence_passed','whole_blitter_equivalence_passed','exhaustive_transparency_passed','mapped_mirror_equivalence_passed','mapped_blitter_equivalence_passed','exact_source_transformation_passed','unchanged_ready_and_memory_owner_state_machines_passed','map_only_passed')
SPR_NZ_BEFORE={'rtl/spr_vram.sv':'eb3b47cd198499013d7f20e15bffc4c590db75c9f74a836b28525279558ff45b','rtl/sprite_blitter.sv':'f67772b62566ab5eb82b09e2785c2456bbfb38fde7e133d0988cfb15238f1371','rtl/BT.sv':'505a7ea40d52fa328dd0b7877446ddea742fd8d26da20ba516829cd448caef5c'}
SPR_NZ_SPR=(('output         PACKET_IDLE\n','output         PACKET_IDLE,\n\toutput [3:0] BLIT_NONZERO\n'),('wire [63:0] mirror_q;','wire [63:0] mirror_q;\n\twire [15:0] mirror_nz;'),('VRAM_SHIFTREG #(10,1,1) read_mirror(','BT_SPR_POST_NONZERO_MIRROR #(10) read_mirror('),('.Q(mirror_q)','.Q(mirror_q),.NZ(mirror_nz)'),('assign CPU_SHIFT_Q = BLIT_WORD;','assign CPU_SHIFT_Q = BLIT_WORD;\n\tassign BLIT_NONZERO = mirror_nz >> {BLIT_LANE2,2\'b00};'))
SPR_NZ_BLITTER=(('module BT_SPRITE_BLITTER (','module BT_SPRITE_BLITTER #(parameter NONZERO_PREDECODE=0) ('),('output BUSY\n','output BUSY,\n    input [3:0] SOURCE_NONZERO\n'),('wire [31:0] address =','wire color_valid=NONZERO_PREDECODE ? SOURCE_NONZERO[nibble] : |color;\n    wire [31:0] address ='),('? |color :','? color_valid :'),('DRAW_WE <= |color;','DRAW_WE <= color_valid;'))
def sprite_nonzero_verified(entry,source_hashes,root):
 try:return _sprite_nonzero_verify(entry,source_hashes,Path(root))
 except (AssertionError,KeyError,TypeError,ValueError,OSError):return False
def _sprite_nonzero_verify(entry,source_hashes,root):
 source_hashes={name.replace('\\','/'):digest for name,digest in source_hashes.items()}
 SPR_NZ_FLAGS = ('hardware_equivalence_passed', 'full_output_equivalence_passed', 'nibble_valid_equivalence_passed', 'whole_blitter_equivalence_passed', 'exhaustive_transparency_passed', 'mapped_mirror_equivalence_passed', 'mapped_blitter_equivalence_passed', 'exact_source_transformation_passed', 'unchanged_ready_and_memory_owner_state_machines_passed', 'map_only_passed')
 SPR_NZ_BEFORE = {'rtl/spr_vram.sv': 'eb3b47cd198499013d7f20e15bffc4c590db75c9f74a836b28525279558ff45b', 'rtl/sprite_blitter.sv': 'f67772b62566ab5eb82b09e2785c2456bbfb38fde7e133d0988cfb15238f1371', 'rtl/BT.sv': '505a7ea40d52fa328dd0b7877446ddea742fd8d26da20ba516829cd448caef5c'}
 SPR_NZ_SPR = (('output         PACKET_IDLE\n', 'output         PACKET_IDLE,\n\toutput [3:0] BLIT_NONZERO\n'), ('wire [63:0] mirror_q;', 'wire [63:0] mirror_q;\n\twire [15:0] mirror_nz;'), ('VRAM_SHIFTREG #(10,1,1) read_mirror(', 'BT_SPR_POST_NONZERO_MIRROR #(10) read_mirror('), ('.Q(mirror_q)', '.Q(mirror_q),.NZ(mirror_nz)'), ('assign CPU_SHIFT_Q = BLIT_WORD;', "assign CPU_SHIFT_Q = BLIT_WORD;\n\tassign BLIT_NONZERO = mirror_nz >> {BLIT_LANE2,2'b00};"))
 SPR_NZ_BLITTER = (('module BT_SPRITE_BLITTER (', 'module BT_SPRITE_BLITTER #(parameter NONZERO_PREDECODE=0) ('), ('output BUSY\n', 'output BUSY,\n    input [3:0] SOURCE_NONZERO\n'), ('wire [31:0] address =', 'wire color_valid=NONZERO_PREDECODE ? SOURCE_NONZERO[nibble] : |color;\n    wire [31:0] address ='), ('? |color :', '? color_valid :'), ('DRAW_WE <= |color;', 'DRAW_WE <= color_valid;'))
 digest=lambda data:hashlib.sha256(data).hexdigest()
 def path(key):return Path(key)if Path(key).is_absolute()else root/key
 def file_sha(key):return digest(path(key).read_bytes())
 def integer(value,minimum=0):assert type(value)is int and value>=minimum
 def zero(value):assert type(value)is int and value==0
 def truth(value):assert value is True
 assert entry['schema']=='sprite-nonzero-publisher-v1'
 truth(entry['current_production'])
 for flag in SPR_NZ_FLAGS:truth(entry[flag])
 for key in ['compile_exit_code','run_exit_code','exit_code']:zero(entry[key])
 assert type(entry['full_map_attempt_exit_code'])is int and entry['full_map_attempt_exit_code']==1 and entry['full_map_attempt_qualifies']is False
 assert entry['before_sha256']==SPR_NZ_BEFORE
 aliases=entry['production_aliases'];history=entry['historical_aliases']
 assert set(aliases)==set(history)==set(SPR_NZ_BEFORE)==set(entry['candidate_sha256'])
 assert len(entry['sources'])>=149
 # The normalized receipt must retain the entire immutable publisher inventory.
 # A count floor could accept a missing producer input padded with unrelated keys.
 publisher_key='build/resource_audit/sprite_nonzero_v2/publisher/receipt.json'
 normalizer_key='build/resource_audit/normalize_sprite_nonzero.py'
 publisher=json.loads(path(publisher_key).read_text())
 assert set(entry['sources'])==set(publisher['sources'])|{publisher_key,normalizer_key}
 assert all(entry['sources'][key]==value for key,value in publisher['sources'].items())
 assert entry['sources'][publisher_key]==file_sha(publisher_key)
 assert entry['sources'][normalizer_key]==file_sha(normalizer_key)
 for key,sha in entry['sources'].items():
  assert isinstance(sha,str)and re.fullmatch(r'[0-9a-f]{64}',sha)
  if key in aliases:
   assert source_hashes.get(key)==sha and file_sha(aliases[key])==sha
  else:
   assert file_sha(key)==sha
   if key.startswith('rtl/'):
    assert key in source_hashes and source_hashes[key]==sha
 for key,sha in SPR_NZ_BEFORE.items():assert file_sha(history[key])==sha
 assert {k:file_sha(p)for k,p in aliases.items()}==entry['candidate_sha256']
 def apply(text,pairs):
  for old,new in pairs:assert text.count(old)==1;text=text.replace(old,new)
  return text
 # Exact literal source transformation, not a caller-defined transformation.
 assert entry['transformations']['spr']==[list(x)for x in SPR_NZ_SPR]
 assert entry['transformations']['blitter']==[list(x)for x in SPR_NZ_BLITTER]
 source_base=root/'build/resource_audit/sprite_nonzero_v2'
 old_spr=path(history['rtl/spr_vram.sv']).read_text();old_blitter=path(history['rtl/sprite_blitter.sv']).read_text()
 bare=(source_base/'spr_candidate.sv').read_bytes();helper=(source_base/'mirror.sv').read_bytes()
 assert digest(helper)=='52f62eceee26ef943dcebc512e7dab50a9b41a7867cf80d51fbe1559604f4a32'
 assert apply(old_spr,SPR_NZ_SPR).encode()==bare
 assert path(aliases['rtl/spr_vram.sv']).read_bytes()==bare+helper
 assert apply(old_blitter,SPR_NZ_BLITTER).encode()==path(aliases['rtl/sprite_blitter.sv']).read_bytes()
 old_bt=path(history['rtl/BT.sv']).read_bytes();eol='\r\n'if b'\r\n'in old_bt else'\n'
 bt_pairs=(('\tBT_SPRITE_BLITTER blitter (','\twire [3:0] SPR_SOURCE_NONZERO;'+eol+'\tBT_SPRITE_BLITTER #(.NONZERO_PREDECODE(1)) blitter ('),('.SOURCE_WORD(SPR_SOURCE_A), .SOURCE_DATA(SPR_SOURCE_Q),','.SOURCE_WORD(SPR_SOURCE_A), .SOURCE_DATA(SPR_SOURCE_Q), .SOURCE_NONZERO(SPR_SOURCE_NONZERO),'),('.BLIT_A(SPR_SOURCE_A), .BLIT_Q(SPR_SOURCE_Q),','.BLIT_A(SPR_SOURCE_A), .BLIT_Q(SPR_SOURCE_Q), .BLIT_NONZERO(SPR_SOURCE_NONZERO),'))
 assert entry['transformations']['BT']==[list(x)for x in bt_pairs]
 assert apply(old_bt.decode(),bt_pairs).encode()==path(aliases['rtl/BT.sv']).read_bytes()
 required={'logical','mapped_mirror','mapped_blitter','mapped_structure','map_attempt','prior_sprite_ready','prior_BT_compose'}
 assert set(entry['proof_receipts'])==required
 proofs={};proof_paths={}
 for role,info in entry['proof_receipts'].items():
  p=path(info['path']);assert digest(p.read_bytes())==info['sha256'];r=json.loads(p.read_text());proofs[role]=r;proof_paths[role]=p
  if role!='map_attempt':zero(r['exit_code'])
  for key,sha in r.get('sources',{}).items():
   if key in history:p_source=path(history[key])
   elif key=='compiled_ready_compose_tb.sv':p_source=Path(r['snapshot'])/'ready_compose_tb.sv'
   else:p_source=path(key)
   assert digest(p_source.read_bytes())==sha,(role,key)
 for role in ['logical','mapped_mirror','mapped_blitter']:
  for step in proofs[role]['steps'].values():zero(step['exit_code']);truth(step['passed'])
 for key in ['before_map','before_eda','after_map','after_eda','mirror_map','mirror_eda']:
  step=proofs['map_attempt']['steps'][key];zero(step['exit_code']);truth(step['passed'])
 assert proofs['map_attempt']['exit_code']==1
 def counters(role,stage,marker):
  step=proofs[role]['steps'][stage];line=step['pass_marker'];assert marker in line
  log=(proof_paths[role].parent/(stage+'.log')).read_text(errors='replace')
  assert line in log and not re.search(r'\bFATAL\b|\*\* Error:|recommended capacity|Missing connection|Error loading design',log)
  parsed={k:int(v,16)if k in ['banks','nibbles']else int(v)for k,v in re.findall(r'(\w+)=([0-9a-f]+)',line)}
  assert entry['coverage'][role][stage]==parsed
  for v in parsed.values():integer(v)
  return parsed
 generic=counters('logical','sprite_run','SPR_NONZERO_DATA_PASS')
 for key,floor in {'comparisons':110766,'defined_bits':23703444,'packet_checks':512,'raw_busy_checks':512,'command_reads':10,'command_writes':8,'ready_checks':221532,'async_resets':50}.items():integer(generic[key],floor)
 flag_log=(proof_paths['logical'].parent/'sprite_run.log').read_text();match=re.search(r'SPR_NONZERO_FLAGS checks=(\d+)',flag_log);assert match and int(match[1])>=443064
 for role,stage in [('logical','blitter_run'),('mapped_blitter','physical')]:
  c=counters(role,stage,'PASS sprite_blitter_groups')
  integer(c['checks'],402114);assert c['banks']==0xffffffff and c['nibbles']==15
  for k in ['emissions','transparent','holes','shadowed','stalled']:integer(c[k],1)
 t=counters('logical','truth_run','SPR_NONZERO_TRUTH_PASS');assert t['checks']==524288
 mirror=counters('mapped_mirror','physical','SPR_NONZERO_PHYSICAL_PASS')
 for k,n in {'checks':42573,'defined_bits':2724480,'nz_checks':681120,'collisions':10940,'equal_writes':1920}.items():integer(mirror[k],n)
 for variant in ['before','after']:
  v=proofs['mapped_structure']['variants'][variant];assert not v['missing_frontiers']and not v['unknown_in_target_cones']
 for role,archived in entry['archive_receipts'].items():assert role in ['prior_sprite_ready','prior_BT_compose']and path(archived).read_bytes()==proof_paths[role].read_bytes()
 assert set(entry['archive_receipts'])=={'prior_sprite_ready','prior_BT_compose'}
 ready=proofs['prior_sprite_ready'];assert ready['candidate_sha256']==SPR_NZ_BEFORE['rtl/spr_vram.sv']and ready['original_sha256']=='12e1c52b6b80351fdff6ea351f637f101f9f7299638a60acf9b8e3c8949913b0'
 for key in ['compile_exit_code','run_exit_code','exit_code']:zero(ready[key])
 for flag in ['generator_transformation_replayed','unchanged_main_memory_and_data_processes_passed','hardware_equivalence_passed','full_output_equivalence_passed','same_edge_completion_equivalence_passed','mapped_control_equivalence_passed','sequential_dependency_closure_passed','sprite_packet_passed','sprite_read_passed','mapped_board_ready_composition_passed']:truth(ready[flag])
 assert len(ready['sources'])>=52 and ready['coverage']['generic']['defined_bits']>=23703444 and ready['coverage']['mapped_control']['defined_bits']>=442952
 closure=ready['closure'];truth(closure['sequential_dependency_closure_passed']);truth(closure['literal_instances_and_defparams_preserved'])
 assert closure['unknown_count']==closure['unresolved_count']==0 and closure['internal_state_substitution']is False and closure['atom_count']>=78
 board=proofs['prior_BT_compose'];assert board['candidate_BT_sha256']==SPR_NZ_BEFORE['rtl/BT.sv']and board['SPR_candidate_sha256']==SPR_NZ_BEFORE['rtl/spr_vram.sv']
 for key in ['compile_exit_code','run_exit_code','exit_code']:zero(board[key])
 truth(board['equivalence_passed']);integer(board['checks'],8192)
 return True

p=argparse.ArgumentParser()
p.add_argument('snapshot',type=Path)
a=p.parse_args()
root=Path(__file__).resolve().parents[2]
snapshot=a.snapshot.resolve()
failures=[]
def require(condition,message):
    if not condition:failures.append(message)
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
fit=snapshot/'output_files/Arcade-Battletoads.fit.summary'
require(fit.exists() and 'Fitter Status : Successful' in fit.read_text(),'fitter did not succeed')
timing=json.loads((snapshot/'timing_receipt.json').read_text())
require(timing['exit_code']==0,'all-corner audit failed')
require(not timing['provisional_constraints'],'provisional constraints cannot authorize assembly')
for name,digest in timing['audit_sources'].items():
    require(sha(Path(name))==digest,'timing audit source changed: '+name)
with (snapshot/'timing_audit/slacks.tsv').open() as f:
    rows=list(csv.DictReader(f,delimiter='\t'))
corners={row['corner'] for row in rows}
require(len(corners)==8,'expected all eight Cyclone V timing models')
require(held_capture_reports_verified(snapshot,corners),
        'held-word capture endpoints, ordinary6.25ns relationship, or timing failed')
with (snapshot/'timing_audit/models.tsv').open() as f:
    models=list(csv.DictReader(f,delimiter='\t'))
require(len(models)==8 and {r['corner'] for r in models}==corners,
        'operating-condition inventory does not match analyzed corners')
worst={}
coverage={}
intentional_hps_roots={'sysmem_lite:sysmem','spi','h2f_gp','hdmi_i2c'}
consistency_checks={'generated_clock','uncertainty','partial_multicycle',
                    'multicycle_consistency','partial_min_max_delay',
                    'io_min_max_delay_consistency','partial_input_delay',
                    'partial_output_delay'}
video_mux_node=re.compile(r'^(?:hdmi_out_(?:vs|hs|de|d\[\d+\])(?:~.*)?|'
                          r'hdmi_dv_(?:vs|hs|de|data\[\d+\])|'
                          r'vs|hs|de|d\[\d+\]|altddio_out:(?:hdmiclk|vgaclk)_ddr\|.*)$')
# These are analogue/indicator pins, clock outputs, or unchanged MiSTer
# platform bus boundaries. HDMI/SDRAM data pins never enter these allowances.
# Dispositions and limits are recorded in docs/TIMING_INTERFACES.md.
async_input_port=re.compile(r'^(?:BTN_(?:OSD|RESET|USER)|VGA_EN|SW\[[0-3]\]|'
                            r'KEY\[[01]\]|IO_SDA|HDMI_TX_INT|HDMI_I2C_SDA|SDCD_SPDIF)$')
async_output_port=re.compile(r'^(?:IO_SDA|IO_SCL|HDMI_I2C_(?:SDA|SCL)|'
                             r'VGA_[RGB]\[[0-5]\]|VGA_[HV]S|AUDIO_[LR]|AUDIO_SPDIF|'
                             r'SDCD_SPDIF|SDIO_(?:CLK|CMD|DAT\[[0-3]\])|SD_SPI_(?:CS|CLK|MOSI)|'
                             r'ADC_(?:SCK|SDI|CONVST)|USER_IO\[[0-6]\]|LED\[[0-7]\]|'
                             r'LED_(?:HDD|POWER|USER)|HDMI_MCLK|HDMI_TX_CLK|HDMI_SCLK|SDRAM_CLK)$')
constraint_reports=list((snapshot/'timing_audit').glob('*_constraints.rpt'))
require(len(constraint_reports)==8,'constraint coverage missing a corner')
for report in constraint_reports:
    table=[line.split(';')[1:-1] for line in report.read_text(errors='replace').splitlines()
           if line.startswith(';')]
    no_clock=[row[0].strip() for row in table
              if len(row)>1 and 'No clock feeds' in row[1]]
    unexpected=[name for name in no_clock
                if name.split('|')[0].split('~')[0] not in intentional_hps_roots]
    require(not unexpected,'unclocked fabric nodes: '+report.name+' '+str(unexpected[:3]))
    summary={row[0].strip():int(row[1]) for row in table
             if len(row)==2 and row[0].strip() in consistency_checks}
    require(set(summary)==consistency_checks,'missing constraint checks: '+report.name)
    require(not any(summary.values()),'inconsistent constraints: '+report.name+' '+str(summary))
    multiple=[row[0].strip() for row in table
              if len(row)>1 and 'More than one clock feeds' in row[1]]
    unreviewed_multiple=[name for name in multiple if not video_mux_node.fullmatch(name)]
    require(not unreviewed_multiple,'unreviewed multiple-clock nodes: '+report.name+
            ' '+str(unreviewed_multiple[:3]))
    missing_input=[r[0].strip() for r in table if len(r)>1 and 'No input delay was set' in r[1]]
    missing_output=[r[0].strip() for r in table if len(r)>1 and 'No output delay was set' in r[1]]
    require(all(async_input_port.fullmatch(n) for n in missing_input),
            'unreviewed input boundary: '+report.name+' '+str([n for n in missing_input if not async_input_port.fullmatch(n)]))
    require(all(async_output_port.fullmatch(n) for n in missing_output),
            'unreviewed output boundary: '+report.name+' '+str([n for n in missing_output if not async_output_port.fullmatch(n)]))
    coverage[report.name]={'unclocked_hps_nodes':len(no_clock),
                           'unexpected_unclocked_nodes':unexpected,
                           'consistency_issues':summary,
                           'exclusive_video_mux_nodes':len(multiple),
                           'unexpected_multiple_clock_nodes':unreviewed_multiple,
                           'intentional_async_inputs':missing_input,
                           'intentional_async_or_clock_outputs':missing_output}
for kind in ('setup','hold','recovery','removal'):
    selected=[r for r in rows if r['analysis']==kind]
    require(len(selected)==8,kind+' missing a corner')
    require({r['corner'] for r in selected}==corners,kind+' corner coverage incomplete')
    require(all(r['slack_ns']!='N/A' for r in selected),kind+' has no checked paths')
    values=[float(r['slack_ns']) for r in selected if r['slack_ns']!='N/A']
    if values:
        worst[kind]=min(values)
        require(min(values)>=0,kind+' has negative slack: '+str(min(values)))
pulse=[]
for report in (snapshot/'timing_audit').glob('*_pulse_width.rpt'):
    m=re.search(r'Worst case slack is\s+(-?[\d.]+)',report.read_text())
    require(m is not None,'pulse-width slack not reported: '+report.name)
    if m:pulse.append(float(m.group(1)))
require(len(pulse)==8,'pulse-width checks missing a corner')
reported_pulse=[r for r in rows if r['analysis']=='pulse_width']
require(len(reported_pulse)==8 and {r['corner'] for r in reported_pulse}==corners,
        'pulse-width corner coverage incomplete')
if pulse:
    worst['pulse_width']=min(pulse)
    require(min(pulse)>=0,'pulse-width failure')
clocks=(snapshot/'timing_audit/clocks.rpt').read_text()
require('bt_hdmi_native' in clocks and 'bt_hdmi_scaled' in clocks,'forwarded HDMI clocks missing')
for name in ('bt_sdram_clk','bt_audio_sclk_internal','bt_hdmi_i2s','bt_hdmi_mclk'):
    require(name in clocks,'forwarded I/O clock missing: '+name)
io_slack={}
for interface in ('sdram_input','sdram_output','hdmi_video','hdmi_audio'):
    for kind in ('setup','hold'):
        reports=list((snapshot/'timing_audit').glob('*_'+interface+'_'+kind+'.rpt'))
        require(len(reports)==8,interface+' '+kind+' missing a corner')
        values=[]
        for report in reports:
            m=re.search(r'Found (\d+) '+kind+r' paths .*?Worst case slack is\s+(-?[\d.]+)',
                        report.read_text(errors='replace'))
            expected={'sdram_input':16,'sdram_output':34,'hdmi_video':54,'hdmi_audio':2}[interface]
            require(m is not None and int(m[1])==expected,'missing I/O paths: '+report.name)
            if m:values.append(float(m[2]))
        if values:
            io_slack[interface+'_'+kind]=min(values)
            require(min(values)>=0,'I/O timing failed: '+interface+' '+kind+' '+str(min(values)))
phase_proofs={}
for case,needed in (('audio',('sys/audio_out.sv','sys/i2s.v','rtl/bt_audio_io.sdc','tests/hdmi_audio_phase_tb.sv')),
                    ('sdram',('rtl/sdram.sv','rtl/pll.v','rtl/pll/pll_0002.v',
                              'rtl/bt_sdram_io.sdc','tests/sdram_phase_tb.sv')),
                    ('cpu_fields',('rtl/TMS34020/TMS34020_MC.sv','rtl/TMS34020/TMS34020_pkg.sv',
                                   'tests/cpu_field_timing_tb.sv')),
                    ('ddr_tags',('rtl/bt_ddr_tag_compare.sv','tests/ddr_tag_compare_ref.sv','tests/ddr_tag_compare_tb.sv')),
                    ('cpu_opcodes',('rtl/TMS34020/TMS34020_ID.sv','rtl/TMS34020/TMS34020_PKG.sv',
                                    'rtl/TMS34020/TMS34020.sv','rtl/bt_cpu_phase.sdc',
                                    'tests/cpu_opcode_equivalence_tb.sv','tests/graphics/predecode_opcode.py'))):
    matched=[]
    for receipt in (root/'tests/graphics/evidence/io-phase').glob('io-'+case+'-*/receipt.json'):
        proof=json.loads(receipt.read_text())
        if proof['exit_code']==0 and all(proof['sources'].get(name)==sha(root/name) for name in needed):
            matched.append(str(receipt))
    require(bool(matched),'I/O phase proof missing or stale: '+case)
    phase_proofs[case]=matched
functional_proofs={}
ddr_current={}
for kind,prefix in (('controller','ddr-request-predecode-'),('boundary','ddr-boundary-')):
    matched=[]
    for receipt in (root/'build/resource_audit/ddr-request-predecode/evidence').glob(prefix+'*/receipt.json'):
        proof=json.loads(receipt.read_text())
        if ddr_request_verified(proof,receipt,root,kind):matched.append(str(receipt))
    require(bool(matched),'current DDR request proof missing or stale: '+kind)
    functional_proofs['ddr-request-'+kind]=matched
    ddr_current[kind]=bool(matched)
ddr_previous_aliases={'rtl/ddram.sv':'build/resource_audit/ddr-request-predecode/reference_ddram.sv'} if ddr_current['controller'] else {}
cpu_rf_receipt=root/'build/resource_audit/rf_flat_write_experiment/current_receipt.json'
cpu_rf_proof=json.loads(cpu_rf_receipt.read_text())if cpu_rf_receipt.is_file()else{}
cpu_rf_verified=cpu_flat_rf_verified(cpu_rf_proof,root)
require(cpu_rf_verified,'CPU flat RF write preservation proof missing or stale')
functional_proofs['cpu-rf-flat']=[str(cpu_rf_receipt)]if cpu_rf_verified else []
cpu_before_aliases={'rtl/TMS34020/TMS34020.sv':cpu_rf_proof['before_source']['path']}if cpu_rf_verified else {}
hole_receipt=root/'build/fg_ready_next_experiment/final_hole_a5/receipt.json'
hole_proof=json.loads(hole_receipt.read_text())if hole_receipt.is_file()else{}
hole_verified=fg_hole_address_promotion_verified(hole_proof,root)
require(hole_verified,'FG same-edge hole read/address-bit5 preservation proof failed')
functional_proofs['fg-hole-a5']=[str(hole_receipt)]if hole_verified else []
ready_receipt=root/hole_proof['previous_ready_transform_receipt']if hole_verified else root/'build/fg_ready_next_experiment/final_1d31/receipt.json'
ready_proof=json.loads(ready_receipt.read_text())if ready_receipt.is_file()else{}
ready_aliases={k:v['path']for k,v in hole_proof['qualified_source_sets']['ready'].items()}if hole_verified else {}
ready_verified=hole_verified and fg_same_edge_ready_verified(ready_proof,root,ready_aliases)
require(ready_verified,'FG same-edge ready preservation and archived RAM proof chain failed')
sprite_snapshot_hashes=json.loads((snapshot/'snapshot.json').read_text())
nonzero_matched=[];nonzero_proof={}
for receipt in (root/'tests/graphics/evidence/sprite-nonzero').glob('sprite-nonzero-*/receipt.json'):
    proof=json.loads(receipt.read_text())
    if sprite_nonzero_verified(proof,sprite_snapshot_hashes,root):
        nonzero_matched.append(str(receipt));nonzero_proof=proof
nonzero_verified=bool(nonzero_matched)
require(nonzero_verified,'SPR nonzero physical mirror/blitter and literal board transformation proof failed')
functional_proofs['sprite-nonzero']=nonzero_matched
sprite_history=nonzero_proof.get('historical_aliases',{})if nonzero_verified else {}
spr_ready_receipt=root/nonzero_proof['proof_receipts']['prior_sprite_ready']['path']if nonzero_verified else root/'build/spr_ready_experiment/final_eb3/receipt.json'
spr_ready_proof=json.loads(spr_ready_receipt.read_text())if spr_ready_receipt.is_file()else{}
spr_ready_verified=nonzero_verified and sprite_same_edge_ready_verified(spr_ready_proof,root,sprite_history)
require(spr_ready_verified,'SPR same-edge ready closed Intel control/full-output proof failed')
functional_proofs['sprite-ready']=[str(spr_ready_receipt)]if spr_ready_verified else []
bt_ready_receipt=root/nonzero_proof['proof_receipts']['prior_BT_compose']['path']if nonzero_verified else root/'build/resource_audit/bt-sprite-ready/receipt.json'
bt_ready_proof=json.loads(bt_ready_receipt.read_text())if bt_ready_receipt.is_file()else{}
bt_ready_verified=spr_ready_verified and bt_sprite_ready_verified(bt_ready_proof,root,sprite_history)
require(bt_ready_verified,'BT sprite-ready board composition proof missing or stale')
functional_proofs['bt-sprite-ready']=[str(bt_ready_receipt)]if bt_ready_verified else []
profile_receipt=root/'build/resource_audit/ddr-no-enable/receipt.json'
profile_aliases={'rtl/ddram.sv':'build/resource_audit/before/ready-cpu-batch-d57d9907e99d4baebbbed9925215b408/rtl/ddram.sv'}
if ready_verified:profile_aliases['rtl/fg_vram.sv']=ready_proof['canonical_before_copies']['rtl/fg_vram.sv']
if bt_ready_verified:profile_aliases['rtl/BT.sv']='build/resource_audit/bt-sprite-ready/reference_BT.sv'
lanes_receipt=root/'build/resource_audit/ddr-return-lanes-v2/final/receipt.json'
lanes_proof=json.loads(lanes_receipt.read_text())if lanes_receipt.is_file()else{}
lanes_verified=(ready_verified and bt_ready_verified and ddr_lane_replicas_verified(lanes_proof,root,profile_aliases,
                 {'rtl/BT.sv':sprite_history['rtl/BT.sv']}))
require(lanes_verified,'DDR return lane-selector exact reconstruction, MAP and all-cycle proof failed')
functional_proofs['ddr-return-lanes']=[str(lanes_receipt)]if lanes_verified else []
profile_verified=(lanes_verified and profile_receipt.is_file()and
                  ddr_selector_profile_verified(json.loads(profile_receipt.read_text()),root,profile_aliases,lanes_proof['before_source']))
require(profile_verified,'DDR selector attribute-only mapped profile proof failed')
functional_proofs['ddr-selector-profile']=[str(profile_receipt)]if profile_verified else []
mirror_receipt=root/'build/resource_audit/mc_be_mirror_experiment/receipt.json'
mirror_verified=cpu_rf_verified and mirror_receipt.is_file()and mc_write_mirrors_verified(json.loads(mirror_receipt.read_text()),root,cpu_before_aliases)
require(mirror_verified,'MC scalar byte-enable mirror proof missing or stale')
functional_proofs['mc-write-mirrors']=[str(mirror_receipt)]if mirror_verified else []
for family,prefix,needed in (
        ('native','native-',tuple(str(f.relative_to(root)) for f in (root/'rtl').rglob('*') if f.is_file())+
         ('Arcade-Battletoads.sv','tests/graphics/native_sim.sv','tests/graphics/ram_models.sv','tests/graphics/native.cpp','tests/graphics/native_run.py')),
        ('ddram-cache','ddram-cache-',('rtl/ddram.sv','tests/ddram_cache_tb.sv')),
        ('ddr-arbiter','ddr-arbiter-',('rtl/ddram.sv','rtl/bt_video_ddr.sv',
            'build/resource_audit/prepare_ddr_arbiter.py','build/resource_audit/qualify_ddr_arbiter.py',
            'build/resource_audit/ddr_decode_truth.py','build/resource_audit/ddr_full_busy_truth.py',
            'build/resource_audit/prepare_ddr_fast_requests.py','build/resource_audit/ddr-arbiter/ddram.sv',
            'build/resource_audit/ddr-arbiter/reference_ddram.sv',
            'build/resource_audit/ddr-arbiter/bt_video_ddr.sv',
            'build/resource_audit/ddr-arbiter/reference_bt_video_ddr.sv',
            'tests/ddram_cache_tb.sv','tests/rotation_ddr_tb.sv',
            'build/resource_audit/video_arbiter_equivalence_tb.sv')),
        ('sprite-packet','sprite-packet-',('rtl/spr_vram.sv','tests/sprite_packet_tb.sv','tests/graphics/ram_models.sv')),
        ('sprite-page','sprite-page-',('rtl/sprite_blitter.sv','tests/sprite_page_equivalence_tb.sv','tests/graphics/qualify_sprite_page.py')),
        ('sprite-read','sprite-read-',('rtl/spr_vram.sv','rtl/BT_mem.sv','tests/sprite_read_equivalence_tb.sv','tests/graphics/ram_models.sv','tests/graphics/qualify_sprite_read.py')),
        ('foreground-read','foreground-read-',('rtl/fg_vram.sv','rtl/BT_mem.sv','tests/foreground_read_equivalence_tb.sv','tests/graphics/ram_models.sv','tests/graphics/qualify_foreground_read.py')),
        ('foreground-ddr','foreground-ddr-',('rtl/fg_vram.sv','rtl/ddram.sv','rtl/bt_fg_ddr_clear.sv','tests/graphics/ram_models.sv','tests/foreground_ddr_tb.sv')),
        ('bt-fg-bridge','bt-fg-bridge-',('rtl/BT.sv','rtl/bg_vram.sv','rtl/fg_vram.sv',
            'rtl/spr_vram.sv','rtl/sprite_blitter.sv','tests/graphics/ram_models.sv',
            'tests/graphics/graphics_sim.sv','tests/bt_foreground_bridge_tb.sv',
            'tests/graphics/qualify_bt_foreground_bridge.py')),
        ('ddr-be-bridge','ddr-be-bridge-',('rtl/BT.sv','rtl/TMS34020/TMS34020.sv',
            'rtl/TMS34020/TMS34020_MC.sv','rtl/TMS34020/TMS34020_CACHE.sv',
            'rtl/TMS34020/TMS34020_pkg.sv','rtl/TMS34020_mem.sv','rtl/BT_mem.sv','rtl/bg_vram.sv',
            'rtl/fg_vram.sv','rtl/spr_vram.sv','rtl/sprite_blitter.sv','tests/graphics/ram_models.sv',
            'rtl/ddram.sv','Arcade-Battletoads.sv','tests/graphics/graphics_sim.sv',
            'build/resource_audit/mc_word_bridge_tb.sv','build/resource_audit/qualify_mc_word_bridge.py',
            'build/resource_audit/ddr_split_bridge_tb.sv','build/resource_audit/qualify_ddr_split_bridge.py',
            'build/resource_audit/prepare_ddr_split_bridge.py',
            'build/resource_audit/ddr_be_bridge_tb.sv','build/resource_audit/qualify_ddr_be_bridge.py',
            'build/resource_audit/prepare_ddr_be_bridge.py',
            'build/resource_audit/ddr_return_split/MC_MEM_RETURN_STAGE.svh')),
        ('mc-pause','mc-pause-',('rtl/TMS34020/TMS34020_MC.sv','rtl/TMS34020/TMS34020_pkg.sv',
            'rtl/bt_clock_enables.sv','tests/tms_memory_tb.sv',
            'build/resource_audit/qualify_mc_pause_equivalence.py',
            'build/resource_audit/pause_mc_candidate.sv','build/resource_audit/pause_mc_reference.sv'))):
    matched=[]
    for receipt in (root/'tests/graphics/evidence'/family).glob(prefix+'*/receipt.json'):
        proof=json.loads(receipt.read_text())
        proof_sources={n.replace('\\','/'):digest for n,digest in proof['sources'].items()}
        aliases=ddr_previous_aliases if family=='ddr-arbiter' else {}
        if type(proof.get('exit_code'))is int and proof['exit_code']==0 and all(proof_sources.get(n.replace('\\','/'))==sha(root/aliases.get(n,n)) for n in needed):
            if family=='bt-fg-bridge' and not (
                    proof.get('compile_exit_code')==0 and proof.get('run_exit_code')==0 and
                    proof.get('testbench_passed') is True):
                continue
            if family=='ddr-arbiter' and not (
                    type(proof.get('exit_code')) is int and proof['exit_code']==0 and
                    proof.get('cycle_equivalence_passed') is True and
                    proof.get('truth_cases',{}).get('busy_flag_truth_cases',0)>=65536 and
                    proof.get('truth_cases',{}).get('complete_busy_truth_cases',0)>=4194304 and
                    proof.get('truth_cases',{}).get('video_payload_truth_cases',0)>=1024 and
                    all(source_bound_run_verified({**proof,**proof.get('results',{}).get(case,{})},
                        needed,root,('cycle_equivalence_passed',),aliases) for case in ('ddram','video'))):
                continue
            if family=='ddr-be-bridge' and not ddr_be_bridge_verified(proof,needed,root):
                continue
            if family=='mc-pause' and not (
                    source_bound_run_verified(proof,needed,root,('normal_cycle_equivalence_passed',)) and
                    retained_inputs_bound(proof,'tests/graphics/evidence/mc-pause/mc-pause-',
                        ('TMS34020_pkg.sv','bt_clock_enables.sv','TMS34020_MC.sv','baseline.sv','tms_memory_tb.sv'))):
                continue
            native_commands=' '.join(' '.join(map(str,c)) for c in proof.get('commands',[]))
            if family!='native' or (proof.get('requested_frames',0)>=128 and
                    '-DMISTER_CPU_PHASE_CHECK=1' in native_commands and
                    '-DMISTER_ALU_PIPE_CHECK=1' in native_commands):
                matched.append(str(receipt))
    require(bool(matched),'functional/phase proof missing or stale: '+family)
    functional_proofs[family]=matched
hardware_proofs={}
for label,pattern,needed in (
        ('hq2x_tails','hq2x_mlab_tail/receipt.json',('sys/hq2x.sv','tests/hq2x_buf_split_tb.sv')),
        ('bsmt_rom','bsmt_rom_slices/receipt.json',('rtl/TMS320C1X_mem.sv','rtl/bsmt2000.mif',
            'rtl/bsmt2000_slice0.mif','rtl/bsmt2000_slice1.mif','rtl/bsmt2000_slice2.mif',
            'rtl/bsmt2000_slice3.mif','scripts/generate_bsmt_rom_slices.py','tests/bsmt_rom_slice_tb.sv')),
        ('foreground_banks','vram-physical/vram-banks-*/receipt.json',('rtl/fg_vram.sv',
            'rtl/BT_mem.sv','tests/graphics/ram_models.sv','tests/vram_slice_tb.sv')),
        ('cache_packing','cache-packing/cache-packing-*/receipt.json',
            ('rtl/TMS34020/TMS34020_CACHE.sv','rtl/TMS34020/TMS34020_pkg.sv',
             'rtl/TMS34020_mem.sv','build/resource_audit/cache_packing_ddr_split.py',
             'build/resource_audit/publish_cache_split_receipt.py',
             'build/resource_audit/ddr_return_split/TMS34020_CACHE.sv'))):
    matched=[]
    for receipt in (root/'tests/graphics/evidence').glob(pattern):
        proof=json.loads(receipt.read_text())
        sources={n.replace('\\','/'):digest.lower() for n,digest in proof.get('sources',{}).items()}
        if (proof.get('exit_code')==0 and proof.get('hardware_equivalence_passed') is True and
                all(sources.get(n)==sha(root/n) for n in needed)):
            if label=='cache_packing' and not cache_split_verified(proof,needed,root):
                continue
            matched.append(str(receipt))
    require(bool(matched),'hardware storage proof missing or stale: '+label)
    hardware_proofs[label]=matched
bank_receipt=root/ready_proof['previous_bank_predecode_receipt']['path']if ready_verified else root/'build/fg_porta_wren_experiment/receipt.json'
bank_proof=json.loads(bank_receipt.read_text())if bank_receipt.is_file()else{}
qa_verified=ready_verified
require(qa_verified,'FG bank write-predecode hardware geometry or archived QA chain failed')
hardware_proofs['fg_bank_write_predecode']=[str(bank_receipt)]if qa_verified else []
hardware_proofs['fg_same_edge_ready']=[str(ready_receipt)]if ready_verified else []
hardware_proofs['fg_hole_address_bit5']=[str(hole_receipt)]if hole_verified else []
qa_receipt=root/bank_proof['previous_postmux_receipt']['path']if qa_verified else root/'build/fg_porta_wren_experiment/before_exact_postmux_receipt.json'
qa_proof=json.loads(qa_receipt.read_text())if qa_verified else {}
hardware_proofs['qa_output_registers']=[str(qa_receipt)]if qa_verified else []
clock_matched=[]
for receipt in (root/'build/resource_audit/ddr_return_split/evidence').glob('clock-predicate-*/receipt.json'):
    proof=json.loads(receipt.read_text())
    if clock_predicate_verified(proof,receipt,root):clock_matched.append(str(receipt))
require(bool(clock_matched),'CPU clock predicate waveform proof missing, failed, or stale')
phase_proofs['cpu_clocks']=clock_matched
serial_receipt=root/'build/fg_serial_wren_experiment/receipt.json'
serial_verified=(serial_receipt.is_file() and
                 qa_verified and fg_serial_write_segment_verified(json.loads(serial_receipt.read_text()),root,
                     qa_proof.get('canonical_before_copies',{})) and
                 sha(serial_receipt)==qa_proof.get('previous_serial_receipt',{}).get('sha256'))
require(serial_verified,'FG serial write-segment hardware proof missing, failed, or stale')
hardware_proofs['fg_serial_write_segments']=[str(serial_receipt)] if serial_verified else []
native_comparisons=[]
for receipt in functional_proofs.get('native',[]):
    comparison=Path(receipt).parent/'raster_comparison.json'
    if not comparison.exists():continue
    if native_raster_verified(Path(receipt),comparison,root):
        native_comparisons.append(str(comparison))
require(bool(native_comparisons),'source-matching native raster preservation proof missing')
manifest=json.loads((snapshot/'snapshot.json').read_text())
for name,digest in manifest.items():
    # Quartus exports sourced pin/settings assignments into the fitted QSF.
    # Bind that tool-expanded file separately and keep the original input hash
    # for the workspace QSF; all sourced QIPs/RTL/SDCs remain hash-checked.
    target_digest=(timing.get('fitted_project_sha256')
                   if name=='Arcade-Battletoads.qsf' else digest)
    require(target_digest is not None and (snapshot/name).exists() and
            sha(snapshot/name)==target_digest,'fitted source changed: '+name)
    if name!='build_id.v':
        require((root/name).exists() and sha(root/name)==digest,'workspace differs from fit: '+name)
result={'snapshot':str(snapshot),'corners':len(corners),'worst_slack_ns':worst,
        'io_worst_slack_ns':io_slack,'io_phase_proofs':phase_proofs,
        'functional_proofs':functional_proofs,'hardware_storage_proofs':hardware_proofs,
        'native_raster_preservation':native_comparisons,
        'clock_coverage':coverage,
        'source_manifest_sha256':sha(snapshot/'snapshot.json'),
        'timing_receipt_sha256':sha(snapshot/'timing_receipt.json'),
        'eligible_for_rbf':not failures,'failures':failures,
        'scope':'configured clocks, all eight models; existing asynchronous/HPS I/O exceptions '
                'must remain documented; runtime PLL modes need their own frequency qualification'}
(snapshot/'rbf_gate.json').write_text(json.dumps(result,indent=2))
retained=root/'tests/graphics/evidence/quartus'/snapshot.name
retained.mkdir(parents=True,exist_ok=True)
(retained/'rbf_gate.json').write_text(json.dumps(result,indent=2))
print(json.dumps({'corners':len(corners),'worst_slack_ns':worst,'eligible_for_rbf':not failures,
                  'failure_count':len(failures),'failures':failures[:8]},indent=2))
sys.exit(bool(failures))
