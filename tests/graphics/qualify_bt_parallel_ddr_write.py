#!/usr/bin/env python3
"""Actual same-edge DDR source capture versus immutable full-controller oracle."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid

from prepare_bt_parallel_ddr_write import ROOT, BASE
from verify_bt_current_qualification import git_blob, REF, parse_read_coverage

def sha(data):
    return hashlib.sha256(data).hexdigest()

def wsl(path):
    path=Path(path).resolve()
    return '/mnt/'+path.drive[0].lower()+path.as_posix()[2:]

def main(candidate, output, prepare_only):
    assert candidate.is_relative_to(ROOT/'build') and not output.exists()
    output.mkdir(parents=True)
    transform=json.loads((candidate.parent/'manifest.json').read_text())
    assert transform['base_sources']==BASE and transform['status']=='PASS'
    source_names=['rtl/ddram.sv','rtl/BT.sv','Arcade-Battletoads.sv']
    data={name:(candidate/name).read_bytes() for name in source_names}
    assert {name:sha(raw) for name,raw in data.items()}==transform['candidate_sources']
    oracle=git_blob('rtl/ddram.sv')
    v9=(candidate.parent/'immutable_oracle/rtl/ddram.sv').read_bytes()
    assert sha(v9)==BASE['rtl/ddram.sv'] and oracle.replace(b'\r\n',b'\n')==v9.replace(b'\r\n',b'\n')
    bt=data['rtl/BT.sv'].decode().replace('\r\n','\n')
    top=data['Arcade-Battletoads.sv'].decode().replace('\r\n','\n')
    for text in ('.EDATA_CANDIDATES(bt_edata_candidates), .EDATA_SELECT(bt_edata_select)',
                 '.parallel_din(bt_edata_candidates), .parallel_din_sel(bt_edata_select)',
                 '.USE_PARALLEL_DIN(1)', '.din (BT_EDATA)', '.sclk(CE_R)',
                 '.io_din (fg_ddr_clear_active ? 32\'d0 : {2{rom_data}})', '.ESDATA(ddr_bin)'):
        assert text in top, 'Actual board binding changed: '+text
    begin=bt.index('\t// BT_PARALLEL_DDR_DATA_BEGIN')
    end=bt.index('\t// BT_PARALLEL_DDR_DATA_END',begin)+len('\t// BT_PARALLEL_DDR_DATA_END')
    legacy=re.search(r'\tassign EDATA = SPR_DDR_REQ.*?;',bt,re.S).group()
    producer='''module bt_parallel_ddr_source(
 input SPR_DDR_REQ, FG_HOLE_COPY, FG0_HOLE_SEL,
 input [7:0] SPR_DRAW_DATA, input [31:0] FG0_HOLE_DATA, FG1_HOLE_DATA, LDO,
 output [31:0] EDATA, output [3:0][31:0] EDATA_CANDIDATES, output [3:0] EDATA_SELECT);
'''+bt[begin:end]+'\n'+legacy+'\nendmodule\n'
    fixture=(ROOT/'tests/ddram_cache_tb.sv').read_bytes().decode().replace('\r\n','\n')
    extra=(ROOT/'tests/bt_parallel_ddr_write_extra.svh').read_text()
    original_instance=re.search(r'    ddram_baseline original\(.*?;',fixture,re.S).group()
    serial_instance=original_instance.replace('ddram_baseline original','ddram serial',1)
    serial_names=('q','busy','io_q','io_busy','burst_q','burst_pos','burst_tick','a','d','be','len','rd','wr')
    for name in serial_names:
        serial_instance=re.sub(r'\b'+name+r'1\b',name+'2',serial_instance)
    declarations='''    wire[31:0] q2,io_q2;wire busy2,io_busy2;
    wire[63:0] burst_q2,d2;wire[9:3] burst_pos2;wire burst_tick2;
    wire[28:0] a2;wire[7:0] be2,len2;wire rd2,wr2;
'''
    changes=[
        ('    ddram candidate(', '    ddram #(.USE_PARALLEL_DIN(1),.USE_PREDECODED_TAGS(1),.USE_PREDECODED_WE(1),.USE_PREDECODED_MISS(1)) candidate('),
        ('.dout(q0),.din(data),', '.dout(q0),.din(accepted_data),\n        .parallel_din(raw_sources),.parallel_din_sel(raw_owner),\n        .external_tag_hit(external_hits),.external_read_hit_part(external_miss_parts),.external_we_any(|write_be),'),
        ('.dout(q1),.din(data),', '.dout(q1),.din(accepted_data),'),
        ('    initial begin\n', declarations+'\n'+serial_instance.replace('.din(data)','.din(accepted_data)')+'\n'+extra+'\n    initial begin\n'),
        ('        if(writes<2048 || checks<2000)', '        parallel_extra();\n        if(writes<2048 || checks<2000)'),
    ]
    adapted=fixture
    for before,after in changes:
        assert adapted.count(before)==1, 'Immutable fixture anchor changed'
        adapted=adapted.replace(before,after,1)
    reversed_fixture=adapted
    for before,after in reversed(changes):
        assert reversed_fixture.count(after)==1
        reversed_fixture=reversed_fixture.replace(after,before,1)
    assert reversed_fixture==fixture
    files={'ddram.sv':data['rtl/ddram.sv'],
           'ddram_baseline.sv':oracle.replace(b'module ddram',b'module ddram_baseline',1),
           'bt_parallel_ddr_source.sv':producer.encode(),
           'ddram_cache_tb.sv':adapted.encode()}
    for name,raw in files.items():(output/name).write_bytes(raw)
    (output/'immutable_oracle_raw.sv').write_bytes(oracle)
    helpers=['tests/graphics/prepare_bt_parallel_ddr_write.py','tests/graphics/qualify_bt_parallel_ddr_write.py',
             'tests/bt_parallel_ddr_write_extra.svh','tests/ddram_cache_tb.sv']
    receipt={'schema':'bt-parallel-ddr-write-proof-v1','status':'PREPARED',
        'oracle_commit':REF,'oracle_git_file':'rtl/ddram.sv','oracle_sha256':sha(oracle),
        'v9_parent_sha256':BASE['rtl/ddram.sv'],'parent_body_identical_lf':True,
        'candidate_dir':str(candidate),'candidate_sources':{name:sha(raw) for name,raw in data.items()},
        'helper_sources':{name:sha((ROOT/name).read_bytes()) for name in helpers},
        'compiled_sources':{name:sha(raw) for name,raw in files.items()},
        'actual_bt_source_slice':sha(producer.encode()),'fixture_transformations':changes,
        'source_order':['sprite','foreground0','foreground1','cpu'],
        'scope':'Full original cache/DDR/64-bit-burst/I/O assertions; full-controller metadata/cache-state equality, exact actual BT acceptance and default-off interface. Behavioral simulation; physical timing remains separate.'}
    (output/'manifest.json').write_text(json.dumps(receipt,indent=2)+'\n')
    if prepare_only:
        print(json.dumps({'status':'PREPARED','manifest':str(output/'manifest.json')}));return
    run(output,receipt)

def run(output,receipt):
    assert receipt['status']=='PREPARED'
    candidate=Path(receipt['candidate_dir'])
    assert all(sha((candidate/name).read_bytes())==digest for name,digest in receipt['candidate_sources'].items())
    assert all(sha((ROOT/name).read_bytes())==digest for name,digest in receipt['helper_sources'].items())
    assert all(sha((output/name).read_bytes())==digest for name,digest in receipt['compiled_sources'].items())
    workspace=Path('R:/Verilator/BT')/('parallel-ddr-'+uuid.uuid4().hex)/'obj'
    workspace.mkdir(parents=True)
    build=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec','/usr/bin/verilator',
        '--binary','--assert','--timing','-Wno-fatal','-Wno-BLKANDNBLK','-j','2','--threads','1',
        '--top-module','ddram_cache_tb','--Mdir',wsl(workspace)]
    build += [wsl(output/name) for name in receipt['compiled_sources']]
    command=['wsl.exe','-d','Ubuntu','--cd',str(ROOT),'--exec',wsl(workspace/'Vddram_cache_tb')]
    receipt['commands']=[build,command]
    for kind,argv in [('compile',build),('run',command)]:
        print(kind+'=parallel-ddr',flush=True)
        with(output/(kind+'.log')).open('w') as log:
            result=subprocess.run(argv,stdout=log,stderr=subprocess.STDOUT,timeout=600)
        receipt[kind+'_exit_code']=result.returncode
        receipt[kind+'_log_sha256']=sha((output/(kind+'.log')).read_bytes())
        if result.returncode:
            receipt['status']='FAIL';(output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
            print((output/(kind+'.log')).read_text(errors='replace')[-5000:]);raise SystemExit(result.returncode)
    report=(output/'run.log').read_text()
    coverage=parse_read_coverage('ddram-cache',report)
    pattern=r'PARALLEL_DDR_PASS acceptance=(\d+) hold=(\d+) reset_blocks=(\d+) priority_collisions=(\d+) state_checks=(\d+) io_cpu=(\d+) fill_patch=(\d+) owners=(\d+),(\d+),(\d+),(\d+) owner_masks=60'
    match=re.search(pattern,report);assert match,'Missing full acceptance/controller coverage'
    names=['acceptance','hold','reset_blocks','priority_collisions','state_checks','io_cpu','fill_patch',
           'sprite','foreground0','foreground1','cpu']
    specific=dict(zip(names,map(int,match.groups())))
    assert all(specific[name]>0 for name in names if name!='fill_patch')
    receipt.update(status='PASS',coverage=coverage,parallel_coverage=specific,
                   owner_mask_cases=60,exact_fixture_restoration=True)
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'status':'PASS','receipt':str(output/'receipt.json'),'coverage':coverage,'parallel':specific}))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--candidate',type=Path,default=ROOT/'build/ddr_parallel_sources_v9_v2/candidate')
    parser.add_argument('--out',type=Path,default=ROOT/'build/ddr_parallel_sources_v9_v2/proof')
    parser.add_argument('--prepare-only',action='store_true')
    parser.add_argument('--run-prepared',type=Path)
    args=parser.parse_args()
    if args.run_prepared:
        manifest=args.run_prepared.resolve();run(manifest.parent,json.loads(manifest.read_text()))
    else:main(args.candidate.resolve(),args.out.resolve(),args.prepare_only)
