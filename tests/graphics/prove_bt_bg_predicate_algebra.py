"""Compiled four-state algebra closes the arbitrary word/mask source induction."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
QUALIFIER=ROOT/'tests/graphics/qualify_bt_bg_pixel_predicates.py'
QUALIFIER_SHA='fe020fa70b2a7ff2ec586d0990fe1c388b0b3123d3bf6d377928ed8fe7216305'
PROOF=ROOT/'build/bg_pixel_predicates_v22_v1/proof-r2/receipt.json'
PROOF_SHA='89b5703b84005df70c6cddb3a192078be9e2745a7919cc29f8ae34bbc81ed19c'
EDGE=ROOT/'build/bg_pixel_predicates_v22_v1/source-edge-r2'

BENCH=r'''module bt_bg_predicate_algebra_tb;
  function automatic logic four(input integer n);
    case(n) 0:four=0;1:four=1;2:four=1'bx;3:four=1'bz;endcase
  endfunction
  integer a,b,c,v,i,distribute=0,associate=0,commute=0,mask_bytes=0,coercions=0;
  integer wrong_or_mutant=0,wrong_scalar_mutant=0;
  logic x,y,z,m,left_d,right_d;logic[7:0] value;
  bit[7:0] coerced;bit final_reduction;
  initial begin
    for(a=0;a<4;a=a+1) for(b=0;b<4;b=b+1) begin
      x=four(a);y=four(b);
      if((x|y) !== (y|x)) $fatal(1,"OR commutativity");
      commute=commute+1;
      for(c=0;c<4;c=c+1) begin
        z=four(c);
        if((x&(y|z)) !== ((x&y)|(x&z))) $fatal(1,"AND distributes over OR");
        if(((x|y)|z) !== (x|(y|z))) $fatal(1,"OR associativity");
        distribute=distribute+1;associate=associate+1;
      end
    end
    for(v=0;v<65536;v=v+1) begin
      for(i=0;i<8;i=i+1) value[i]=four((v>>(i*2))&3);
      coerced=value;final_reduction=|value;
      if(final_reduction !== (|coerced)) $fatal(1,"final bit boundary differs from original bit byte");
      coercions=coercions+1;
      if(bit'(value) != final_reduction) wrong_scalar_mutant=wrong_scalar_mutant+1;
      for(a=0;a<4;a=a+1) begin
        m=four(a);left_d=|({8{m}}&value);right_d=m&(|value);
        if(left_d !== right_d) $fatal(1,"arbitrary four-state lane mask/byte distribution");
        if(left_d !== (m|(|value))) wrong_or_mutant=wrong_or_mutant+1;
        mask_bytes=mask_bytes+1;
      end
    end
    if(wrong_or_mutant==0 || wrong_scalar_mutant==0) $fatal(1,"wrong operator/scalar mutants not detected");
    $display("BG_PREDICATE_ALGEBRA_PASS distribute=%0d associate=%0d commute=%0d mask_bytes=%0d coercions=%0d wrong_or_mutant=%0d wrong_scalar_mutant=%0d",distribute,associate,commute,mask_bytes,coercions,wrong_or_mutant,wrong_scalar_mutant);
    $finish;
  end
endmodule
'''

def sha(data):return hashlib.sha256(data).hexdigest()

def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result

def verify_source_induction():
    if sha(QUALIFIER.read_bytes())!=QUALIFIER_SHA or sha(PROOF.read_bytes())!=PROOF_SHA:
        raise AssertionError('immutable actual BG/pixel proof changed')
    q=load(QUALIFIER,'bg_predicate_actual_qualifier')
    q.verify_composition_receipt(PROOF)
    p=load(q.PREPARER,'bg_predicate_source_preparer')
    files,manifest=p.verify_edge(EDGE)
    old=q.canonical(files['rtl/bg_vram.sv'][0]);new=q.canonical(files['rtl/bg_vram.sv'][1])
    compact=lambda value:re.sub(r'\s+','',value)
    old_rhs=re.search(r'\t\t\tSQ <= (\(.*?);',old,re.S).group(1)
    byte_rhs=re.search(r'wire \[7:0\] SERIAL_BYTE_D = (.*?);',new,re.S).group(1)
    nz_rhs=re.search(r'wire SERIAL_NZ_D = (.*?);',new,re.S).group(1)
    expected_byte='|'.join(f'({{8{{VIDEO_LANE_OH[{i}]}}}}&VIDEO_WORD[{8*i+7}:{8*i}])' for i in range(8))
    expected_nz='|'.join(f'(VIDEO_LANE_OH[{i}]&(|VIDEO_WORD[{8*i+7}:{8*i}]))' for i in range(8))
    if compact(old_rhs)!=expected_byte or compact(byte_rhs)!=expected_byte or compact(nz_rhs)!=expected_nz:
        raise AssertionError('all and only the eight exact lane operands required')
    return q,dict(old_sq_d=old_rhs,new_sq_d=byte_rhs,new_nz_d=nz_rhs,
                  full_original_word_and_mask_bit_positions_verified=True,
                  hardware_word_and_mask_are_bit_types=True,
                  widened_compiled_domain='all four-state independent word/mask operands',
                  induction=['replicated scalar mask distributes across each byte reduction',
                             'OR associativity/commutativity reorder 8x8 independent bit terms',
                             'final bit reduction equals reduction of the original BT bit byte'])

def parse(text):
    pattern=r'BG_PREDICATE_ALGEBRA_PASS distribute=(\d+) associate=(\d+) commute=(\d+) mask_bytes=(\d+) coercions=(\d+) wrong_or_mutant=(\d+) wrong_scalar_mutant=(\d+)'
    matches=re.findall(pattern,text)
    if len(matches)!=1:raise AssertionError('single exact algebra coverage marker required')
    counts=tuple(int(x) for x in matches[0])
    if counts[:5]!=(64,64,16,262144,65536) or min(counts[5:])<=0:
        raise AssertionError('exhaustive algebra coverage missing')
    return counts

def verify_composition_receipt(path):
    path=Path(path).resolve();r=json.loads(path.read_text());q,induction=verify_source_induction()
    if r['schema']!='bt-v22-bg-pixel-predicate-algebra-v1' or r['status']!='PASS_COMPILED_ALGEBRA_AND_SOURCE_INDUCTION':
        raise AssertionError('wrong algebra proof schema/status')
    for name,digest in r['retained_files'].items():
        if sha(Path(name).read_bytes())!=digest:raise AssertionError('changed retained algebra artifact')
    if r['induction']!=induction or Path(r['compiled_bench']).read_bytes()!=BENCH.encode():
        raise AssertionError('source formula or actual bench changed')
    expected=[[str(q.SIM/'vlib.exe'),'work'],
              [str(q.SIM/'vlog.exe'),'-sv','-work','work',r['compiled_bench']],
              [str(q.SIM/'vsim.exe'),'-c','-lib','work','bt_bg_predicate_algebra_tb','-do','run -all; quit -f']]
    if len(r['commands'])!=3:raise AssertionError('three real compiler/simulator commands required')
    for record,argv in zip(r['commands'],expected):
        if record['argv']!=argv or record['exit_code']!=0 or Path(record['cwd'])!=path.parent:
            raise AssertionError('wrong algebra command/exit')
        if re.search(r'\*\*\s+(?:Error|Fatal)|\$fatal|Error loading design',Path(record['log']).read_text()):
            raise AssertionError('actual algebra simulation failed')
    counts=parse(Path(r['commands'][-1]['log']).read_text())
    if r['coverage']!=list(counts):raise AssertionError('algebra coverage changed')
    return dict(status=r['status'],coverage=counts,source_induction=True,
                exact_actual_bg_pixel_proof_sha256=PROOF_SHA,new_clock_edges=0,timing_qualified=False)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();out=args.output.resolve();out.mkdir(parents=True,exist_ok=False)
    q,induction=verify_source_induction();bench=out/'bt_bg_predicate_algebra_tb.sv';bench.write_bytes(BENCH.encode())
    helper=out/Path(__file__).name;helper.write_bytes(Path(__file__).read_bytes())
    commands=[]
    for argv,name in (([q.SIM/'vlib.exe','work'],'vlib'),
                      ([q.SIM/'vlog.exe','-sv','-work','work',bench],'compile'),
                      ([q.SIM/'vsim.exe','-c','-lib','work','bt_bg_predicate_algebra_tb','-do','run -all; quit -f'],'run')):
        commands.append(q.run_command(argv,out,out/f'{name}.log'))
    counts=parse((out/'run.log').read_text())
    retained={str(p):sha(p.read_bytes()) for p in (PROOF,QUALIFIER,q.PREPARER,EDGE/'manifest.json',bench,helper,Path(__file__).resolve())}
    for record in commands:retained[record['log']]=record['log_sha256']
    r=dict(schema='bt-v22-bg-pixel-predicate-algebra-v1',status='PASS_COMPILED_ALGEBRA_AND_SOURCE_INDUCTION',
           actual_bg_pixel_proof=str(PROOF),actual_bg_pixel_proof_sha256=PROOF_SHA,
           compiled_bench=str(bench),commands=commands,coverage=counts,induction=induction,
           retained_files=retained,no_masks_or_exclusions=True,new_clock_edges=0,timing_qualified=False)
    target=out/'receipt.json';target.write_text(json.dumps(r,indent=2)+'\n');verify_composition_receipt(target)
    print(json.dumps(dict(status=r['status'],receipt=str(target),sha256=sha(target.read_bytes()),coverage=counts)))

if __name__=='__main__':main()
