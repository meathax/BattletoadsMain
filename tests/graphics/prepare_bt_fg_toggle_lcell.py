"""Guarded private first-MEM-stage foreground toggle LCELL transform."""
from pathlib import Path
import argparse
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
FG = 'rtl/fg_vram.sv'
PARENT_SHA = '15ca6106299cebaa05e7651b340c4c908b692385af89a75498bf0d60674cf6ae'
DECL = b'\tbit WRITE_TOGGLE_M;\r\n'
OLD_CAPTURE = b'\t\t\tWRITE_TOGGLE_M <= WRITE_TOGGLE;\r\n'
NEW_CAPTURE = b'\t\t\tWRITE_TOGGLE_M <= WRITE_TOGGLE_DELAY1;\r\n'
INSERT = (b'\t// Two kept identity cells delay only the first MEM capture data path.\r\n'
          b'\t// No register, clock edge, packet consumer or memory mode changes.\r\n'
          b'\t(* keep *) wire WRITE_TOGGLE_DELAY0, WRITE_TOGGLE_DELAY1;\r\n'
          b'\tlcell write_toggle_delay0(.in(WRITE_TOGGLE), .out(WRITE_TOGGLE_DELAY0));\r\n'
          b'\tlcell write_toggle_delay1(.in(WRITE_TOGGLE_DELAY0), .out(WRITE_TOGGLE_DELAY1));\r\n')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def transform(data):
    assert sha(data) == PARENT_SHA, 'Exact v18 foreground parent required'
    assert data.count(DECL) == 1 and data.count(OLD_CAPTURE) == 1
    assert b'WRITE_TOGGLE_DELAY' not in data
    candidate = data.replace(DECL, INSERT+DECL, 1).replace(OLD_CAPTURE, NEW_CAPTURE, 1)
    assert reverse(candidate) == data
    return candidate

def reverse(data):
    assert data.count(INSERT) == 1 and data.count(NEW_CAPTURE) == 1
    return data.replace(INSERT, b'', 1).replace(NEW_CAPTURE, OLD_CAPTURE, 1)

def verify_edge(directory):
    directory = Path(directory)
    manifest = json.loads((directory/'manifest.json').read_text())
    old = (directory/'oracle'/FG).read_bytes()
    new = (directory/'candidate'/FG).read_bytes()
    assert sha(old) == PARENT_SHA
    assert transform(old) == new and reverse(new) == old
    assert manifest['candidate_sha256'] == sha(new)
    assert manifest['parent_sha256'] == sha(old)
    assert manifest['helper_sha256'] == sha(Path(__file__).read_bytes())
    return old,new,manifest

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--parent-dir',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a = p.parse_args()
    assert not a.output.exists(), 'Output must be fresh'
    old = (a.parent_dir/FG).read_bytes()
    new = transform(old)
    for kind,data in (('oracle',old),('candidate',new)):
        target = a.output/kind/FG
        target.parent.mkdir(parents=True,exist_ok=True)
        target.write_bytes(data)
    manifest = {'schema':'bt-fg-first-mem-toggle-lcell-source-edge-v1',
                'parent_source_root':str(a.parent_dir.resolve()),'parent_sha256':sha(old),
                'candidate_sha256':sha(new),'candidate_lf_sha256':sha(new.replace(b'\r\n',b'\n')),
                'helper_sha256':sha(Path(__file__).read_bytes()),'full_file_byte_inverse':True,
                'changed_source_files':[FG],'cells':2,'keep_output_nets':True,
                'new_registers':0,'capture_cycle_changed':False,'reset_changed':False,
                'raw_toggle_other_consumers_unchanged':True,'qsf_sdc_clock_changes':0,
                'scope':'Source identity transform only. The original fitted setup/hold budget and actual retained-cell timing require separate native evidence.'}
    (a.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    verify_edge(a.output)
    print(json.dumps({'candidate':str(a.output/'candidate'/FG),'candidate_sha256':sha(new),
                      'manifest':str(a.output/'manifest.json'),'manifest_sha256':sha((a.output/'manifest.json').read_bytes())}))

if __name__ == '__main__':
    main()
