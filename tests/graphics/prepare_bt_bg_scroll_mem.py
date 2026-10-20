"""Guarded v23 background scroll adder relocation onto its existing MEM stage."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
PARENT=ROOT/'build/timing_closure_20261011/pixel_cpu_fg_v23_private'
PINS={'rtl/BT.sv':'49896ce904746ef65d03c63f38333e18dcdcf48550f092c35682073aaa956891',
      'rtl/bg_vram.sv':'b0080afc9ae4a5cc110058150f5cc710085e3394be20604524bfe443602ecd17'}
ADDRESS_STAGE='''\tbit  [15: 0] A_M;
\tgenerate
\t\tif (MEM_SCROLL_ADDER) begin : scroll_address_mem
\t\t\t// Capture raw operands on the original A_M edge. Four-state storage
\t\t\t// preserves unknown arithmetic until the original final bit boundary.
\t\t\t(* preserve, dont_merge *) reg [15:0] base_m = 16'd0;
\t\t\t(* preserve, dont_merge *) reg [15:0] offset_m = 16'd0;
\t\t\t(* preserve, dont_merge *) reg transfer_m = 1'b0;
\t\t\talways @(posedge CLK) begin
\t\t\t\tbase_m <= SCROLL_BASE;
\t\t\t\toffset_m <= SCROLL_OFFSET;
\t\t\t\ttransfer_m <= SCROLL_TRANSFER;
\t\t\tend
\t\t\twire [7:0] row_d = base_m[15:8] + offset_m[15:8];
\t\t\twire [7:0] col_d = base_m[7:0] + offset_m[7:0];
\t\t\talways_comb A_M = transfer_m ? {row_d,col_d} : {base_m[15:8],base_m[7:1],1'b0};
\t\tend else begin : unscrolled_address_input
\t\t\talways @(posedge CLK) A_M <= A;
\t\tend
\tendgenerate'''

def sha(data):return hashlib.sha256(data).hexdigest()
def require(value,message):
    if not value:raise AssertionError(message)
def text_bytes(text,newline):return text.replace('\n',newline).encode()

def operations(relative,parent):
    require(relative in PINS and sha(parent)==PINS[relative],'immutable v23 parent required')
    newline='\r\n' if b'\r\n' in parent else '\n'
    edits=[]
    def add(before,after,role):
        before=text_bytes(before,newline);after=text_bytes(after,newline)
        require(parent.count(before)==1,'unique original source anchor required: '+role)
        edits.append(dict(old=before.decode(),new=after.decode(),role=role))
    if relative=='rtl/bg_vram.sv':
        add('module BG_VRAM (','module BG_VRAM #(parameter MEM_SCROLL_ADDER = 0) (','default-off parameter')
        add('output bit     SQ_HIGH','output bit     SQ_HIGH,\ninput [15:0]   SCROLL_BASE,\ninput [15:0]   SCROLL_OFFSET,\ninput          SCROLL_TRANSFER','append operand ports after all original positions')
        add('\tbit  [15: 0] A_M;',ADDRESS_STAGE,'same-edge raw operand stage and original final bit conversion')
        add('\t\tA_M <= A;\n','', 'relocate only original A_M assignment into default-off branch')
    else:
        for bg in (0,1):
            for bank in (0,1):
                add(f'BG_VRAM BG{bg}_VRAM_{bank} (',f'BG_VRAM #(.MEM_SCROLL_ADDER(1)) BG{bg}_VRAM_{bank} (',f'BG{bg} bank{bank} activation')
                anchor=f'\t\t.SQ_HIGH(BG{bg}_SQ_HIGH[{bank}])'
                extra=anchor+f',\n\t\t.SCROLL_BASE({{LA[21:14],LA[11:4]}}),\n\t\t.SCROLL_OFFSET(SCROLL{bg}),\n\t\t.SCROLL_TRANSFER(LA[3:0] == 4\'b0100)'
                add(anchor,extra,f'BG{bg} bank{bank} exact original adder operands and four-state selector')
    return edits

def forward(data,edits):
    for item in edits:
        old=item['old'].encode();new=item['new'].encode()
        require(data.count(old)==1,'forward edge anchor changed: '+item['role']);data=data.replace(old,new,1)
    return data
def inverse(data,edits):
    for item in reversed(edits):
        old=item['old'].encode();new=item['new'].encode()
        if not new:
            # The removed assignment has a unique unchanged CPU-address anchor.
            anchor=b'\t\tCPU_A_M <= CPU_A;'
            require(data.count(anchor)==1,'original A_M assignment recovery anchor changed')
            data=data.replace(anchor,old+anchor,1)
        else:
            require(data.count(new)==1,'inverse edge anchor changed: '+item['role']);data=data.replace(new,old,1)
    return data

def transform(relative,parent):
    edits=operations(relative,parent);candidate=forward(parent,edits)
    require(inverse(candidate,edits)==parent,'whole raw-file inverse failed');return candidate,edits

def source_proof(relative,parent,candidate,edits):
    require(edits==operations(relative,parent) and forward(parent,edits)==candidate
            and inverse(candidate,edits)==parent,'complete declared source edge required')
    if relative=='rtl/bg_vram.sv':
        canonical=parent.decode().replace('\r\n','\n')
        expected=candidate.decode().replace('\r\n','\n')
        require(canonical.count('\t\tA_M <= A;')==1 and expected.count('A_M <= A;')==1,
                'original default-off capture must remain exact')
        require(expected.count('always @(posedge CLK) begin')==canonical.count('always @(posedge CLK) begin')+1,
                'one raw capture block only')
        require('base_m <= SCROLL_BASE;' in expected and 'offset_m <= SCROLL_OFFSET;' in expected
                and 'transfer_m <= SCROLL_TRANSFER;' in expected,'original edge must sample raw current inputs')
    return dict(relative=relative,parent_sha256=sha(parent),candidate_sha256=sha(candidate),raw_whole_file_inverse=True,
                original_capture_and_consumer_MEM_edges_unchanged=True,raw_XZ_before_final_bit_boundary_retained=True,
                old_A_M_initial_value=0,old_A_M_no_reset_behavior_retained=True)

def negatives(files):
    bg,bt=files['rtl/bg_vram.sv'],files['rtl/BT.sv'];checks=[]
    mutations=[('rtl/bg_vram.sv',b'reg [15:0] base_m',b'bit [15:0] base_m','early X/Z coercion'),
      ('rtl/bg_vram.sv',b'base_m <= SCROLL_BASE;',b'base_m <= A_M;','old-Q extra edge'),
      ('rtl/bg_vram.sv',b"base_m = 16'd0",b"base_m = 16'd1",'wrong initialized address'),
      ('rtl/bg_vram.sv',b'base_m[7:1]',b'base_m[6:0]','wrong ordinary column'),
      ('rtl/bg_vram.sv',b'offset_m[15:8]',b'offset_m[7:0]','wrong row offset'),
      ('rtl/bg_vram.sv',b'always @(posedge CLK) begin',b'always @(negedge CLK) begin','wrong MEM edge'),
      ('rtl/BT.sv',b'.SCROLL_OFFSET(SCROLL1)',b'.SCROLL_OFFSET(SCROLL0)','wrong bank scroll'),
      ('rtl/BT.sv',b'LA[3:0] == 4\'b0100',b'LA[3:0] == 4\'b0101','wrong raw selector')]
    for relative,old,new,name in mutations:
        data=files[relative];require(old in data,'negative control anchor absent');data=data.replace(old,new,1)
        parent=(PARENT/relative).read_bytes();edits=operations(relative,parent)
        try:source_proof(relative,parent,data,edits)
        except AssertionError:checks.append(dict(name=name,rejected=True))
        else:raise AssertionError('source mutation accepted: '+name)
    return checks

def verify_edge(directory):
    directory=Path(directory).resolve();m=json.loads((directory/'manifest.json').read_bytes())
    require(m['schema']=='bt-v23-bg-scroll-MEM-source-edge-v1' and m['status']=='PASS_SOURCE_EDGE','wrong source edge')
    require(m['helper_sha256']==sha(Path(__file__).read_bytes()),'executed source helper changed')
    files={}
    for relative,record in m['files'].items():
        parent=Path(record['parent']).read_bytes();candidate=Path(record['candidate']).read_bytes()
        require(sha(parent)==record['parent_sha256']==PINS[relative] and sha(candidate)==record['candidate_sha256'],
                'source bytes changed')
        require(source_proof(relative,parent,candidate,record['edits'])==record['source_proof'],'source induction changed')
        files[relative]=candidate
    require(set(files)==set(PINS) and negatives(files)==m['negative_controls'],'complete guarded source edge required')
    return files,m

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    out=args.output.resolve();require(not out.exists(),'exclusive new source edge required');out.mkdir(parents=True)
    files={};records={}
    for relative in PINS:
        path=PARENT/relative;parent=path.read_bytes();candidate,edits=transform(relative,parent)
        target=out/'candidate'/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(candidate)
        files[relative]=candidate;records[relative]=dict(parent=str(path),parent_sha256=sha(parent),candidate=str(target),
          candidate_sha256=sha(candidate),edits=edits,source_proof=source_proof(relative,parent,candidate,edits))
    helper=out/'executed-helpers'/Path(__file__).name;helper.parent.mkdir();helper.write_bytes(Path(__file__).read_bytes())
    manifest=dict(schema='bt-v23-bg-scroll-MEM-source-edge-v1',status='PASS_SOURCE_EDGE',
      helper_sha256=sha(Path(__file__).read_bytes()),executed_helper=dict(path=str(helper),sha256=sha(helper.read_bytes())),
      files=records,negative_controls=negatives(files),default_off_parameter='MEM_SCROLL_ADDER',
      activated_instances=['BG0_VRAM_0','BG0_VRAM_1','BG1_VRAM_0','BG1_VRAM_1'],logical_additional_FFs=68,
      old_consumer_edges_and_RAM_storage_unchanged=True,physical_placement_or_timing_claim=False)
    target=out/'manifest.json';target.write_text(json.dumps(manifest,indent=2)+'\n');verify_edge(out)
    print(json.dumps(dict(status=manifest['status'],manifest=str(target),sha256=sha(target.read_bytes()),
                         sources={relative:sha(data) for relative,data in files.items()})))
if __name__=='__main__':main()
