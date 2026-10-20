"""Mechanically retime only literal opcode comparisons, with a frozen decoder.

No instruction state, conditions, priority, or cycle is changed. --apply writes
the conversion; the default checks that the committed conversion regenerates.
The generated miter compares the complete decode control word.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = Path('D:/vibes/fpga/temp/bt-graphics-c036dac59690474faff563209eafc766')
ID = 'rtl/TMS34020/TMS34020_ID.sv'
PKG = 'rtl/TMS34020/TMS34020_PKG.sv'
CPU = 'rtl/TMS34020/TMS34020.sv'
SDC = 'rtl/bt_cpu_phase.sdc'
NUM = r"\d+'[bBhH][0-9a-fA-F_xXzZ?]+"
EVENT = re.compile(r'\b(?P<case>case[xz]?)\s*\((?P<expr>[^()]*)\)'
    r'|\b(?P<end>endcase)\b|(?P<label>' + NUM + r'(?:\s*,\s*' + NUM + r')*)\s*:')


def convert(source):
    clean = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
        lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()),
        source, flags=re.S)
    stack, predicates, replacements = [], [], []
    cases = labels = 0
    for event in EVENT.finditer(clean):
        if event.group('case'):
            expr = event.group('expr').strip()
            match = re.fullmatch(r'IC(?:\[(\d+)(?::(\d+))?\])?', expr)
            if 'IC' in expr and not match:
                raise ValueError('Unsupported opcode selector: ' + expr)
            selector = None
            if match:
                high = int(match[1]) if match[1] else 15
                low = int(match[2]) if match[2] else (high if match[1] else 0)
                selector = (high, low, event.group('case'))
                cases += 1
                replacements.append((event.start(), event.end(), "case (1'b1)"))
            stack.append(selector)
        elif event.group('end'):
            if not stack:
                raise ValueError('Unbalanced endcase')
            stack.pop()
        elif stack and stack[-1]:
            high, low, kind = stack[-1]
            flags = []
            for literal in re.findall(NUM, event.group('label')):
                width, radix, digits = re.fullmatch(r"(\d+)'([bBhH])(.+)", literal).groups()
                if int(width) != high - low + 1:
                    raise ValueError('Width mismatch: ' + literal)
                digits = digits.replace('_', '').lower()
                if radix.lower() == 'h':
                    digits = ''.join('xxxx' if c in 'xz?' else f'{int(c,16):04b}' for c in digits)
                digits = digits.zfill(int(width))
                if len(digits) != int(width):
                    raise ValueError('Unexpected literal: ' + literal)
                if any(c in 'xz?' for c in digits) and kind == 'case':
                    raise ValueError('Four-state exact case needs separate handling')
                mask = value = 0
                for bit, digit in enumerate(reversed(digits), start=low):
                    if digit in '01':
                        mask |= 1 << bit
                        value |= int(digit) << bit
                    elif kind != 'casex' and digit == 'x':
                        raise ValueError('casez X is not a wildcard')
                predicate = (mask, value)
                if predicate not in predicates:
                    predicates.append(predicate)
                flags.append(f'IC_MATCHES[{predicates.index(predicate)}]')
            labels += 1
            replacements.append((event.start(), event.end(), ', '.join(flags) + ':'))
    if stack or cases == 0:
        raise ValueError('Case parser did not consume the decoder')
    output = source
    for start, end, replacement in reversed(replacements):
        output = output[:start] + replacement + output[end:]
    output = output.replace('input      [15: 0] IC,',
        'input      [15: 0] IC,\n\tinput ICMatches_t IC_MATCHES,', 1)
    if output == source or 'input ICMatches_t IC_MATCHES' not in output:
        raise ValueError('Decoder header mismatch')
    return output, predicates, cases, labels


def full_opcode_classes(source):
    """Select only literal IC cases, leaving all dynamic control untouched.

    Every selected branch retains its surrounding begin/end and statements.
    A complete 4096-word partition validates the minimized opcode cubes.
    """
    clean = re.sub(r'//[^\n]*|/\*.*?\*/|"(?:\\.|[^"\\])*"',
        lambda m: ''.join('\n' if c == '\n' else ' ' for c in m.group()),
        source, flags=re.S)
    events = re.compile(r'(?:(?:unique|priority)\s+)?\b(?P<case>case[xz]?)\s*\((?P<expr>[^()]*)\)'
        r'|\b(?P<end>endcase)\b|^[ \t]*(?P<label>'+NUM+r'(?:\s*,\s*'+NUM+r')*|default)\s*:', re.M)
    stack, nodes = [], []
    labels = 0
    for event in events.finditer(clean):
        if event.group('case'):
            expr = event.group('expr').strip()
            match = re.fullmatch(r'IC(?:\[(\d+)(?::(\d+))?\])?', expr)
            if 'IC' in expr and not match:
                raise ValueError('Unsupported opcode selector: '+expr)
            node = {'start': event.start(), 'end': None, 'branches': [], 'opcode': bool(match)}
            if match:
                high = int(match[1]) if match[1] else 15
                low = int(match[2]) if match[2] else (high if match[1] else 0)
                if low < 4:
                    # Low-word cases also interpret register/immediate bits.
                    # Retain them verbatim; only opcode-field cases are folded.
                    node['opcode']=False
                else:
                    node.update(high=high, low=low, kind=event.group('case'))
                    nodes.append(node)
            stack.append(node)
        elif event.group('end'):
            if not stack:
                raise ValueError('Unbalanced case')
            node = stack.pop()
            node['end'] = event.end()
            if node['branches']:
                node['branches'][-1]['end'] = event.start()
        elif stack and stack[-1]['opcode']:
            node = stack[-1]
            if node['branches']:
                node['branches'][-1]['end'] = event.start()
            node['branches'].append({'label': event.group('label'), 'start': event.end()})
            labels += event.group('label') != 'default'
    if stack or not nodes:
        raise ValueError('Incomplete decoder parse')
    nodes.sort(key=lambda n:n['start'])
    root = nodes[0]

    def accepts(literal, node, instruction):
        width, radix, digits = re.fullmatch(r"(\d+)'([bBhH])(.+)", literal).groups()
        if int(width) != node['high']-node['low']+1:
            raise ValueError('Opcode label width changed: '+literal)
        digits = digits.replace('_','').lower()
        if radix.lower() == 'h':
            digits = ''.join('xxxx' if c in 'xz?' else f'{int(c,16):04b}' for c in digits)
        digits = digits.zfill(int(width))
        if len(digits) != int(width):
            raise ValueError('Unexpected opcode literal: '+literal)
        for bit,digit in enumerate(reversed(digits),start=node['low']):
            if digit in '01':
                if ((instruction>>bit)&1) != int(digit):return False
            elif node['kind']=='case' or (node['kind']=='casez' and digit=='x'):
                raise ValueError('Four-state exact opcode label needs separate handling')
        return True

    def fold_region(start,end,instruction):
        parts=[]
        cursor=start
        for node in nodes:
            if node['start']<cursor or node['start']>=end:continue
            if node['end']>end:raise ValueError('Overlapping opcode cases')
            parts.append(source[cursor:node['start']])
            selected=None
            default=None
            for branch in node['branches']:
                if branch['label']=='default':default=branch
                elif any(accepts(literal,node,instruction) for literal in re.findall(NUM,branch['label'])):
                    selected=branch
                    break
            selected=selected or default
            if selected:
                parts.append(fold_region(selected['start'],selected['end'],instruction))
            cursor=node['end']
        parts.append(source[cursor:end])
        return ''.join(parts)

    bodies=[]
    body_keys=[]
    members=[]
    partition=[]
    for op in range(4096):
        body=fold_region(root['start'],root['end'],op<<4)
        body='\n'.join(line.strip() for line in body.splitlines() if line.strip())
        key=re.sub(r'//[^\n]*|/\*.*?\*/', '', body, flags=re.S)
        key='\n'.join(line.strip() for line in key.splitlines() if line.strip())
        if key not in body_keys:
            body_keys.append(key)
            bodies.append(body)
            members.append(set())
        index=body_keys.index(key)
        members[index].add(op)
        partition.append(index)

    def cover(values):
        current={(value,0xFFF) for value in values}
        primes=set()
        while current:
            combined=set()
            following=set()
            for value,mask in current:
                for bit in range(12):
                    other=(value^(1<<bit),mask)
                    if mask&(1<<bit) and other in current:
                        combined.update(((value,mask),other))
                        following.add((value&~(1<<bit),mask&~(1<<bit)))
            primes.update(current-combined)
            current=following
        uncovered=set(values)
        result=[]
        candidates=[(value,mask,{op for op in values if op&mask==value}) for value,mask in sorted(primes)]
        while uncovered:
            value,mask,hits=max(candidates,key=lambda item:(len(item[2]&uncovered),-item[1].bit_count(),-item[0]))
            if not hits&uncovered:raise ValueError('Opcode cover failed')
            result.append((mask<<4,value<<4))
            uncovered-=hits
        return result

    # A register-to-register opcode always selects IC[8:5] before any state
    # branch; other opcodes default to IC[3:0]. Capture that static choice
    # alongside IC instead of routing every class flag through the RF address.
    rs_upper=set()
    rs_upper_classes=set()
    upper_pattern=r"DECI\.RS = 0;\s*rs_low_keep = 0;\s*rs_high_keep = 4'hf;"
    for index,body in enumerate(bodies):
        masked=re.sub(r'//[^\n]*|/\*.*?\*/',lambda m:' ' * len(m.group()),body,flags=re.S)
        match=re.search(upper_pattern,masked)
        if not match: continue
        prefix=re.sub(r'\bbegin\b|\s','',masked[:match.start()])
        if prefix: raise ValueError('Source register choice is conditional')
        if len(re.findall(upper_pattern,masked))!=1: raise ValueError('Repeated source selector')
        rs_upper.update(members[index])
        rs_upper_classes.add(index)
        body=body[:match.start()]+body[match.end():]
        # After removing the static choice, low_keep means the captured
        # field. Preserve state-specific selections of the opposite field.
        bodies[index]=re.sub(r'\brs_(low|high)_keep\b',
            lambda m:'rs_high_keep' if m[1]=='low' else 'rs_low_keep',body)
    rs_predicates=cover(rs_upper)
    predicates=[cover(values) for values in members]
    for op in range(4096):
        active=[i for i,cubes in enumerate(predicates)
                if any((op<<4)&mask==value for mask,value in cubes)]
        if active != [partition[op]]:
            raise ValueError('Opcode partition is not complete and exclusive')
    # Compute each mutually exclusive instruction's dynamic controls in
    # parallel. The registered opcode class enters only the final AND/OR
    # selection, rather than a priority tree before register-file reads.
    comb_start=source.rfind('always_comb begin', 0, root['start'])
    module_end=source.rfind('endmodule')
    if comb_start < 0 or module_end < root['end']:
        raise ValueError('Decoder combinational block boundaries changed')
    defaults=source[comb_start:root['start']]
    finish=source[root['end']:module_end]
    if finish.count('IC[3:0] & rs_low_keep')!=1: raise ValueError('Source field mask changed')
    finish=finish.replace('IC[3:0] & rs_low_keep','IC_RS_STATIC & rs_low_keep')
    blocks=[source[:comb_start],
        f'\tDecInstr_t CLASS_DECI[{len(bodies)}];\n',
        '\tDecInstr_t BASE_DECI, CLASS_DELTA;\n',
        '\t'+re.sub(r'\bDECI\b', 'BASE_DECI', defaults+'\n'+finish)]
    for index,body in enumerate(bodies):
        class_finish=finish.replace('IC[8:5] & rs_high_keep','IC[3:0] & rs_high_keep') if index in rs_upper_classes else finish
        block=defaults+'\n'+body+'\n'+class_finish
        block=re.sub(r'\bDECI\b', f'CLASS_DECI[{index}]', block)
        blocks.append(f'\t// Parallel opcode class {index}.\n\t'+block)
    # Exactly one class is captured with IC, including asynchronous reset.
    # XOR away each class's common defaults before selecting it. This keeps
    # unchanged controls off the wide one-hot OR tree; base ^ selected delta
    # is exactly the original complete control word for every opcode/state.
    blocks.extend(['\t// IC_MATCHES is the complete one-hot opcode partition.',
        '\talways_comb begin', "\t\tCLASS_DELTA = '0;",
        f'\t\tfor (int c=0; c<{len(bodies)}; c++)',
        '\t\t\tCLASS_DELTA |= (CLASS_DECI[c] ^ BASE_DECI) & {$bits(DecInstr_t){IC_MATCHES[c]}};',
        '\t\tDECI = BASE_DECI ^ CLASS_DELTA;',
        '\tend\n', source[module_end:]])
    converted='\n'.join(blocks)
    converted=converted.replace('input      [15: 0] IC,',
        'input      [15: 0] IC,\n\tinput ICMatches_t IC_MATCHES,\n\tinput bit [3:0] IC_RS_STATIC,',1)
    converted=converted.replace('input bit [3:0] IC_RS_STATIC,','input bit [3:0] IC_RS_STATIC,\n\tinput ICRFAddress_t IC_RF_ADDR,\n\tinput ICRFAddress_t IC_RF_ADDR_POS,',1)
    converted=converted.replace('DECI = BASE_DECI ^ CLASS_DELTA;',
        'DECI = BASE_DECI ^ CLASS_DELTA;\n\t\tDECI.MMA = LINE_GZ ? IC_RF_ADDR_POS[9] : IC_RF_ADDR[9];\n\t\tDECI.R = LINE_GZ ? IC_RF_ADDR_POS[8] : IC_RF_ADDR[8];\n\t\tDECI.RD = LINE_GZ ? IC_RF_ADDR_POS[7:4] : IC_RF_ADDR[7:4];\n\t\tDECI.RS = LINE_GZ ? IC_RF_ADDR_POS[3:0] : IC_RF_ADDR[3:0];',1)
    return converted,predicates,rs_predicates,len(nodes),labels


def package_helper(predicates,rs_predicates):
    lines = ['\t// Literal opcode comparisons captured with IC on the same R edge.',
        f'\ttypedef bit [{len(predicates)-1}:0] ICMatches_t;',
        '\tfunction automatic ICMatches_t DecodeICMatches(input bit [15:0] ic_word);']
    for i, cubes in enumerate(predicates):
        expressions=[f"((ic_word & 16'h{mask:04X}) == 16'h{value:04X})" for mask,value in cubes]
        lines.append(f'\t\tDecodeICMatches[{i}] = '+' |\n\t\t\t'.join(expressions)+';')
    lines.append('\tendfunction\n')
    rs_expression=' |\n\t\t\t'.join(f"((ic_word & 16'h{mask:04X}) == 16'h{value:04X})" for mask,value in rs_predicates)
    lines.extend(['\t// Static source-register field captured on the instruction edge.',
        '\tfunction automatic bit [3:0] DecodeICRS(input bit [15:0] ic_word);',
        '\t\tbit upper_field;', '\t\tupper_field = '+rs_expression+';',
        '\t\tDecodeICRS = upper_field ? ic_word[8:5] : ic_word[3:0];', '\tendfunction\n'])
    return '\n'.join(lines)




def rf_address_helper(source):
    # Preserve the original address-control statements and their case/state
    # structure. Remove other control assignments with null statements, so
    # conditional statement boundaries cannot change. The complete-control
    # miter checks these four fields against every original opcode/state.
    match=re.search(r'\balways_comb\s+begin(.*)\bend\s*\n\s*endmodule',source,re.S)
    if not match: raise ValueError('Address decoder boundaries changed')
    body=re.sub(r'//[^\n]*|/\*.*?\*/','',match[1],flags=re.S)
    fields={'R','RD','RS','MMA'}
    body=re.sub(r'DECI\.(\w+(?:\.\w+)*)\s*=\s*.*?;',
        lambda m:m[0] if m[1] in fields else ';',body,flags=re.S)
    remaining=set(re.findall(r'\bDECI\.(\w+)',body))
    if remaining-fields: raise ValueError('Address controls depend on another decoded field: '+str(remaining-fields))
    for width,name in re.findall(r'^\s*input\s*(\[[^\]]+\])?\s*(\w+)\s*,',source,re.M):
        if name not in ('IC','STATE','STATE_OH','LINE_GZ'):
            body=re.sub(r'\b'+name+r'\b',"'0",body)
    declarations=re.match(r'\s*(?:bit\s+[^;]+;\s*)*',body).end()
    body=body[:declarations]+"\n        STATE_OH = 32'b1 << STATE;\n"+body[declarations:]
    return '\n'.join(['\ttypedef bit [9:0] ICRFAddress_t;',
        '\tfunction automatic ICRFAddress_t DecodeICRFAddress(input bit [15:0] IC, input bit [4:0] STATE, input bit LINE_GZ);',
        '\t\tDecInstr_t DECI;', '\t\tbit [31:0] STATE_OH;', body,
        '\t\tDecodeICRFAddress = {DECI.MMA,DECI.R,DECI.RD,DECI.RS};', '\tendfunction\n'])


def expected_files():
    original = (BASE/ID).read_text()
    converted, predicates, rs_predicates, cases, labels = full_opcode_classes(original)
    helper = package_helper(predicates,rs_predicates) + rf_address_helper(original)
    package = (BASE/PKG).read_text().replace('endpackage', helper + '\nendpackage')
    cpu = (BASE/CPU).read_text()
    cpu = cpu.replace('bit  [15: 0] IC;', 'bit  [15: 0] IC;\n\tICMatches_t IC_MATCHES;\n\tbit [3:0] IC_RS_STATIC;\n\tICRFAddress_t IC_RF_ADDR, IC_RF_ADDR_POS;')
    cpu = cpu.replace('.IC(IC),', '.IC(IC),\n\t\t.IC_MATCHES(IC_MATCHES),\n\t\t.IC_RS_STATIC(IC_RS_STATIC),\n\t\t.IC_RF_ADDR(IC_RF_ADDR),\n\t\t.IC_RF_ADDR_POS(IC_RF_ADDR_POS),', 1)
    cpu = cpu.replace("IC <= 16'h0900;", "IC <= 16'h0900;\n\t\t\tIC_MATCHES <= DecodeICMatches(16'h0900);\n\t\t\tIC_RS_STATIC <= DecodeICRS(16'h0900);")
    cpu = cpu.replace("IC <= 16'h090A;", "IC <= 16'h090A;\n\t\t\t\t\tIC_MATCHES <= DecodeICMatches(16'h090A);\n\t\t\t\t\tIC_RS_STATIC <= DecodeICRS(16'h090A);")
    cpu = cpu.replace('IC <= !PC[4] ? CACHE_Q[15:0] : CACHE_Q[31:16];',
        'IC <= !PC[4] ? CACHE_Q[15:0] : CACHE_Q[31:16];\n'
        '\t\t\t\t\t\tIC_MATCHES <= !PC[4] ? DecodeICMatches(CACHE_Q[15:0]) : DecodeICMatches(CACHE_Q[31:16]);\n'
        '\t\t\t\t\t\tIC_RS_STATIC <= !PC[4] ? DecodeICRS(CACHE_Q[15:0]) : DecodeICRS(CACHE_Q[31:16]);')
    cpu = cpu.replace('{IC,IW,PC,STATE,STATE_OH,MD_ACC,', '{IC,IC_MATCHES,IC_RS_STATIC,IC_RF_ADDR,IC_RF_ADDR_POS,IW,PC,STATE,STATE_OH,MD_ACC,')
    cpu = cpu.replace('always @(negedge CLK) begin\n\t\tif (RST_N',
        'always @(negedge CLK) begin\n\t\tif (RST_N)\n'
        '\t\t\tassert (IC_MATCHES == DecodeICMatches(IC))\n'
        '\t\t\t\telse $fatal(1,"Opcode predecode changed instruction identity");\n'
        '\t\tif (RST_N) assert (IC_RS_STATIC == DecodeICRS(IC))\n'
        '\t\t\telse $fatal(1,"Static source register changed instruction identity");\n\t\tif (RST_N', 1)
    state_pairs=list(re.finditer(r'begin STATE <= ([^;]+); STATE_OH <= [^;]+; end',cpu))
    if len(state_pairs)!=7: raise ValueError('State capture ownership changed: '+str(len(state_pairs)))
    for ordinal,match in reversed(list(enumerate(state_pairs))):
        state=match[1]
        instruction="16'h0900" if ordinal==0 else "16'h090A" if ordinal==1 else "(!PC[4] ? CACHE_Q[15:0] : CACHE_Q[31:16])" if ordinal==3 else 'IC'
        replacement=match[0][:-4]+' IC_RF_ADDR <= DecodeICRFAddress('+instruction+', '+state+', 0); IC_RF_ADDR_POS <= DecodeICRFAddress('+instruction+', '+state+', 1); end'
        cpu=cpu[:match.start()]+replacement+cpu[match.end():]
    anchor='\t\tif (RST_N) assert (IC_RS_STATIC == DecodeICRS(IC))'
    if cpu.count(anchor)!=1: raise ValueError('CPU identity assertions changed')
    cpu=cpu.replace(anchor,'\t\tif (RST_N) assert (IC_RF_ADDR == DecodeICRFAddress(IC,STATE,0) && IC_RF_ADDR_POS == DecodeICRFAddress(IC,STATE,1))\n'
        '\t\t\telse $fatal(1,"Registered RF address changed instruction/state identity");\n'+anchor,1)
    if cpu.count('IC_MATCHES <=') != 3 or cpu.count('ICMatches_t IC_MATCHES') != 1:
        raise ValueError('Instruction ownership changed; review the generator')
    sdc = (BASE/SDC).read_text().replace('*|CPU|IC[*]*', '*|CPU|IC[*]* *|CPU|IC_MATCHES[*]* *|CPU|IC_RS_STATIC[*]* *|CPU|IC_RF_ADDR[*]* *|CPU|IC_RF_ADDR_POS[*]*', 1)
    inputs = re.findall(r'^\s*input\s*(\[[^\]]+\])?\s*(\w+)\s*,', original, re.M)
    connections = [f'.{name}({name})' for _, name in inputs]
    scalar = [name for width, name in inputs if not width]
    tb = ['`timescale 1ns/1ps', 'import TMS34020_PKG::*;',
        'module cpu_opcode_equivalence_tb;']
    tb += [f'  bit {width or ""} {name};' for width, name in inputs]
    tb += ['  DecInstr_t candidate, reference;', '  ICMatches_t flags;', '  assign flags = DecodeICMatches(IC);',
        '  TMS34020_ID dut(' + ','.join(connections + ['.IC_MATCHES(flags)', '.IC_RS_STATIC(DecodeICRS(IC))', '.IC_RF_ADDR(DecodeICRFAddress(IC,STATE,0))', '.IC_RF_ADDR_POS(DecodeICRFAddress(IC,STATE,1))', '.DECI(candidate)']) + ');',
        '  TMS34020_ID_REFERENCE golden(' + ','.join(connections + ['.DECI(reference)']) + ');',
        "  int unsigned seed=32'h51CEB00C;", '  int unsigned checks=0;',
        '  function automatic int unsigned random_bits();',
        '    seed ^= seed << 13; seed ^= seed >> 17; seed ^= seed << 5;',
        '    return seed;', '  endfunction', '  initial begin',
        '    for(int op=0;op<65536;op++) begin', '      IC=16\'(op);',
        '      for(int state_index=0;state_index<32;state_index++) begin',
        '        STATE=5\'(state_index); STATE_OH=32\'b1 << state_index;',
        '        for(int profile=0;profile<3;profile++) begin']
    tb += [f"          {name} = profile==0 ? 1'b0 : profile==1 ? 1'b1 : 1'(random_bits());" for name in scalar]
    tb += ["          PIX_WINCC = profile==0 ? 4'h0 : profile==1 ? 4'hf : 4'(random_bits());",
        '          #1;', '          assert(candidate === reference)',
        '            else $fatal(1,"Opcode decode mismatch IC=%h state=%0d profile=%0d candidate=%h reference=%h",IC,STATE,profile,candidate,reference);',
        '          checks++;', '        end', '      end', '    end',
        '    $display("PASS opcode predecode: all 65536 opcodes, 32 states, 3 condition profiles, %0d complete-control comparisons",checks);',
        '    $finish;', '  end', 'endmodule', '']
    return {ID: converted, PKG: package, CPU: cpu, SDC: sdc,
        'tests/cpu_opcode_equivalence_tb.sv': '\n'.join(tb)}, {
        'cases': cases, 'labels': labels, 'registered_predicates': len(predicates), 'static_source_cubes':len(rs_predicates),
        'baseline': str(BASE/ID), 'baseline_sha256': hashlib.sha256((BASE/ID).read_bytes()).hexdigest()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    files, details = expected_files()
    for name, content in files.items():
        path = ROOT/name
        if args.apply:
            path.write_text(content)
        elif path.read_text() != content:
            raise SystemExit('Generated predecode differs: ' + name)
    print(json.dumps(details, indent=2))


if __name__ == '__main__':
    main()
