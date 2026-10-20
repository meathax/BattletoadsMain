"""Convert state comparisons to a registered one-hot shadow without changing state transitions."""
from pathlib import Path
import re

root=Path(__file__).resolve().parents[2]
decoder=root/'rtl/TMS34020/TMS34020_ID.sv'
cpu=root/'rtl/TMS34020/TMS34020.sv'
def code_only(text):
    return re.sub(r'/\*.*?\*/|//[^\n]*',lambda m: ''.join('\n' if c=='\n' else ' ' for c in m[0]),text,flags=re.S)
source=decoder.read_text()
masked=code_only(source)
if 'STATE_OH' in masked:
    raise SystemExit('The decoder already has a one-hot shadow.')
tokens=re.compile(r'\bcase(?:x|z)?\s*\([^)]*\)|\bendcase\b|(?m:^[\t ]*5\s*\x27[dD]\s*\d+\s*:)')
stack=[]
edits=[]
cases=labels=0
for token in tokens.finditer(masked):
    value=token[0]
    if value.startswith('case'):
        is_state=bool(re.fullmatch(r'case\s*\(\s*STATE\s*\)',value))
        stack.append(is_state)
        if is_state:
            edits.append((token.start(),token.end(),"unique case (1'b1)"))
            cases+=1
    elif value=='endcase':
        if not stack: raise RuntimeError('Unbalanced decoder cases.')
        stack.pop()
    elif stack and stack[-1]:
        number=int(re.search(r'\x27[dD]\s*(\d+)',value)[1])
        if number>=32: raise RuntimeError('Invalid state literal.')
        literal=re.search(r'5\s*\x27[dD]\s*\d+',value)
        edits.append((token.start()+literal.start(),token.start()+literal.end(),f'STATE_OH[{number}]'))
        labels+=1
if stack or cases<50 or labels<150:
    raise RuntimeError(f'Unexpected decoder structure cases={cases} labels={labels}')
for start,end,replacement in reversed(edits):
    source=source[:start]+replacement+source[end:]
source,count=re.subn(r'(input\s+\[\s*4:\s*0\]\s+STATE,)',r'\1\n\tinput      [31: 0] STATE_OH,',source,count=1)
if count!=1: raise RuntimeError('Missing binary state input.')
current=cpu.read_text()
masked=code_only(current)
updates=list(re.finditer(r'\bSTATE\s*<=\s*([^;]+);',masked))
if len(updates)!=7: raise RuntimeError(f'Unexpected state writes: {len(updates)}')
for update in reversed(updates):
    expression=current[update.start(1):update.end(1)].strip()
    replacement=f"begin STATE <= {expression}; STATE_OH <= 32'b1 << ({expression}); end"
    current=current[:update.start()]+replacement+current[update.end():]
current,count=re.subn(r'(bit\s+\[\s*4:\s*0\]\s+STATE;)',r"\1\n\tbit [31:0] STATE_OH = 32'b1;",current,count=1)
if count!=1: raise RuntimeError('Missing state register.')
if current.count('.STATE(STATE),')!=1: raise RuntimeError('Unexpected decoder connection.')
current=current.replace('.STATE(STATE),','.STATE(STATE),\n\t\t.STATE_OH(STATE_OH),')
current=current.replace("\tbit [31:0] STATE_OH = 32'b1;","""\tbit [31:0] STATE_OH = 32'b1;
`ifndef SYNTHESIS
\talways @(negedge CLK) if (RST_N) begin
\t\tassert (STATE_OH == (32'b1 << STATE))
\t\t\telse $fatal(1, "TMS34020 state/shadow divergence");
\tend
`endif""")
decoder.write_text(source)
cpu.write_text(current)
print(f'Converted {cases} state cases, {labels} labels and {len(updates)} paired state writes.')
