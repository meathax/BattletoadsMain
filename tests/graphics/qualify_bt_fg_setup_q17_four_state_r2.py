"""Four-state FG replay and explicit reset/bit-capture proof; new evidence only.

Consumes frozen actual native inputs without modifying them. Canonical RAM is
unchanged; this is not an Intel primitive, mapped timing, or hardware claim.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SHA = lambda raw: hashlib.sha256(raw).hexdigest()


def declaration_order(raw, names):
    """Move only named module declarations; retain initialization/driver sites.

    A net-declaration assignment is replaced at its ORIGINAL source site by
    the identical continuous assignment. Uninitialized variables, or the
    TB's literal-zero variable, have no dependent initialization evaluation.
    Every body change and every moved declaration is explicitly invertible.
    """
    text = raw.decode()
    end = text.index('endmodule')
    head, tail = text[:end], text[end:]
    pattern = r'^[ \t]*(?:\(\*[^\n]*?\*\)[ \t]*)?(?:bit|logic|reg|wire)\b[^;]*;[^\n]*\n'
    selected=[]; found={name:0 for name in names}
    for match in re.finditer(pattern,head,re.M):
        statement=match.group(0)
        lhs=statement.split('=',1)[0].split('//',1)[0]
        present=[name for name in names if re.search(r'\b'+re.escape(name)+r'\b',lhs)]
        if not present: continue
        for name in present:found[name]+=1
        assert 'begin' not in statement and len(statement)<1400
        if re.search(r'\bwire\b',lhs) and '=' in statement:
            assert len(present)==1
            declaration=lhs.rstrip()+';\n'
            rhs=statement.split('=',1)[1]
            body='assign '+present[0]+' ='+rhs
        else:
            if '=' in statement:
                assert re.search(r'=\s*(?:0|[0-9]+\'d0)\s*;',statement), 'No dependent variable initializer may move'
            declaration=statement;body=''
        marker='// bt_modelsims_decl_site_'+str(len(selected))+'\n'
        selected.append({'old':statement,'new':marker+body,'declaration':declaration,'names':present})
    assert all(count==1 for count in found.values()),found
    for edit in selected:
        assert head.count(edit['old'])==1
        head=head.replace(edit['old'],edit['new'],1)
    anchor=re.search(pattern,head,re.M)
    assert anchor
    index=anchor.start()
    header='// bt_modelsims_declarations_begin\n'+''.join(edit['declaration'] for edit in selected)+'// bt_modelsims_declarations_end\n'
    head=head[:index]+header+head[index:]
    adapted=head+tail
    inverse=adapted.replace(header,'',1)
    for edit in selected:
        assert inverse.count(edit['new'])==1
        inverse=inverse.replace(edit['new'],edit['old'],1)
    assert inverse.encode()==raw
    return adapted.encode(), {'schema':'bt-private-modelsim-declaration-order-v1','edits':selected,'header':header,
        'raw_parent_sha256':SHA(raw),'adapted_sha256':SHA(adapted.encode()),'raw_inverse':True,
        'variable_initialization_dependencies_changed':False,'continuous_driver_expression_and_site_preserved':True,
        'assertions_or_workload_removed':False,'production_source_changed':False}


def checked(path, expected):
    raw = Path(path).read_bytes()
    assert SHA(raw) == expected, ('Frozen input changed', str(path))
    return raw


def run(command, cwd, log):
    with log.open('w') as target:
        result = subprocess.run(command, cwd=cwd, stdout=target, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    return {'command':command,'exit_code':result.returncode,'log':str(log),'log_sha256':SHA(log.read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native-proof', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    native = args.native_proof.resolve()
    output = args.output.resolve()
    output.relative_to(ROOT/'build')
    assert not output.exists(), 'Do not overwrite proof or failure evidence'
    receipt_raw = (native/'receipt.json').read_bytes()
    native_receipt = json.loads(receipt_raw)
    assert native_receipt['status'] == 'PASS' and native_receipt['profile'] == 'native'
    prep_raw = checked(native_receipt['preparation'], native_receipt['preparation_sha256'])
    prep = json.loads(prep_raw)
    assert prep['original_assertion_workload_inverse'] and not prep['case_equality_exclusions']
    original_inputs = {Path(path).name:checked(path,expected) for path,expected in prep['compiled_inputs'].items()}
    output.mkdir(parents=True)
    inputs = output/'inputs';inputs.mkdir()
    for name,raw in original_inputs.items():(inputs/name).write_bytes(raw)
    tb = original_inputs['item4_foreground_equivalence_tb.sv'].decode()
    extra = '''
  integer setup_addr_pre_edges=0,setup_addr_post_edges=0,setup_addr_reset_edges=0,setup_addr_async_resets=0;
  always @(posedge CLK or negedge CLK) begin
    setup_addr_pre_edges++;
    assert(candidate.SADDR_C_BK === reference.SADDR_C_BK && candidate.SADDR_CN_BK === reference.SADDR_CN_BK)
      else $fatal(1,"serial address register differs before capture, including reset");
    #0.1;
    setup_addr_post_edges++;
    if(!RST_N) setup_addr_reset_edges++;
    assert(candidate.SADDR_C_BK === reference.SADDR_C_BK && candidate.SADDR_CN_BK === reference.SADDR_CN_BK)
      else $fatal(1,"serial address register differs after capture, including reset");
  end
  always @(negedge RST_N) begin
    setup_addr_async_resets++;
    #0.1;
    assert(candidate.SADDR_C_BK === reference.SADDR_C_BK && candidate.SADDR_CN_BK === reference.SADDR_CN_BK)
      else $fatal(1,"reset assertion changed synchronous serial address register");
  end
'''
    assert tb.count('  initial begin\n') >= 1
    tb = tb.replace('  initial begin\n', extra+'  initial begin\n',1)
    marker = '    $display("PASS FG setup same-edge predicates:'
    assert tb.count(marker) == 1
    report = '    $display("PASS FG setup reset addresses: pre=%0d post=%0d reset_edges=%0d asynchronous_resets=%0d",setup_addr_pre_edges,setup_addr_post_edges,setup_addr_reset_edges,setup_addr_async_resets);\n'
    tb = tb.replace(marker,report+marker,1)
    assert tb.replace(extra,'',1).replace(report,'',1) == original_inputs['item4_foreground_equivalence_tb.sv'].decode()
    (inputs/'item4_foreground_equivalence_tb.sv').write_text(tb,newline='\n')
    parent = (native.parent/'immutable_parent/rtl/fg_vram.sv').read_bytes().decode().replace('\r\n','\n')
    candidate = original_inputs['fg_vram.sv'].decode().replace('\r\n','\n')
    # Actual producer statements, not a replacement model: retained verbatim
    # from the original and candidate byte-bound source modules.
    fields = ['RAS_N','OE_N','WE_N','TRANSFER']
    old_capture = []
    for field in fields:
        line = '\t\t'+field+'_M <= '+field+';'
        assert parent.count(line)==1 and candidate.count(line)==1
        old_capture.append(line)
    function_start = candidate.index('\t// Bit-valued automatic arguments')
    function_end = candidate.index('\tendfunction\n',function_start)+len('\tendfunction\n')
    actual_function = candidate[function_start:function_end]
    declaration = actual_function + '\t(* preserve, dont_merge *) bit [7:0] COPY_READ_REQUEST_M = \'0;'
    new_capture = '\t\tCOPY_READ_REQUEST_M <= {8{FG_READ_COMMAND(RAS_N, OE_N, WE_N, TRANSFER)}};'
    assert candidate.count(declaration)==1 and candidate.count(new_capture)==1
    # The original address capture has no async sensitivity, and original
    # top-level reset dominates every command/collect update of its D.
    old_addr = '\talways @(posedge CLK) begin\n\t\tfor (integer b = 0; b < 4; b = b + 1)\n\t\t\tSADDR_C_BK[b] <= {HOLE_NEXT_ADDR[15:10], HOLE_NEXT_ADDR[7:3]};\n\tend'
    assert parent.count(old_addr)==1
    assert parent.count('HOLE_NEXT_COPY_ADDR_5 = 1\'b0; HOLE_NEXT_ADDR = 18\'d0; HOLE_NEXT_ADDR_N = 18\'d1;')==1
    assert candidate.count('always @(posedge CLK) begin\n\t\t\tif (!RST_N) begin\n\t\t\t\tSADDR_C_BK[serial_copy_bank] <= \'0;')==1
    command_tb = '''`timescale 1ns/1ps
module fg_setup_capture_x_tb;
  logic CLK=0; always #5 CLK=~CLK;
  logic RAS_N=1, OE_N=1, WE_N=1, TRANSFER=0;
  bit RAS_N_M=1, OE_N_M=1, WE_N_M=1, TRANSFER_M;
DECLARATION
  always @(posedge CLK) begin
OLD_CAPTURE
NEW_CAPTURE
  end
  function automatic logic quad(input integer value);
    case(value) 0:quad=0; 1:quad=1; 2:quad=1'bx; 3:quad=1'bz; endcase
  endfunction
  integer checks=0;
  initial begin
    assert(COPY_READ_REQUEST_M === {8{!RAS_N_M && !OE_N_M && WE_N_M && TRANSFER_M}})
      else $fatal(1,"current read startup differs");
    for(integer n=0;n<256;n++) begin
      @(negedge CLK);
      RAS_N=quad(n%4); OE_N=quad((n/4)%4); WE_N=quad((n/16)%4); TRANSFER=quad((n/64)%4);
      @(posedge CLK); #0.1;
      assert(COPY_READ_REQUEST_M === {8{!RAS_N_M && !OE_N_M && WE_N_M && TRANSFER_M}})
        else $fatal(1,"original bit flags and current read decode disagree XZ tuple=%0d",n);
      checks++;
    end
    $display("PASS FG setup original/new raw capture: four_state_tuples=%0d replica_bits=8 startup_checked=1",checks);
    $finish;
  end
endmodule
'''.replace('DECLARATION',declaration).replace('OLD_CAPTURE','\n'.join(old_capture)).replace('NEW_CAPTURE',new_capture)
    (inputs/'fg_setup_capture_x_tb.sv').write_text(command_tb,newline='\n')
    adapters = {}
    names=['MEM_ROW','SREG_POS','COPY_ADDR','RDY_NEXT_COPY_WE','HOLE_NEXT_ADDR','COPY_ADDR_STEP_VALUE','COPY_ADDR_START_VALUE','CPU_CACHE_READY','CPU_PAIR_POS','SQ_D']
    for filename, selected_names in [('fg_vram.sv',names),('reference-fg_vram.sv',names),('item4_foreground_equivalence_tb.sv',['DRAW_ADDR'])]:
        adapted,record=declaration_order((inputs/filename).read_bytes(),selected_names)
        adapters[filename]=record
        (inputs/filename).write_bytes(adapted)
    preparation={'schema':'bt-fg-setup-four-state-inputs-v2','native_receipt':str(native/'receipt.json'),
        'native_receipt_sha256':SHA(receipt_raw),'native_preparation_sha256':SHA(prep_raw),
        'helper_path':str(Path(__file__).resolve()),'helper_sha256':SHA(Path(__file__).read_bytes()),
        'compiled_inputs':{str(p):SHA(p.read_bytes()) for p in inputs.iterdir()},
        'original_fixture_inverse':True,'original_addresses_clk_only':True,'original_reset_dominates_commands':True,
        'added_address_monitor':extra,'exact_original_capture_statements':old_capture,'exact_candidate_capture_statement':new_capture,
        'compiler_input_order_adapters':adapters,'actual_argument_coercion_function':actual_function,
        'canonical_ram_only':True,'case_equality_exclusions':0,'collision_masks_added':0,'source_parent_sha256':prep['parent_sources']['rtl/fg_vram.sv'],
        'source_candidate_sha256':prep['candidate_sha256']}
    (output/'preparation.json').write_text(json.dumps(preparation,indent=2)+'\n')
    tool=Path('D:/q17/modelsim_ase/win32aloem')
    records=[run([str(tool/'vlib.exe'),'work'],output,output/'vlib.log')]
    if records[-1]['exit_code']==0:
        records.append(run([str(tool/'vlog.exe'),'-sv','-work','work',*[str(inputs/name) for name in
            ['fg_vram.sv','reference-fg_vram.sv','ram_models.sv','item4_foreground_equivalence_tb.sv','fg_setup_capture_x_tb.sv']]],output,output/'build.log'))
    if records[-1]['exit_code']==0:
        for top in ['fg_setup_capture_x_tb','item4_foreground_equivalence_tb']:
            records.append(run([str(tool/'vsim.exe'),'-c','-assertdebug','-onfinish','stop','work.'+top,
                '-do','onerror {quit -code 1}; run -all; quit -code 0'],output,output/(top+'.log')))
            if records[-1]['exit_code']:break
    passed = all(record['exit_code']==0 for record in records) and len(records)==4
    coverage={}
    if passed:
        texts=[(output/(top+'.log')).read_text(errors='replace') for top in ['fg_setup_capture_x_tb','item4_foreground_equivalence_tb']]
        passed = all(not re.search(r'\*\* (?:Error|Fatal):|\b(?:fatal|failed)\b',text,re.I) for text in texts)
        x=re.search(r'four_state_tuples=(\d+) replica_bits=8 startup_checked=1',texts[0])
        state=re.search(r'PASS serial chunk complete pins/state: state_edges=(\d+) bank_edge_checks=(\d+)',texts[1])
        reset=re.search(r'PASS FG setup reset addresses: pre=(\d+) post=(\d+) reset_edges=(\d+) asynchronous_resets=(\d+)',texts[1])
        predicates=re.search(r'PASS FG setup same-edge predicates: checks=(\d+)',texts[1])
        passed=bool(passed and x and state and reset and predicates)
        if passed:
            coverage={'four_state_read_command_tuples':int(x[1]),'state_edges':int(state[1]),'bank_edge_checks':int(state[2]),
                'same_edge_predicate_checks':int(predicates[1]),'address_pre_edges':int(reset[1]),'address_post_edges':int(reset[2]),
                'address_reset_edges':int(reset[3]),'asynchronous_reset_assertions':int(reset[4]),
                'states':31,'ram_banks':4,'ram_pin_fields':13,'startup_checked':True}
            assert coverage['four_state_read_command_tuples']==256 and coverage['state_edges']>100000
            assert coverage['address_pre_edges']==coverage['address_post_edges'] and coverage['address_reset_edges']>1
            assert coverage['asynchronous_reset_assertions']>=2
            assert 'restart_collisions=8 abort_collisions=8 reset_collects=2' in texts[1]
    for path,expected in prep['compiled_inputs'].items():checked(path,expected)
    for path,expected in preparation['compiled_inputs'].items():checked(path,expected)
    final={'schema':'bt-fg-setup-v18-four-state-reset-v2','status':'PASS' if passed else 'FAIL',
        'preparation':str(output/'preparation.json'),'preparation_sha256':SHA((output/'preparation.json').read_bytes()),
        'records':records,'coverage':coverage,'case_equality_exclusions':0,'collision_masks_added':0,
        'intel_primitive_claim':False,'mapped_timing_or_hardware_claim':False}
    (output/'receipt.json').write_text(json.dumps(final,indent=2)+'\n')
    print(json.dumps({'receipt':str(output/'receipt.json'),'sha256':SHA((output/'receipt.json').read_bytes()),
        'status':final['status'],'coverage':coverage},separators=(',',':')))
    raise SystemExit(0 if passed else 1)


if __name__=='__main__':main()
